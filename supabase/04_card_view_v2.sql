-- SUPERSEDED by 05_view_perf.sql and then by 12_card_prices_latest_matview.sql.
-- Kept for historical context; running it on a fresh deploy is harmless because
-- 12_* drops and recreates card_prices_latest as a materialized view.
--
-- Extend card_prices_latest to expose card filtering attributes (cost, inkable,
-- card_type, classifications, text/flavor_text). Adding columns to a view
-- requires a `create or replace view`, which Postgres only allows when the
-- column order/types from the SELECT are a strict superset of the existing
-- view. Safer: drop and recreate.

drop view if exists public.card_prices_latest;

create view public.card_prices_latest as
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
  p.direct_low_price
from public.prices_daily p
join public.cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv'
  and p.grade  = 'raw'
order by p.tcgplayer_product_id, p.printing, p.date desc;

-- Re-grant read access (dropping the view dropped the grants).
grant select on public.card_prices_latest to anon, authenticated;
