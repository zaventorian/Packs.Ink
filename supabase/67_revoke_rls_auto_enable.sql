-- 67_revoke_rls_auto_enable.sql
--
-- Hardening: revoke EXECUTE on the rls_auto_enable() event-trigger helper from
-- the API roles. It's a SECURITY DEFINER function wired to a DDL event trigger
-- (it auto-enables RLS on newly created public tables). It should never be
-- reachable as a PostgREST RPC. Calling it outside a DDL event is inert
-- (pg_event_trigger_ddl_commands() returns empty rows), so this is defense-in-
-- depth, not a live-exploit fix. Flagged by Supabase advisor 0028
-- (anon_security_definer_function_executable).
--
-- Event triggers fire as the table owner regardless of any EXECUTE grant, so
-- removing the grant does NOT affect the auto-RLS behavior.

revoke execute on function public.rls_auto_enable() from public, anon, authenticated;

notify pgrst, 'reload schema';
