-- Migration 124: price_movers carries low_last_changed — when the Low price
-- last took a different value.
--
-- TCGCSV low_price is the lowest active LISTING, not a sale: for high-value
-- cards it sits frozen for weeks (71%% of Lows measured unchanged over 8 days,
-- see the low-price memos), and the Screener renders that stickiness as if it
-- were live signal. The wishlist item: flag rows whose Low has not moved in
-- days so a parked listing is not read as a fresh price.
--
-- low_last_changed = the START of the current constant-Low streak: the most
-- recent date whose (non-null) low_price differs from the previous non-null
-- low. A series that never changed reports its first non-null date (the lag of
-- the first row is null, which IS DISTINCT FROM the value). Rows with no Low
-- at all (market-only) carry null. The client renders the staleness hint when
-- today - low_last_changed > 3 days.
--
-- Otherwise byte-identical to migration 120 (same pre-release guard, window
-- math, indexes, grants). Idempotent: drops and recreates. The extra cost is
-- one lag() window pass over the filtered series inside the refresh, which
-- runs under refresh_price_movers' pinned 5-minute statement_timeout.
--
-- Client follow-through ships in the same commit: the Screener fetch adds the
-- column schema-tolerantly (42703 -> retry without), so deploying the code
-- before applying this migration is safe.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='price_movers') then
    execute 'drop materialized view public.price_movers cascade';
  end if;
end $$;

create materialized view public.price_movers as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
),
-- Per-pid earliest acceptable date. Defaults to 1900-01-01 when the card's
-- set has no released_at — that's effectively no filtering, by design.
card_release_floor as (
  select
    c.tcgplayer_product_id,
    coalesce((s.released_at::date + 1), '1900-01-01'::date) as floor_date
  from public.cards c
  left join public.sets s on s.id = c.set_id
  where c.tcgplayer_product_id is not null
),
-- prices_daily minus pre-release rows. Every CTE below reads from `filtered`
-- instead of `prices_daily` directly so the guard applies uniformly.
filtered as (
  select p.*
  from public.prices_daily p
  join card_release_floor crf
    on crf.tcgplayer_product_id = p.tcgplayer_product_id
  where p.source = 'tcgcsv'
    and p.grade  = 'raw'
    and p.date::date >= crf.floor_date
),
latest_per_card as (
  select
    tcgplayer_product_id,
    printing,
    max(date) filter (where low_price    is not null) as latest_low_date,
    max(date) filter (where market_price is not null) as latest_market_date
  from filtered
  group by tcgplayer_product_id, printing
),
low_changes as (
  select tcgplayer_product_id, printing,
         max(date) filter (where is_change) as low_last_changed
  from (
    select tcgplayer_product_id, printing, date,
           low_price is distinct from
             lag(low_price) over (partition by tcgplayer_product_id, printing order by date) as is_change
    from filtered
    where low_price is not null
  ) t
  group by tcgplayer_product_id, printing
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null))[1]                                      as low_today,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date < lpc.latest_low_date))[1]    as low_prev,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 7))[1]               as low_7d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 30))[1]              as low_30d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 90))[1]              as low_90d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 180))[1]             as low_180d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 365))[1]             as low_365d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null))[1]                                       as market_today,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date < lpc.latest_market_date))[1]   as market_prev,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 7))[1]                 as market_7d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 30))[1]                as market_30d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 90))[1]                as market_90d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 180))[1]               as market_180d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 365))[1]               as market_365d
  from filtered p
  cross join latest l
  join latest_per_card lpc
    on lpc.tcgplayer_product_id = p.tcgplayer_product_id
   and lpc.printing             = p.printing
  group by p.tcgplayer_product_id, p.printing, l.d, lpc.latest_low_date, lpc.latest_market_date
)
select
  c.id              as card_id,
  c.set_id,
  c.name,
  c.version,
  c.rarity,
  c.ink,
  c.collector_number,
  c.image_small,
  c.image_normal,
  a.tcgplayer_product_id,
  a.printing,
  a.low_today,
  a.low_prev,
  a.low_7d,
  a.low_30d,
  a.low_90d,
  a.low_180d,
  a.low_365d,
  lc.low_last_changed,
  case when a.low_prev > 0 then round(((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as pct_1d,
  case when a.low_7d   > 0 then round(((a.low_today - a.low_7d)   / a.low_7d   * 100)::numeric, 2) end as pct_7d,
  case when a.low_30d  > 0 then round(((a.low_today - a.low_30d)  / a.low_30d  * 100)::numeric, 2) end as pct_30d,
  case when a.low_90d  > 0 then round(((a.low_today - a.low_90d)  / a.low_90d  * 100)::numeric, 2) end as pct_90d,
  case when a.low_180d > 0 then round(((a.low_today - a.low_180d) / a.low_180d * 100)::numeric, 2) end as pct_180d,
  case when a.low_365d > 0 then round(((a.low_today - a.low_365d) / a.low_365d * 100)::numeric, 2) end as pct_365d,
  case when a.low_prev > 0 then round(abs((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as abs_pct_1d,
  a.market_today,
  a.market_prev,
  a.market_7d,
  a.market_30d,
  a.market_90d,
  a.market_180d,
  a.market_365d,
  case when a.market_prev  > 0 then round(((a.market_today - a.market_prev)  / a.market_prev  * 100)::numeric, 2) end as mkt_pct_1d,
  case when a.market_7d    > 0 then round(((a.market_today - a.market_7d)    / a.market_7d    * 100)::numeric, 2) end as mkt_pct_7d,
  case when a.market_30d   > 0 then round(((a.market_today - a.market_30d)   / a.market_30d   * 100)::numeric, 2) end as mkt_pct_30d,
  case when a.market_90d   > 0 then round(((a.market_today - a.market_90d)   / a.market_90d   * 100)::numeric, 2) end as mkt_pct_90d,
  case when a.market_180d  > 0 then round(((a.market_today - a.market_180d)  / a.market_180d  * 100)::numeric, 2) end as mkt_pct_180d,
  case when a.market_365d  > 0 then round(((a.market_today - a.market_365d)  / a.market_365d  * 100)::numeric, 2) end as mkt_pct_365d
from agg a
left join low_changes lc
  on lc.tcgplayer_product_id = a.tcgplayer_product_id
 and lc.printing             = a.printing
join public.cards c on c.tcgplayer_product_id = a.tcgplayer_product_id
where a.low_today is not null
   or a.market_today is not null;

create index if not exists price_movers_abs_pct_1d_idx
  on public.price_movers (abs_pct_1d desc nulls last);

create unique index if not exists price_movers_unique
  on public.price_movers (card_id, printing);

-- `drop ... cascade` takes the grants with it. service_role is NOT implicit —
-- migration 45 exists because a missing service_role grant broke the selfheal
-- job with HTTP 403.
grant select on public.price_movers to anon, authenticated, service_role;

notify pgrst, 'reload schema';
