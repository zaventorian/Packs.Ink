-- 122_rph_event_attendance.sql — who actually PLAYED, per event.
--
-- RPH's two people-metrics are not what we've been approximating:
--
--   Event Tickets — "the total number of players across all events". Players,
--                   not registrants. We were using lorcana_events.
--                   registered_user_count, which is pre-registrations frozen at
--                   the last time the upcoming feed listed the event. That is
--                   wrong in BOTH directions: it misses walk-ins who played
--                   without registering (stores with ~1 ticket per event are
--                   this), and counts no-shows who registered and didn't play.
--
--   Unique Fans   — "individuals that have played in at least 1 event". We were
--                   counting distinct players in elo_matches, which only exists
--                   for the SC-shaped slice the Elo pipeline ingested, so most
--                   of a store's events contributed nobody.
--
-- Both come from the same place: /api/v2/events/{id}/registrations/, which the
-- probe confirmed is readable for PAST events and carries the user, their
-- standing, and their match record.
--
-- elo_event_roster_members can't be reused: its parent FKs to
-- set_championships, so it structurally cannot hold a league night, and it
-- stores no participation fields.
--
-- ── Why the raw fields, not a computed flag ────────────────────────────────
-- "Played" is a judgement call — a final standing, or any match played, or a
-- registration_status. Storing the components means the rule can be changed in
-- the client without re-scraping ~4,200 events. Don't collapse this to a
-- boolean at ingest.

create table if not exists public.rph_event_attendance (
  event_id                bigint not null,
  -- best_identifier is the tournament display name and the join key into
  -- elo_players.display_name; rph_user_id is the stable account id, which is
  -- the one to count distinct on (display names get changed).
  best_identifier         text   not null,
  rph_user_id             bigint,
  account_name            text,
  registration_status     text,
  -- Participation. A player who registered and never sat down has no standing
  -- and no match record; that is the difference between a registrant and a
  -- ticket.
  final_place_in_standings int,
  matches_won             int,
  matches_lost            int,
  matches_drawn           int,
  total_match_points      int,
  is_guest                boolean,
  scraped_at              timestamptz not null default now(),
  primary key (event_id, best_identifier)
);

-- The tier queries are "this store, these seasons", which resolve to a set of
-- event_ids, then distinct users within them.
create index if not exists rph_event_attendance_event_idx
  on public.rph_event_attendance (event_id);
create index if not exists rph_event_attendance_user_idx
  on public.rph_event_attendance (rph_user_id);

-- Which events have been scraped, so a re-run can skip them cheaply and so an
-- event with genuinely zero attendance is distinguishable from one never tried.
create table if not exists public.rph_event_attendance_scans (
  event_id     bigint primary key,
  player_count int not null default 0,
  row_count    int not null default 0,
  scraped_at   timestamptz not null default now()
);

alter table public.rph_event_attendance       enable row level security;
alter table public.rph_event_attendance_scans enable row level security;

-- Same posture as lorcana_events_history: this is the public RPH event listing's
-- participant side. Read for everyone, writes only via the service key.
drop policy if exists "public read rph_event_attendance" on public.rph_event_attendance;
create policy "public read rph_event_attendance"
  on public.rph_event_attendance for select using (true);
drop policy if exists "public read rph_event_attendance_scans" on public.rph_event_attendance_scans;
create policy "public read rph_event_attendance_scans"
  on public.rph_event_attendance_scans for select using (true);

grant select on public.rph_event_attendance, public.rph_event_attendance_scans
  to anon, authenticated;
-- service_role does NOT inherit grants implicitly (per the matview grant trap).
grant select, insert, update, delete
  on public.rph_event_attendance, public.rph_event_attendance_scans to service_role;

notify pgrst, 'reload schema';
