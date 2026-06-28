-- 92: Add covering indexes for foreign keys that lack one.
-- Flagged by the Supabase `unindexed_foreign_keys` advisor. An FK with no index on
-- the referencing column forces sequential scans on joins and on parent-row
-- deletes/updates (the FK constraint check). All additive / safe.
--
-- NOTE (deliberately NOT done here):
--   * The `unused_index` advisor hits are left in place — CLAUDE.md's standing policy
--     is to wait until index-usage stats mature (~13 days) before dropping, since a
--     stats reset can make a still-needed index look unused. Re-run
--     supabase/diagnostics/index_usage_audit.sql later and drop then.
--   * public._scan_revert_backup_20260627 (leftover from the scanner auto-add revert)
--     is a recovery safety-net for a money-affecting incident — drop it manually
--     once the revert is confirmed settled, not in an automated migration.

create index if not exists idx_elo_eso_player_id
  on public.elo_event_standings_official (player_id);
create index if not exists idx_elo_matches_winner_id
  on public.elo_matches (winner_id);
create index if not exists idx_elo_players_first_event_id
  on public.elo_players (first_event_id);
create index if not exists idx_elo_ratings_opponent_id
  on public.elo_ratings (opponent_id);
create index if not exists idx_graded_collection_goals_set_id
  on public.graded_collection_goals (set_id);
create index if not exists idx_graded_sale_reports_user_id
  on public.graded_sale_reports (user_id);
create index if not exists idx_scan_samples_user_id
  on public.scan_samples (user_id);
create index if not exists idx_tournaments_uploaded_by
  on public.tournaments (uploaded_by);
create index if not exists idx_trades_user_id
  on public.trades (user_id);

notify pgrst, 'reload schema';
