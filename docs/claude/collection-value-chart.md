# Collection Value chart: phantom-spike smoothing (migration 55)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

TCGCSV's `low_price` is a published aggregate, not a sale price (and NOT the listing floor — see the TCGCSV notes) — it detaches from what is actually trading and pins Low at $99 / $200 / $2,140 for days while NM Market never moves (Black Cauldron Cold Foil 2026-05-14 → 2026-05-26 is the canonical example: ~$14 → $2,140 → $99 → $15 across 13 days, Market stayed $13.62-$14.15 the whole time). Without intervention that single bad listing renders as a multi-thousand-dollar windfall/crash on the Collection Value chart. **Migration 55 adds `prices_daily.low_price_smoothed`** (nullable numeric); the nightly `scripts/smooth_low_prices.py` ETL writes smoothed values for days it identifies as phantom spikes; `computeCollectionValueHistory` reads `r.low_price_smoothed ?? r.low_price` so unflagged days pass through untouched.

**Scoped to the Collection Value rollup ONLY.** Every other surface — card detail Price History, Price Graphing, Compare, Screener, mover banner, `price_movers` matview, "Your Top Movers" home tiles — keeps reading raw `low_price`. Phantom spikes are real market events worth seeing in those views; smoothing only kicks in for "what was my portfolio actually worth on day X" where honesty matters more than realtime signal. The user explicitly wants the spike to appear on the per-card history; only the portfolio rollup should be denoised.

### Algorithm (`scripts/smooth_low_prices.py`)

Two-phase per `(tcgplayer_product_id, printing)` series:

1. **Mark anomalous days.** For each day D with ≥ 15 days of `low_price` data in [D-30, D-1], compute the rolling median. Day is anomalous if `low(D) ≥ 2.5 × median` OR `low(D) ≤ 0.4 × median`.
2. **Group into stretches** — consecutive anomalous days, tolerating gaps ≤ 3 days (brief mid-phantom returns to baseline like Black Cauldron's May 16 = $13 between May 15 = $119 and May 18 = $61 are part of the same phantom).
3. **Per-stretch evaluation.** For each stretch `[start, end]`:
   - **Duration cap:** if `end - start + 1 > 14` days → real move (meta hype etc), leave raw.
   - **Outer baselines:** median of `[start-30, start-1]` (≥ 15 samples) and `[end+8, end+21]` (≥ 10 samples). Post window starts at end+8 so any tail of the phantom doesn't pollute the post-median.
   - **Snap-back check:** post within ±30% of pre (`0.7 ≤ post/pre ≤ 1.3`). If not → real move, leave raw.
   - **Substitution:** every day in the stretch (including intermediate gap days) gets `low_price_smoothed = (pre + post) / 2`.

Median (not trimmed mean) is used throughout for robustness — even when 6 of 20 days in a window are spikes, the median still picks a normal-day value.

**Per-day algorithms don't work — must be stretch-based.** A per-day check can't distinguish "phantom that lasted 13 days" from "real move that lasted 13 days, now over": both look identical (pre ≈ post ≈ old baseline) if pre/post windows reach beyond the deviation. The duration cap is the only thing separating phantom from meta-hype, and it has to be measured against the *full stretch*, not a single day. (Initial implementation was per-day; failed the 14-day-true-move synthetic test case — both endpoints had pre/post matching old baseline.)

**Settling lag is intentional.** Today's row is never smoothed — we can't tell if a current spike is real or phantom yet. The script walks the trailing 60 days but stops at `today - RECENT_SKIP (=7)`. A spike won't be smoothed until ≥ 10 days of post-window data exist AND the median confirms snap-back, so Black Cauldron's May 14-26 stretch starts getting smoothed ~2026-06-13. User explicitly accepts the lag — "chart honesty in the moment matters more than instant historical revision."

### Wiring

- **ETL:** `.github/workflows/etl.yml` `smooth` job, `needs: prices`, fires on the daily safety-net cron + `workflow_dispatch` (job=prices|both). Idempotent — re-runs the trailing 60 days and overwrites as needed. Days outside the eval window stay frozen.
- **Client:** `fetchCollectionPriceHistory` adds `low_price_smoothed` to the SELECT with schema-tolerant 42703 retry (fetch still works pre-migration). `computeCollectionValueHistory` swaps in the coalesce. Other paths (`fetchCardHistory`, the EV/sealed price-history fetch at ~line 6439) intentionally keep `select: "...low_price..."` raw.
- **Cache invalidation:** `packsink:colvalue:v2:...` → `v3` (rollup logic changed); `AUX_CACHE_VERSION = "2026-05-30-low-price-smoothed"` wipes every existing user's aux cache on next page load; `sw.js` CACHE_VERSION → `packsink-v111`; `?v=110` → `?v=111` on styles.css/logo.js.

### Tunables

All at the top of `scripts/smooth_low_prices.py`. If outcomes feel off:

- `MAX_PHANTOM_DURATION_DAYS = 14` — phantom-vs-trend dividing line.
- `UP_SPIKE = 2.5` / `DOWN_SPIKE = 0.4` — anomaly thresholds vs rolling median.
- `SNAP_LOW = 0.7` / `SNAP_HIGH = 1.3` — post/pre snap-back band.
- `GAP_TOLERANCE_DAYS = 3` — max gap between anomalous days inside a single stretch.
- `RECENT_SKIP = 7` — minimum days between today and the most-recent smoothable day.

The FAQ ("Tracking your collection" section, Help bubble `?`) explains this user-facing in plain English. If the algorithm gets retuned, update both the script comments AND the FAQ paragraph.

### Synthetic test cases (run before changing the algorithm)

`scripts/smooth_low_prices.py` exposes `compute_smoothed_for_series(series, eval_start, eval_end)`. Four cases must all hold:

1. **13-day phantom (Black Cauldron shape):** all 13 days smoothed to the surrounding baseline.
2. **30-day sustained move ($3 → $30 → $3):** 0 days smoothed (duration > 14).
3. **3-day pump ($3 → $100 → $3):** all 3 days smoothed.
4. **Step-up with no return ($3 → $30 forever):** 0 days smoothed (post never snaps back).
