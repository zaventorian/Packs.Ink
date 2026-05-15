-- Fix: price_movers pct_1d collapses to 0 for cards that aren't priced today.
--
-- Bug in 10_price_movers_matview.sql:
--   low_today = most recent non-null low_price (no date filter)
--   low_prev  = most recent non-null low_price WHERE date < l.d  (l.d = global max)
--
-- If a card's most-recent non-null low is from 2026-05-13 and today is
-- 2026-05-15 (no fresh TCGCSV row for the card), then:
--   low_today = 2026-05-13 price
--   low_prev  = also 2026-05-13 price (it's "before 2026-05-15" too)
--   pct_1d    = 0
--
-- This silently zeros out movers for any card with sparse listings — exactly
-- the chase/high-value cards the home page banner wants to surface.
--
-- Fix: low_prev should be the most recent non-null low BEFORE the date that
-- low_today came from, not before l.d. Same fix for market_prev. The 7d /
-- 30d / 90d / 180d / 365d windows are fine because they compare against an
-- explicit "≥ N days ago" floor.
--
-- Implementation: pre-resolve each (product, printing)'s latest-non-null
-- snapshot date for low and market, then aggregate prev against that date.
--
-- Idempotent: drops the existing matview and recreates it.

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
-- Per-(product, printing) latest non-null low/market dates. We need these so
-- "prev" can be defined as the most-recent snapshot BEFORE the latest
-- snapshot for that specific card, not before the global max date.
latest_per_card as (
  select
    tcgplayer_product_id,
    printing,
    max(date) filter (where low_price    is not null) as latest_low_date,
    max(date) filter (where market_price is not null) as latest_market_date
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
  group by tcgplayer_product_id, printing
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    -- Low snapshots. low_today = most recent non-null. low_prev = most recent
    -- non-null BEFORE low_today's own date (per latest_per_card), so it never
    -- equals low_today when the card hasn't been priced for several days.
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null))[1]                                      as low_today,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date < lpc.latest_low_date))[1]    as low_prev,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 7))[1]               as low_7d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 30))[1]              as low_30d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 90))[1]              as low_90d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 180))[1]             as low_180d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 365))[1]             as low_365d,
    -- Market snapshots: same pattern.
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null))[1]                                       as market_today,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date < lpc.latest_market_date))[1]   as market_prev,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 7))[1]                 as market_7d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 30))[1]                as market_30d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 90))[1]                as market_90d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 180))[1]               as market_180d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 365))[1]               as market_365d
  from public.prices_daily p
  cross join latest l
  join latest_per_card lpc
    on lpc.tcgplayer_product_id = p.tcgplayer_product_id
   and lpc.printing             = p.printing
  where p.source = 'tcgcsv' and p.grade = 'raw'
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
join public.cards c on c.tcgplayer_product_id = a.tcgplayer_product_id
where a.low_today is not null
  and greatest(a.low_prev, a.low_7d, a.low_30d, a.low_90d, a.low_180d, a.low_365d) >= 5;

create index if not exists price_movers_abs_pct_1d_idx
  on public.price_movers (abs_pct_1d desc nulls last);

create unique index if not exists price_movers_unique
  on public.price_movers (card_id, printing);

grant select on public.price_movers to anon, authenticated;

notify pgrst, 'reload schema';
