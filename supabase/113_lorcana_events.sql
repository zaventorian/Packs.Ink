-- 113_lorcana_events.sql
-- ONE table for EVERY upcoming Lorcana event on Ravensburger Play (~16.7k rows
-- measured 2026-07-30), so the home "Upcoming near me" box can surface regular
-- locals / league nights / draft nights alongside the Set Championships and
-- prereleases it already knew about.
--
-- Why a new table instead of widening one of the two existing ones:
--   * set_championships MUST keep its exact shape and contents — the Elo pipeline
--     binds to it through the elo_upcoming_scs view, an FK from elo_event_roster,
--     get_event_roster / get_roster_scout, sync_elo_tracked_stores.py,
--     scrape_rosters.py and the refresh-elo-rosters edge function. Pouring 16.7k
--     locals into it would silently widen every one of those.
--   * prerelease_events was only ever the second classified subset. Once the
--     client reads lorcana_events for all three modes it is dead; drop it in a
--     later migration, AFTER prod is confirmed on this table (same ordering rule
--     as 112).
--
-- `kind` is classified by scripts/elo/discover_events.py, NOT by RPH: RPH's own
-- event_type reads "LOCALS" for ~99% of events (measured 2026-07-30, 1972/1991
-- in the soonest sample), so it cannot separate a Set Championship from a
-- Tuesday league night.

create table if not exists public.lorcana_events (
  event_id        bigint primary key,
  kind            text not null default 'other',   -- 'sc' | 'prerelease' | 'other'
  name            text,
  set_name        text,                             -- nullable: a league night is for no set
  store_id        bigint,
  store_name      text,
  store_website   text,
  start_datetime  timestamptz,
  end_datetime    timestamptz,
  timezone        text,
  full_address    text,
  city            text,
  state           text,
  country         text,
  latitude        double precision,
  longitude       double precision,
  registered_user_count integer,
  capacity        integer,
  cost_cents      integer,
  currency        text,
  gameplay_format text,
  display_status  text,
  url             text,
  -- Stamped on every upsert so the daily job can prune events RPH cancelled or
  -- deleted. Locals churn far more than SCs did, so "never prune" (the old
  -- behaviour of both subset tables) would leave dead weeklies on the map.
  last_seen_at    timestamptz not null default now(),
  scraped_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists lorcana_events_start_idx      on public.lorcana_events (start_datetime);
create index if not exists lorcana_events_geo_idx         on public.lorcana_events (latitude, longitude);
create index if not exists lorcana_events_kind_start_idx  on public.lorcana_events (kind, start_datetime);
create index if not exists lorcana_events_last_seen_idx   on public.lorcana_events (last_seen_at);

alter table public.lorcana_events enable row level security;
drop policy if exists "lorcana_events public read" on public.lorcana_events;
create policy "lorcana_events public read" on public.lorcana_events for select using (true);

grant select on public.lorcana_events to anon, authenticated;
-- service_role does NOT inherit grants — the discovery script upserts as service_role.
grant select, insert, update, delete on public.lorcana_events to service_role;


-- `timestamptz at time zone <name>` throws on a bad zone name. RPH sends IANA
-- names, but one malformed row must not fail the whole query, so fall back to UTC.
-- STABLE (not immutable): the result depends on the tz database.
create or replace function public.safe_local_ts(p_ts timestamptz, p_tz text)
returns timestamp
language plpgsql
stable
set search_path = public, pg_catalog
as $$
begin
  return p_ts at time zone coalesce(nullif(p_tz, ''), 'UTC');
exception when others then
  return p_ts at time zone 'UTC';
end;
$$;


-- Nearby events, COLLAPSED INTO SERIES.
--
-- 68% of upcoming events are the same weekly repeating (measured 2026-07-30:
-- 4050 of 5953 events in a 3-week window shared a venue+title with another).
-- Los Angeles at 50mi with no date ceiling is ~1.8k raw rows but only ~58 real
-- series, so grouping here instead of on the client turns a ~half-MB payload
-- into a few dozen rows and gives the UI "every Thu 6pm, next Aug 6" directly.
drop function if exists public.get_nearby_lorcana_events(
  double precision, double precision, double precision, text, integer, integer);

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
        'registered_user_count', i.registered_user_count
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

grant execute on function public.get_nearby_lorcana_events(
  double precision, double precision, double precision, text, integer, integer)
  to anon, authenticated;

notify pgrst, 'reload schema';
