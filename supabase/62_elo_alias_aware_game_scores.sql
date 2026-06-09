-- 62_elo_alias_aware_game_scores.sql
--
-- Bug: melee match game scores (e.g. 2-1, 1-2, 0-2) weren't showing on profile
-- pages or contributing to GW% for any player who had a melee→rph alias merge.
-- Cause: views matched `m.player1_id = rt.player_id` to decide which side the
-- focus player was on, but for merged accounts:
--   - elo_matches stores the ORIGINAL pre-merge player_id (e.g. melee Adam000
--     pid 864) — that's the id melee's API returned at ingest time.
--   - elo_ratings stores the CANONICAL post-merge player_id (e.g. rph
--     I&L⟡Adam pid 240) — set by the local elo.py compute that walks the
--     merged_into_id chain before assigning ratings.
-- The CASE never matched (864 ≠ 240), so `my_games_won` / `opp_games_won`
-- came back null and GW% rolled up to 0/null. RPH events were unaffected
-- because their player_ids stay canonical end-to-end (no merge happens in RPH
-- match data).
--
-- Fix: join elo_players twice (as p1 / p2) and use coalesce(merged_into_id,
-- player_id) so the comparison resolves to the canonical id on both sides.
-- This works transparently for unmerged players (merged_into_id is null →
-- coalesce returns the original id, which already matches rt.player_id).
--
-- Three views need this patch:
--   - elo_player_rounds_v       (round-by-round on profile: surfaces 2-1 score)
--   - elo_player_events_v       (per-event GW% on profile)
--   - elo_event_standings_v     (per-event GW% on event detail page)
--
-- Implementation note: we use CREATE OR REPLACE VIEW (not DROP + CREATE)
-- because elo_event_standings_v has dependents (elo_event_summary_v in
-- migration 60) that would otherwise require CASCADE. CREATE OR REPLACE is
-- allowed when the column shape (names + types + order) is unchanged —
-- which it is here, since we're only modifying JOIN logic.

-- ── 1. elo_player_rounds_v ────────────────────────────────────────────────
create or replace view public.elo_player_rounds_v
  with (security_invoker = on)
as
-- regular matches (now alias-aware)
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
       false as is_bye
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
       true             as is_bye
  from public.elo_matches m
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players p1 on p1.player_id = m.player1_id
  where m.is_bye = true;

grant select on public.elo_player_rounds_v to anon, authenticated, service_role;


-- ── 2. elo_player_events_v ────────────────────────────────────────────────
create or replace view public.elo_player_events_v
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
       min(rt.rating_id) as first_rating_id,
       -- Alias-aware: resolve match player_ids through merged_into_id before comparing.
       sum(case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then coalesce(m.games_won_p1,0)
                when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then coalesce(m.games_won_p2,0)
                else 0 end) as games_won,
       sum(case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                else 0 end) as total_games
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  join public.elo_events  e on e.event_id = m.event_id
  left join public.elo_players p1 on p1.player_id = m.player1_id
  left join public.elo_players p2 on p2.player_id = m.player2_id
  group by rt.player_id, m.event_id, e.name, e.store, e.location, e.event_date, e.season, e.platform;

grant select on public.elo_player_events_v to anon, authenticated, service_role;


-- ── 3. elo_event_standings_v ──────────────────────────────────────────────
create or replace view public.elo_event_standings_v
  with (security_invoker = on)
as
with per_event as (
  select rt.player_id, m.event_id,
         count(*) filter (where rt.score = 1.0) as wins,
         count(*) filter (where rt.score = 0.0) as losses,
         count(*) filter (where rt.score = 0.5) as draws,
         -- Alias-aware (see migration header for rationale).
         sum(case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then coalesce(m.games_won_p1,0)
                  when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then coalesce(m.games_won_p2,0)
                  else 0 end) as games_won,
         sum(case when coalesce(p1.merged_into_id, m.player1_id) = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  when coalesce(p2.merged_into_id, m.player2_id) = rt.player_id then coalesce(m.games_won_p1,0) + coalesce(m.games_won_p2,0)
                  else 0 end) as total_games,
         (array_agg(rt.rating_after order by rt.rating_id desc))[1] as end_rating
  from public.elo_ratings rt
  join public.elo_matches m on m.match_id = rt.match_id
  left join public.elo_players p1 on p1.player_id = m.player1_id
  left join public.elo_players p2 on p2.player_id = m.player2_id
  group by rt.player_id, m.event_id
)
select pe.event_id,
       pe.player_id,
       p.display_name,
       p.platform,
       coalesce(off.matches_won,  pe.wins)   as wins,
       coalesce(off.matches_lost, pe.losses) as losses,
       coalesce(off.matches_drawn, pe.draws) as draws,
       coalesce(off.match_points, pe.wins*3 + pe.draws) as points,
       case when pe.total_games > 0
            then round((pe.games_won::numeric / pe.total_games) * 100, 1)
            else null end as gw_pct,
       coalesce(off.mw_pct,
                case when (coalesce(off.matches_won, pe.wins)
                         + coalesce(off.matches_lost, pe.losses)
                         + coalesce(off.matches_drawn, pe.draws)) > 0
                     then round(
                       ((coalesce(off.matches_won, pe.wins)
                         + 0.5 * coalesce(off.matches_drawn, pe.draws))::numeric
                       / (coalesce(off.matches_won, pe.wins)
                          + coalesce(off.matches_lost, pe.losses)
                          + coalesce(off.matches_drawn, pe.draws))) * 100, 1)
                     else null end) as mw_pct,
       off.omw_pct,
       pe.end_rating,
       coalesce(off.place,
                rank() over (partition by pe.event_id
                             order by (pe.wins * 3 + pe.draws) desc, pe.wins desc)
       ) as event_rank
  from per_event pe
  join public.elo_players p on p.player_id = pe.player_id
  left join public.elo_event_standings_official off
    on off.event_id = pe.event_id and off.player_id = pe.player_id;

grant select on public.elo_event_standings_v to anon, authenticated, service_role;

notify pgrst, 'reload schema';
