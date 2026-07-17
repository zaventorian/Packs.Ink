-- 104_prerelease_events.sql
-- Upcoming set-launch Prerelease events (scraped from Ravensburger Play), the
-- sibling of public.set_championships. Powers the "Prereleases" mode of the
-- home "Upcoming near me" box. Populated by scripts/elo/discover_prereleases.py
-- (RPH /api/v2/events/). Same shape/RLS/grants as set_championships so the
-- frontend can query either table with an identical column list.
-- Idempotent; safe to re-run.

create table if not exists public.prerelease_events (
  event_id        bigint primary key,
  name            text,
  set_name        text not null,
  store_id        bigint,
  store_name      text,
  store_website   text,
  start_datetime  timestamptz,
  end_datetime    timestamptz,
  timezone        text,
  full_address    text,
  city text, state text, country text,
  latitude double precision, longitude double precision,
  registered_user_count integer,
  capacity integer,
  cost_cents integer, currency text,
  gameplay_format text,
  display_status text,
  url text,
  scraped_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists prerelease_events_start_idx   on public.prerelease_events (start_datetime);
create index if not exists prerelease_events_country_idx on public.prerelease_events (country);
alter table public.prerelease_events enable row level security;
drop policy if exists "public read prerelease_events" on public.prerelease_events;
create policy "public read prerelease_events" on public.prerelease_events for select using (true);
grant select on public.prerelease_events to anon, authenticated;
-- service_role does NOT inherit grants — the discovery script upserts as service_role.
grant select, insert, update, delete on public.prerelease_events to service_role;

notify pgrst, 'reload schema';
