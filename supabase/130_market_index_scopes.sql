-- Migration 130: more index scopes, and a floor that lets narrow ones exist.
--
-- Supersedes the matview bodies from migration 128. Same methodology
-- (chain-linked, equal-weighted return index rebased to 100 — see 128's header
-- for why it is not a CL50-style price sum); this changes WHICH universes get
-- one and HOW a day qualifies.
--
-- ── The floor was the blocker ───────────────────────────────────────────────
-- 128 kept a day only if >= 20 cards contributed a return. That is the right
-- shape of guard for a wide scope: an "all" index computed from three cards is
-- noise wearing an index's clothes. It is the WRONG guard for a narrow one. A
-- single set has roughly 12-18 Enchanteds and a handful of Iconics, so
-- "Azurite Sea Enchanteds" could never clear 20 and would have emitted an empty
-- series forever — silently, which is the worst way to ship a feature.
--
-- The mistake was measuring absolutely. Twelve cards out of a twelve-card
-- universe is not a thin sample, it is the entire market. Three cards out of
-- four thousand is. What actually matters is COVERAGE: did most of the cards
-- this scope normally sees actually price today?
--
--   keep the day when  n >= MIN_ABS  AND  n >= MIN_COVERAGE * (recent max n)
--
-- The trailing max is the scope's own recent best coverage, so the rule
-- self-calibrates to any width with no per-scope tuning and no extra join. A
-- partial TCGCSV publish still drops a day from "all" (100 of ~5,800 fails the
-- ratio); a complete day for a 14-card tier passes. MIN_ABS stays as a hard
-- floor so a 4-card universe never produces an "index" at all — that is a
-- number, not a benchmark, and it should be absent rather than misleading.
--
-- `universe` is projected alongside `n_components` so the UI can label a thin
-- index honestly ("14 of 14 cards") instead of presenting every series as
-- equally solid.
--
-- ── Scopes ──────────────────────────────────────────────────────────────────
--   ('all',        '')                    every priced single
--   ('set',        <set_id>)
--   ('rarity',     <rarity>)
--   ('setrarity',  <set_id>|<rarity>)     e.g. this set's Enchanteds
--   ('chase',      '')                    Enchanted + Epic + Iconic together
--   ('ink',        <ink>)
--   ('sealed',     '')                    sealed products, Promo Single excluded
--   ('sealedtype', <product_type>)        e.g. the Booster Box index
--
-- Sealed is its own universe rather than folded into 'all': a booster box and a
-- single are different assets with different buyers, and averaging them would
-- describe neither. 'all' stays singles-only, which is what "the Lorcana market
-- is up 3%" is understood to mean.
--
-- Rarity keys are whatever `cards.rarity` stores. That column is canonical by
-- invariant (migration 42 + the Lorcast loader normalise "Super_rare"), and it
-- deliberately ignores the client-side PROMO_RARITY_SETS override: that is a
-- display decision, and an index should be computed on what a card is.
--
-- ── Cost ────────────────────────────────────────────────────────────────────
-- The expensive part — the lag() window over ~3M price rows — still runs ONCE;
-- only the aggregation fans out, from 3 grouped passes to 8. Scope count goes
-- from ~35 to ~275, so market_index_daily grows to a few hundred thousand rows.
-- Both are cheap for Postgres, but this was already the slowest refresh on the
-- site, so the timeout pin is raised to 10 minutes.
--
-- ⚠ Created WITH NO DATA on purpose. `create materialized view` normally
-- populates immediately, and that initial build runs under the SQL EDITOR's
-- statement timeout, not the pin on refresh_market_index() — which is how an
-- expensive matview creation times out in the dashboard for reasons that look
-- like nothing to do with the migration. Create empty, then populate through
-- the RPC, which carries the pin:
--
--   select public.refresh_market_index();
--
-- Until that runs, both matviews exist and are empty; the client treats an
-- empty result exactly like a missing one and simply offers no benchmark.
--
-- Idempotent.

do $$
begin
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='market_index_latest') then
    execute 'drop materialized view public.market_index_latest cascade';
  end if;
  if exists (select 1 from pg_matviews where schemaname='public' and matviewname='market_index_daily') then
    execute 'drop materialized view public.market_index_daily cascade';
  end if;
end $$;

create materialized view public.market_index_daily as
with params as (
  select 7::int       as max_gap_days,
         2.0::numeric as ret_clamp,
         5::int       as min_abs,
         0.6::numeric as min_coverage
),
-- NOTE: the 30-observation coverage window is inlined in the frame clause
-- below rather than living here. A window frame bound must be a constant --
-- Postgres will not accept a column reference -- so a param for it would be a
-- number that looks authoritative and drives nothing.

