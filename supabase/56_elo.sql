-- 56_elo.sql — Chicagoland Lorcana ELO leaderboard
--
-- Hidden feature on Packs.Ink. Source data lives in a local SQLite DB
-- (lorcana_elo.db) and is exported here via scripts/export_elo_to_supabase.py.
-- Public read for the leaderboard + tournament + player views. Writes locked
-- to elo_admins (same allowlist pattern as tournament_admins).
--
-- ID strategy: SQLite primary keys (event_id, player_id, match_id) are
-- INTEGERs and are preserved verbatim here for round-trip simplicity.
-- merged_into_id is a self-FK on elo_players that resolves an aliased
-- platform identity (e.g. melee 'ZavenTorian' merged into RPH 'I&L⟡Zaven').

-- ============================================================
-- Tables
-- ============================================================

create table if not exists public.elo_events (
  event_id      integer primary key,
  name          text not null,
  store         text,
  location      text,
  event_date    date,
  season        text,
  num_players   integer,
  status        text,
  platform      text not null default 'rph',           -- 'rph' | 'melee'
  is_ignored    boolean not null default false,
  notes         text,
  ingested_at   timestamptz not null default now()
);
create index if not exists elo_events_date_idx     on public.elo_events (event_date desc);
create index if not exists elo_events_season_idx   on public.elo_events (season);
create index if not exists elo_events_platform_idx on public.elo_events (platform);

create table if not exists public.elo_players (
  player_id          integer primary key,
  display_name       text not null,
  platform           text not null default 'rph',      -- 'rph' | 'melee'
  external_username  text,
  merged_into_id     integer references public.elo_players(player_id),
  first_event_id     integer references public.elo_events(event_id),
  created_at         timestamptz not null default now(),
  unique (platform, display_name)
);
create index if not exists elo_players_merged_idx on public.elo_players (merged_into_id);
create index if not exists elo_players_display_idx on public.elo_players (lower(display_name));

create table if not exists public.elo_matches (
  match_id      integer primary key,
  event_id      integer not null references public.elo_events(event_id) on delete cascade,
  round_id      integer not null,
  round_number  integer not null,
  round_type    text,
  table_number  integer,
  player1_id    integer not null references public.elo_players(player_id),
  player2_id    integer          references public.elo_players(player_id),
  winner_id     integer          references public.elo_players(player_id),
  games_won_p1  integer,
  games_won_p2  integer,
  is_bye        boolean not null default false,
  source        text not null default 'api'           -- 'api' | 'manual'
);
create index if not exists elo_matches_event_idx on public.elo_matches (event_id, round_number, table_number);
create index if not exists elo_matches_p1_idx    on public.elo_matches (player1_id);
create index if not exists elo_matches_p2_idx    on public.elo_matches (player2_id);

create table if not exists public.elo_ratings (
  rating_id        bigserial primary key,
  player_id        integer not null references public.elo_players(player_id),
  match_id         integer not null references public.elo_matches(match_id) on delete cascade,
  rating_before    real not null,
  rating_after     real not null,
  opponent_id      integer references public.elo_players(player_id),
  opponent_rating  real,
  k_factor         real not null,
  score            real not null,                       -- 1 win, 0 loss, 0.5 draw
  computed_at      timestamptz not null default now(),
  unique (player_id, match_id)                          -- safe re-export
);
create index if not exists elo_ratings_player_idx on public.elo_ratings (player_id, rating_id);
create index if not exists elo_ratings_match_idx  on public.elo_ratings (match_id);

create table if not exists public.elo_admins (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  granted_at timestamptz not null default now()
);

create or replace function public.is_elo_admin(p_user uuid)
returns boolean
language sql
security definer
set search_path = public
stable
as $$
  select exists (select 1 from public.elo_admins where user_id = p_user)
$$;

-- ============================================================
-- RLS
-- ============================================================

alter table public.elo_events  enable row level security;
alter table public.elo_players enable row level security;
alter table public.elo_matches enable row level security;
alter table public.elo_ratings enable row level security;
alter table public.elo_admins  enable row level security;

drop policy if exists "elo_events_public_read" on public.elo_events;
create policy "elo_events_public_read"
  on public.elo_events for select to anon, authenticated using (true);
drop policy if exists "elo_events_admin_write" on public.elo_events;
create policy "elo_events_admin_write"
  on public.elo_events for all to authenticated
  using (public.is_elo_admin(auth.uid()))
  with check (public.is_elo_admin(auth.uid()));

