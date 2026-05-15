-- Audit: are we ingesting sealed-product prices we don't know about?
--
-- The daily ETL pulls every productId TCGCSV returns for category 71
-- (Lorcana), but the UI only surfaces rows that also have a matching entry
-- in `cards`. Anything in `prices_daily` without a `cards` match is either
-- a sealed product, a promo we haven't catalogued, or a TCGPlayer SKU
-- Lorcast doesn't index.
--
-- Run in the Supabase SQL editor. Not a migration.

-- 1) High-level count: priced products without a cards row, latest date only.
with latest as (
  select max(date) as d from prices_daily where source='tcgcsv' and grade='raw'
)
select
  count(distinct p.tcgplayer_product_id) as orphan_product_count
from prices_daily p
left join cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
cross join latest
where p.source='tcgcsv' and p.grade='raw'
  and p.date = latest.d
  and c.id is null;

-- 2) Sample of the orphans with their price snapshot. The product names
--    will be obvious — "Booster Pack", "Booster Box", "Starter Deck", etc.
--    Since we don't store the product name anywhere yet, this just shows
--    the IDs and prices; cross-reference IDs at https://tcgcsv.com/tcgplayer/71
with latest as (
  select max(date) as d from prices_daily where source='tcgcsv' and grade='raw'
)
select
  p.tcgplayer_product_id,
  p.printing,
  p.low_price,
  p.market_price,
  p.high_price
from prices_daily p
left join cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
cross join latest
where p.source='tcgcsv' and p.grade='raw'
  and p.date = latest.d
  and c.id is null
order by p.market_price desc nulls last
limit 50;

-- 3) Distribution by printing/subType — sealed product usually comes through
--    with subTypeName='Normal'. If you see large counts only on 'Normal' and
--    no 'Foil'/'Cold Foil', that's a strong sealed-product fingerprint.
with latest as (
  select max(date) as d from prices_daily where source='tcgcsv' and grade='raw'
)
select
  p.printing,
  count(*) as orphan_row_count
from prices_daily p
left join cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
cross join latest
where p.source='tcgcsv' and p.grade='raw'
  and p.date = latest.d
  and c.id is null
group by p.printing
order by orphan_row_count desc;
