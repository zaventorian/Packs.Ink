-- 69_elo_tracked_stores_service_role_grant.sql
-- Fix: scripts/elo/sync_elo_tracked_stores.py (and the new Sync step in the
-- daily Discover-SCs workflow) upserts public.elo_tracked_stores using the
-- service_role key, but migration 66 created the table without granting writes
-- to service_role. service_role does NOT inherit table privileges implicitly
-- (same trap fixed for the price matviews in migration 45), so every sync run
-- 403'd with: "permission denied for table elo_tracked_stores" (42501).
--
-- Consequence: elo_tracked_stores went stale — new Chicagoland stores and new
-- LOCATIONS of tracked chains (e.g. "Chupacabra Games Joliet", store_id 20733,
-- event 586841) never reached the ELO "Upcoming SCs" tab even after their SC was
-- discovered. This grant unblocks the automated sync.
--
-- Idempotent; safe to re-run.

grant select, insert, update, delete on public.elo_tracked_stores to service_role;

notify pgrst, 'reload schema';
