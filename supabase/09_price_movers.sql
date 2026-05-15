-- SUPERSEDED by 10_price_movers_matview.sql, which drops this regular view
-- and recreates price_movers as a materialized view (the regular view hit
-- Supabase's 10s statement timeout). Kept for historical context.
--
-- price_movers: per (card, printing), today's low_price plus the most recent
-- prior, 7-day-ago, and 30-day-ago low_price, with signed Δ% for each window.
--
-- Purpose: powers the Home page "biggest movers" banners. Ranking by
-- abs_pct_1d (absolute 1-day percent change) catches buyouts AND drops with
-- a single sort key.
--
-- Floor: low_prev (yesterday's last observed low) must be ≥ $5. Without this,
-- a $0.10 → $0.20 mover would dominate the list and tell nobody anything
-- meaningful. ("Started under $5" filter, per product spec.)
--
-- Window semantics: each "N-day-ago" value is the most recent non-null
-- low_price observation on or before (latest_snapshot_date - N). This is
-- forgiving — if a card was missing from a specific day's snapshot (sold out,
-- delisted), we still get a meaningful comparator from its nearest prior
-- observation.
--
-- Performance: leans on the partial index from 05_view_perf.sql
-- (prices_daily_tcgcsv_raw_idx). For ~5000 (product, printing) groups the
-- per-group array_agg walks the index in order — sub-second on warm cache.
-- If this becomes hot enough to matter, promote to a materialized view and
-- refresh from the daily ETL alongside rarity_avg_daily.

drop view if exists public.price_movers;

create view public.price_movers as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    -- low_today: most recent non-null low_price ≤ latest snapshot date.
    -- (Usually == today's snapshot, but tolerates cards missing from today.)
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null))[1] as low_today,
    -- low_prev: most recent non-null low_price strictly before today's snapshot.
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date < l.d))[1] as low_prev,
    -- low_7d: most recent non-null low_price on or before (latest - 7).
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 7))[1] as low_7d,
    -- low_30d: same but 30 days back.
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 30))[1] as low_30d
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
  a.low_today,
  a.low_prev,
  a.low_7d,
  a.low_30d,
  case when a.low_prev > 0 then round(((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as pct_1d,
  case when a.low_7d   > 0 then round(((a.low_today - a.low_7d)   / a.low_7d   * 100)::numeric, 2) end as pct_7d,
  case when a.low_30d  > 0 then round(((a.low_today - a.low_30d)  / a.low_30d  * 100)::numeric, 2) end as pct_30d,
  case when a.low_prev > 0 then round(abs((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as abs_pct_1d
from agg a
join public.cards c on c.tcgplayer_product_id = a.tcgplayer_product_id
where a.low_today is not null
  and a.low_prev  is not null
  and a.low_prev  >= 5;

grant select on public.price_movers to anon, authenticated;
