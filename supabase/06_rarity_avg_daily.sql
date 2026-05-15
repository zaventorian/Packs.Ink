-- Aggregated daily average prices per (set, rarity, printing).
-- Used to chart Set EV over time without aggregating ~3M rows on each query.
--
-- This is a MATERIALIZED view (pre-computed) — direct queries are instant.
-- The daily ETL refreshes it after each daily price snapshot. To refresh
-- manually:
--     REFRESH MATERIALIZED VIEW public.rarity_avg_daily;
--
-- Re-running this script rebuilds the view from scratch.

-- Drop whichever variant currently exists (regular view OR materialized).
-- DROP ... IF EXISTS doesn't bridge types, so we check pg_views / pg_matviews
-- explicitly. Safe to run on a brand-new database too.
do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='rarity_avg_daily') then
    execute 'drop materialized view public.rarity_avg_daily cascade';
  end if;
  if exists (select 1 from pg_views where schemaname='public' and viewname='rarity_avg_daily') then
    execute 'drop view public.rarity_avg_daily cascade';
  end if;
end $$;

create materialized view public.rarity_avg_daily as
select
  c.set_id,
  c.rarity,
  p.printing,
  p.date,
  avg(p.low_price)::numeric(10,2)    as avg_low,
  avg(p.market_price)::numeric(10,2) as avg_market,
  -- "No-pennies" averages: cards under $1 count as $0 BEFORE averaging,
  -- matching the existing EV view's "<$1 → $0" toggle math.
  avg(case when p.low_price    < 1 then 0 else p.low_price    end)::numeric(10,2) as avg_low_nc,
  avg(case when p.market_price < 1 then 0 else p.market_price end)::numeric(10,2) as avg_market_nc,
  count(*)                            as card_count
from public.prices_daily p
join public.cards c on c.tcgplayer_product_id = p.tcgplayer_product_id
where p.source = 'tcgcsv'
  and p.grade  = 'raw'
  and c.set_id is not null
  and c.rarity is not null
group by c.set_id, c.rarity, p.printing, p.date;

-- Index for the typical query pattern (filter by set, order by date).
create index if not exists rarity_avg_daily_set_date_idx
  on public.rarity_avg_daily (set_id, date);

-- A unique index lets us use REFRESH MATERIALIZED VIEW CONCURRENTLY later
-- so refreshes don't block reads. (Concurrent refresh requires a unique idx.)
create unique index if not exists rarity_avg_daily_unique
  on public.rarity_avg_daily (set_id, rarity, printing, date);

grant select on public.rarity_avg_daily to anon, authenticated;
