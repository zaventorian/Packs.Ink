-- 172_price_movers_freshness.sql
-- price_movers stops reporting a SKU's last-ever change as today's move. Every
-- windowed Δ% is null unless that side's latest observation falls INSIDE the
-- window, and the latest observation dates ship as low_date / market_date.
-- Idempotent; safe to re-run.
--
-- THE BUG. Migration 26 defined low_prev / market_prev as the observation just
-- before the card's OWN latest one, so a sparse chase card not priced today
-- would still show a 1D move instead of collapsing to 0. That is right while
-- the latest observation is today. Once a SKU stops updating it is wrong
-- forever: the matview keeps reporting the last change it ever saw as the
-- card's 1D move, every day, until TCGplayer publishes a new price.
--
-- Measured 2026-09-27 against the newest price date, 2026-09-26: 34 of 5,893
-- rows have a side whose latest observation is older than that date, and 19 of
-- them carry a nonzero 1D value (5 Low, 14 NM Market). The worst:
--   Cruella De Vil - Miserable As Usual (Promo Set 1, Holofoil)
--     mkt_pct_1d +108.33%   a Jun 1 -> Aug 9 move; last market row 48 days old
--     pct_1d     -99.98%    a $0.25 listing from Sep 4; last low row 22 days old
-- It was live as the #1 tile of the home Promo Movers banner at 1D, #1 in the
-- Screener's NM Market view, the #1 riser on any NM Market ticker reel, and the
-- lead of the Discord digest's "Heating up". Captain Hook - Forceful Duelist
-- (71 days stale), Simba - Pride Protector (129) and two Whispers in the Well
-- cold foils last priced 2026-03-09 (201) followed it onto the ticker.
--
-- WHY ONLY 1D SHOWED IT. The longer windows compare against the last
-- observation on or before newest - N. When a SKU's latest observation is
-- older than N days, that baseline IS the latest observation, so the window
-- computes exactly 0% — which every movers surface already drops. The guard
-- still applies to them: a 0% we cannot actually observe becomes null, the
-- same "we don't know" a missing price already means.
--
-- THE RULE: a window's Δ% needs that side's latest observation inside the
-- window, i.e. date > newest - N. For 1D that means observed on the newest
-- price date itself. abs_pct_1d follows pct_1d. Prices are untouched: the
-- Screener still shows a SKU's last known Low and Market (low_date /
-- market_date now say when that was); only the claim that it MOVED is gone.
--
-- DELIBERATELY NOT CHANGED: a fresh row whose PREVIOUS observation is several
-- days old still compares against it, the same forward-filled baseline every
-- longer window uses. It is a one-day misattribution at worst rather than a
-- phantom repeated daily, and it measured 0 rows today: every row observed on
-- 2026-09-26 also has a 2026-09-25 observation.
--
-- No client change is needed. Every consumer selects explicit columns and
-- already treats a null Δ% as "no move": the home banners' qualifies(), the
-- ticker's gt.0 / lt.0 filters, the Screener's nulls-last sort, and the price
-- alerts' alertConditionMet(). The Discord digest also checks freshness itself
-- against prices_daily, so it is safe before this migration lands.
--
-- Otherwise byte-identical to migration 124: same pre-release guard, window
-- math, low_last_changed, indexes and grants. The build costs what 124's did —
-- the three dates it now carries were already in agg's GROUP BY.

