-- 164_lorcana_event_description.sql
--
-- ############################################################################
-- ##  DO NOT PASTE THIS AT THE LIVE DATABASE WITHOUT READING THIS FIRST.    ##
-- ############################################################################
--
-- The live database ALREADY satisfies everything below. Probed 2026-09-20 with
-- the publishable key:
--
--     lorcana_events.description          -> 200, null           (exists)
--     lorcana_events_history.description  -> 200, null           (exists)
--     lorcana_events.nonexistent_col_xyz  -> 400 42703           (control)
--     get_nearby_lorcana_events(...)      -> occurrences[0] HAS 'description'
--
-- None of that is in this repo: 113 creates the table and the function without
-- the column, so the column and the function change were made OUTSIDE the
-- migrations. This file exists so a database built from the repo alone matches
-- what is live -- NOT because anything needs running.
--
-- ⚠ Running it anyway would re-create get_nearby_lorcana_events from 113's
-- body. That keeps `description` (it is added below) but would REVERT any other
-- out-of-repo edit to that function, which is exactly the hazard CLAUDE.md
-- records: "When you re-run any historical migration, diff the function bodies
-- against the newest migration that touched them." The live body cannot be read
-- through PostgREST, so diff it in the dashboard (pg_get_functiondef) before
-- running this. If it matches 113 plus the description key, this is a no-op and
-- you may as well skip it.
--
-- What the column is for
-- ----------------------
-- What a store WROTE about its event. We have been fetching it on every ETL run
-- and throwing it away: to_row() in scripts/elo/discover_wu_scs.py maps a fixed
-- field list and `description` was never in it -- which is why the column is
-- null on all 21k rows. Measured against the live RPH API on 2026-09-20:
--
--     all upcoming Lorcana events   45% have one   (446 of 993 sampled)
--     Set Championships             59%            (290 of 494)
--     Prereleases                   60%            (300 of 496)
--
-- and what is in them is the part a listing cannot otherwise say -- entry fee,
-- registration vs start time, round structure, prize split. Median 121
-- characters, longest seen 4,009.
--
-- So the ETL change is the one that matters; this is bookkeeping. Descriptions
-- start appearing within a day of it shipping, as the sweep re-sees each event.
--
-- Two things the ETL side handles, noted here because they are easy to lose:
--
--   * HISTORY_COLS in discover_events.py is a hand-kept copy of the history
--     table's columns. Anything missing from it is dropped from the archive
--     with no error at all.
--
--   * The ETL strips HTML before storing (~2% of these carry <br>, because it
--     is a free-text box people paste into). Unescape THEN strip, or an escaped
--     &lt;script&gt; is turned into a live tag by the unescape.

alter table public.lorcana_events         add column if not exists description text;
alter table public.lorcana_events_history add column if not exists description text;

-- ⚠ create or replace, NOT drop + create. The signature and the RETURNS TABLE
-- are unchanged (only the jsonb the occurrences are built from gains a key), so
-- a replace is legal here -- and it keeps migration 134's grants, which a drop
-- would take with it. They are re-asserted at the foot anyway, idempotently, in
-- case someone later turns this into a drop.

