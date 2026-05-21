-- 32_graded_prices.sql — graded card prices from TCGPriceLookup (eBay sold averages).
--
-- Why: the existing prices_daily table is for RAW TCGPlayer market/low. Graded
-- prices (PSA / BGS / CGC / SGC / TAG) live in a different secondary market
-- and have a different shape — one price per (product, grader, grade, date)
-- — so we store them separately rather than overloading prices_daily.
--
-- Source: TCGPriceLookup Trader API (api.tcgpricelookup.com/v1/cards/{id}),
-- pulled daily by scripts/etl_tcgpricelookup_daily.py.

create table if not exists public.graded_prices_daily (
  tcgplayer_product_id integer not null,
  grader               text    not null,  -- 'psa' | 'bgs' | 'cgc' | 'sgc' | 'tag'
  grade                text    not null,  -- '9', '9.5', '10', etc. (string so half-grades parse)
  date                 date    not null,
  ebay_avg_1d          numeric,
  ebay_avg_7d          numeric,
  ebay_avg_30d         numeric,
  source               text    not null default 'tcgpricelookup',
  inserted_at          timestamptz not null default now(),
  primary key (tcgplayer_product_id, grader, grade, date)
);

create index if not exists graded_prices_daily_product_idx
  on public.graded_prices_daily (tcgplayer_product_id);
create index if not exists graded_prices_daily_date_idx
  on public.graded_prices_daily (date desc);

-- Latest-per-card matview for fast Screener/Card-modal reads. Mirrors the
-- card_prices_latest pattern: one row per (product, grader, grade) carrying
-- the most recent date + the eBay rolling averages from that day.
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
       ebay_avg_1d, ebay_avg_7d, ebay_avg_30d, source
from ranked
where rn = 1;

create unique index if not exists graded_prices_latest_unique_idx
  on public.graded_prices_latest (tcgplayer_product_id, grader, grade);
create index if not exists graded_prices_latest_product_idx
  on public.graded_prices_latest (tcgplayer_product_id);

-- Refresh function (SECURITY DEFINER + statement_timeout pinned, same pattern
-- as refresh_card_prices_latest). Falls back to non-concurrent on first run.
create or replace function public.refresh_graded_prices_latest()
returns void
language plpgsql
security definer
set search_path = public, extensions
as $$
begin
  set local statement_timeout = '5min';
  begin
    refresh materialized view concurrently public.graded_prices_latest;
  exception when feature_not_supported then
    refresh materialized view public.graded_prices_latest;
  end;
end;
$$;

grant select on public.graded_prices_daily   to anon, authenticated, service_role;
grant insert, update on public.graded_prices_daily to service_role;
grant select on public.graded_prices_latest  to anon, authenticated, service_role;
grant execute on function public.refresh_graded_prices_latest() to service_role;

-- Graded prices are public market data, so anyone should be able to read.
-- Use the canonical Supabase pattern: RLS on with a permissive SELECT policy
-- (writes stay restricted to service_role since there's no write policy).
-- This satisfies the dashboard's RLS lint and still allows anon reads.
alter table public.graded_prices_daily enable row level security;
drop policy if exists "graded_prices_daily_public_read" on public.graded_prices_daily;
create policy "graded_prices_daily_public_read"
  on public.graded_prices_daily
  for select
  to anon, authenticated
  using (true);

notify pgrst, 'reload schema';
