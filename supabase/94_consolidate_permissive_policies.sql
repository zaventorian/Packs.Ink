-- 94: Consolidate multiple-permissive RLS (multiple_permissive_policies advisor).
-- Each of these 7 tables had BOTH an admin `FOR ALL` policy AND a public-read
-- `FOR SELECT (true)` policy, so every authenticated SELECT evaluated both. Admins
-- already read via the public-read policy, so the admin policy only needs to cover
-- WRITES. Split each `FOR ALL` into FOR INSERT / UPDATE / DELETE so it drops off the
-- SELECT path. The is_*_admin(auth.uid()) check stays wrapped in (select ...) so the
-- initplan optimization (migrations 91/93) is preserved. No behavior change:
-- non-admins still cannot write; admins still read (public policy) and write.

-- elo_event_standings_official
drop policy "elo_eso_admin_write" on public.elo_event_standings_official;
create policy "elo_eso_admin_insert" on public.elo_event_standings_official
  for insert to authenticated with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_eso_admin_update" on public.elo_event_standings_official
  for update to authenticated using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_eso_admin_delete" on public.elo_event_standings_official
  for delete to authenticated using ((select is_elo_admin((select auth.uid()))));

-- elo_events
drop policy "elo_events_admin_write" on public.elo_events;
create policy "elo_events_admin_insert" on public.elo_events
  for insert to authenticated with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_events_admin_update" on public.elo_events
  for update to authenticated using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_events_admin_delete" on public.elo_events
  for delete to authenticated using ((select is_elo_admin((select auth.uid()))));

-- elo_matches
drop policy "elo_matches_admin_write" on public.elo_matches;
create policy "elo_matches_admin_insert" on public.elo_matches
  for insert to authenticated with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_matches_admin_update" on public.elo_matches
  for update to authenticated using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_matches_admin_delete" on public.elo_matches
  for delete to authenticated using ((select is_elo_admin((select auth.uid()))));

-- elo_players
drop policy "elo_players_admin_write" on public.elo_players;
create policy "elo_players_admin_insert" on public.elo_players
  for insert to authenticated with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_players_admin_update" on public.elo_players
  for update to authenticated using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_players_admin_delete" on public.elo_players
  for delete to authenticated using ((select is_elo_admin((select auth.uid()))));

-- elo_ratings
drop policy "elo_ratings_admin_write" on public.elo_ratings;
create policy "elo_ratings_admin_insert" on public.elo_ratings
  for insert to authenticated with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_ratings_admin_update" on public.elo_ratings
  for update to authenticated using ((select is_elo_admin((select auth.uid())))) with check ((select is_elo_admin((select auth.uid()))));
create policy "elo_ratings_admin_delete" on public.elo_ratings
  for delete to authenticated using ((select is_elo_admin((select auth.uid()))));

-- tournament_decks
drop policy "tournament_decks_admin_write" on public.tournament_decks;
create policy "tournament_decks_admin_insert" on public.tournament_decks
  for insert to authenticated with check ((select is_tournament_admin((select auth.uid()))));
create policy "tournament_decks_admin_update" on public.tournament_decks
  for update to authenticated using ((select is_tournament_admin((select auth.uid())))) with check ((select is_tournament_admin((select auth.uid()))));
create policy "tournament_decks_admin_delete" on public.tournament_decks
  for delete to authenticated using ((select is_tournament_admin((select auth.uid()))));

-- tournaments
drop policy "tournaments_admin_write" on public.tournaments;
create policy "tournaments_admin_insert" on public.tournaments
  for insert to authenticated with check ((select is_tournament_admin((select auth.uid()))));
create policy "tournaments_admin_update" on public.tournaments
  for update to authenticated using ((select is_tournament_admin((select auth.uid())))) with check ((select is_tournament_admin((select auth.uid()))));
create policy "tournaments_admin_delete" on public.tournaments
  for delete to authenticated using ((select is_tournament_admin((select auth.uid()))));

notify pgrst, 'reload schema';
