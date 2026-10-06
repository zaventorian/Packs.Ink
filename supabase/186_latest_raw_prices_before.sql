-- Migration 186: latest_raw_prices_before — the price each owned item had
-- going INTO a chart range.
--
-- Applied 2026-10-06 through the connector. Additive; the client tolerates its
-- absence (no seeds, the chart behaves as before).
--
-- The home Collection chart fetched prices_daily from the range start only,
-- so an item with no price row inside the range (a promo last priced months
-- ago) was missing from the whole chart, and one priced sparsely joined it
-- part-way through. The headline counted both at today's price, and the range
-- pill (headline minus the chart's first point) read them as gains: owning a
-- $5,999.99 Elsa last priced in June showed "+$5,999.99 (+150,000%) past 1M"
-- (review, 2026-10-06). Seeding each owned (product, printing) with its
-- newest priced row before the range is what forward-fill needs to be true.
--
-- One index probe per key on prices_daily_tcgcsv_raw_idx
-- (tcgplayer_product_id, printing, date desc). Measured: 1,500 keys in ~2.7s
-- on a mostly cold cache, so the client sends batches of 250 in parallel
-- rather than raising the anon statement_timeout (a raised timeout is a lever
-- for anyone). Capped at 500 keys per call for the same reason.
--
-- Invoker rights: prices_daily is already anon-readable; this reads nothing
-- the caller couldn't fetch row by row.
--
-- Idempotent.

create or replace function public.latest_raw_prices_before(
  p_pids int[], p_printings text[], p_before date)
returns table (tcgplayer_product_id int, printing text, date date,
               low_price numeric, low_price_smoothed numeric)
language sql stable security invoker set search_path = public as $$
  select k.pid, k.printing, x.date, x.low_price, x.low_price_smoothed
  from unnest(p_pids[1:500], p_printings[1:500]) as k(pid, printing)
  cross join lateral (
    select p.date, p.low_price, p.low_price_smoothed
    from public.prices_daily p
    where p.source = 'tcgcsv' and p.grade = 'raw'
      and p.tcgplayer_product_id = k.pid and p.printing = k.printing
      and p.date < p_before and p.low_price is not null
    order by p.date desc
    limit 1) x;
$$;

revoke execute on function public.latest_raw_prices_before(int[], text[], date) from public;
grant execute on function public.latest_raw_prices_before(int[], text[], date) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
