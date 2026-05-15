-- SUPERSEDED by 08_stale_price_fallback.sql (which kept this performance
-- shape but added the is_stale fallback) and then by 12_card_prices_latest_matview.sql
-- (which promoted it to a materialized view). Kept for historical context.
--
-- Performance fix: rewrite card_prices_latest to use the most recent date
-- as a filter instead of DISTINCT ON across the whole prices_daily table.
--
-- Why this is faster: with the daily ETL writing every priced product on every
-- run, "the latest price per product" is the same as "every row from the
-- latest date". A single max(date) lookup + date-filtered scan beats sorting
-- the entire history (~340k rows and growing).
--
-- Side effect: products that don't appear in the latest snapshot (e.g., the
-- ~9 chase cards currently sold out) won't appear in the view. They didn't
-- show up in the UI before either (the transform filters null prices), so
-- this is a no-op for users — we'll add a "stale price fallback" later.

drop view if exists public.card_prices_latest;

create view public.card_prices_latest as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
)
select
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
  p.direct_low_price
from public.prices_daily p
join latest l on p.date = l.d
join public.cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv' and p.grade = 'raw';

grant select on public.card_prices_latest to anon, authenticated;

-- Supporting partial index: speeds up future DISTINCT ON / time-window queries
-- (e.g., "give me last 7 days of prices for this card" for charts).
create index if not exists prices_daily_tcgcsv_raw_idx
  on public.prices_daily (tcgplayer_product_id, printing, date desc)
  where source = 'tcgcsv' and grade = 'raw';
