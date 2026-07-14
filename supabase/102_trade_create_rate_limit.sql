-- Anonymous-write hardening for trade share links (pre-public-launch).
--
-- create_trade is deliberately callable by anon — unauthenticated users can
-- share a Trade Compare — which makes it a free anonymous write endpoint once
-- the site is public (each call can insert up to 100KB into `trades`).
-- The 30-day retention sweep bounds total growth but not burst spam.
--
-- This caps creations per source IP at 30/hour, tracked in a tiny
-- definer-only events table keyed by a salted SHA-256 of the caller's IP
-- (no raw IPs are stored — same privacy posture as before). The events
-- table self-prunes on every call (rows older than 2h).

create table if not exists public.trade_create_events (
  ip_hash    text        not null,
  created_at timestamptz not null default now()
);

create index if not exists trade_create_events_hash_time_idx
  on public.trade_create_events (ip_hash, created_at);

-- RLS on with no policies: only the SECURITY DEFINER function below touches it.
alter table public.trade_create_events enable row level security;

-- pgcrypto's digest() lives in the extensions schema on Supabase, so the
-- definer search_path must include it (see CLAUDE.md PostgREST gotchas).
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
begin
  if p_token is null or p_token !~ '^[A-Za-z0-9_-]{16,64}$' then
    raise exception 'invalid token';
  end if;
  if p_payload is null or length(p_payload::text) > 100000 then
    raise exception 'invalid or oversized payload';
  end if;

  -- First hop of X-Forwarded-For = client IP as seen by the API gateway.
  begin
    v_ip := split_part(coalesce(
      (current_setting('request.headers', true))::jsonb ->> 'x-forwarded-for', ''), ',', 1);
  exception when others then
    v_ip := '';
  end;
  v_hash := encode(digest('packsink-trade|' || coalesce(nullif(v_ip, ''), 'unknown'), 'sha256'), 'hex');

  delete from public.trade_create_events where created_at < now() - interval '2 hours';

  select count(*) into v_recent
  from public.trade_create_events
  where ip_hash = v_hash and created_at > now() - interval '1 hour';

  if v_recent >= 30 then
    raise exception 'rate limited: too many trade links created — try again in an hour';
  end if;

  insert into public.trade_create_events (ip_hash) values (v_hash);

  insert into public.trades (token, payload, user_id)
  values (p_token, p_payload, auth.uid());
  return p_token;
end;
$$;

notify pgrst, 'reload schema';
