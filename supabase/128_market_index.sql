-- Migration 128: market indices.
--
-- The site can tell you a card is +18% in a month. It cannot tell you whether
-- that is leading or lagging, because there is nothing to read it against. Every
-- comparable tool has a benchmark — Card Ladder's CL50, a fund's category
-- average, an equity's sector index — and the benchmark is what turns a number
-- into a judgement.
--
-- ── Methodology ─────────────────────────────────────────────────────────────
-- A CHAIN-LINKED, EQUAL-WEIGHTED RETURN INDEX, rebased to 100 at its first day.
--
--   I_d = I_(d-1) x mean_i( p_i,d / p_i,d-1 )
--
-- over the cards priced on BOTH days. Deliberately not Card Ladder's CL50
-- shape (sum of component prices / N, the original Dow formula): a price-sum
-- index is dominated by its most expensive component, so a single $900
-- Enchanted would drown out four thousand commons and the "market" would just
-- be that card. Averaging RETURNS instead of prices weights every card equally,
-- which is what "how is the Lorcana market doing" actually means.
--
-- Chain-linking is what makes a growing catalog safe. A card that starts being
-- priced in month 8 contributes returns from month 8 onward and never creates a
-- phantom jump on the day it appears, because it is absent from that day's
-- pairwise comparison. Same for a card that stops.
--
-- Three deliberate guards, all of which exist because raw TCGCSV is noisy:
--
--   1. market_price FIRST, low_price only as a fallback. CLAUDE.md is emphatic
--      that low_price is a sticker and not a sale — any-condition, parked for
--      weeks, contaminated by foreign listings. market_price is the smoothed
--      sale average, which is the right input for a market aggregate.
--   2. MAX_GAP_DAYS. lag() returns the previous ROW, not the previous DAY. A
--      card with a 40-day hole would hand its 40-day move to a single day as if
--      it happened overnight. Gaps past the cap contribute nothing.
--   3. Daily returns winsorized to [1/RET_CLAMP, RET_CLAMP]. One mispriced
--      listing — the Black Cauldron $14 -> $2,140 class of event that needed a
--      whole smoothing ETL — should not be able to move a market average.
--
-- And MIN_COMPONENTS: a day computed from three cards is noise wearing an
-- index's clothes. Below the floor the day is dropped, which (because the index
-- is chained) simply means the series holds its previous level rather than
-- inventing a move.
--
-- ── Scopes ──────────────────────────────────────────────────────────────────
-- One row per (scope, scope_key, date):
--   ('all',    '')          the whole tracked market
--   ('set',    <set_id>)    one per set
--   ('rarity', <rarity>)    one per rarity
-- Rarity is the value stored on `cards`, so promo-set cards index under their
-- Lorcast rarity, not under the client-side PROMO_RARITY_SETS override. That is
-- intentional: the override is a display decision, and an index should be
-- computed on what the card actually is.
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
  select 7::int      as max_gap_days,
         2.0::numeric as ret_clamp,
         20::int      as min_components
),
-- Same pre-release guard price_movers uses: launch-week listings sit 10-20x the
-- eventual floor, and letting them in would open every set's index with a crash
-- that never happened.
card_release_floor as (
  select c.tcgplayer_product_id,
         coalesce((s.released_at::date + 1), '1900-01-01'::date) as floor_date
  from public.cards c
  left join public.sets s on s.id = c.set_id
  where c.tcgplayer_product_id is not null
),
px as (
  select p.tcgplayer_product_id,
         p.printing,
         p.date::date as d,
         coalesce(p.market_price, p.low_price)::numeric as v
  from public.prices_daily p
  join card_release_floor crf on crf.tcgplayer_product_id = p.tcgplayer_product_id
  where p.source = 'tcgcsv'
    and p.grade  = 'raw'
    and p.date::date >= crf.floor_date
    and coalesce(p.market_price, p.low_price) > 0
),
stepped as (
  select px.tcgplayer_product_id,
         px.printing,
         px.d,
         px.v,
         lag(px.v) over w as prev_v,
         px.d - lag(px.d) over w as gap
  from px
  window w as (partition by px.tcgplayer_product_id, px.printing order by px.d)
),
rets as (
  select s.d,
         c.set_id,
         c.rarity,
         -- Winsorize rather than discard: a genuine large move should still
         -- register, just capped. Discarding would bias the index upward on
         -- crash days, when the extreme moves are disproportionately negative.
         least(greatest(s.v / s.prev_v, 1.0 / p.ret_clamp), p.ret_clamp) as ret
  from stepped s
  cross join params p
  join public.cards c on c.tcgplayer_product_id = s.tcgplayer_product_id
  where s.prev_v is not null
    and s.prev_v > 0
    and s.gap is not null
    and s.gap <= p.max_gap_days
),
-- Arithmetic mean of returns = a daily-rebalanced equal-weight portfolio, which
-- is the standard construction. (A geometric mean would be the average CARD's
-- experience, a different and less useful question here.)
scoped as (
  select 'all'::text as scope, ''::text as scope_key, d, avg(ret) as mean_ret, count(*)::int as n
  from rets group by d
  union all
  select 'set', set_id, d, avg(ret), count(*)::int
  from rets where set_id is not null group by set_id, d
  union all
  select 'rarity', rarity, d, avg(ret), count(*)::int
  from rets where rarity is not null group by rarity, d
),
kept as (
  select s.* from scoped s cross join params p where s.n >= p.min_components
)
select
  scope,
  scope_key,
  d as date,
  -- Cumulative product of daily mean returns, via logs (Postgres has no
  -- product aggregate). x100 makes the first retained day read 100.
  round((100 * exp(sum(ln(mean_ret)) over (
    partition by scope, scope_key order by d rows between unbounded preceding and current row
  )))::numeric, 4) as value,
  n as n_components