create or replace function public.get_nearby_lorcana_events(
  p_lat double precision,
  p_lng double precision,
  p_radius_mi double precision default 50,
  p_kind text default null,               -- null / 'all' = every kind
  p_max_series integer default 400,
  p_max_occurrences integer default 24
)
returns table (
  series_key       text,
  kind             text,
  name             text,
  set_name         text,
  store_id         bigint,
  store_name       text,
  store_website    text,
  city             text,
  state            text,
  country          text,
  full_address     text,
  latitude         double precision,
  longitude        double precision,
  timezone         text,
  gameplay_format  text,
  distance_mi      double precision,
  dow              smallint,
  local_time       text,
  occurrence_count integer,
  next_start       timestamptz,
  occurrences      jsonb
)
language sql
stable
security invoker
set search_path = public, pg_catalog
as $$
  with p as (
    select
      greatest(1, least(500, coalesce(p_radius_mi, 50)))                             as r,
      greatest(1, least(500, coalesce(p_radius_mi, 50))) / 69.0                      as d_la,
      greatest(1, least(500, coalesce(p_radius_mi, 50)))
        / (69.0 * greatest(0.15, cos(radians(p_lat))))                               as d_lo,
      nullif(lower(coalesce(p_kind, '')), '')                                        as want_kind
  ),
  near as (
    select
      e.*,
      3958.8 * 2 * asin(least(1, sqrt(
        power(sin(radians(e.latitude - p_lat) / 2), 2)
        + cos(radians(p_lat)) * cos(radians(e.latitude))
          * power(sin(radians(e.longitude - p_lng) / 2), 2)
      ))) as dist_mi,
      public.safe_local_ts(e.start_datetime, e.timezone) as local_ts
    from public.lorcana_events e
    where e.latitude  between p_lat - (select d_la from p) and p_lat + (select d_la from p)
      and e.longitude between p_lng - (select d_lo from p) and p_lng + (select d_lo from p)
      and e.start_datetime >= date_trunc('day', now())
      and ((select want_kind from p) is null
           or (select want_kind from p) = 'all'
           or e.kind = (select want_kind from p))
  ),
  inr as (
    select
      n.*,
      extract(dow from n.local_ts)::smallint as ev_dow,
      to_char(n.local_ts, 'HH24:MI')         as ev_time,
      -- A "series" is one store running one recurring slot: same venue, same
      -- kind, same format, same local weekday + start time. Deliberately NOT
      -- keyed on the title — stores stamp the date into it ("7/30/26 Lake Forest
      -- Lorcana Core Constructed Thursday"), which would split every weekly into
      -- one-offs. A genuine one-off just becomes a series of length 1.
      coalesce(n.store_id::text,
               'addr:' || coalesce(n.full_address, '') || '|' || coalesce(n.city, ''))
        || '|' || n.kind
        || '|' || coalesce(n.gameplay_format, '-')
        || '|' || extract(dow from n.local_ts)::smallint
        || '|' || to_char(n.local_ts, 'HH24:MI') as skey
    from near n
    where n.dist_mi <= (select r from p)
  ),
  grp as (
    select
      i.skey                                                          as series_key,
      (array_agg(i.kind            order by i.start_datetime))[1]     as kind,
      (array_agg(i.name            order by i.start_datetime))[1]     as name,
      (array_agg(i.set_name        order by i.start_datetime))[1]     as set_name,
      (array_agg(i.store_id        order by i.start_datetime))[1]     as store_id,
      (array_agg(i.store_name      order by i.start_datetime))[1]     as store_name,
      (array_agg(i.store_website   order by i.start_datetime))[1]     as store_website,
      (array_agg(i.city            order by i.start_datetime))[1]     as city,
      (array_agg(i.state           order by i.start_datetime))[1]     as state,
      (array_agg(i.country         order by i.start_datetime))[1]     as country,
      (array_agg(i.full_address    order by i.start_datetime))[1]     as full_address,
      (array_agg(i.latitude        order by i.start_datetime))[1]     as latitude,
      (array_agg(i.longitude       order by i.start_datetime))[1]     as longitude,
      (array_agg(i.timezone        order by i.start_datetime))[1]     as timezone,
      (array_agg(i.gameplay_format order by i.start_datetime))[1]     as gameplay_format,
      min(i.dist_mi)                                                  as distance_mi,
      (array_agg(i.ev_dow          order by i.start_datetime))[1]     as dow,
      (array_agg(i.ev_time         order by i.start_datetime))[1]     as local_time,
      count(*)::integer                                               as occurrence_count,
      min(i.start_datetime)                                           as next_start,
      jsonb_agg(jsonb_build_object(
        'event_id',              i.event_id,
        'name',                  i.name,
        'start_datetime',        i.start_datetime,
        'end_datetime',          i.end_datetime,
        'url',                   i.url,
        'capacity',              i.capacity,
        'cost_cents',            i.cost_cents,
        'currency',              i.currency,
        'registered_user_count', i.registered_user_count,
        -- ⚠ TRUNCATED here, stored whole. A dense metro returns ~2k occurrences
        -- and this field runs to 4,009 characters in the wild, so the untruncated
        -- form is a multi-megabyte response for a field whose MEDIAN is 121
        -- characters. The calendar path reads the column directly and gets all of
        -- it; this is the one place that pays per row.
        'description',           left(i.description, 1000)
      ) order by i.start_datetime)                                    as occurrences
    from inr i
    group by i.skey
  )
  select
    g.series_key, g.kind, g.name, g.set_name, g.store_id, g.store_name,
    g.store_website, g.city, g.state, g.country, g.full_address,
    g.latitude, g.longitude, g.timezone, g.gameplay_format,
    g.distance_mi, g.dow, g.local_time, g.occurrence_count, g.next_start,
    -- Cap the expanded date list; occurrence_count stays the true total.
    case when jsonb_array_length(g.occurrences) > greatest(1, coalesce(p_max_occurrences, 24))
      then (select jsonb_agg(x)
              from (select x from jsonb_array_elements(g.occurrences) x
                     limit greatest(1, coalesce(p_max_occurrences, 24))) s)
      else g.occurrences
    end as occurrences
  from grp g
  order by g.next_start, g.distance_mi
  limit greatest(1, least(2000, coalesce(p_max_series, 400)));
$$;

-- Re-assert 134's grants. A `create or replace` does not disturb them; this is
-- here so that converting the statement above into a drop + create cannot
-- silently re-open the function to PUBLIC.
revoke all on function public.get_nearby_lorcana_events(
  double precision, double precision, double precision, text, integer, integer) from public;
grant execute on function public.get_nearby_lorcana_events(
  double precision, double precision, double precision, text, integer, integer) to anon, authenticated;

notify pgrst, 'reload schema';
