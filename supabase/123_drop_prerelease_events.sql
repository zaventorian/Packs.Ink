-- 123_drop_prerelease_events.sql
-- Drop the dead prerelease_events table.
--
-- Dead since migration 113: lorcana_events holds EVERY upcoming RPH event with
-- kind ∈ sc|prerelease|other, and the client's "Upcoming near me" box reads it
-- exclusively through get_nearby_lorcana_events() — nothing has queried
-- prerelease_events since that client shipped (confirmed live on prod).
--
-- The last writer was scripts/elo/discover_prereleases.py's standalone main();
-- that upsert path was retired 2026-08-22 (the script is analysis-only now —
-- its classify() remains imported by discover_events.py, which writes the
-- kind='prerelease' rows into lorcana_events). The daily workflow
-- (discover_scs.yml) never called it.
--
-- Provenance: migration 104 created the table (+ RLS/grants mirroring
-- set_championships). No RPC, view, or matview references it. Nothing to
-- archive — it holds only upcoming events, all of which lorcana_events
-- already carries with more context.

begin;

drop table if exists public.prerelease_events;

commit;

notify pgrst, 'reload schema';
