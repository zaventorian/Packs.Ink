-- supabase/diagnostics/softest_set_championships.sql
--
-- "What is the most destitute city in the middle of nowhere that I need to drive
--  to to win a Set Championship?"   — Hank, #tourney-planning, 2026-09-09
--
-- READ-ONLY. Paste into the Supabase SQL editor and read the table.
--
-- The premise worth stating before the numbers: between players of equal skill,
-- your odds of winning an N-player event are exactly 1/N. Field SIZE is therefore
-- the dominant term and field STRENGTH is the multiplier on top of it, which is
-- why this reports the two separately and never collapses them into one number it
-- cannot defend. `score` exists only to order the rows.
--
-- The trap the obvious query falls into: ranking by "smallest field" alone finds
-- the stores that CANNOT FIRE. A 6-player Tuesday shop does not get handed a Set
-- Championship, and an SC that no-shows is a five-hour drive for nothing. Block B
-- at the bottom measures where that floor actually sits before you trust block A.
--
-- "Outside the Chicago Elo bubble" has a literal definition in this repo:
-- RADIUS_MI = 75.0 in scripts/elo/sync_elo_tracked_stores.py, plus the curated
-- Milwaukee-ring store at ~94 mi. `in_bubble` below reproduces it, and
-- `known_faces` is the better test anyway — it asks whether rated players have
-- actually turned up at that store, which is the thing you are driving away from.

-- ===========================================================================
-- BLOCK A — every upcoming Set Championship, ranked by winnability
-- ===========================================================================
with params as (
  select 41.8781::float8      as chi_lat,      -- CHICAGO in sync_elo_tracked_stores.py
         -87.6298::float8     as chi_lng,
         400::float8          as max_miles,    -- how far you are willing to drive
         75::float8           as bubble_miles, -- RADIUS_MI, ibid.
         1600::numeric        as shark_rating, -- Elo starts at 1500 (elo.py --start)
         5::int               as min_matches,  -- below this a rating is noise
         interval '24 months' as lookback
),

-- A ticket, not a registration: someone who sat down. Identical rule to
-- played() in scripts/elo/scrape_event_attendance.py and RPH_PLAYED_FILTER in
-- Index.html — keep the three in step.
played as (
  select event_id, count(*)::float8 as players
    from public.rph_event_attendance
   where final_place_in_standings is not null
      or coalesce(matches_won, 0)   > 0
      or coalesce(matches_lost, 0)  > 0
      or coalesce(matches_drawn, 0) > 0
   group by event_id
),

-- Aliases resolve to the person. A shark playing under a second handle is
-- exactly the one you would rather not discover on site.
name_to_player as (
  select lower(display_name) as nm, coalesce(merged_into_id, player_id) as pid
    from public.elo_players
),

-- How big this store's OWN Set Championships have run.
store_sc as (
  select h.store_id,
         count(*)::int as past_scs,
         percentile_cont(0.5) within group (order by p.players) as med_sc_field,
         max(p.players)::int as max_sc_field
    from public.lorcana_events_history h
    join played p on p.event_id = h.event_id
   where h.kind = 'sc'
   group by h.store_id
),

-- Everything else the store runs — the fallback when it has never hosted an SC,
-- and on its own a fair read of how alive the local scene is. SCs are EXCLUDED
-- so this stays the same population sc_lift's denominator is measured over;
-- multiplying an SC-inflated median by an SC lift would double-count.
store_any as (
  select h.store_id,
         count(*)::int as past_events,
         percentile_cont(0.5) within group (order by p.players) as med_any_field
    from public.lorcana_events_history h
    join played p on p.event_id = h.event_id
    cross join params pm
   where h.start_datetime > now() - pm.lookback
     and h.kind is distinct from 'sc'
   group by h.store_id
),

-- Site-wide, an SC draws this many times a normal event. Measured here rather
-- than guessed, so the fallback estimate is anchored to real behaviour.
sc_lift as (
  select coalesce(
           (select percentile_cont(0.5) within group (order by p.players)
              from public.lorcana_events_history h join played p on p.event_id = h.event_id
             where h.kind = 'sc')
           / nullif((select percentile_cont(0.5) within group (order by p.players)
                       from public.lorcana_events_history h join played p on p.event_id = h.event_id
                      where h.kind is distinct from 'sc'), 0),
         1.0) as lift
),

