-- 93: Silence the residual `auth_rls_initplan` advisor false-positives.
-- Migration 91 wrapped the admin-write policies as `(select is_*_admin(auth.uid()))`,
-- which already hoists the whole check to a once-per-statement initplan — but the
-- Supabase linter still flags them because `auth.uid()` appears textually as an
-- argument that isn't itself in a subselect. Nest it: `is_*_admin((select auth.uid()))`.
-- Purely cosmetic (no behavior/perf change); gets the advisor to 0.

alter policy "elo_eso_admin_write" on public.elo_event_standings_official
  using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
alter policy "elo_events_admin_write" on public.elo_events
  using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
alter policy "elo_matches_admin_write" on public.elo_matches
  using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
alter policy "elo_players_admin_write" on public.elo_players
  using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
alter policy "elo_ratings_admin_write" on public.elo_ratings
  using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
alter policy "tournament_decks_admin_write" on public.tournament_decks
  using ((select is_tournament_admin((select auth.uid())))) with check ((select is_tournament_admin((select auth.uid()))));
alter policy "tournaments_admin_write" on public.tournaments
  using ((select is_tournament_admin((select auth.uid())))) with check ((select is_tournament_admin((select auth.uid()))));

notify pgrst, 'reload schema';
