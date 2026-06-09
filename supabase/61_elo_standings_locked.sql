-- 61_elo_standings_locked.sql
--
-- Add a `locked` flag to elo_event_standings_official so manually-corrected
-- placements survive future runs of `backfill_official_standings.py --force`.
--
-- Background: the RPH /tv/standings/ API occasionally returns garbage for
-- bracket-cut events (e.g. e276338 had the Final stored as
-- "LoL Xelephanor vs Lil.boy.jay 0-0 draw" — Lil.boy.jay was eliminated in
-- SF). We hand-correct those rows in the local DB, then export. Without a
-- locked flag, the next --force backfill would clobber the fix.
--
-- Convention: lock at the EVENT level (every row for a locked event has
-- locked=true). Backfill skips the entire event when ANY row is locked,
-- because backfill replaces the full row set per event.

alter table public.elo_event_standings_official
  add column if not exists locked boolean not null default false;

create index if not exists elo_event_standings_official_locked_idx
  on public.elo_event_standings_official (event_id)
  where locked = true;

notify pgrst, 'reload schema';
