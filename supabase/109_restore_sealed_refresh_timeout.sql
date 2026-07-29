-- Restore the statement_timeout pin on refresh_sealed_prices_latest().
--
-- Migration 25 added `set statement_timeout = '5min'` to all four raw-price
-- refresh functions. Migration 16 was later re-run (during sealed-products
-- work), which clobbered the sealed one back to its original body: no timeout
-- pin and the narrower `search_path = public`. The other three kept theirs.
--
-- Consequence: the RPC inherited the PostgREST role's 8s statement_timeout.
-- sealed_prices_latest is tiny (337 rows) but its query DISTINCT ON's over the
-- whole 3.1M-row prices_daily, so it sits near that 8s line and fails
-- intermittently with 57014 -- non-fatally from load_sealed_products.py, but
-- fatally from etl_tcgcsv_daily.py (ETL run failure 2026-07-28, also seen
-- 2026-07-26). It gets worse as prices_daily grows ~6.2k rows/day.
--
-- This restores migration 25's definition verbatim.

create or replace function public.refresh_sealed_prices_latest()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '5min'
as $$
begin
  begin
    refresh materialized view concurrently public.sealed_prices_latest;
  exception when others then
    refresh materialized view public.sealed_prices_latest;
  end;
end $$;

revoke all on function public.refresh_sealed_prices_latest() from public, anon, authenticated;
grant  execute on function public.refresh_sealed_prices_latest() to service_role;

notify pgrst, 'reload schema';
