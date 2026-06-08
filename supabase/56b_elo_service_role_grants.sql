-- 56b_elo_service_role_grants.sql — follow-up to 56_elo.sql
--
-- The first version of 56_elo.sql omitted service_role grants on the elo_*
-- tables. service_role bypasses RLS but does NOT inherit table privileges
-- implicitly (see CLAUDE.md matview-grants trap). The ETL exporter that
-- writes ELO data uses the service key, so without these grants writes 403
-- with hint 42501 ("Grant the required privileges to the current role with
-- GRANT SELECT, INSERT, UPDATE ON public.elo_events TO service_role").
--
-- Paste-and-run once in the SQL editor. Idempotent.

grant select, insert, update, delete
  on public.elo_events, public.elo_players, public.elo_matches, public.elo_ratings
  to service_role;

grant usage, select on sequence public.elo_ratings_rating_id_seq to service_role;

grant execute on function public.is_elo_admin(uuid) to service_role;

-- Views also need explicit service_role grants (security_invoker means the view
-- runs as the calling role, but PostgREST still checks the GRANT on the view).
grant select
  on public.elo_leaderboard_v,
     public.elo_player_events_v,
     public.elo_player_rounds_v,
     public.elo_event_standings_v
  to anon, authenticated, service_role;

notify pgrst, 'reload schema';
