-- 133_anon_write_backstop.sql
--
-- STAGED — not applied; review + paste in the SQL editor.
--
-- Audit item: H1 — the per-IP rate limits on the two anonymous write RPCs read
-- the FIRST hop of X-Forwarded-For (102_trade_create_rate_limit.sql:45-52,
-- 106_feedback.sql:56-62). Edge proxies APPEND the real client address to
-- whatever X-Forwarded-For the caller already sent, so the first element is
-- attacker-chosen: a fresh random header per request is a fresh bucket per
-- request, and create_trade (anon, <= 100 KB/row, 30-day retention) and
-- submit_feedback (anon, 5 KB/row, no retention) become unbounded inserts.
--
-- WHAT THIS CHANGES
--   1. public._client_ip() — new helper. Prefers the `cf-connecting-ip`
--      request header (Cloudflare overwrites it with the true client address;
--      a caller cannot forge it through Cloudflare). If that header is absent
--      it falls back to the CURRENT behaviour (first hop of x-forwarded-for),
--      so nothing regresses on a path that does not pass through Cloudflare.
--   2. create_trade(text, jsonb) — body copied VERBATIM from
--      102_trade_create_rate_limit.sql:26-69 (its latest definition). Only two
--      edits: (a) `v_ip := public._client_ip()` replaces the inline header
--      parse; (b) a global backstop — at most 300 trade links per hour across
--      ALL callers — raising the same 'rate limited: …' error the per-IP limit
--      raises (the client shows error.message verbatim; it matches no string).
--   3. submit_feedback(text, text, text) — body copied VERBATIM from
--      106_feedback.sql:37-83 (latest); the same two edits, global backstop
--      120 per hour.
--   The per-IP limits (30/h trades, 10/h feedback), the token/payload checks,
--   the 2-hour self-prune and the grants are unchanged.
--
-- CONFIRM WHICH HEADER CARRIES THE REAL CLIENT IP (once, before applying)
--   The SQL editor does not go through PostgREST, so current_setting(
--   'request.headers', true) is null there. Create the throwaway echo helper
--   from supabase/diagnostics/public_release_live_checks.sql section 7, then
--   from the site's devtools console:
--     sbClient.rpc("_echo_request_headers").then(r => console.log(r.data))
--   and once more with a forged first hop:
--     fetch(SUPABASE_URL + "/rest/v1/rpc/_echo_request_headers", {method: "POST",
--       headers: {...sbHeaders(), "Content-Type": "application/json",
--                 "X-Forwarded-For": "203.0.113.9"}, body: "{}"})
--       .then(r => r.json()).then(console.log)
--   Expected: `cf-connecting-ip` is your real address both times, while
--   `x-forwarded-for` STARTS WITH 203.0.113.9 in the second call — that is the
--   defect. If `cf-connecting-ip` is absent in your logs, the fallback below is
--   exactly the pre-133 behaviour and you should look for whichever header the
--   gateway does set (e.g. `x-real-ip`). Drop the helper afterwards.
--
-- PRECONDITIONS: migrations 54, 65, 102 and 106 applied (trades,
--   trade_create_events, feedback, feedback_submit_events exist; pgcrypto lives
--   in `extensions`). CREATE OR REPLACE keeps the existing ACLs; the grants are
--   re-asserted anyway.
--
-- Idempotent.

-- 1. Client-IP helper. A plain (invoker) function: it only reads a transaction
--    GUC that PostgREST sets, and it is called from inside the two SECURITY
--    DEFINER functions below, so the privilege check runs against their owner.
--    Not callable through the API.
create or replace function public._client_ip()
returns text
language plpgsql
stable
set search_path = ''
as $$
declare
  v_headers jsonb;
  v_cf      text;
  v_xff     text;
