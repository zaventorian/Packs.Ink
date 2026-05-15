-- Sealed price snapshot — latest TCGCSV price per (sealed product, printing).
-- Mirrors card_prices_latest's structure so the frontend can join sealed
-- prices to product metadata the same way it joins card prices to `cards`.
--
-- Refresh policy: the daily ETL calls refresh_sealed_prices_latest() right
-- after upserting prices_daily, alongside the other matview refreshes.
--
-- Idempotent: drops whatever shape currently exists before recreating.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='sealed_prices_latest') then
    execute 'drop materialized view public.sealed_prices_latest cascade';
  end if;
  if exists (select 1 from pg_views where schemaname='public' and viewname='sealed_prices_latest') then
    execute 'drop view public.sealed_prices_latest cascade';
  end if;
end $$;

create materialized view public.sealed_prices_latest as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
)
select distinct on (p.tcgplayer_product_id, p.printing)
  s.tcgplayer_product_id,
  s.tcgplayer_group_id,
  s.set_id,
  s.name,
  s.clean_name,
  s.product_type,
  s.image_url,
  s.tcgplayer_url,
  p.printing,
  p.date            as price_date,
  p.low_price,
  p.mid_price,
  p.market_price,
  p.high_price,
  p.direct_low_price,
  (p.date < (select d from latest)) as is_stale
from public.prices_daily p
join public.sealed_products s on s.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv'
  and p.grade  = 'raw'
  and (
    p.low_price    is not null
    or p.market_price is not null
    or p.mid_price    is not null
    or p.high_price   is not null
  )
order by p.tcgplayer_product_id, p.printing, p.date desc;

create unique index if not exists sealed_prices_latest_unique
  on public.sealed_prices_latest (tcgplayer_product_id, printing);

-- Hot path: "find the Booster Box for set X" filters by (set_id, product_type).
create index if not exists sealed_prices_latest_set_type_idx
  on public.sealed_prices_latest (set_id, product_type);

grant select on public.sealed_prices_latest to anon, authenticated;

create or replace function public.refresh_sealed_prices_latest()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  begin
    refresh materialized view concurrently public.sealed_prices_latest;
  exception when others then
    refresh materialized view public.sealed_prices_latest;
  end;
end $$;

revoke all on function public.refresh_sealed_prices_latest() from public, anon, authenticated;
grant  execute on function public.refresh_sealed_prices_latest() to service_role;