-- Pre-release guard, applied to singles AND sealed: launch-week listings sit
-- 10-20x the eventual floor, and letting them in opens a set's index with a
-- crash that never happened. Sealed needs it as much as singles — pre-order
-- booster boxes are exactly that pattern.
product_floor as (
  select c.tcgplayer_product_id as pid,
         coalesce((s.released_at::date + 1), '1900-01-01'::date) as floor_date
  from public.cards c
  left join public.sets s on s.id = c.set_id
  where c.tcgplayer_product_id is not null
  union all
  select sp.tcgplayer_product_id,
         coalesce((s.released_at::date + 1), '1900-01-01'::date)
  from public.sealed_products sp
  left join public.sets s on s.id = sp.set_id
  where not exists (
    select 1 from public.cards c2 where c2.tcgplayer_product_id = sp.tcgplayer_product_id
  )
),
-- One row per pid naming every dimension it can be sliced on. The `not exists`
-- above keeps a pid from landing in both branches: a product counted as both a
-- card and a sealed item would contribute its return twice to 'all'-adjacent
-- aggregates. reconcile_catalog.py exists to keep that from happening upstream;
-- this is the belt to its braces.
dims as (
  select c.tcgplayer_product_id as pid, 'card'::text as kind,
         c.set_id, c.rarity, c.ink, null::text as product_type
  from public.cards c
  where c.tcgplayer_product_id is not null
  union all
  select sp.tcgplayer_product_id, 'sealed',
         sp.set_id, null::text, null::text, sp.product_type
  from public.sealed_products sp
  where coalesce(sp.product_type, '') <> 'Promo Single'
    and not exists (
      select 1 from public.cards c2 where c2.tcgplayer_product_id = sp.tcgplayer_product_id
    )
),
px as (
  select p.tcgplayer_product_id as pid,
         p.printing,
         p.date::date as d,
         -- market_price first: low_price is the lowest active LISTING, which
         -- sits parked for weeks on high-value cards. The smoothed sale average
         -- is the right input for a market aggregate.
         coalesce(p.market_price, p.low_price)::numeric as v
  from public.prices_daily p
  join product_floor pf on pf.pid = p.tcgplayer_product_id
  where p.source = 'tcgcsv'
    and p.grade  = 'raw'
    and p.date::date >= pf.floor_date
    and coalesce(p.market_price, p.low_price) > 0
),
stepped as (
  select px.pid, px.printing, px.d, px.v,
         lag(px.v) over w as prev_v,
         px.d - lag(px.d) over w as gap
  from px
  window w as (partition by px.pid, px.printing order by px.d)
),
rets as (
  select s.d, dm.kind, dm.set_id, dm.rarity, dm.ink, dm.product_type,
         -- Winsorized, not discarded: discarding extremes biases the index
         -- upward on crash days, when the outliers skew negative.
         least(greatest(s.v / s.prev_v, 1.0 / p.ret_clamp), p.ret_clamp) as ret
  from stepped s
  cross join params p
  join dims dm on dm.pid = s.pid
  where s.prev_v is not null
    and s.prev_v > 0
    and s.gap is not null
    -- lag() returns the previous ROW, not the previous DAY. Without this a card
    -- with a 40-day hole hands its 40-day move to one day as if it happened
    -- overnight.
    and s.gap <= p.max_gap_days
),
-- Arithmetic mean of returns = a daily-rebalanced equal-weight portfolio, the
-- standard construction. (A geometric mean answers "the average card's
-- experience", a different and less useful question here.)
scoped as (
  select 'all'::text as scope, ''::text as scope_key, d, avg(ret) as mean_ret, count(*)::int as n
  from rets where kind = 'card' group by d
  union all
  select 'set', set_id, d, avg(ret), count(*)::int
  from rets where kind = 'card' and set_id is not null group by set_id, d
  union all
  select 'rarity', rarity, d, avg(ret), count(*)::int
  from rets where kind = 'card' and rarity is not null group by rarity, d
  union all
  select 'setrarity', set_id || '|' || rarity, d, avg(ret), count(*)::int
  from rets where kind = 'card' and set_id is not null and rarity is not null
  group by set_id, rarity, d
  union all
  select 'chase', '', d, avg(ret), count(*)::int
  from rets where kind = 'card' and rarity in ('Enchanted','Epic','Iconic') group by d
  union all
  select 'ink', ink, d, avg(ret), count(*)::int
  from rets where kind = 'card' and ink is not null group by ink, d
  union all
  select 'sealed', '', d, avg(ret), count(*)::int
  from rets where kind = 'sealed' group by d
  union all
  select 'sealedtype', product_type, d, avg(ret), count(*)::int
  from rets where kind = 'sealed' and product_type is not null group by product_type, d
),
-- Coverage baseline: the best participation this scope has seen recently. One
-- row per (scope, date), so a 30-row frame is ~30 observation days.
scored as (
  select s.*,
         max(s.n) over (partition by s.scope, s.scope_key order by s.d
                        rows between 30 preceding and current row) as universe
  from scoped s
),
kept as (
  select k.* from scored k cross join params p
  where k.n >= p.min_abs
    and k.n >= p.min_coverage * k.universe
),
chained as (
  select k.*,
         -- Cumulative product of daily mean returns, via logs (Postgres has no
         -- product aggregate).
         exp(sum(ln(k.mean_ret)) over (
           partition by k.scope, k.scope_key order by k.d
           rows between unbounded preceding and current row
         )) as cum
  from kept k
)
select
  scope,
  scope_key,
  d as date,
  -- Divide by the partition's OWN first cumulative value so the series begins
  -- at exactly 100 on its inception date.
  --
  -- Multiplying the raw cumulative by 100 is NOT equivalent and was wrong: a
  -- scope's first EMITTED day is already the second day it had data, because a
  -- return needs a prior observation. That day's return was therefore baked
  -- into the base, so the series opened at 100 x that return -- 100.6, 99.2 --
  -- instead of 100. It looked correct in a spot check because a return near
  -- 1.0 rounds to 100 anyway; only 32 of ~275 fixture series showed it. An
  -- index whose base is not its base makes every comparison against it wrong
  -- by a day-one wobble that never washes out.
  round((100 * cum / first_value(cum) over (
    partition by scope, scope_key order by d
  ))::numeric, 4) as value,
  n as n_components,
  universe
from chained
with no data;

create unique index if not exists market_index_daily_unique
  on public.market_index_daily (scope, scope_key, date);
create index if not exists market_index_daily_scope_date_idx
  on public.market_index_daily (scope, scope_key, date desc);

create materialized view public.market_index_latest as
with latest as (
  select scope, scope_key, max(date) as d
  from public.market_index_daily
  group by scope, scope_key
),
back as (
  select
    l.scope, l.scope_key, l.d as date,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d))[1]       as value,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 1))[1]   as v_1d,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 7))[1]   as v_7d,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 30))[1]  as v_30d,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 90))[1]  as v_90d,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 180))[1] as v_180d,
    (array_agg(m.value order by m.date desc) filter (where m.date <= l.d - 365))[1] as v_365d,
    max(m.n_components) filter (where m.date = l.d) as n_components,
    max(m.universe)     filter (where m.date = l.d) as universe
  from latest l
  join public.market_index_daily m
    on m.scope = l.scope and m.scope_key = l.scope_key
  group by l.scope, l.scope_key, l.d
)
select
  scope, scope_key, date, value, n_components, universe,
  case when v_1d   > 0 then round(((value - v_1d)   / v_1d   * 100)::numeric, 2) end as pct_1d,
  case when v_7d   > 0 then round(((value - v_7d)   / v_7d   * 100)::numeric, 2) end as pct_7d,
  case when v_30d  > 0 then round(((value - v_30d)  / v_30d  * 100)::numeric, 2) end as pct_30d,
  case when v_90d  > 0 then round(((value - v_90d)  / v_90d  * 100)::numeric, 2) end as pct_90d,
  case when v_180d > 0 then round(((value - v_180d) / v_180d * 100)::numeric, 2) end as pct_180d,
  case when v_365d > 0 then round(((value - v_365d) / v_365d * 100)::numeric, 2) end as pct_365d
