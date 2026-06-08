-- 60_elo_byes_and_event_summary.sql
--
-- (1) elo_player_rounds_v: UNION in bye rows so a player's profile shows
--     "BYE" at the correct round number instead of silently skipping it.
--     Byes don't enter elo_ratings (they're +0 ELO), so the original view
--     never returned them. The bye half of the union resolves through
--     merged_into_id so a bye picked up under a melee handle still shows
--     on the canonical profile.
--
-- (2) elo_event_summary_v: NEW. One row per event with avg starting ELO
--     of participants + champion name + rated participant count, used by
--     the Tournaments tab.

drop view if exists public.elo_player_rounds_v;
create view public.elo_player_rounds_v
  with (security_invoker = on)
as
-- regular matches
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
       (rt.rating_after - rt.rating_before) as elo_delta,
       false as is_bye
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players opp on opp.player_id = rt.opponent_id

union all

-- bye rows synthesized from matches (resolve player_id through merged_into_id
-- so an alias's bye still shows on the canonical player's profile)
select null::bigint     as rating_id,
       coalesce(p1.merged_into_id, m.player1_id) as player_id,
       m.event_id,
       e.name           as event_name,
       e.event_date,
       m.round_number,
       m.table_number,
       null::int        as opponent_id,
       null::text       as opponent_name,
       null::text       as opponent_platform,
       null::real       as opponent_rating,
       null::int        as my_games_won,
       null::int        as opp_games_won,
       null::real       as score,    -- null score signals bye to the UI
       null::real       as rating_before,
       null::real       as rating_after,
       0::real          as elo_delta,
       true             as is_bye
  from public.elo_matches m
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players p1 on p1.player_id = m.player1_id
  where m.is_bye = true;

grant select on public.elo_player_rounds_v to anon, authenticated, service_role;


drop view if exists public.elo_event_summary_v;
create view public.elo_event_summary_v
  with (security_invoker = on)
as
with participant_starts as (
  -- Each player's first match at the event. min(rating_before) approximates
  -- their starting ELO at the event (across multiple events on the same day
  -- this is fine because the local elo.py compute now orders by event_id).
  select m.event_id, rt.player_id, min(rt.rating_before) as start_rating
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  group by m.event_id, rt.player_id
),
agg as (
  select event_id,
         count(*) as rated_players,
         round(avg(start_rating))::int as avg_start_elo,
         max(start_rating)::int        as top_seed_elo
  from participant_starts
  group by event_id
),
champ as (
  select distinct on (s.event_id)
         s.event_id, s.player_id, p.display_name as champion_name
  from public.elo_event_standings_v s
  join public.elo_players p on p.player_id = s.player_id
  where s.event_rank = 1
  order by s.event_id, p.display_name
)
select e.event_id,
       e.name,
       e.store,
       e.location,
       e.event_date,
       e.season,
       e.platform,
       e.num_players,
       coalesce(a.rated_players, 0) as rated_players,
       a.avg_start_elo,
       a.top_seed_elo,
       c.champion_name,
       c.player_id as champion_player_id
  from public.elo_events e
  left join agg   a on a.event_id = e.event_id
  left join champ c on c.event_id = e.event_id
  where e.is_ignored = false;

grant select on public.elo_event_summary_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