from kept;

-- REFRESH CONCURRENTLY needs a unique index; this is also the natural read key.
create unique index if not exists market_index_daily_unique
  on public.market_index_daily (scope, scope_key, date);
create index if not exists market_index_daily_scope_date_idx
  on public.market_index_daily (scope, scope_key, date desc);

-- Latest level per scope plus the same Δ% windows the Screener already speaks,
-- so a "vs market" column is one lookup rather than a client-side reduction
-- over the whole series.
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
    max(m.n_components) filter (where m.date = l.d) as n_components
  from latest l
  join public.market_index_daily m
    on m.scope = l.scope and m.scope_key = l.scope_key
  group by l.scope, l.scope_key, l.d
)
select
  scope, scope_key, date, value, n_components,
  case when v_1d   > 0 then round(((value - v_1d)   / v_1d   * 100)::numeric, 2) end as pct_1d,
  case when v_7d   > 0 then round(((value - v_7d)   / v_7d   * 100)::numeric, 2) end as pct_7d,
  case when v_30d  > 0 then round(((value - v_30d)  / v_30d  * 100)::numeric, 2) end as pct_30d,
  case when v_90d  > 0 then round(((value - v_90d)  / v_90d  * 100)::numeric, 2) end as pct_90d,
  case when v_180d > 0 then round(((value - v_180d) / v_180d * 100)::numeric, 2) end as pct_180d,
  case when v_365d > 0 then round(((value - v_365d) / v_365d * 100)::numeric, 2) end as pct_365d
from back;

create unique index if not exists market_index_latest_unique
  on public.market_index_latest (scope, scope_key);

-- A `drop ... cascade` takes grants with it, and service_role is NOT implicit —
-- migration 45 exists because a missing service_role grant broke the selfheal
-- job with a 403.
grant select on public.market_index_daily  to anon, authenticated, service_role;
grant select on public.market_index_latest to anon, authenticated, service_role;

-- ⚠ The statement_timeout pin is load-bearing. Without it the RPC inherits
-- PostgREST's role setting (anon 3s / authenticated 8s) and dies with 57014;
-- service_role has no rolconfig of its own and does NOT get a free pass. This
-- is the pin migration 109 had to restore after a re-run of 16 clobbered it off
-- refresh_sealed_prices_latest. Full history over ~3M price rows is the slowest
-- refresh on the site — do not remove it.
create or replace function public.refresh_market_index()
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  set local statement_timeout = '5min';
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
