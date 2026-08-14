-- Migration 120: price_movers covers the whole catalog.
--
-- Reported via the feedback widget 2026-08-14: "I filtered for All, Attack of
-- the Vine, commons only and nothing showed up — I think the screener is
-- hiding results." It was. The Screener reads price_movers, and migration 41
-- (inherited from 10/26) ended the matview with:
--
--   where a.low_today is not null
--     and greatest(low_prev, low_7d, low_30d, low_90d, low_180d, low_365d) >= 5;
--
-- That $5 baseline gate made sense when price_movers only fed the home movers
-- banners — a $0.02 → $0.06 common is a +200% "mover" nobody wants on the front
-- page. But the Screener was later built on the same matview as a full
-- financial-database table, and inherited a filter that had nothing to do with
-- it. Measured before this migration:
--
--   rarity      price_movers   catalog (card_prices_latest)
--   Common               0            1886     <- every common, invisible
--   Uncommon            15            1413
--   Rare                38            1269
--   Super Rare          36             487
--   Legendary          137             316
--   TOTAL              622            5877
--
-- So the Screener could only ever show ~11% of the catalog, and the missing 89%
-- skewed hard toward the cheap end — exactly the cards a "commons only" filter
-- asks for. No UI said so; the rows simply were not in the data.
--
-- Fix: drop the price gate. The banners do NOT regress — they already re-apply
-- their own floor client-side, per-window, which is strictly better than the
-- matview's "qualified in ANY window" test (Index.html, the `qualifies()` in
-- the MoversBanner buckets memo: `if(pct == null || prior == null || prior < 5)
-- return false;`). That code carries the comment "the matview only enforced 'at
-- any window', so we re-apply here" — it was already treating the matview gate
-- as untrustworthy.
--
-- Also broadens the null check from `low_today is not null` to "has either
-- price". A card TCGCSV prices only by market_price would otherwise vanish
-- entirely; the Screener renders a dash for a missing Low already. This is a
-- no-op against today's data (0 rows in card_prices_latest have a null
-- low_price) — it's here so the row can never silently disappear later.
--
-- Expected row count after refresh: ~5,800 (was 622). scripts/synthetic_monitor.py
-- MIN_MOVERS_ROWS is raised in the same commit — at 300 it would no longer
-- notice a badly-truncated refresh.
--
-- Otherwise byte-identical to migration 41: same pre-release guard CTEs, same
-- window math, same columns. Idempotent: drops and recreates.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='price_movers') then
    execute 'drop materialized view public.price_movers cascade';
  end if;
end $$;

create materialized view public.price_movers as
with latest as (
  select max(date) as d
  from public.prices_daily
  where source = 'tcgcsv' and grade = 'raw'
),
-- Per-pid earliest acceptable date. Defaults to 1900-01-01 when the card's
-- set has no released_at — that's effectively no filtering, by design.
card_release_floor as (
  select
    c.tcgplayer_product_id,
    coalesce((s.released_at::date + 1), '1900-01-01'::date) as floor_date
  from public.cards c
  left join public.sets s on s.id = c.set_id
  where c.tcgplayer_product_id is not null
),
-- prices_daily minus pre-release rows. Every CTE below reads from `filtered`
-- instead of `prices_daily` directly so the guard applies uniformly.
filtered as (
  select p.*
  from public.prices_daily p
  join card_release_floor crf
    on crf.tcgplayer_product_id = p.tcgplayer_product_id
  where p.source = 'tcgcsv'
    and p.grade  = 'raw'
    and p.date::date >= crf.floor_date
),
latest_per_card as (
  select
    tcgplayer_product_id,
    printing,
    max(date) filter (where low_price    is not null) as latest_low_date,
    max(date) filter (where market_price is not null) as latest_market_date
  from filtered
  group by tcgplayer_product_id, printing
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null))[1]                                      as low_today,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date < lpc.latest_low_date))[1]    as low_prev,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 7))[1]               as low_7d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 30))[1]              as low_30d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 90))[1]              as low_90d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 180))[1]             as low_180d,
    (array_agg(p.low_price order by p.date desc) filter (where p.low_price is not null and p.date <= l.d - 365))[1]             as low_365d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null))[1]                                       as market_today,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date < lpc.latest_market_date))[1]   as market_prev,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 7))[1]                 as market_7d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 30))[1]                as market_30d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 90))[1]                as market_90d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 180))[1]               as market_180d,
    (array_agg(p.market_price order by p.date desc) filter (where p.market_price is not null and p.date <= l.d - 365))[1]               as market_365d
  from filtered p
  cross join latest l
  join latest_per_card lpc
    on lpc.tcgplayer_product_id = p.tcgplayer_product_id
   and lpc.printing             = p.printing
  group by p.tcgplayer_product_id, p.printing, l.d, lpc.latest_low_date, lpc.latest_market_date
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
  a.low_90d,
  a.low_180d,
  a.low_365d,
  case when a.low_prev > 0 then round(((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as pct_1d,
  case when a.low_7d   > 0 then round(((a.low_today - a.low_7d)   / a.low_7d   * 100)::numeric, 2) end as pct_7d,
  case when a.low_30d  > 0 then round(((a.low_today - a.low_30d)  / a.low_30d  * 100)::numeric, 2) end as pct_30d,
  case when a.low_90d  > 0 then round(((a.low_today - a.low_90d)  / a.low_90d  * 100)::numeric, 2) end as pct_90d,
  case when a.low_180d > 0 then round(((a.low_today - a.low_180d) / a.low_180d * 100)::numeric, 2) end as pct_180d,
  case when a.low_365d > 0 then round(((a.low_today - a.low_365d) / a.low_365d * 100)::numeric, 2) end as pct_365d,
  case when a.low_prev > 0 then round(abs((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as abs_pct_1d,
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
   or a.market_today is not null;

create index if not exists price_movers_abs_pct_1d_idx
  on public.price_movers (abs_pct_1d desc nulls last);

create unique index if not exists price_movers_unique
  on public.price_movers (card_id, printing);

-- `drop ... cascade` takes the grants with it. service_role is NOT implicit —
-- migration 45 exists because a missing service_role grant broke the selfheal
-- job with HTTP 403.
grant select on public.price_movers to anon, authenticated, service_role;

notify pgrst, 'reload schema';
