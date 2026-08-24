-- 126_deck_versions_grants.sql — the GRANT that 125 forgot.
--
-- Migration 125 created deck_versions with RLS policies but no table grants, so
-- an owner reading their own history got a flat 403 from PostgREST before RLS
-- was ever consulted. Caught the moment 125 went live: the History modal fell
-- through to its "isn't switched on yet" branch, because deckVersionsUnavailable
-- can't tell "no such table" from "no permission" — and shouldn't try.
--
-- This is the table version of the rule CLAUDE.md already states for matviews:
-- a new relation grants nothing implicitly. RLS narrows what a role can see; it
-- cannot hand out access the role was never granted.
--
-- anon is deliberately NOT granted. Shared reads go through
-- get_shared_deck_versions, which is SECURITY DEFINER and so needs no grant on
-- the caller's side — and giving anon a direct grant would put the whole table
-- one RLS-policy mistake away from being public.
--
-- Applied: NOT YET (staged for Zaven).

grant select, delete on public.deck_versions to authenticated;
grant select, insert, update, delete on public.deck_versions to service_role;

-- One artifact row from diagnosing the 403: save_deck_version is SECURITY
-- DEFINER, so the WRITE succeeded even while every read was denied — which is
-- how we proved it was a grant and not the policy. It has an empty card list
-- and would otherwise show up as a real "v1" with a blank changelog. Removed
-- here rather than left for someone to puzzle over. No-op if it's already gone.
delete from public.deck_versions
 where deck_id = 'd9cb0df2-5e1a-4acc-8392-fed7ad31420b'
   and cards = '[]'::jsonb;

notify pgrst, 'reload schema';
