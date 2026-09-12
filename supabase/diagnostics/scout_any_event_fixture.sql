-- scout_any_event_fixture.sql - a throwaway-Postgres harness for the scouting
-- chain (143 -> 144 -> 147 -> 148).
--
-- The scouting RPCs are the one part of this site whose failure modes are all
-- silent: a gate that refuses too much hides a sheet somebody is filling in, and
-- a gate that refuses too little hands the team's notes to the wrong reader.
-- Neither raises anything a green deploy would show. scripts/test_scout.mjs pins
-- the SQL's TEXT; this pins its BEHAVIOUR by actually running it.
--
-- It is NOT wired into CI (no Postgres there, and a red job everyone learns to
-- ignore is worse than a script you run when you touch the file). Run it against
-- a scratch cluster after editing any of the four migrations:
--
--   initdb -D /tmp/pgt/data -U pgtest --auth=trust
--   pg_ctl -D /tmp/pgt/data -o "-k /tmp/pgt -h ''" -l /tmp/pgt/log start
--   psql -h /tmp/pgt -U pgtest -d postgres -v ON_ERROR_STOP=1 \
--        -f supabase/diagnostics/scout_any_event_fixture.sql \
--        -f supabase/143_scout_team.sql -f supabase/144_scout_off_roster.sql \
--        -f supabase/147_scout_window_24h.sql -f supabase/148_scout_any_event.sql \
--        -f supabase/diagnostics/scout_any_event_checks.sql
--
-- NEVER point this at a real database: it creates roles and a stub auth schema.

create role anon;
create role authenticated;
create role service_role;
create extension if not exists pgcrypto;
create schema if not exists extensions;
create schema if not exists auth;
create table auth.users(id uuid primary key default gen_random_uuid(), email text);
-- Whoever the session is pretending to be.
create table auth._who(id uuid);
create or replace function auth.uid() returns uuid language sql stable as $$ select id from auth._who limit 1 $$;
create or replace function auth.jwt() returns jsonb language sql stable as
  $$ select jsonb_build_object('email', (select u.email from auth.users u where u.id = auth.uid())) $$;

create table public.profiles(user_id uuid primary key, display_name text);
create table public.elo_tracked_stores(store_id bigint primary key, store_name text);
create table public.lorcana_events(
  event_id bigint primary key, name text, store_id bigint, store_name text,
  start_datetime timestamptz, timezone text, city text, state text,
  capacity int, kind text, set_name text, registered_user_count integer);
create table public.lorcana_events_history(like public.lorcana_events including all);
create table public.set_championships(
  event_id bigint primary key, name text, store_id bigint, store_name text,
  start_datetime timestamptz, timezone text, city text, state text,
  capacity int, set_name text, registered_user_count integer);
create table public.elo_event_roster(
  event_id bigint primary key, capacity int, registered_count int, scraped_at timestamptz);
create table public.elo_event_roster_members(
  event_id bigint, best_identifier text, account_name text, rph_user_id bigint,
  primary key(event_id, best_identifier));
create table public.elo_players(
  player_id bigint primary key, platform text, display_name text, merged_into_id bigint);
create view public.elo_leaderboard_v as
  select player_id, display_name, 1500::numeric as current_rating, 1 as rank, 0 as wins, 0 as losses
    from public.elo_players;
create or replace function public.is_tournament_admin(p uuid) returns boolean language sql stable as $$ select false $$;
create or replace function public.can_view_store_report() returns boolean language sql stable as $$ select false $$;
