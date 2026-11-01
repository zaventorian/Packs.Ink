-- 199_latest_raw_prices_before_market.sql (2026-10-24): seeds carry market_price too.
--
-- The Home Collection chart now has a Low / NM Market switch (one preference for
-- the Home panel, the Collection tab, and the Sealed and Playmats tabs). Its
-- range seeds (migration 186) come from this function, which returned Low only.
-- Without the market price a seeded item would be valued at its LOW going into
-- the range and at NM Market after it, and the range pill (chart last minus chart
-- first) would show a gain that never happened: the same shape of lie 186 fixed.
--
-- The return type changes, so the old function is dropped first (CREATE OR
-- REPLACE cannot change it). Everything else is migration 186 verbatim, INCLUDING
-- the `low_price is not null` filter: the row chosen is the same row Low mode has
-- always seeded with, so Low mode is byte-identical; Market mode reads
-- market_price from that row and falls back to the smoothed Low when it is null.
--
-- An old client ignores the extra column; a new client against a database
-- without this migration gets seeds with no market_price and falls back to Low.
--
-- Invoker rights, same grants as 186. Idempotent.

drop function if exists public.latest_raw_prices_before(int[], text[], date);

create function public.latest_raw_prices_before(
  p_pids int[], p_printings text[], p_before date)
returns table (tcgplayer_product_id int, printing text, date date,
               low_price numeric, low_price_smoothed numeric, market_price numeric)
language sql stable security invoker set search_path = public as $$
  select k.pid, k.printing, x.date, x.low_price, x.low_price_smoothed, x.market_price
  from unnest(p_pids[1:500], p_printings[1:500]) as k(pid, printing)
  cross join lateral (
    select p.date, p.low_price, p.low_price_smoothed, p.market_price
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
