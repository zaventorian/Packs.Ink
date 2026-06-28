-- 90: Close the cross-user purchase-price leak on the collection tables.
--
-- Migration 65 stripped amount_paid / custom_value from the get_shared_collection_*
-- RPCs so collection-share VIEWERS can't see what an owner paid. But the underlying
-- tables still had a SELECT policy of the form:
--     (auth.uid() = user_id) OR (profile is public)
-- with a table-level column SELECT grant to `authenticated`. That "OR public" branch
-- let ANY signed-in user read every public collection's rows DIRECTLY via PostgREST,
-- including the hidden amount_paid / custom_value / notes columns — defeating mig 65.
--
-- The public/viewer path in the client ALWAYS goes through the SECURITY DEFINER
-- get_shared_collection_{raw,sealed,graded} RPCs (which already omit the cost columns).
-- Every direct table read in the client is `.eq("user_id", auth.uid())` (own only).
-- So the "OR public" branch on the table is redundant AND the leak vector: drop it,
-- making direct table SELECT strictly owner-only (the documented intent in CLAUDE.md:
-- "Direct table reads stay owner-only via RLS").
--
-- Same statements also wrap auth.uid() in a scalar subselect so the check is evaluated
-- once per statement instead of once per row (RLS initplan perf — see migration 91).

alter policy "collection_items: select own or public" on public.collection_items
  using ((select auth.uid()) = user_id);
alter policy "collection_items: select own or public" on public.collection_items
  rename to "collection_items: select own";

alter policy "sealed_collection_items: select own or public" on public.sealed_collection_items
  using ((select auth.uid()) = user_id);
alter policy "sealed_collection_items: select own or public" on public.sealed_collection_items
  rename to "sealed_collection_items: select own";

alter policy "graded_collection_items: select own or public" on public.graded_collection_items
  using ((select auth.uid()) = user_id);
alter policy "graded_collection_items: select own or public" on public.graded_collection_items
  rename to "graded_collection_items: select own";

notify pgrst, 'reload schema';
