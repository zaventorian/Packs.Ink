-- 91: RLS performance — wrap auth.<fn>() calls in a scalar subselect so Postgres
-- evaluates them ONCE per statement (initplan) instead of once per row.
-- Flagged by the Supabase `auth_rls_initplan` advisor across ~46 policies; on the
-- big per-user tables (collection_items, deck_cards) the per-row re-evaluation is a
-- real, measurable slowdown. The wrap is semantically identical: auth.uid() /
-- is_*_admin() return the same value for every row within a statement.
-- (The three collection SELECT policies are handled in migration 90.)
-- Ref: https://supabase.com/docs/guides/database/postgres/row-level-security#call-functions-with-select

-- collection_items
alter policy "collection_items: delete own" on public.collection_items
  using ((select auth.uid()) = user_id);
alter policy "collection_items: insert own" on public.collection_items
  with check ((select auth.uid()) = user_id);
alter policy "collection_items: update own" on public.collection_items
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- deck_cards (ownership via parent decks row)
alter policy "deck_cards: delete own" on public.deck_cards
  using (exists (select 1 from public.decks d where d.id = deck_cards.deck_id and d.user_id = (select auth.uid())));
alter policy "deck_cards: insert own" on public.deck_cards
  with check (exists (select 1 from public.decks d where d.id = deck_cards.deck_id and d.user_id = (select auth.uid())));
alter policy "deck_cards: select own or public" on public.deck_cards
  using (exists (select 1 from public.decks d where d.id = deck_cards.deck_id and (d.user_id = (select auth.uid()) or d.visibility = 'public')));
alter policy "deck_cards: update own" on public.deck_cards
  using (exists (select 1 from public.decks d where d.id = deck_cards.deck_id and d.user_id = (select auth.uid())))
  with check (exists (select 1 from public.decks d where d.id = deck_cards.deck_id and d.user_id = (select auth.uid())));

-- deck_favorites
alter policy "deck_favorites: delete own" on public.deck_favorites
  using ((select auth.uid()) = user_id);
alter policy "deck_favorites: insert own" on public.deck_favorites
  with check ((select auth.uid()) = user_id);
alter policy "deck_favorites: read own" on public.deck_favorites
  using ((select auth.uid()) = user_id);

-- deck_views
alter policy "deck_views: insert own" on public.deck_views
  with check ((select auth.uid()) = user_id);

-- decks
alter policy "decks: delete own" on public.decks
  using ((select auth.uid()) = user_id);
alter policy "decks: insert own" on public.decks
  with check ((select auth.uid()) = user_id);
alter policy "decks: select own or public" on public.decks
  using (((select auth.uid()) = user_id) or (visibility = 'public'));
alter policy "decks: update own" on public.decks
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- elo_* admin-write (wrap the whole is_elo_admin(...) call once)
alter policy "elo_eso_admin_write" on public.elo_event_standings_official
  using ((select is_elo_admin(auth.uid()))) with check ((select is_elo_admin(auth.uid())));
alter policy "elo_events_admin_write" on public.elo_events
  using ((select is_elo_admin(auth.uid()))) with check ((select is_elo_admin(auth.uid())));
alter policy "elo_matches_admin_write" on public.elo_matches
  using ((select is_elo_admin(auth.uid()))) with check ((select is_elo_admin(auth.uid())));
alter policy "elo_players_admin_write" on public.elo_players
  using ((select is_elo_admin(auth.uid()))) with check ((select is_elo_admin(auth.uid())));
alter policy "elo_ratings_admin_write" on public.elo_ratings
  using ((select is_elo_admin(auth.uid()))) with check ((select is_elo_admin(auth.uid())));

-- graded_collection_goals
alter policy "graded_collection_goals_owner_all" on public.graded_collection_goals
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- graded_collection_items (select handled in mig 90)
alter policy "graded_collection_items: delete own" on public.graded_collection_items
  using ((select auth.uid()) = user_id);
alter policy "graded_collection_items: insert own" on public.graded_collection_items
  with check ((select auth.uid()) = user_id);
alter policy "graded_collection_items: update own" on public.graded_collection_items
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- graded_sale_reports
alter policy "graded report insert own" on public.graded_sale_reports
  with check (user_id = (select auth.uid()));

-- grading_submissions
alter policy "grading_submissions_owner_all" on public.grading_submissions
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- profiles
alter policy "profiles: insert own" on public.profiles
  with check ((select auth.uid()) = user_id);
alter policy "profiles: update own" on public.profiles
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- scan_samples (own or graded-admin)
alter policy "scan_samples_insert" on public.scan_samples
  with check ((select auth.uid()) = user_id);
alter policy "scan_samples_select" on public.scan_samples
  using (((select auth.uid()) = user_id) or (select is_graded_admin()));
alter policy "scan_samples_update" on public.scan_samples
  using (((select auth.uid()) = user_id) or (select is_graded_admin()))
  with check (((select auth.uid()) = user_id) or (select is_graded_admin()));

-- screener_views
alter policy "screener_views: delete own" on public.screener_views
  using ((select auth.uid()) = user_id);
alter policy "screener_views: insert own" on public.screener_views
  with check ((select auth.uid()) = user_id);
alter policy "screener_views: select own" on public.screener_views
  using ((select auth.uid()) = user_id);
alter policy "screener_views: update own" on public.screener_views
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- sealed_collection_items (select handled in mig 90)
alter policy "sealed_collection_items: delete own" on public.sealed_collection_items
  using ((select auth.uid()) = user_id);
alter policy "sealed_collection_items: insert own" on public.sealed_collection_items
  with check ((select auth.uid()) = user_id);
alter policy "sealed_collection_items: update own" on public.sealed_collection_items
  using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);

-- sealed_pack_arts
alter policy "sealed_pack_arts: delete own" on public.sealed_pack_arts
  using ((select auth.uid()) = user_id);
alter policy "sealed_pack_arts: insert own" on public.sealed_pack_arts
  with check ((select auth.uid()) = user_id);
alter policy "sealed_pack_arts: select own" on public.sealed_pack_arts
  using ((select auth.uid()) = user_id);

-- tournaments / tournament_decks admin-write
alter policy "tournament_decks_admin_write" on public.tournament_decks
  using ((select is_tournament_admin(auth.uid()))) with check ((select is_tournament_admin(auth.uid())));
alter policy "tournaments_admin_write" on public.tournaments
  using ((select is_tournament_admin(auth.uid()))) with check ((select is_tournament_admin(auth.uid())));

-- user_follows
alter policy "user_follows: delete own" on public.user_follows
  using ((select auth.uid()) = follower_id);
alter policy "user_follows: insert own" on public.user_follows
  with check ((select auth.uid()) = follower_id);
alter policy "user_follows: read own" on public.user_follows
  using (((select auth.uid()) = follower_id) or ((select auth.uid()) = followed_id));

notify pgrst, 'reload schema';
