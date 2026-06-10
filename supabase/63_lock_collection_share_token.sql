-- 63: Lock down collection_share_token so it can't be harvested via the public
-- profiles SELECT grant.
--
-- Bug: migration 18 grants `select` on all of `public.profiles` to anon +
-- authenticated with policy `using (true)`, and migration 39 added
-- `collection_share_token` as a plain column on that same table. That made the
-- secret that gates every *unlisted* collection share readable in bulk by
-- anyone holding the publishable anon key:
--   GET /rest/v1/profiles?select=user_id,collection_share_token
-- An attacker could scrape every token and call get_shared_collection_* to read
-- collections (incl. amount_paid) that the owner intended to share by link only.
--
-- Fix: revoke SELECT on just the token column from the API roles. Public
-- display fields (display_name, avatar_url) and the visibility flags stay
-- readable. The owner reads their OWN token through a SECURITY DEFINER RPC that
-- is hard-scoped to auth.uid(), so no caller can read anyone else's token.
--
-- DEPLOY ORDER (important): the create-function half is additive and safe to
-- apply anytime. The REVOKE breaks the *old* client (it still selects the token
-- column in its profile read), so apply the REVOKE only once the new Index.html
-- that reads the token via get_my_collection_settings() is live.

create or replace function public.get_my_collection_settings()
returns table (
  collection_share_token       text,
  collection_raw_visibility    text,
  collection_sealed_visibility text,
  collection_graded_visibility text
)
language sql
security definer
set search_path = public
stable
as $$
  select p.collection_share_token,
         p.collection_raw_visibility,
         p.collection_sealed_visibility,
         p.collection_graded_visibility
  from public.profiles p
  where p.user_id = auth.uid();
$$;

revoke all on function public.get_my_collection_settings() from public;
grant execute on function public.get_my_collection_settings() to authenticated;

-- The actual lockdown. Apply at deploy time (see DEPLOY ORDER note above).
--
-- A column-level `revoke select (collection_share_token)` does NOT work here:
-- migration 18 granted SELECT at the TABLE level, and Postgres will not subtract
-- a single column from a table-level grant (verified live — the token stays
-- readable). The only way to hide one column is to drop the table-level SELECT
-- and re-grant SELECT on the explicit safe-column allow-list (everything except
-- collection_share_token). INSERT/UPDATE grants are untouched, so owner writes
-- still work; the owner reads their own token via the SECURITY DEFINER RPC above
-- (which bypasses table grants).
revoke select on public.profiles from anon, authenticated;
grant select (
  user_id, display_name, avatar_url, created_at, updated_at,
  collection_raw_visibility, collection_sealed_visibility, collection_graded_visibility
) on public.profiles to anon, authenticated;

notify pgrst, 'reload schema';
