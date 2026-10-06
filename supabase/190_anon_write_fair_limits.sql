-- Migration 190: one abuser can no longer use up the anonymous write limits.
--
-- Server-only; the client is unchanged (same functions, same signatures,
-- same 'rate limited: ...' messages; the em dash in them is
-- chr(8212), so this file stays ASCII). Idempotent.
--
-- 133 gave create_trade and the feedback box (submit_feedback, and since 138
-- reply_my_feedback through _feedback_rate_limit) a per-IP limit (30 / 10
-- an hour) and a GLOBAL backstop (300 / 120 an hour). Checked 2026-10-06:
--   * the per-IP key is sound: _client_ip() reads cf-connecting-ip, which
--     Cloudflare sets (a forged one is refused with a 403, error 1000),
--     not the caller-controlled first hop of x-forwarded-for;
--   * a refused attempt is never counted (the raise comes before the insert);
--   * but ONE abuser holding 10 addresses (12 for feedback) fills the global
--     bucket with requests the per-IP limit allows, and from then on every
--     caller on the site, signed in or not, is refused for the rest of the
--     hour, renewable every hour.
--
-- What changes:
--   1. _rate_bucket(scope): a signed-in caller is bucketed by ACCOUNT, an
--      anonymous one by address, an IPv6 address folded to its /64 (one host
--      routinely owns a whole /64, so per-address buckets would be free to
--      mint). An IPv4 bucket hashes exactly as before, so counts already in
--      the tables carry over.
--   2. Two pools: the global cap counts signed-in and anonymous writes
--      separately, so an anonymous abuser can never lock out signed-in users.
--   3. Fair share under pressure: once a pool is past half its cap, only
--      buckets with fewer than 2 writes this hour get in, until the hard cap
--      (unchanged: 300 trades, 120 feedback). Filling it now takes about
--      80 / 36 fresh addresses instead of 10 / 12, and people writing once
--      or twice keep working while one heavy writer sits at the soft cap.
--   The worst case per hour is now two pools at the old cap instead of one:
--   a deliberate trade, since the second pool needs real accounts.

alter table public.trade_create_events    add column if not exists signed_in boolean not null default false;
alter table public.feedback_submit_events add column if not exists signed_in boolean not null default false;

create or replace function public._rate_bucket(p_scope text)
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_uid uuid := (select auth.uid());
  v_ip  text;
  v_net text;
begin
  if v_uid is not null then
    return encode(extensions.digest(p_scope || '|u:' || v_uid::text, 'sha256'), 'hex');
  end if;
  v_ip := nullif(public._client_ip(), '');
  begin
    v_net := case when family(v_ip::inet) = 6
                  then host(network(set_masklen(v_ip::inet, 64)))
                  else host(v_ip::inet) end;
  exception when others then
    v_net := v_ip;
  end;
  return encode(extensions.digest(p_scope || '|' || coalesce(v_net, 'unknown'), 'sha256'), 'hex');
end;
$$;
revoke all on function public._rate_bucket(text) from public, anon, authenticated;

-- create_trade: body from 133 (the live definition), limits rewritten.
create or replace function public.create_trade(p_token text, p_payload jsonb)
returns text
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_signed boolean := (select auth.uid()) is not null;
  v_hash   text;
  v_recent int;
  v_total  int;
begin
  if p_token is null or p_token !~ '^[A-Za-z0-9_-]{16,64}$' then
    raise exception 'invalid token';
  end if;
  if p_payload is null or length(p_payload::text) > 100000 then
    raise exception 'invalid or oversized payload';
  end if;

  v_hash := public._rate_bucket('packsink-trade');

  delete from public.trade_create_events where created_at < now() - interval '2 hours';

  select count(*) into v_recent
  from public.trade_create_events
  where ip_hash = v_hash and created_at > now() - interval '1 hour';

  if v_recent >= 30 then
    raise exception 'rate limited: too many trade links created % try again in an hour', chr(8212);
  end if;

  -- Per pool. Past 150 only light writers get in; at 300 nobody does.
  select count(*) into v_total
  from public.trade_create_events
  where signed_in = v_signed and created_at > now() - interval '1 hour';

  if v_total >= 300 or (v_total >= 150 and v_recent >= 2) then
    raise exception 'rate limited: too many trade links created % try again in an hour', chr(8212);
  end if;

  insert into public.trade_create_events (ip_hash, signed_in) values (v_hash, v_signed);

  insert into public.trades (token, payload, user_id)
  values (p_token, p_payload, auth.uid());
  return p_token;
end;
$$;
revoke all on function public.create_trade(text, jsonb) from public;
grant execute on function public.create_trade(text, jsonb) to anon, authenticated;

-- _feedback_rate_limit: body from 138 (the live definition), limits rewritten.
-- Shared by submit_feedback and reply_my_feedback, which call it unchanged.
create or replace function public._feedback_rate_limit()
returns void
language plpgsql
set search_path to 'public', 'extensions'
as $$
declare
  v_signed boolean := (select auth.uid()) is not null;
  v_hash   text;
  v_recent int;
  v_total  int;
begin
  -- 10 messages / hour / account or address.
  v_hash := public._rate_bucket('packsink-feedback');
  delete from public.feedback_submit_events where created_at < now() - interval '2 hours';
  select count(*) into v_recent from public.feedback_submit_events
    where ip_hash = v_hash and created_at > now() - interval '1 hour';
  if v_recent >= 10 then
    raise exception 'rate limited: too much feedback submitted % try again in an hour', chr(8212);
  end if;
  -- Per pool. Past 60 only light writers get in; at 120 nobody does.
  select count(*) into v_total from public.feedback_submit_events
    where signed_in = v_signed and created_at > now() - interval '1 hour';
  if v_total >= 120 or (v_total >= 60 and v_recent >= 2) then
    raise exception 'rate limited: too much feedback submitted % try again in an hour', chr(8212);
  end if;
  insert into public.feedback_submit_events (ip_hash, signed_in) values (v_hash, v_signed);
end;
$$;
revoke all on function public._feedback_rate_limit() from public, anon, authenticated;

notify pgrst, 'reload schema';