drop policy if exists "elo_players_public_read" on public.elo_players;
create policy "elo_players_public_read"
  on public.elo_players for select to anon, authenticated using (true);
drop policy if exists "elo_players_admin_write" on public.elo_players;
create policy "elo_players_admin_write"
  on public.elo_players for all to authenticated
  using (public.is_elo_admin(auth.uid()))
  with check (public.is_elo_admin(auth.uid()));

drop policy if exists "elo_matches_public_read" on public.elo_matches;
create policy "elo_matches_public_read"
  on public.elo_matches for select to anon, authenticated using (true);
drop policy if exists "elo_matches_admin_write" on public.elo_matches;
create policy "elo_matches_admin_write"
  on public.elo_matches for all to authenticated
  using (public.is_elo_admin(auth.uid()))
  with check (public.is_elo_admin(auth.uid()));

drop policy if exists "elo_ratings_public_read" on public.elo_ratings;
create policy "elo_ratings_public_read"
  on public.elo_ratings for select to anon, authenticated using (true);
drop policy if exists "elo_ratings_admin_write" on public.elo_ratings;
create policy "elo_ratings_admin_write"
  on public.elo_ratings for all to authenticated
  using (public.is_elo_admin(auth.uid()))
  with check (public.is_elo_admin(auth.uid()));

-- elo_admins: API-invisible (manage manually via Supabase dashboard)
drop policy if exists "elo_admins_locked" on public.elo_admins;
create policy "elo_admins_locked"
  on public.elo_admins for select to anon, authenticated using (false);

grant select on public.elo_events, public.elo_players, public.elo_matches, public.elo_ratings
  to anon, authenticated;
grant insert, update, delete on public.elo_events, public.elo_players, public.elo_matches, public.elo_ratings
  to authenticated;
-- service_role does NOT inherit grants implicitly (per CLAUDE.md matview grant trap).
-- Bypasses RLS but still needs explicit table privileges. The ETL upsert script
-- uses the service key, so omit this and writes 403 with hint 42501.
grant select, insert, update, delete on public.elo_events, public.elo_players, public.elo_matches, public.elo_ratings
  to service_role;
grant usage, select on sequence public.elo_ratings_rating_id_seq to service_role;
grant execute on function public.is_elo_admin(uuid) to anon, authenticated, service_role;

-- ============================================================
-- Views (read-optimized for the dashboard surfaces)
-- ============================================================

-- Leaderboard: one row per CANONICAL player (i.e. merged_into_id IS NULL),
-- with current rating, peak rating, games played, win/loss/draw, GW%.
drop view if exists public.elo_leaderboard_v;
create view public.elo_leaderboard_v
  with (security_invoker = on)
as
with last_ratings as (
  select player_id,
         rating_after as current_rating,
         row_number() over (partition by player_id order by rating_id desc) as rn,
         count(*) over (partition by player_id) as n_matches
  from public.elo_ratings
),
peaks as (
  select player_id, max(rating_after) as peak_rating from public.elo_ratings group by player_id
),
wld as (
  select player_id,
         sum(case when score = 1.0 then 1 else 0 end) as wins,
         sum(case when score = 0.0 then 1 else 0 end) as losses,
         sum(case when score = 0.5 then 1 else 0 end) as draws
  from public.elo_ratings group by player_id
),
gw as (
  -- game-win percentage: each match contributes games_won / (games_won + games_lost)
  -- for the player. Joins ratings → matches to find which side of each match the
  -- player was on, then aggregates.
  select rt.player_id,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p2,0)
                  else 0 end) as games_won,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  else 0 end) as total_games
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  where m.games_won_p1 is not null and m.games_won_p2 is not null
  group by rt.player_id
),
peak_event as (
  -- event id + round number where each player hit their peak rating
  select distinct on (rt.player_id)
         rt.player_id,
         m.event_id as peak_event_id,
         m.round_number as peak_round_number
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join peaks pk on pk.player_id = rt.player_id and rt.rating_after = pk.peak_rating
  order by rt.player_id, rt.rating_id asc
)
select p.player_id,
       p.display_name,
       p.platform,
       lr.current_rating,
       lr.n_matches,
       pk.peak_rating,
       coalesce(w.wins, 0)   as wins,
       coalesce(w.losses, 0) as losses,
       coalesce(w.draws, 0)  as draws,
       case when coalesce(g.total_games,0) > 0
            then round((g.games_won::numeric / g.total_games) * 100, 1)
            else null end as gw_pct,
       pe.peak_event_id,
       pe.peak_round_number,
       rank() over (order by lr.current_rating desc) as rank
  from public.elo_players p
  join last_ratings lr on lr.player_id = p.player_id and lr.rn = 1
  join peaks pk        on pk.player_id = p.player_id
  left join wld w      on w.player_id  = p.player_id
  left join gw g       on g.player_id  = p.player_id
  left join peak_event pe on pe.player_id = p.player_id
  where p.merged_into_id is null;

