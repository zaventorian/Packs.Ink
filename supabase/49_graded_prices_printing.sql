-- 49_graded_prices_printing.sql — add `printing` to graded_prices_daily so
-- split-printing sets (LCP C1: Normal + Holofoil share one tcgplayer_product_id)
-- store foil and non-foil graded prices in separate rows instead of
-- silently overwriting each other on upsert.
--
-- Mirrors the prices_daily schema (which already has `printing` as a PK
-- component). After this migration:
--   - graded_prices_daily PK = (tcgplayer_product_id, printing, grader, grade, date)
--   - graded_prices_latest matview unique index = (tcgplayer_product_id, printing, grader, grade)
--   - ETL writes printing="Normal" for non-foil rows, "Holofoil"/"Cold Foil" for foil.
--
-- Backfill strategy: existing rows can't be retroactively split because we
-- don't know which printing they came from. Default them to "Normal" so
-- the not-null constraint passes, then the ETL re-pulls everything on its
-- next run. For split-printing cards (C1), foil rows land on first run
-- after deploy; the prior "Normal" rows for those pids carry mixed-printing
-- prices for one historical day until rotated out.
--
-- Cache implications: AUX_CACHE_VERSION + packsink:catalog:vN must both
-- bump after this migration deploys so price-derived client caches are
-- invalidated.

-- Drop the existing PK + matview unique index first so we can add the column.
alter table public.graded_prices_daily drop constraint if exists graded_prices_daily_pkey;
drop index if exists public.graded_prices_latest_unique_idx;

-- Add printing column. Default 'Normal' is intentional: TCGPriceLookup
-- historically only indexed one printing per pid, so existing rows are
-- mostly the non-foil printing for split-printing cards (or the sole
-- printing for non-split cards). After deploy the ETL fills both.
alter table public.graded_prices_daily
  add column if not exists printing text not null default 'Normal';

-- Drop the default so future inserts must specify printing explicitly.
alter table public.graded_prices_daily
  alter column printing drop default;

-- New PK including printing.
alter table public.graded_prices_daily
  add constraint graded_prices_daily_pkey
  primary key (tcgplayer_product_id, printing, grader, grade, date);

-- Index for join-by-pid (most common query pattern in the modal).
create index if not exists graded_prices_daily_product_printing_idx
  on public.graded_prices_daily (tcgplayer_product_id, printing);

-- Recreate the matview with printing in the partition + projection.
drop materialized view if exists public.graded_prices_latest;
create materialized view public.graded_prices_latest as
with ranked as (
  select g.*,
         row_number() over (
           partition by g.tcgplayer_product_id, g.printing, g.grader, g.grade
           order by g.date desc
         ) as rn
  from public.graded_prices_daily g
)
select tcgplayer_product_id, printing, grader, grade, date as price_date,
       ebay_avg_1d, ebay_avg_7d, ebay_avg_30d, ebay_low_price, ebay_high_price, source
from ranked
where rn = 1;

create unique index graded_prices_latest_unique_idx
  on public.graded_prices_latest (tcgplayer_product_id, printing, grader, grade);
create index graded_prices_latest_product_idx
  on public.graded_prices_latest (tcgplayer_product_id);

-- Re-grant SELECT (matview drop revokes grants).
grant select on public.graded_prices_latest to anon, authenticated, service_role;

-- service_role needs DELETE on graded_prices_daily so the daily ETL can
-- apply manual deletes from graded_overrides.json (and so cleanup scripts
-- can prune stale rows after schema/printing changes).
grant delete on public.graded_prices_daily to service_role;

notify pgrst, 'reload schema';