begin
  begin
    v_headers := (current_setting('request.headers', true))::jsonb;
  exception when others then
    return '';
  end;
  v_cf := coalesce(v_headers ->> 'cf-connecting-ip', '');
  if v_cf <> '' then
    return btrim(v_cf);
  end if;
  -- Fallback = pre-133 behaviour (first hop of x-forwarded-for).
  v_xff := coalesce(v_headers ->> 'x-forwarded-for', '');
  return btrim(split_part(v_xff, ',', 1));
end;
$$;

revoke all on function public._client_ip() from public, anon, authenticated;

-- 2. create_trade — body from 102_trade_create_rate_limit.sql:26-69.
create or replace function public.create_trade(p_token text, p_payload jsonb)
returns text
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_ip     text;
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

  -- 133: was the first hop of x-forwarded-for (caller-controlled).
  v_ip := public._client_ip();
  v_hash := encode(digest('packsink-trade|' || coalesce(nullif(v_ip, ''), 'unknown'), 'sha256'), 'hex');

  delete from public.trade_create_events where created_at < now() - interval '2 hours';

  select count(*) into v_recent
  from public.trade_create_events
  where ip_hash = v_hash and created_at > now() - interval '1 hour';

  if v_recent >= 30 then
    raise exception 'rate limited: too many trade links created — try again in an hour';
  end if;

  -- 133: global backstop across every caller. A spoofed-header bypass of the
  -- per-IP bucket is still bounded to 300 rows (<= 30 MB) an hour.
  select count(*) into v_total
  from public.trade_create_events
  where created_at > now() - interval '1 hour';

  if v_total >= 300 then
    raise exception 'rate limited: too many trade links created — try again in an hour';
  end if;

  insert into public.trade_create_events (ip_hash) values (v_hash);

  insert into public.trades (token, payload, user_id)
  values (p_token, p_payload, auth.uid());
  return p_token;
end;
$$;

revoke all on function public.create_trade(text, jsonb) from public;
grant execute on function public.create_trade(text, jsonb) to anon, authenticated;

-- 3. submit_feedback — body from 106_feedback.sql:37-83.
create or replace function public.submit_feedback(
  p_comment text, p_page text default null, p_user_agent text default null)
returns uuid
language plpgsql
security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_id     uuid;
  v_email  text;
  v_ip     text;
  v_hash   text;
  v_recent int;
  v_total  int;
begin
  if p_comment is null or length(btrim(p_comment)) = 0 then
    raise exception 'empty feedback';
  end if;

  -- IP-hash rate limit: 10 submissions / hour / IP.
  -- 133: was the first hop of x-forwarded-for (caller-controlled).
  v_ip := public._client_ip();
  v_hash := encode(digest('packsink-feedback|' || coalesce(nullif(v_ip, ''), 'unknown'), 'sha256'), 'hex');
  delete from public.feedback_submit_events where created_at < now() - interval '2 hours';
  select count(*) into v_recent from public.feedback_submit_events
    where ip_hash = v_hash and created_at > now() - interval '1 hour';
  if v_recent >= 10 then
    raise exception 'rate limited: too much feedback submitted — try again in an hour';
  end if;
  -- 133: global backstop across every caller (120 / hour).
  select count(*) into v_total from public.feedback_submit_events
    where created_at > now() - interval '1 hour';
  if v_total >= 120 then
    raise exception 'rate limited: too much feedback submitted — try again in an hour';
  end if;
  insert into public.feedback_submit_events (ip_hash) values (v_hash);

  if auth.uid() is not null then
    select email into v_email from auth.users where id = auth.uid();
  end if;

  insert into public.feedback (user_id, user_email, page, comment, user_agent)
  values (auth.uid(), v_email,
          left(coalesce(p_page, ''), 400),
          left(p_comment, 5000),
          left(coalesce(p_user_agent, ''), 500))
  returning id into v_id;
  return v_id;
end;
$$;

revoke execute on function public.submit_feedback(text, text, text) from public;
grant execute on function public.submit_feedback(text, text, text) to anon, authenticated;

notify pgrst, 'reload schema';
