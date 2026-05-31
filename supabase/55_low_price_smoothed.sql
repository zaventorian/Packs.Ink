-- Per-day phantom-spike smoothing for collection value.
--
-- TCGCSV's `low_price` is the lowest *active listing*, not the lowest sale.
-- A single mispriced listing (overpriced LP copy, foreign-language listing,
-- "$99.99 stuck for 5 days") drags Low far away from what the card is
-- actually worth, and that shows up on the user's portfolio chart as a
-- multi-thousand-dollar phantom move. The 2026-05-14 → 2026-05-26 Black
-- Cauldron Cold Foil run is the canonical example: Low went from ~$14 to
-- $2,140 to $99.99 to $15 while NM Market never left the $13.62–$14.15 band.
--
-- This column carries a smoothed value for days that an off-line job has
-- identified as phantom spikes (short-lived deviations that snap back to
-- baseline). The smoothing job runs nightly over the trailing ~60 days and:
--   1. computes a robust baseline from the surrounding window (median of
--      [D-30, D-1] and [D+8, D+45]),
--   2. flags days where Low(D) > 2.5× pre_baseline OR < 0.4× pre_baseline
--      AND the post_baseline confirms a snap-back (post within ±30% of pre),
--   3. writes (pre+post)/2 into low_price_smoothed for the flagged days.
--
-- Days the job doesn't flag stay NULL. The collection-value chart reads
-- coalesce(low_price_smoothed, low_price) so unflagged days pass through
-- untouched.
--
-- Scope: collection-value chart ONLY. Every other surface (card detail
-- price history, Price Graphing, Screener, mover banner, price_movers
-- matview) keeps reading raw low_price so real-time market signal stays
-- intact. Today's row is never smoothed (we can't tell yet if it's a
-- phantom) — the smoothing reaches back at most ~7 days from "today" once
-- there's enough post-data to confirm a snap-back.
--
-- Idempotent on re-run.

alter table public.prices_daily
  add column if not exists low_price_smoothed numeric(12,4);

comment on column public.prices_daily.low_price_smoothed is
  'Phantom-spike-smoothed low_price for collection-value rollup only. '
  'NULL means use raw low_price. Written nightly by scripts/smooth_low_prices.py.';

-- PostgREST schema cache refresh so the column is queryable immediately.
notify pgrst, 'reload schema';