grant select on public.elo_leaderboard_v to anon, authenticated;

-- Per-player tournament summary: one row per (player, event) with per-event
-- record, ending ELO, GW%, peak rating during the event.
drop view if exists public.elo_player_events_v;
create view public.elo_player_events_v
  with (security_invoker = on)
as
select rt.player_id,
       m.event_id,
       e.name        as event_name,
       e.store,
       e.location,
       e.event_date,
       e.season,
       e.platform    as event_platform,
       count(*) filter (where rt.score = 1.0) as wins,
       count(*) filter (where rt.score = 0.0) as losses,
       count(*) filter (where rt.score = 0.5) as draws,
       min(rt.rating_before) as start_rating,
       (array_agg(rt.rating_after order by rt.rating_id desc))[1] as end_rating,
       max(rt.rating_after) as peak_rating_this_event,
       sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0)
                when m.player2_id = rt.player_id then coalesce(m.games_won_p2,0)
                else 0 end) as games_won,
       sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                when m.player2_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                else 0 end) as total_games
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
  group by rt.player_id, m.event_id, e.name, e.store, e.location, e.event_date, e.season, e.platform;

grant select on public.elo_player_events_v to anon, authenticated;

-- Round-by-round trajectory for a player. Used by the profile view.
drop view if exists public.elo_player_rounds_v;
create view public.elo_player_rounds_v
  with (security_invoker = on)
as
select rt.rating_id,
       rt.player_id,
       m.event_id,
       e.name        as event_name,
       e.event_date,
       m.round_number,
       m.table_number,
       opp.player_id    as opponent_id,
       opp.display_name as opponent_name,
       opp.platform     as opponent_platform,
       rt.opponent_rating,
       case when m.player1_id = rt.player_id then m.games_won_p1
            when m.player2_id = rt.player_id then m.games_won_p2 end as my_games_won,
       case when m.player1_id = rt.player_id then m.games_won_p2
            when m.player2_id = rt.player_id then m.games_won_p1 end as opp_games_won,
       rt.score,
       rt.rating_before,
       rt.rating_after,
       (rt.rating_after - rt.rating_before) as elo_delta
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players opp on opp.player_id = rt.opponent_id;

grant select on public.elo_player_rounds_v to anon, authenticated;

-- Per-event final standings (one row per player in that event, ordered by rank)
drop view if exists public.elo_event_standings_v;
create view public.elo_event_standings_v
  with (security_invoker = on)
as
with per_event as (
  select rt.player_id, m.event_id,
         count(*) filter (where rt.score = 1.0) as wins,
         count(*) filter (where rt.score = 0.0) as losses,
         count(*) filter (where rt.score = 0.5) as draws,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p2,0)
                  else 0 end) as games_won,
         sum(case when m.player1_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  when m.player2_id = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  else 0 end) as total_games,
         (array_agg(rt.rating_after order by rt.rating_id desc))[1] as end_rating
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  group by rt.player_id, m.event_id
)
select pe.event_id,
       pe.player_id,
       p.display_name,
       p.platform,
       pe.wins,
       pe.losses,
       pe.draws,
       (pe.wins * 3 + pe.draws) as points,
       case when pe.total_games > 0
            then round((pe.games_won::numeric / pe.total_games) * 100, 1)
            else null end as gw_pct,
       pe.end_rating,
       rank() over (partition by pe.event_id
                    order by (pe.wins * 3 + pe.draws) desc, pe.wins desc) as event_rank
  from per_event pe
  join public.elo_players p on p.player_id = pe.player_id;

grant select on public.elo_event_standings_v to anon, authenticated;

notify pgrst, 'reload schema';
