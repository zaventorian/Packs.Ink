-- 136_elo_player_rounds_intentional_draw.sql
--
-- Surface elo_matches.is_intentional_draw (migration 135) on the profile's
-- round-by-round table, so an agreed draw READS as one.
--
-- Until now the only visible sign that a draw was an ID was its Elo Δ sitting
-- at +0.0 — which is exactly the thing a reader has to already know to notice.
-- The pill said DRAW either way.
--
-- CREATE OR REPLACE VIEW (not DROP + CREATE) because elo_player_rounds_v may
-- have dependents, and replace is allowed as long as existing columns keep
-- their names, types and order — appending at the END is fine. The body below
-- is migration 62's verbatim, plus one trailing column per UNION half.
--
-- The bye half hardcodes false: a bye is not a draw, so it can never be an ID.

create or replace view public.elo_player_rounds_v
  with (security_invoker = on)
as
-- regular matches (alias-aware, unchanged from migration 62)
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
       case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then m.games_won_p1
            when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then m.games_won_p2 end as my_games_won,
       case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then m.games_won_p2
            when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then m.games_won_p1 end as opp_games_won,
       rt.score,
       rt.rating_before,
       rt.rating_after,
       (rt.rating_after - rt.rating_before) as elo_delta,
       false as is_bye,
       coalesce(m.is_intentional_draw, false) as is_intentional_draw
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players opp on opp.player_id = rt.opponent_id
  left join public.elo_players p1  on p1.player_id  = m.player1_id
  left join public.elo_players p2  on p2.player_id  = m.player2_id

union all

-- bye rows (resolve through merged_into_id; unchanged from migration 60)
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
       null::real       as score,
       null::real       as rating_before,
       null::real       as rating_after,
       0::real          as elo_delta,
       true             as is_bye,
       false            as is_intentional_draw
  from public.elo_matches m
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players p1 on p1.player_id = m.player1_id
  where m.is_bye = true;

grant select on public.elo_player_rounds_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
