-- 183: let service_role read tournaments.
-- reconcile_catalog.py --watch checks that tournament results are not stale,
-- and it runs with the service key. service_role had no SELECT on
-- public.tournaments, so the check failed with 42501 and skipped itself,
-- non-fatally, every day. Read-only; RLS is unaffected (service_role bypasses it).

grant select on public.tournaments to service_role;

notify pgrst, 'reload schema';
