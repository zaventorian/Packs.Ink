# price_movers matview gotcha

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Computes Δ% across 6 windows (1D / 1W / 1M / 3M / 6M / 1Y) for both low and market. **`low_prev` is "most recent non-null low BEFORE low_today's own date"** — migration 26 fixes the original bug that collapsed pct_1d to 0 for sparse-listing chase cards.

### ⚠ A move has to be OBSERVED inside its window (migration 172, 2026-09-27)

Migration 26's anchoring had a second edge nobody saw for months: once a SKU stops
updating, the matview reported the last change it ever had as its **1D move, every day,
forever**. On 2026-09-26 Cruella De Vil - Miserable As Usual (Promo Set 1, Holofoil) read
**+108% 1D** (a Jun 1 -> Aug 9 move, last market price 48 days old) and −99.98% on a
junk $0.25 listing. It was the #1 tile of the home Promo Movers, #1 in the Screener's NM
Market view, the #1 riser on any NM Market ticker reel, and led the Discord digest.

- **The rule: a window's Δ% is null unless that side's latest observation falls INSIDE
  the window — `date > newest - N`.** For 1D that means observed on the newest price date
  itself. `abs_pct_1d` follows `pct_1d`. Prices (`low_today` / `market_today` and the
  baselines) are untouched — the Screener still shows a SKU's last known price.
- **`low_date` / `market_date`** carry each side's latest observation date, so a client
  can tell a stale price from a live one.
- **Only 1D ever showed a phantom.** The longer windows compare against the last
  observation on or before `newest - N`; when the latest one is older than N days that
  baseline IS the latest one and the window computed exactly 0% (which every movers
  surface already drops). The guard turns those into null too.
- **Measured: 34 of 5,893 rows** had a stale side, 19 with a nonzero 1D. After applying,
  an exhaustive live check (all 70,704 row × side × window cells) found every present Δ%
  arithmetically right, 275 withheld for age, and `low_date` / `market_date` equal to
  `prices_daily` on every row.
- **Deliberately NOT bounded: the PREVIOUS observation.** A fresh row whose prior price
  is days old still compares against it (forward-filled, like every longer baseline). It
  measured 0 rows that day, and it is a one-day misattribution rather than a daily repeat.
- **The same flaw lived in both client Δ% helpers**, which anchored every window on the
  series' own last sample — so the card page said Stitch - Rock Star moved **+102% in 1M**,
  81 days after its last price. Both now take the same rule (guarded by
  `node scripts/test_price_freshness.mjs`):
  - **`computeSeriesDeltas(rows, field, asOf)`** (card page Price changes, its banner tile
    and the image export) reads `asOf = catalogPriceDate()` — the catalog's newest
    `price_date`, stamped by App wherever it sets the catalog. **⚠ It is that date and not
    `lastRawPriceDate` on purpose**: the per-card history cache (`packsink:hist:`) is
    wiped exactly when the catalog date advances, so the two can never disagree about
    which day is "today". An asOf NEWER than the data it judges would blank 1D on every
    fresh card.
  - **`computeSealedDeltas(history, {asOf})`** floors asOf at the newest date in its own
    input (the matview's `latest` CTE does the same), so every batch caller — Screener
    Sealed, Sealed Movers, sealed tiles — guards itself with no argument. Only the
    single-product sealed modal passes `catalogPriceDate()`, because it reads the same
    wiped cache. **⚠ Never pass it to a batch whose history is cached separately**
    (`_sealedMoverHist`): after an ETL the catalog date moves first and every product
    in that batch would read "—" for an hour.
  - **Neither is ever anchored BEFORE the data's own last sample** — an asOf older than
    the data (a session that outlived an ETL) is ignored.
  - **The card page's price-standing chip needs a price TODAY** (`seriesPricedOn`), the
    rule `SealedDetailModal` already had: otherwise "near its 12-month high" judged a
    price nobody could buy.
- **The Discord digest checks the rule again itself** against `prices_daily`, so a
  matview rebuilt from an older migration still can't put a stale move in a post. See
  the digest section.
- **The Discord bot follows it too** (added when this shipped, 2026-09-28): the bot
  copies `computeSeriesDeltas` and `seriesPricedOn` from Index.html, and
  `discord/src/data.js` `priceSummary(rows, asOf)` passes the card index's `priceDate` —
  the bot's copy of `catalogPriceDate()`. The index is rebuilt daily after the ETL, and an
  asOf older than the data is ignored, so a late index costs nothing. Guarded in
  `test_discord_bot.mjs`.
- **⚠ Re-running an older price_movers migration reverts all of this** — and migration
  10 would also bring back the $5 gate 120 removed. The ETL's recovery hint used to say
  "run supabase/10_price_movers_matview.sql"; it now names 172, which alone restores the
  matview, its grants and the pinned `refresh_price_movers()`.
