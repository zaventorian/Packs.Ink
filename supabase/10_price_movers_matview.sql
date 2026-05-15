-- Promote price_movers from a regular view to a materialized view.
--
-- Why: the regular view in 09_price_movers.sql does an array_agg over the
-- full prices_daily history (~3M rows) on every fetch. That blows past
-- Supabase's 10s statement timeout on the first home-page load. Same pattern
-- as rarity_avg_daily — pre-compute on the daily ETL, query the snapshot.
--
-- Refresh policy: the daily ETL calls public.refresh_price_movers() after
-- upserting new prices. Concurrent refresh is preferred so reads don't block;
-- requires a unique index, provided below.
--
-- Idempotency: drops whichever variant currently exists (regular view from
-- 09 or matview from a prior run of this file). Safe to re-run.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='price_movers') then
    execute 'drop materialized view public.price_movers cascade';
  end if;
  if exists (select 1 from pg_views where schemaname='public' and viewname='price_movers') then
    execute 'drop view public.price_movers cascade';
  end if;
end $$;

create materialized view public.price_movers as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    -- Low price snapshots across all windows we expose ("today" = most-recent-non-null).
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null))[1] as low_today,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date < l.d))[1]            as low_prev,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 7))[1]       as low_7d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 30))[1]      as low_30d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 90))[1]      as low_90d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 180))[1]     as low_180d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 365))[1]     as low_365d,
    -- Market price snapshots (same windows). market_price is the "real"
    -- centerpoint price and lags low_price; we surface both so users can
    -- see whether a low-price move has translated into market-price move yet.
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null))[1] as market_today,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date < l.d))[1]        as market_prev,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 7))[1]   as market_7d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 30))[1]  as market_30d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 90))[1]  as market_90d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 180))[1] as market_180d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 365))[1] as market_365d
  from public.prices_daily p
  cross join latest l
  where p.source = 'tcgcsv' and p.grade = 'raw'
  group by p.tcgplayer_product_id, p.printing, l.d
)
select
  c.id              as card_id,
  c.set_id,
  c.name,
  c.version,
  c.rarity,
  c.ink,
  c.collector_number,
  c.image_small,
  c.image_normal,
  a.tcgplayer_product_id,
  a.printing,
  -- Low snapshots + signed Δ% for each window.
  a.low_today,
  a.low_prev,
  a.low_7d,
  a.low_30d,
  a.low_90d,
  a.low_180d,
  a.low_365d,
  case when a.low_prev > 0 then round(((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as pct_1d,
  case when a.low_7d   > 0 then round(((a.low_today - a.low_7d)   / a.low_7d   * 100)::numeric, 2) end as pct_7d,
  case when a.low_30d  > 0 then round(((a.low_today - a.low_30d)  / a.low_30d  * 100)::numeric, 2) end as pct_30d,
  case when a.low_90d  > 0 then round(((a.low_today - a.low_90d)  / a.low_90d  * 100)::numeric, 2) end as pct_90d,
  case when a.low_180d > 0 then round(((a.low_today - a.low_180d) / a.low_180d * 100)::numeric, 2) end as pct_180d,
  case when a.low_365d > 0 then round(((a.low_today - a.low_365d) / a.low_365d * 100)::numeric, 2) end as pct_365d,
  -- Kept for the default Home order even though the client now sorts per window.
  case when a.low_prev > 0 then round(abs((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as abs_pct_1d,
  -- Market snapshots + signed Δ%.
  a.market_today,
  a.market_prev,
  a.market_7d,
  a.market_30d,
  a.market_90d,
  a.market_180d,
  a.market_365d,
  case when a.market_prev  > 0 then round(((a.market_today - a.market_prev)  / a.market_prev  * 100)::numeric, 2) end as mkt_pct_1d,
  case when a.market_7d    > 0 then round(((a.market_today - a.market_7d)    / a.market_7d    * 100)::numeric, 2) end as mkt_pct_7d,
  case when a.market_30d   > 0 then round(((a.market_today - a.market_30d)   / a.market_30d   * 100)::numeric, 2) end as mkt_pct_30d,
  case when a.market_90d   > 0 then round(((a.market_today - a.market_90d)   / a.market_90d   * 100)::numeric, 2) end as mkt_pct_90d,
  case when a.market_180d  > 0 then round(((a.market_today - a.market_180d)  / a.market_180d  * 100)::numeric, 2) end as mkt_pct_180d,
  case when a.market_365d  > 0 then round(((a.market_today - a.market_365d)  / a.market_365d  * 100)::numeric, 2) end as mkt_pct_365d
from agg a
join public.cards c on c.tcgplayer_product_id = a.tcgplayer_product_id
where a.low_today is not null
  -- Relaxed floor: a card qualifies if it was ever worth ≥ $5 at ANY tracked
  -- snapshot window (yesterday OR 7d/30d/90d/180d/365d ago). This lets 1Y
  -- movers through even when they're under $5 today, and vice versa. The
  -- client further filters per selected window so the user-facing rule
  -- stays "started above $5 in this window".
  and greatest(a.low_prev, a.low_7d, a.low_30d, a.low_90d, a.low_180d, a.low_365d) >= 5;

-- Sort/filter helper for the typical Home query (top N by |Δ%|).
create index if not exists price_movers_abs_pct_1d_idx
  on public.price_movers (abs_pct_1d desc nulls last);

-- Unique index required by REFRESH MATERIALIZED VIEW CONCURRENTLY.
-- (card_id, printing) is the natural key — one row per (card, printing).
create unique index if not exists price_movers_unique
  on public.price_movers (card_id, printing);

grant select on public.price_movers to anon, authenticated;

-- Refresh function called by the daily ETL. Mirrors refresh_rarity_avg_daily
-- in 07_refresh_rpc.sql: SECURITY DEFINER, falls back to non-concurrent if
-- concurrent fails (e.g., first run, no rows yet).
create or replace function public.refresh_price_movers()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  begin
    refresh materialized view concurrently public.price_movers;
  exception when others then
    refresh materialized view public.price_movers;
  end;
end $$;

revoke all on function public.refresh_price_movers() from public, anon, authenticated;
grant  execute on function public.refresh_price_movers() to service_role;
