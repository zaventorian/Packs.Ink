-- 139_calendar_events.sql — the curated Lorcana calendar (2026-09-12).
--
-- The four things a player wants dated that NO feed can tell us:
--   set   — prerelease weekend / LGS release / retail release
--   product — a release not tied to a set (the Rapunzel gift set, the book)
--   dlc   — Disney Lorcana Challenge: the official championship weekends
--   ccq   — Challenge Championship Qualifier
--
-- Why a table rather than a const in Index.html (the EVENT_TILES / LORCANA_PINS
-- pattern): release dates SLIP. Ravensburger moves them, and a const means every
-- correction is a commit, a cache bump and a metered deploy that only a laptop
-- can perform. Here a date change is an edit from the phone, live immediately.
--
-- ⚠ SET RELEASES ARE NOT SEEDED HERE, AND THAT IS DELIBERATE. The client merges
-- SET_RELEASE_DATES (Index.html — 13 sets x {lgs, retail}, already correct, and
-- already what the Set EV chart's markers are drawn from) with this table, and a
-- row here WINS on (kind, set_name, subtitle). So history is free and can never
-- disagree with the EV chart, while a future set — or a slipped date — is
-- editable without a deploy. Seeding them would fork one fact into two stores.
--
-- ⚠ `confirmed` exists because CCQs cannot be detected, only guessed at. Probed
-- 2026-09-12: the 11 CCQ-ish events on Ravensburger Play are all store-created
-- with ad-hoc names ("Tournament Lorcana Core - possible CCQ", "Woodzshacktcg
-- multi case ccq") and classified kind='other'. The phase_template_group trick
-- that makes Set Championship detection robust does NOT work — the template two
-- of them share (7ffe1457…) turns out to be a generic Swiss template covering
-- Set Championships and "Sunday Evening Weekly Play" alike, 10 of 992 upcoming
-- events in the sample. So scripts/scan_ccq_candidates.py PROPOSES rows with
-- confirmed=false and a person rules on them, the same shape as the acks in
-- scripts/catalog_watch.json. Never flip a candidate to confirmed in a script.

create table if not exists public.calendar_events (
  id          uuid primary key default gen_random_uuid(),
  kind        text not null check (kind in ('set','product','dlc','ccq')),
  title       text not null check (char_length(title) between 1 and 200),
  -- "Prerelease" / "LGS release" / "Retail release" for a set; the venue for a
  -- DLC. Part of the merge key against SET_RELEASE_DATES, so for kind='set' it
  -- must match the client's SET_RELEASE_LABELS spelling exactly or the row adds
  -- a duplicate entry instead of overriding the derived one.
  subtitle    text check (subtitle is null or char_length(subtitle) <= 120),
  -- The calendar-grid key: a plain calendar day, never shifted into a viewer's
  -- zone (a release is "March 7" everywhere, not 8pm the night before in Tokyo).
  starts_on   date not null,
  ends_on     date check (ends_on is null or ends_on >= starts_on),
  -- Optional precise start, for a thing that happens at a TIME (a CCQ's 10am
  -- registration). Null = all-day, which is how every set release renders.
  -- The .ics writer picks VALUE=DATE vs a stamped DTSTART off exactly this.
  starts_at   timestamptz,
  timezone    text check (timezone is null or char_length(timezone) <= 64),
  location    text check (location is null or char_length(location) <= 200),
  url         text check (url is null or char_length(url) <= 500),
  set_name    text check (set_name is null or char_length(set_name) <= 120),
  -- 'manual' | 'ccq-scan'. Which rows a re-scan is allowed to touch: a hand-typed
  -- row must survive a scan that no longer proposes it.
  source      text not null default 'manual',
  -- lorcana_events.event_id when this came from (or was promoted from) a real
  -- RPH event. Doubles as the scan's dedupe key, so re-running proposes nothing
  -- twice; unique so two scans can't race a duplicate in.
  event_id    bigint unique,
  confirmed   boolean not null default true,
  notes       text check (notes is null or char_length(notes) <= 1000),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists calendar_events_starts_idx on public.calendar_events (starts_on);
create index if not exists calendar_events_kind_starts_idx on public.calendar_events (kind, starts_on);
-- The public calendar's hot query is "confirmed, from today forward".
create index if not exists calendar_events_public_idx
  on public.calendar_events (starts_on) where confirmed;

alter table public.calendar_events enable row level security;

-- ⚠ The OR here is the documented RLS-broadening shape, and it is intended: an
-- admin must see unconfirmed candidates to rule on them. The CONSEQUENCE is that
-- an unfiltered select returns candidates too, so the public calendar's own read
-- passes .eq("confirmed", true) explicitly rather than trusting the policy —
-- otherwise an admin would silently browse a calendar nobody else can see.
drop policy if exists calendar_events_read on public.calendar_events;
create policy calendar_events_read on public.calendar_events
  for select to anon, authenticated
  using (confirmed or (select public.is_graded_admin()));

drop policy if exists calendar_events_admin_insert on public.calendar_events;
create policy calendar_events_admin_insert on public.calendar_events
  for insert to authenticated with check ((select public.is_graded_admin()));

drop policy if exists calendar_events_admin_update on public.calendar_events;
create policy calendar_events_admin_update on public.calendar_events
  for update to authenticated
  using ((select public.is_graded_admin()))
  with check ((select public.is_graded_admin()));

drop policy if exists calendar_events_admin_delete on public.calendar_events;
create policy calendar_events_admin_delete on public.calendar_events
  for delete to authenticated using ((select public.is_graded_admin()));

-- A new table grants nothing implicitly (the migration-126 lesson): without
-- these, every read is a flat 403 before RLS is ever consulted.
grant select on public.calendar_events to anon, authenticated;
grant insert, update, delete on public.calendar_events to authenticated;
grant select, insert, update, delete on public.calendar_events to service_role;

-- Seed: ONLY what the repo already holds as fact. EVENT_TILES in Index.html
-- carries these two with their dates and fanfinity URLs, so they are a copy of a
-- committed fact rather than a date somebody remembered. Everything else is
-- typed in through the editor — inventing a street date for a product is the one
-- failure a calendar must never have, and a confident wrong date is worse than
-- an empty row. Set releases arrive from SET_RELEASE_DATES (see above), so the
-- calendar is populated on day one regardless.
insert into public.calendar_events (id, kind, title, subtitle, starts_on, ends_on, location, url, source)
values
  ('7afbb8d1-51f9-5a5a-bca9-6d6636a9fc42', 'dlc', 'North American Championship', 'Disney Lorcana Challenge',
   date '2026-08-28', date '2026-08-30', 'Disneyland Hotel, Anaheim, CA',
   'https://www.fanfinity.gg/event/disney-lorcana-tcg-challenge-north-american-championship-2026/', 'manual'),
  ('27870d16-a0e4-553a-a593-cd1396d08af3', 'dlc', 'European Championship', 'Disney Lorcana Challenge',
   date '2026-09-11', date '2026-09-13', 'Disneyland Paris',
   'https://www.fanfinity.gg/event/disney-lorcana-tcg-challenge-european-championship-2026/', 'manual')
-- ⚠ Fixed ids, so re-running this migration UPDATES these two instead of
-- inserting a second copy. `on conflict do nothing` on its own could never have
-- worked here: the only unique column is event_id, which is null on both, so a
-- re-run would have duplicated them silently.
on conflict (id) do update set
  starts_on = excluded.starts_on, ends_on = excluded.ends_on,
  location  = excluded.location,  url     = excluded.url,
  updated_at = now();

notify pgrst, 'reload schema';
