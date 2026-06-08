-- 57_elo_chronological_views.sql — fix ordering in elo views.
--
-- Bug: elo_leaderboard_v and elo_player_events_v ordered by rating_id (the
-- bigserial PK of elo_ratings) to find each player's "most recent" rating.
-- That works on the original SQLite source (where rating_id is auto-
-- incremented in chronological insert order) but breaks on Supabase whenever
-- a chronologically-earlier season is added in a later export: the new
-- earlier-event ratings get HIGHER rating_id values than older later-event
-- ratings already in the table. Result: a player's "current_rating" shows
-- their stats at the end of a season we just imported (e.g. Azurite Sea
-- Winter 2025) instead of their actual most recent match (end of Fabled
-- Fall 2025).
--
-- Fix: order by event_date + round_number + table_number (which IS chrono-
-- logical) with rating_id as a final tiebreaker.

drop view if exists public.elo_leaderboard_v;
create view public.elo_leaderboard_v
  with (security_invoker = on)
as
with chrono as (
  -- Per-player chronological ordinal. rn_desc=1 → the player's most recent match.
  select rt.rating_id, rt.player_id, rt.rating_after,
         row_number() over (
           partition by rt.player_id
           order by e.event_date desc nulls last,
                    m.round_number desc,
                    m.table_number desc nulls last,
                    rt.rating_id desc
         ) as rn_desc,
         count(*) over (partition by rt.player_id) as n_matches
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
),
last_ratings as (
  select player_id, rating_after as current_rating, n_matches
  from chrono where rn_desc = 1
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
  join last_ratings lr on lr.player_id = p.player_id
  join peaks pk        on pk.player_id = p.player_id
  left join wld w      on w.player_id  = p.player_id
  left join gw g       on g.player_id  = p.player_id
  left join peak_event pe on pe.player_id = p.player_id
  where p.merged_into_id is null;

grant select on public.elo_leaderboard_v to anon, authenticated, service_role;

-- Per-player tournament summary. Both start_rating (was MIN, which picks the
-- lowest rating_before in the event rather than the FIRST one) and end_rating
-- (was array_agg ordered by rating_id) were affected by the same ordering bug.
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
       (array_agg(rt.rating_before order by m.round_number asc, m.table_number asc nulls last, rt.rating_id asc))[1] as start_rating,
       (array_agg(rt.rating_after  order by m.round_number desc, m.table_number desc nulls last, rt.rating_id desc))[1] as end_rating,
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

grant select on public.elo_player_events_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
