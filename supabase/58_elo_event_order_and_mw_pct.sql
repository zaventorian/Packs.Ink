-- 58_elo_event_order_and_mw_pct.sql
--
-- (1) Same-date event ordering: events that happened on the same calendar day
--     for the same player were returning in arbitrary order from
--     elo_player_events_v. Add `first_rating_id` (the player's earliest match
--     at that event) so the React client can secondary-sort by it and display
--     the day's events in true chronological play order.
--
-- (2) Match-Win % (mw_pct): like game-win % but match-level. The standard TCG
--     formula counts draws as 0.5: (wins + 0.5*draws) / (wins + losses + draws).
--     Added to elo_leaderboard_v, elo_player_events_v, elo_event_standings_v.

drop view if exists public.elo_leaderboard_v;
create view public.elo_leaderboard_v
  with (security_invoker = on)
as
with chrono as (
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
         rt.player_id, m.event_id as peak_event_id, m.round_number as peak_round_number
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
       case when (coalesce(w.wins,0) + coalesce(w.losses,0) + coalesce(w.draws,0)) > 0
            then round(
              ((coalesce(w.wins,0) + 0.5 * coalesce(w.draws,0))::numeric
                / (coalesce(w.wins,0) + coalesce(w.losses,0) + coalesce(w.draws,0))) * 100,
              1)
            else null end as mw_pct,
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
       case when count(*) > 0
            then round(
              ((count(*) filter (where rt.score = 1.0)
                + 0.5 * count(*) filter (where rt.score = 0.5))::numeric / count(*)) * 100,
              1)
            else null end as mw_pct,
       (array_agg(rt.rating_before order by m.round_number asc, m.table_number asc nulls last, rt.rating_id asc))[1] as start_rating,
       (array_agg(rt.rating_after  order by m.round_number desc, m.table_number desc nulls last, rt.rating_id desc))[1] as end_rating,
       max(rt.rating_after) as peak_rating_this_event,
       -- Player-specific chronological sort key for same-date ties. rating_id
       -- is assigned in chronological order during local SQLite ELO compute
       -- and round-trips to Supabase via the upsert, so MIN(rating_id) for a
       -- (player, event) is when that player FIRST played at that event.
       min(rt.rating_id) as first_rating_id,
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
       case when (pe.wins + pe.losses + pe.draws) > 0
            then round(
              ((pe.wins + 0.5 * pe.draws)::numeric / (pe.wins + pe.losses + pe.draws)) * 100,
              1)
            else null end as mw_pct,
       pe.end_rating,
       rank() over (partition by pe.event_id
                    order by (pe.wins * 3 + pe.draws) desc, pe.wins desc) as event_rank
  from per_event pe
  join public.elo_players p on p.player_id = pe.player_id;

grant select on public.elo_event_standings_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