-- The CREATE below populates the matview in this session, not through
-- refresh_price_movers(), so its build runs under this session's timeout.
-- Give it the refresh function's own 5-minute budget.
set statement_timeout = '5min';

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
low_changes as (
  select tcgplayer_product_id, printing,
         max(date) filter (where is_change) as low_last_changed
  from (
    select tcgplayer_product_id, printing, date,
           low_price is distinct from
             lag(low_price) over (partition by tcgplayer_product_id, printing order by date) as is_change
    from filtered
    where low_price is not null
  ) t
  group by tcgplayer_product_id, printing
),
agg as (
  select
    p.tcgplayer_product_id,
    p.printing,
    l.d                    as newest_date,
    lpc.latest_low_date    as low_date,
    lpc.latest_market_date as market_date,
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
  a.low_date,
  a.low_prev,
  a.low_7d,
  a.low_30d,
  a.low_90d,
  a.low_180d,
  a.low_365d,
  lc.low_last_changed,
  -- A window's move needs its closing observation INSIDE the window
  -- (date > newest - N). For 1D: observed on the newest price date.
  case when a.low_prev > 0 and a.low_date > a.newest_date - 1   then round(((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as pct_1d,
  case when a.low_7d   > 0 and a.low_date > a.newest_date - 7   then round(((a.low_today - a.low_7d)   / a.low_7d   * 100)::numeric, 2) end as pct_7d,
  case when a.low_30d  > 0 and a.low_date > a.newest_date - 30  then round(((a.low_today - a.low_30d)  / a.low_30d  * 100)::numeric, 2) end as pct_30d,
  case when a.low_90d  > 0 and a.low_date > a.newest_date - 90  then round(((a.low_today - a.low_90d)  / a.low_90d  * 100)::numeric, 2) end as pct_90d,
  case when a.low_180d > 0 and a.low_date > a.newest_date - 180 then round(((a.low_today - a.low_180d) / a.low_180d * 100)::numeric, 2) end as pct_180d,
  case when a.low_365d > 0 and a.low_date > a.newest_date - 365 then round(((a.low_today - a.low_365d) / a.low_365d * 100)::numeric, 2) end as pct_365d,
  case when a.low_prev > 0 and a.low_date > a.newest_date - 1   then round(abs((a.low_today - a.low_prev) / a.low_prev * 100)::numeric, 2) end as abs_pct_1d,
  a.market_today,
  a.market_date,
  a.market_prev,
  a.market_7d,
  a.market_30d,
  a.market_90d,
  a.market_180d,
  a.market_365d,
  case when a.market_prev  > 0 and a.market_date > a.newest_date - 1   then round(((a.market_today - a.market_prev)  / a.market_prev  * 100)::numeric, 2) end as mkt_pct_1d,
  case when a.market_7d    > 0 and a.market_date > a.newest_date - 7   then round(((a.market_today - a.market_7d)    / a.market_7d    * 100)::numeric, 2) end as mkt_pct_7d,
  case when a.market_30d   > 0 and a.market_date > a.newest_date - 30  then round(((a.market_today - a.market_30d)   / a.market_30d   * 100)::numeric, 2) end as mkt_pct_30d,
  case when a.market_90d   > 0 and a.market_date > a.newest_date - 90  then round(((a.market_today - a.market_90d)   / a.market_90d   * 100)::numeric, 2) end as mkt_pct_90d,
  case when a.market_180d  > 0 and a.market_date > a.newest_date - 180 then round(((a.market_today - a.market_180d)  / a.market_180d  * 100)::numeric, 2) end as mkt_pct_180d,
  case when a.market_365d  > 0 and a.market_date > a.newest_date - 365 then round(((a.market_today - a.market_365d)  / a.market_365d  * 100)::numeric, 2) end as mkt_pct_365d
from agg a
left join low_changes lc
  on lc.tcgplayer_product_id = a.tcgplayer_product_id
 and lc.printing             = a.printing
join public.cards c on c.tcgplayer_product_id = a.tcgplayer_product_id
where a.low_today is not null
   or a.market_today is not null;

create index if not exists price_movers_abs_pct_1d_idx
  on public.price_movers (abs_pct_1d desc nulls last);

-- REFRESH ... CONCURRENTLY needs a unique index, or refresh_price_movers()
-- falls back to a blocking refresh every night.
create unique index if not exists price_movers_unique
  on public.price_movers (card_id, printing);

-- `drop ... cascade` takes the grants with it. service_role is NOT implicit —
-- migration 45 exists because a missing service_role grant broke the selfheal
-- job with HTTP 403.
grant select on public.price_movers to anon, authenticated, service_role;

-- Re-asserted exactly as migration 25 left it, so this file alone restores a
-- working refresh. The timeout is a FUNCTION-LEVEL SET clause on purpose: a
-- `set local` inside the body is armed too late to govern the statement that
-- is already running (see migration 131).
create or replace function public.refresh_price_movers()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.price_movers;
  exception when others then
    refresh materialized view public.price_movers;
  end;
end $$;

-- Migration 10's lockdown, re-stated as 109 does for its sibling: a refresh is
-- a 40-second full rebuild, never something an anonymous caller may trigger.
revoke all on function public.refresh_price_movers() from public, anon, authenticated;
grant  execute on function public.refresh_price_movers() to service_role;

notify pgrst, 'reload schema';