-- Who actually shows up there. Counted over people who PLAYED, so a name on a
-- registration list that never sat down is not evidence of a hard room.
faces as (
  select h.store_id,
         count(distinct a.best_identifier)
           filter (where lb.current_rating is not null)                    as rated_seen,
         count(distinct a.best_identifier)
           filter (where lb.current_rating >= pm.shark_rating)             as sharks_seen,
         max(lb.current_rating)                                           as top_rating_seen
    from public.lorcana_events_history h
    join public.rph_event_attendance a on a.event_id = h.event_id
    cross join params pm
    left join name_to_player np on np.nm = lower(a.best_identifier)
    left join public.elo_leaderboard_v lb
           on lb.player_id = np.pid and lb.n_matches >= pm.min_matches
   where h.start_datetime > now() - pm.lookback
     and (a.final_place_in_standings is not null
          or coalesce(a.matches_won, 0)   > 0
          or coalesce(a.matches_lost, 0)  > 0
          or coalesce(a.matches_drawn, 0) > 0)
   group by h.store_id
),

-- Coverage. A store with no scanned events reports nothing, and nothing must not
-- be read as "nobody goes there" — that is the same mistake as a silent zero.
scanned as (
  select h.store_id, count(*)::int as scanned_events
    from public.lorcana_events_history h
    join public.rph_event_attendance_scans s on s.event_id = h.event_id
   group by h.store_id
),

upcoming as (
  select e.event_id, e.name, e.store_id, e.store_name, e.city, e.state, e.url,
         e.start_datetime, e.registered_user_count, e.capacity,
         3958.7613 * 2 * asin(sqrt(
           power(sin(radians(e.latitude - pm.chi_lat) / 2), 2)
           + cos(radians(pm.chi_lat)) * cos(radians(e.latitude))
             * power(sin(radians(e.longitude - pm.chi_lng) / 2), 2)
         )) as miles
    from public.lorcana_events e
    cross join params pm
   where e.kind = 'sc'
     and e.start_datetime > now()
     and e.latitude is not null and e.longitude is not null
)

select
  round(u.miles)::int                                        as miles,          -- great circle; road is ~1.15-1.25x
  u.start_datetime::date                                     as event_date,
  u.store_name,
  u.city, u.state,
  (u.miles <= pm.bubble_miles or t.store_id is not null)      as in_bubble,
  coalesce(sc.past_scs, 0)                                   as past_scs,
  round(sc.med_sc_field)::int                                as med_sc_field,
  sa.past_events                                             as past_non_sc,
  round(sa.med_any_field)::int                               as med_non_sc_field,
  greatest(
    coalesce(sc.med_sc_field, sa.med_any_field * l.lift, 12),
    coalesce(u.registered_user_count, 0)
  )::int                                                     as est_field,
  u.registered_user_count                                    as signed_up_now,
  u.capacity,
  coalesce(f.rated_seen, 0)                                  as rated_seen,
  coalesce(f.sharks_seen, 0)                                 as sharks_seen,
  round(f.top_rating_seen)                                   as top_rating_seen,
  coalesce(sn.scanned_events, 0)                             as scanned_events,
  -- Sort key, not a model: bodies in the room, plus a body's worth for every
  -- rated regular and two more for every 1600+ shark, since a shark both takes a
  -- slot and beats you when you meet.
  round(
    greatest(coalesce(sc.med_sc_field, sa.med_any_field * l.lift, 12),
             coalesce(u.registered_user_count, 0))
    + coalesce(f.rated_seen, 0) + 2 * coalesce(f.sharks_seen, 0)
  )::int                                                     as score,
  u.url
from upcoming u
cross join params pm
cross join sc_lift l
left join store_sc  sc on sc.store_id = u.store_id
left join store_any sa on sa.store_id = u.store_id
left join faces     f  on f.store_id  = u.store_id
left join scanned   sn on sn.store_id = u.store_id
left join public.elo_tracked_stores t on t.store_id = u.store_id
where u.miles <= pm.max_miles
order by score asc, u.miles asc
limit 60;


-- ===========================================================================
-- BLOCK B — the floor. Run this BEFORE trusting a tiny number in block A.
--
-- Does a genuinely destitute shop ever host a Set Championship? This is the
-- distribution of real attendance at every SC we have attendance for, so you can
-- see where the bottom actually is rather than assuming there is no bottom.
-- ===========================================================================
-- with played as (
--   select event_id, count(*)::float8 as players
--     from public.rph_event_attendance
--    where final_place_in_standings is not null
--       or coalesce(matches_won,0) > 0 or coalesce(matches_lost,0) > 0
--       or coalesce(matches_drawn,0) > 0
--    group by event_id
-- )
-- select count(*)                                                as scs_measured,
--        min(p.players)                                          as smallest,
--        percentile_cont(0.10) within group (order by p.players)  as p10,
--        percentile_cont(0.25) within group (order by p.players)  as p25,
--        percentile_cont(0.50) within group (order by p.players)  as median,
--        percentile_cont(0.90) within group (order by p.players)  as p90,
--        max(p.players)                                          as largest,
--        count(*) filter (where p.players <= 8)                  as at_or_under_8
--   from public.lorcana_events_history h
--   join played p on p.event_id = h.event_id
--  where h.kind = 'sc';
