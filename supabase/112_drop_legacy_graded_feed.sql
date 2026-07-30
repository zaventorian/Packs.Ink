-- Drop the legacy third-party graded price feed.
--
-- ⚠ DO NOT APPLY THIS BEFORE THE CLIENT CHANGE IS DEPLOYED. The currently-live
-- Index.html still reads graded_prices_latest for pre-ToS visitors; dropping
-- these objects first makes those reads 404 in production. Order:
--   1. deploy the Index.html that no longer references the legacy tables
--   2. confirm prod is serving it
--   3. run this migration
--
-- Context: the feed was discontinued 2026-06-30, so graded_prices_daily has been
-- frozen at that date ever since — nothing has written to it in a month. It is
-- superseded by our own per-sale graded_sales -> graded_sales_rollup, which is
-- strictly wider: 2023-06-19..present vs 2025-05-17..2026-06-30, and 7,704
-- (card, grader, grade) tiers vs 1,761.
--
-- Not a pure superset, though: 103 legacy tiers (5.8%) have no rows in
-- graded_sales. Those lose their last known reference price here. All 70,990
-- rows were archived to Desktop/graded_prices_daily_archive_20260729.jsonl
-- (18.9 MB, newline-delimited JSON, verified 70,990 distinct PKs) before this
-- was written, so the drop is recoverable.
--
-- Provenance: migration 32 created the table + matview + refresh function + the
-- `graded_prices_daily_public_read` RLS policy; 33 added ebay_low_price /
-- ebay_high_price and recreated the matview; 49 rebuilt the PK and matview around
-- `printing` and granted service_role DELETE; 45 backfilled matview grants; 64
-- revoked the refresh function's PUBLIC execute. All of it goes here.
--
-- The refresh function is retired with them — the ETL that called it
-- (etl_tcgpricelookup_daily.py) was deleted in the same change.
--
-- No RPC returns legacy columns, so nothing needs recreating alongside this.
-- get_shared_collection_graded() reads only graded_collection_items + profiles
-- (verified against migration 51, its most recent definition).

begin;

drop materialized view if exists public.graded_prices_latest;

-- Refresh helper for the matview above; nothing else calls it.
drop function if exists public.refresh_graded_prices_latest();

-- Indexes and grants go with the table.
drop table if exists public.graded_prices_daily;

commit;

notify pgrst, 'reload schema';
