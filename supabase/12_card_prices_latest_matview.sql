-- Promote card_prices_latest from a regular view to a materialized view.
--
-- Why: prices_daily is now ~3M rows. The DISTINCT ON walk in the regular
-- view (08_stale_price_fallback.sql) routinely exceeds Supabase's 10s
-- statement timeout on the home-page load (PG error 57014). Same pattern
-- as rarity_avg_daily and price_movers — pre-compute on the daily ETL,
-- read the snapshot.
--
-- Refresh policy: the daily ETL calls public.refresh_card_prices_latest()
-- after upserting new prices. Concurrent refresh is preferred so reads
-- don't block; requires a unique index, provided below.
--
-- Idempotency: drops whichever variant currently exists (regular view or
-- matview from a prior run). Safe to re-run.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='card_prices_latest') then
    execute 'drop materialized view public.card_prices_latest cascade';
  end if;
  if exists (select 1 from pg_views where schemaname='public' and viewname='card_prices_latest') then
    execute 'drop view public.card_prices_latest cascade';
  end if;
end $$;

create materialized view public.card_prices_latest as
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

-- Unique index required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- (card_id, tcgplayer_product_id, printing) — card_id because the join can
-- in principle duplicate a (product_id, printing) pair when two cards share
-- the same product_id (our new connecting-foil pattern doesn't do this, but
-- we keep the safety belt).
create unique index if not exists card_prices_latest_unique
  on public.card_prices_latest (card_id, tcgplayer_product_id, printing);

-- Common query indexes mirroring the previous view's hot read paths.
create index if not exists card_prices_latest_product_idx
  on public.card_prices_latest (tcgplayer_product_id);

grant select on public.card_prices_latest to anon, authenticated;

-- Refresh function. Mirrors refresh_rarity_avg_daily / refresh_price_movers
-- in the previous migrations: SECURITY DEFINER, falls back to non-concurrent
-- if concurrent fails (e.g., first run, no rows yet).
create or replace function public.refresh_card_prices_latest()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  begin
    refresh materialized view concurrently public.card_prices_latest;
  exception when others then
    refresh materialized view public.card_prices_latest;
  end;
end $$;

revoke all on function public.refresh_card_prices_latest() from public, anon, authenticated;
grant  execute on function public.refresh_card_prices_latest() to service_role;
