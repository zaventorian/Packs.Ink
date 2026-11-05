-- 203: Discover reads decks minus tournament decks that finished outside a top 8.
--
-- Tournaments can now carry their whole field (scripts/upload_tournament.py, 202):
-- DLC Bangkok went up with 706 decks on 2026-11-04, and Discover's window of the
-- 200 most recently updated public decks was then all Bangkok. Discover keeps
-- tournament top 8s (as before, when only top 8s were uploaded) and every other
-- deck, the ownerless Coconut starters included; it filters on rank, not on
-- user_id. security_invoker, so the decks RLS (own or public) still applies.
create or replace view public.discover_decks_v
with (security_invoker = on) as
select d.*
  from public.decks d
 where not exists (
   select 1 from public.tournament_decks td
    where td.deck_id = d.id and td.place_rank > 8
 );

grant select on public.discover_decks_v to anon, authenticated;
