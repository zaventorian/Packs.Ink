-- 38_tournament_view_invoker.sql — flip tournament_results_v to SECURITY INVOKER.
--
-- Supabase's linter flags views created by the owner role as SECURITY DEFINER,
-- which bypasses the querying user's RLS. The view itself only joins three
-- tables that already have permissive public SELECT policies, but explicitly
-- running as the invoker is the canonical pattern and satisfies the lint.

alter view public.tournament_results_v set (security_invoker = on);

notify pgrst, 'reload schema';
