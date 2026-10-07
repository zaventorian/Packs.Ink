-- 193: three wrong numbers on the public Elo board (audit 2026-10-07).
--
-- 1. elo_leaderboard_v.current_rating picked a player's "last" rating by
--    (event_date, round, table, rating_id). elo.py builds the chain by
--    (event_date, EVENT_ID, round, table, match_id), so for anyone who played
--    two Elo events on one date the view took the event with the higher round
--    number, not the one processed last. 16 players read wrong, up to 44
--    points (AlecM 1668.5 shown, chain ends at 1627.4); rank, the scout sheet's
--    Elo, the store report's Avg Elo and the season review all read this view.
-- 2. elo_leaderboard_v.gw_pct compared match player ids to the rating's
--    CANONICAL id, so every game played under a merged or renamed account
--    counted as 0 of 0 (SunnyDay: 72.4% from 42/58 games; true 65.0% from
--    217/334). Migration 62 fixed this in three other views and missed this
--    one. Resolved through TWO merge hops: three live chains are two deep, and
--    their ratings sit on the final account.
-- 3. elo_event_summary_v's "Avg Elo" took min(rating_before) per player, i.e.
--    each player's LOWEST rating during the event, so anyone who lost a round
--    pulled the average down (CT's Hobbies 9/27: 1582 shown, 1597 real). It is
--    each player's rating BEFORE their first match there now, the rule
--    elo_player_events_v.start_rating already uses.
--
-- Column lists are unchanged, so CREATE OR REPLACE keeps grants and dependants.

create or replace view public.elo_leaderboard_v with (security_invoker = on) as
 WITH chrono AS (
         SELECT rt.rating_id,
            rt.player_id,
            rt.rating_after,
            row_number() OVER (PARTITION BY rt.player_id ORDER BY e.event_date DESC NULLS LAST, m.event_id DESC, m.round_number DESC, m.table_number DESC NULLS LAST, m.match_id DESC) AS rn_desc,
            count(*) OVER (PARTITION BY rt.player_id) AS n_matches
           FROM elo_ratings rt
             JOIN elo_matches m ON m.match_id = rt.match_id
             JOIN elo_events e ON e.event_id = m.event_id
        ), last_ratings AS (
         SELECT chrono.player_id,
            chrono.rating_after AS current_rating,
            chrono.n_matches
           FROM chrono
          WHERE chrono.rn_desc = 1
        ), peaks AS (
         SELECT elo_ratings.player_id,
            max(elo_ratings.rating_after) AS peak_rating
           FROM elo_ratings
          GROUP BY elo_ratings.player_id
        ), wld AS (
         SELECT elo_ratings.player_id,
            sum(
                CASE
                    WHEN elo_ratings.score = 1.0::double precision THEN 1
                    ELSE 0
                END) AS wins,
            sum(
                CASE
                    WHEN elo_ratings.score = 0.0::double precision THEN 1
                    ELSE 0
                END) AS losses,
            sum(
                CASE
                    WHEN elo_ratings.score = 0.5::double precision THEN 1
                    ELSE 0
                END) AS draws
           FROM elo_ratings
          GROUP BY elo_ratings.player_id
        ), resolved AS (
         SELECT rt.player_id,
            m.games_won_p1,
            m.games_won_p2,
            COALESCE(p1b.merged_into_id, p1.merged_into_id, m.player1_id) AS c1,
            COALESCE(p2b.merged_into_id, p2.merged_into_id, m.player2_id) AS c2
           FROM elo_ratings rt
             JOIN elo_matches m ON m.match_id = rt.match_id
             LEFT JOIN elo_players p1 ON p1.player_id = m.player1_id
             LEFT JOIN elo_players p1b ON p1b.player_id = p1.merged_into_id
             LEFT JOIN elo_players p2 ON p2.player_id = m.player2_id
             LEFT JOIN elo_players p2b ON p2b.player_id = p2.merged_into_id
          WHERE m.games_won_p1 IS NOT NULL AND m.games_won_p2 IS NOT NULL
        ), gw AS (
         SELECT resolved.player_id,
            sum(
                CASE
                    WHEN resolved.c1 = resolved.player_id THEN COALESCE(resolved.games_won_p1, 0)
                    WHEN resolved.c2 = resolved.player_id THEN COALESCE(resolved.games_won_p2, 0)
                    ELSE 0
                END) AS games_won,
            sum(
                CASE
                    WHEN resolved.c1 = resolved.player_id OR resolved.c2 = resolved.player_id
                    THEN COALESCE(resolved.games_won_p1, 0) + COALESCE(resolved.games_won_p2, 0)
                    ELSE 0
                END) AS total_games
           FROM resolved
          GROUP BY resolved.player_id
        ), peak_event AS (
         SELECT DISTINCT ON (rt.player_id) rt.player_id,
            m.event_id AS peak_event_id,
            m.round_number AS peak_round_number
           FROM elo_ratings rt
             JOIN elo_matches m ON m.match_id = rt.match_id
             JOIN peaks pk_1 ON pk_1.player_id = rt.player_id AND rt.rating_after = pk_1.peak_rating
          ORDER BY rt.player_id, rt.rating_id
        )
 SELECT p.player_id,
    p.display_name,
    p.platform,
    lr.current_rating,
    lr.n_matches,
    pk.peak_rating,
    COALESCE(w.wins, 0::bigint) AS wins,
    COALESCE(w.losses, 0::bigint) AS losses,
    COALESCE(w.draws, 0::bigint) AS draws,
        CASE
            WHEN COALESCE(g.total_games, 0::bigint) > 0 THEN round(g.games_won::numeric / g.total_games::numeric * 100::numeric, 1)
            ELSE NULL::numeric
        END AS gw_pct,
        CASE
            WHEN (COALESCE(w.wins, 0::bigint) + COALESCE(w.losses, 0::bigint) + COALESCE(w.draws, 0::bigint)) > 0 THEN round((COALESCE(w.wins, 0::bigint)::numeric + 0.5 * COALESCE(w.draws, 0::bigint)::numeric) / (COALESCE(w.wins, 0::bigint) + COALESCE(w.losses, 0::bigint) + COALESCE(w.draws, 0::bigint))::numeric * 100::numeric, 1)
            ELSE NULL::numeric
        END AS mw_pct,
    pe.peak_event_id,
    pe.peak_round_number,
    rank() OVER (ORDER BY lr.current_rating DESC) AS rank
   FROM elo_players p
     JOIN last_ratings lr ON lr.player_id = p.player_id
     JOIN peaks pk ON pk.player_id = p.player_id
     LEFT JOIN wld w ON w.player_id = p.player_id
     LEFT JOIN gw g ON g.player_id = p.player_id
     LEFT JOIN peak_event pe ON pe.player_id = p.player_id
  WHERE p.merged_into_id IS NULL;

create or replace view public.elo_event_summary_v with (security_invoker = on) as
 WITH participant_starts AS (
         SELECT m.event_id,
            rt.player_id,
            (array_agg(rt.rating_before ORDER BY m.round_number, m.table_number NULLS FIRST, m.match_id))[1] AS start_rating
           FROM elo_ratings rt
             JOIN elo_matches m ON m.match_id = rt.match_id
          GROUP BY m.event_id, rt.player_id
        ), agg AS (
         SELECT participant_starts.event_id,
            count(*) AS rated_players,
            round(avg(participant_starts.start_rating))::integer AS avg_start_elo,
            max(participant_starts.start_rating)::integer AS top_seed_elo
           FROM participant_starts
          GROUP BY participant_starts.event_id
        ), champ AS (
         SELECT DISTINCT ON (s.event_id) s.event_id,
            s.player_id,
            p.display_name AS champion_name
           FROM elo_event_standings_v s
             JOIN elo_players p ON p.player_id = s.player_id
          WHERE s.event_rank = 1
          ORDER BY s.event_id, p.display_name
        )
 SELECT e.event_id,
    e.name,
    e.store,
    e.location,
    e.event_date,
    e.season,
    e.platform,
    e.num_players,
    COALESCE(a.rated_players, 0::bigint) AS rated_players,
    a.avg_start_elo,
    a.top_seed_elo,
    c.champion_name,
    c.player_id AS champion_player_id
   FROM elo_events e
     LEFT JOIN agg a ON a.event_id = e.event_id
     LEFT JOIN champ c ON c.event_id = e.event_id
  WHERE e.is_ignored = false;

NOTIFY pgrst, 'reload schema';
