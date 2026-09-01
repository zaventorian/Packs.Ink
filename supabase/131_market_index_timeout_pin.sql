-- 131 — refresh_market_index(): put the statement_timeout pin where it works.
--
-- SYMPTOM: market_index_daily / market_index_latest have been EMPTY since 130
-- landed. Every read is a 500 (`55000 … has not been populated`), so the
-- Screener's "vs Mkt" column and Price Graphing's benchmark picker / By Index
-- mode have silently shown nothing. Nothing alerted, because 130 deliberately
-- creates both matviews WITH NO DATA and leaves the populate as a manual
-- step 2 — and that step could never have succeeded (see below).
--
-- CAUSE: 130 pinned the timeout INSIDE the function body:
--
--     as $$ begin
--       set local statement_timeout = '10min';   -- ← too late
--
-- `statement_timeout` is armed when the OUTER statement (`select
-- refresh_market_index()`) begins. Changing the GUC part-way through that
-- statement does not re-arm the timer already running, so the refresh kept
-- dying at the role default. Measured over PostgREST with the service key:
-- 8s, then 57014, reproducibly, on every attempt.
--
-- Every refresh function that WORKS pins it as a function-level SET clause
-- instead — applied by the function-call machinery at entry, before the body
-- runs. Compare migration 25 (and 109, which had to restore exactly this
-- after a re-run of 16 clobbered it off refresh_sealed_prices_latest):
--
--     security definer
--     set search_path = public, extensions, pg_catalog
--     set statement_timeout = '5min'             -- ← here
--
-- Proof the difference is the placement and nothing else: refresh_price_movers
-- carries the identical `begin … exception … end` sub-block and pins at the
-- function level, and it completes a 38-second refresh over the same PostgREST
-- path with the same key. So this is the migration-109 lesson recurring, and
-- CLAUDE.md's rule should be read as "pin it as a function-level SET clause",
-- not merely "pin it".
--
-- Also replaces the exception-driven CONCURRENTLY probe with an explicit
-- `relispopulated` check. The try/catch worked, but on a matview created WITH
-- NO DATA the CONCURRENTLY attempt is GUARANTEED to raise on the first run, so
-- the happy path was an error path — which is what made the failure read as
-- ambiguous. Branching on the catalog says what we mean, and still falls back
-- to a plain refresh if CONCURRENTLY fails for any other reason.
--
-- Idempotent, additive, no DDL on the matviews themselves — safe to re-run.

create or replace function public.refresh_market_index()
returns void
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
set statement_timeout = '10min'
as $$
declare
  v_populated boolean;
begin
  -- market_index_daily
  select c.relispopulated into v_populated
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relname = 'market_index_daily';

  if coalesce(v_populated, false) then
    begin
      refresh materialized view concurrently public.market_index_daily;
    exception when others then
      refresh materialized view public.market_index_daily;
    end;
  else
    refresh materialized view public.market_index_daily;
  end if;

  -- market_index_latest
  select c.relispopulated into v_populated
    from pg_class c
    join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'public' and c.relname = 'market_index_latest';

  if coalesce(v_populated, false) then
    begin
      refresh materialized view concurrently public.market_index_latest;
    exception when others then
      refresh materialized view public.market_index_latest;
    end;
  else
    refresh materialized view public.market_index_latest;
  end if;
end $$;

revoke all on function public.refresh_market_index() from public, anon, authenticated;
grant  execute on function public.refresh_market_index() to service_role;

notify pgrst, 'reload schema';

-- AFTER APPLYING, run the initial build (it is the step 130 left undone):
--
--     select public.refresh_market_index();
--
-- It is the slowest refresh on the site and the first run is non-concurrent
-- (CONCURRENTLY cannot populate an empty matview), so give it a few minutes.
-- From then on the ETL selfheal job keeps it current — see the "Refresh the
-- market index" step in .github/workflows/etl.yml, which is deliberately
-- non-fatal: a stale benchmark costs a column for a day, and failing the ETL
-- over it would train us to ignore its alerts.
