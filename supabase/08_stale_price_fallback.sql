-- Stale price fallback for card_prices_latest.
--
-- 05_view_perf.sql narrowed the view to "rows from the latest snapshot date"
-- for speed. The trade-off (called out in that file) is that products absent
-- from today's TCGCSV snapshot — e.g., chase cards bought out of TCGPlayer,
-- or a card temporarily delisted — disappear from the view, which means they
-- get $— in the UI and are excluded from EV / simulator math.
--
-- This migration rewrites the view to surface, per (product, printing), the
-- most recent row that has at least one non-null price field. Cards with any
-- price history continue to populate with their last-known values. The
-- supporting index from 05_view_perf.sql (prices_daily_tcgcsv_raw_idx on
-- (tcgplayer_product_id, printing, date desc) WHERE source='tcgcsv' AND
-- grade='raw') lets the DISTINCT ON walk the index per group instead of
-- sorting the whole history, so this stays cheap.
--
-- `is_stale` lets the UI mark prices older than the latest snapshot. We use
-- "older than the max date in the table" rather than `current_date` so the
-- flag doesn't go true for every card during the window before the daily
-- ETL has run for the current UTC day.

drop view if exists public.card_prices_latest;

create view public.card_prices_latest as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
)
select distinct on (p.tcgplayer_product_id, p.printing)
  c.id              as card_id,
  c.set_id,
  c.name,
  c.version,
  c.rarity,
  c.ink,
  c.collector_number,
  c.cost,
  c.inkable,
  c.card_type,
  c.classifications,
  c.text,
  c.flavor_text,
  c.image_small,
  c.image_normal,
  c.image_large,
  p.tcgplayer_product_id,
  p.printing,
  p.date            as price_date,
  p.low_price,
  p.mid_price,
  p.market_price,
  p.high_price,
  p.direct_low_price,
  (p.date < (select d from latest)) as is_stale
from public.prices_daily p
join public.cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv'
  and p.grade  = 'raw'
  and (
    p.low_price    is not null
    or p.market_price is not null
    or p.mid_price    is not null
    or p.high_price   is not null
  )
order by p.tcgplayer_product_id, p.printing, p.date desc;

grant select on public.card_prices_latest to anon, authenticated;
