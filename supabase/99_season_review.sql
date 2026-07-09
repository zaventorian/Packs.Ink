-- 99_season_review.sql
-- Public, read-only season review for the Elo circuit (e.g. "Wilds Unknown Summer 2026").
-- Powers the link-only /?season=<slug> review page. One RPC returns event-level summary
-- facts + a per-player season table (events, W-L-D, match-win%, game-win%, Elo change,
-- season peak, placements, current all-time rating/rank). The client derives superlatives
-- (biggest gainer, most active, best win rate) from the players array.
--
-- Elo/leaderboard data is already public (elo_leaderboard_v, set_championships), so this
-- RPC is granted to anon+authenticated to match. Season scope is gated through
-- elo_event_summary_v, which already excludes is_ignored events.

create or replace function public.get_season_review(p_season text)
returns jsonb
language sql
stable
security definer
set search_path = public
as $$
with ev as (
  select event_id, name, store, event_date, num_players
  from elo_event_summary_v
  where season = p_season
),
pe as (  -- per player-event within the season, canonical players only
  select v.player_id, v.event_id, v.wins, v.losses, v.draws,
         v.start_rating, v.end_rating, v.peak_rating_this_event,
         v.games_won, v.total_games
  from elo_player_events_v v
  join elo_players p on p.player_id = v.player_id and p.merged_into_id is null
  where v.season = p_season
    and v.event_id in (select event_id from ev)
),
agg as (
  select player_id,
         count(*)                              as events,
         sum(wins)                             as w,
         sum(losses)                           as l,
         sum(draws)                            as d,
         sum(end_rating - start_rating)        as elo_change,
         max(peak_rating_this_event)           as season_peak,
         sum(games_won)                        as gw,
         sum(total_games)                      as tg
  from pe
  group by player_id
),
place as (  -- placements from official standings, canonical players only
  select s.player_id,
         min(s.place)                          as best_place,
         sum((s.place = 1)::int)               as titles,
         sum((s.place = 2)::int)               as finals,
         sum((s.place <= 4)::int)              as top4,
         sum((s.place <= 8)::int)              as top8
  from elo_event_standings_official s
  join elo_players p on p.player_id = s.player_id and p.merged_into_id is null
  where s.event_id in (select event_id from ev)
  group by s.player_id
),
players as (
  select
    a.player_id,
    p.display_name                             as name,
    p.platform,
    a.events,
    a.w, a.l, a.d,
    case when (a.w + a.l + a.d) > 0
      then round((a.w + 0.5 * a.d) / (a.w + a.l + a.d) * 100, 1) end   as mw_pct,
    case when a.tg > 0
      then round(a.gw::numeric / a.tg * 100, 1) end                    as gw_pct,
    round(a.elo_change)::int                   as elo_change,
    round(a.season_peak)::int                  as season_peak,
    round(lb.current_rating)::int              as current_rating,
    lb.rank                                    as current_rank,
    coalesce(pc.titles, 0)                     as titles,
    coalesce(pc.finals, 0)                     as finals,
    coalesce(pc.top4, 0)                       as top4,
    coalesce(pc.top8, 0)                       as top8,
    pc.best_place
  from agg a
  join elo_players p on p.player_id = a.player_id
  left join elo_leaderboard_v lb on lb.player_id = a.player_id
  left join place pc on pc.player_id = a.player_id
)
select jsonb_build_object(
  'season', p_season,
  'summary', jsonb_build_object(
     'events',      (select count(*) from ev),
     'players',     (select count(*) from agg),
     'matches',     (select count(*) from elo_matches m
                       where m.event_id in (select event_id from ev)
                         and coalesce(m.is_bye, false) = false),
     'total_games', (select coalesce(sum(tg), 0) from agg),
     'avg_field',   (select round(avg(num_players), 1) from ev),
     'stores',      (select count(distinct store) from ev),
     'date_from',   (select min(event_date) from ev),
     'date_to',     (select max(event_date) from ev),
     'largest',     (select jsonb_build_object('name', name, 'store', store,
                                               'n', num_players, 'date', event_date)
                       from ev order by num_players desc nulls last, event_date limit 1)
  ),
  'players', coalesce(
     (select jsonb_agg(to_jsonb(pr) order by pr.current_rating desc nulls last)
        from players pr),
     '[]'::jsonb)
);
$$;

revoke all on function public.get_season_review(text) from public;
grant execute on function public.get_season_review(text) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
