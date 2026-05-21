-- 33_graded_low_high.sql — extend graded_prices_daily with low/high range
-- bounds from the TCGPriceLookup /history endpoint.
--
-- Why: the /v1/cards/search response we use for the daily ETL only gives the
-- rolling averages (avg_1d/7d/30d). The /v1/cards/{id}/history endpoint also
-- exposes per-snapshot price_low and price_high — the actual sale-range
-- bounds — which is much more useful for chart sparklines and chase-card
-- "stretch high" signals. The one-time backfill (scripts/backfill_graded_history.py)
-- populates these for historical rows; daily search ETL leaves them NULL.

alter table public.graded_prices_daily
  add column if not exists ebay_low_price  numeric,
  add column if not exists ebay_high_price numeric;

-- Recreate the latest matview so it carries the new columns. DROP + CREATE
-- because Postgres can't ALTER a matview's column list.
drop materialized view if exists public.graded_prices_latest;
create materialized view public.graded_prices_latest as
with ranked as (
  select g.*,
         row_number() over (
           partition by g.tcgplayer_product_id, g.grader, g.grade
           order by g.date desc
         ) as rn
  from public.graded_prices_daily g
)
select tcgplayer_product_id, grader, grade, date as price_date,
       ebay_avg_1d, ebay_avg_7d, ebay_avg_30d,
       ebay_low_price, ebay_high_price, source
from ranked
where rn = 1;

create unique index if not exists graded_prices_latest_unique_idx
  on public.graded_prices_latest (tcgplayer_product_id, grader, grade);
create index if not exists graded_prices_latest_product_idx
  on public.graded_prices_latest (tcgplayer_product_id);

grant select on public.graded_prices_latest to anon, authenticated, service_role;

notify pgrst, 'reload schema';