from back
with no data;

create unique index if not exists market_index_latest_unique
  on public.market_index_latest (scope, scope_key);

-- A `drop ... cascade` takes grants with it, and service_role is NOT implicit —
-- migration 45 exists because a missing service_role grant broke the selfheal
-- job with a 403.
grant select on public.market_index_daily  to anon, authenticated, service_role;
grant select on public.market_index_latest to anon, authenticated, service_role;

-- 10 minutes, up from 5: the aggregation now fans out to 8 grouped passes. The
-- pin itself is load-bearing — without it the RPC inherits PostgREST's role
-- setting (anon 3s / authenticated 8s) and dies with 57014, and service_role
-- has no rolconfig of its own so it gets no free pass. This is the pin
-- migration 109 had to restore after a re-run of 16 clobbered it off
-- refresh_sealed_prices_latest.
create or replace function public.refresh_market_index()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  set local statement_timeout = '10min';
  -- CONCURRENTLY cannot populate a matview created WITH NO DATA, so the first
  -- run always takes the non-concurrent path through this handler. That is
  -- intended: it is also the only path that can do the initial build.
  begin
    refresh materialized view concurrently public.market_index_daily;
  exception when others then
    refresh materialized view public.market_index_daily;
  end;
  begin
    refresh materialized view concurrently public.market_index_latest;
  exception when others then
    refresh materialized view public.market_index_latest;
  end;
end $$;

revoke all on function public.refresh_market_index() from public, anon, authenticated;
grant  execute on function public.refresh_market_index() to service_role;

notify pgrst, 'reload schema';
