-- Migration 189: anon reads attendance by pseudonym only.
--
-- STAGED. Apply only AFTER the client that reads person_key / played (the
-- commit that ships with migration 188) is LIVE and the edge has been
-- purged. Applied earlier, the live Store Status tab fails: it selects
-- best_identifier / rph_user_id and filters on the standing columns, and
-- every one of those becomes a 42501 for anon.
--
-- Revokes the table-wide SELECT from anon and authenticated and grants back
-- exactly what the Store Status tab reads: the event, the person key (188),
-- whether they played, and the registration status the no-results fallback
-- uses. Names, account ids, the "First L." account name, standings, records
-- and guest flags stay readable only with the service key (the attendance
-- scrape, report_store_tiers.py, diagnose_store_fans.py).
--
-- Rollback: grant select on public.rph_event_attendance to anon, authenticated;
--
-- Idempotent.

revoke select on public.rph_event_attendance from anon, authenticated;
grant select (event_id, person_key, played, registration_status)
  on public.rph_event_attendance to anon, authenticated;

notify pgrst, 'reload schema';
