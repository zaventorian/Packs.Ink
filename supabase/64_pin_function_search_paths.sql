-- 64: Pin search_path on the three trigger/utility functions the Supabase
-- linter flags as `function_search_path_mutable` (0011). A function without a
-- pinned search_path resolves unqualified names against the caller's
-- search_path, which is a privilege-escalation vector for any function that
-- could be invoked in an attacker-influenced search_path context. These three
-- are SECURITY INVOKER triggers so the risk is low, but pinning is free
-- defense-in-depth and clears the advisor warning.
--
-- Behavior-preserving (no body change), so safe to apply anytime, independent
-- of client deploys. `extensions` is included because the rotate_* functions
-- transitively call public.gen_share_token() which uses pgcrypto (gen_random_*)
-- from the extensions schema.

alter function public.set_updated_at()                        set search_path = public, extensions;
alter function public.rotate_share_token_on_private()         set search_path = public, extensions;
alter function public.rotate_collection_token_on_all_private() set search_path = public, extensions;

-- Lock down refresh_graded_prices_latest to match its 4 sibling refresh
-- functions. It alone carried a PUBLIC EXECUTE grant, so anon/authenticated
-- could POST /rest/v1/rpc/refresh_graded_prices_latest and trigger an expensive
-- REFRESH MATERIALIZED VIEW on demand (cost/DoS vector on a metered project).
-- Revoking from PUBLIC leaves the explicit postgres + service_role grants, so
-- the ETL (service_role) still refreshes normally.
revoke execute on function public.refresh_graded_prices_latest() from public;

notify pgrst, 'reload schema';
