-- 121_lorcana_events_history.sql — keep the events we used to throw away.
--
-- public.lorcana_events is an UPCOMING-events feed: discover_events.py refreshes
-- it daily from RPH (display_statuses=upcoming) and then sweeps rows older than
-- KEEP_PAST_DAYS so the table doesn't grow without bound. That sweep was
-- deleting the only record we have of what a store actually ran.
--
-- Ravensburger Play Hub store tiers are scored on Total Events / Unique Fans /
-- Event Tickets over the four most recent set seasons, across EVERY event type —
-- locals and league nights count the same as Set Championships. The Elo ingest
-- can't answer that (it's a curated, SC-shaped, hand-compiled list), but the
-- daily discovery pull already sees all of it, tagged kind='sc'|'prerelease'|
-- 'other' with registered_user_count — which IS the Event Tickets metric.
--
-- So: archive before the sweep instead of deleting outright. From the first run
-- after this lands, every event that passes through the feed is kept forever.
-- This does NOT backfill what was already swept; recovering that depends on
-- whether RPH will serve past events at all (see scripts/elo/probe_rph_history.py).
--
-- Columns mirror lorcana_events exactly so the archive step is a straight copy
-- (see archive_past_events() in discover_events.py) — if you add a column there,
-- add it here too or the copy silently drops it.

create table if not exists public.lorcana_events_history (
  event_id              bigint primary key,
  name                  text,
  kind                  text,                 -- 'sc' | 'prerelease' | 'other'
  set_name              text,                 -- nullable: a league night belongs to no set
  store_id              bigint,
  store_name            text,
  store_website         text,
  start_datetime        timestamptz,
  end_datetime          timestamptz,
  timezone              text,
  full_address          text,
  city                  text,
  state                 text,
  country               text,
  latitude              double precision,
  longitude             double precision,
  -- Registrations as of the LAST time the upcoming feed showed us this event,
  -- i.e. roughly the day before it ran. Day-of signups are not reflected, so
  -- treat this as a floor on attendance rather than a final count.
  registered_user_count integer,
  capacity              integer,
  cost_cents            integer,
  currency              text,
  gameplay_format       text,
  display_status        text,
  url                   text,
  last_seen_at          timestamptz,          -- last daily pull that saw it listed
  archived_at           timestamptz not null default now()
);

-- store_id + time is the tier query ("this store, these four seasons"); the
-- start_datetime index also serves the archive step's own cutoff scan.
create index if not exists lorcana_events_history_store_idx
  on public.lorcana_events_history (store_id, start_datetime desc);
create index if not exists lorcana_events_history_start_idx
  on public.lorcana_events_history (start_datetime desc);
create index if not exists lorcana_events_history_kind_idx
  on public.lorcana_events_history (kind);
create index if not exists lorcana_events_history_set_idx
  on public.lorcana_events_history (set_name);

alter table public.lorcana_events_history enable row level security;

-- Same posture as lorcana_events: this is the public RPH events listing, just
-- after the fact. Read for everyone, writes only via the service key.
drop policy if exists "public read lorcana_events_history" on public.lorcana_events_history;
create policy "public read lorcana_events_history"
  on public.lorcana_events_history for select using (true);

grant select on public.lorcana_events_history to anon, authenticated;
-- service_role does NOT inherit grants implicitly (per the matview grant trap in
-- CLAUDE.md) — the discovery script writes with the service key, so be explicit.
grant select, insert, update, delete on public.lorcana_events_history to service_role;

notify pgrst, 'reload schema';
