# TCGCSV / Lorcast notes

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

- categoryId 71 = Lorcana. Archive starts 2024-02-08.
- TCGCSV daily snapshot lands ~20:00 UTC.
- **⚠ `prices_daily.date` is the UTC day TCGCSV PUBLISHED the file, read off
  `https://tcgcsv.com/last-updated.txt`, never the UTC day the run happens on**
  (2026-10-06). The 01:00 UTC retry and the GitHub fallback cron (landing as late as
  ~07:30) run on the next calendar day while TCGCSV still serves the previous evening's
  file; dated by the clock, they left that evening a hole and filed its file under the
  next day, and a late publish could claim the next day with a post-publish stamp and
  lock that day's real file out. Without the stamp, the newest 20:15 UTC cutoff that has
  passed stands in for it. `backfill_playmat_prices.py --live` already dated by the same
  stamp. Guarded by `python scripts/test_etl_snapshot_date.py`, which drives the real
  `main()` through a day of cron firings.
- **`low_price` is a sticker, not a sale.** Catalog-wide over 8 days, `market_price` changed on 30% of SKUs and `low_price` on only 9% — **71% of SKUs held an identical Low all 8 days**. Use `market_price` / `mkt_pct_*` for short-window (≤7d) movement; reserve `low_price` for medium-to-long windows. "0 movers" on a short window is usually the sticky Low, not a broken ETL — check `low_today == low_prev` first.
- **⚠ `low_price` is NOT the listing floor, and the old "any condition" story is WRONG.** TCGCSV mirrors TCGplayer's **Pricing API** `lowPrice` — a published aggregate, not a scrape of the live listing ladder. We have never pulled one: no `prices_daily` row has ever had `source != 'tcgcsv'`, back to 2024-02-08. It lands **above or below** the real floor in both directions — across 11 Attack of the Vine! cards it was below on 5, above on 3, equal on 3, and Mushu - Stealthy Dragon (#97) read $7.58 against a 72-listing floor of $8.98 on a card that exists only in NM and LP, so no cheap played copy can explain it. Independently, against the 281k-row `tcgplayer_sales_weekly` table, **41% of Lows sit >10% below the cheapest NM sale that actually happened** (p10 ratio 0.20). The discarded "that's just an LP listing" reading was a plausible story for one 2026-05 data point; it doesn't generalize and can't explain a Low *above* the floor. **`market_price` IS accurate** — median ratio 1.000 against both TCGplayer's own displayed Market and real sales — so use it as the reference value. UI labels: "Low" (no NM qualifier) and "NM Market" (explicitly NM); user-facing copy is **"TCGplayer's published Low Price for the card. It tracks the cheap end of the market."** Do not reintroduce a floor or per-condition claim anywhere. There is no per-condition pricing in the feed — TCGplayer's public pricing API doesn't expose it.
- Low price can also be contaminated by foreign-language listings — prefer Market when in doubt, but for set-level averages the `processData` fallback means Low is more inclusive.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded URL>`. The `tcgUrl()` helper wraps every TCGPlayer link — never link directly.
- **Lorcast's API key for inkable is `inkwell`**, not `inkable`. Our column is `inkable`; loader translates.
- **The legacy graded feed (retired 2026-06-30) capped `/history` at ~1 year and was very sparse for low-liquidity cards** — which is why the graded value chart needs its backward-fill. Kept only to explain that backward-fill's existence; the API and the tables are gone (see "Legacy graded deletion").
- **Image sizes**: small (200w), normal (400w), large (734w). Use `img_normal` for tiles ≤200px; `img_large` for hover/modal/poster; `img_small` ≤80px thumbs. `img_large` NOT in catalog cache (stripped); fallback to img_normal.
- **⚠ TCGCSV took its public price ARCHIVE offline (found 2026-09-27).** Every
  `/archive/tcgplayer/prices-<date>.ppmd.7z` now answers 403 with a notice from its operator
  ("temporarily removed due to rising server costs"; he asks for per-group requests and for no
  file to be fetched twice in 24 hours). The live `/tcgplayer/<category>/<group>/prices`
  endpoints still work — the daily ETL is unaffected. **`scripts/backfill_cache/` (825
  archives, 2024-02-08..2026-05-11) is therefore the only copy of those days anywhere we can
  reach: don't delete it, and it is worth a backup off OneDrive.** Any backfill of a category we
  never pulled (the playmats were the first) can reach that range and no further;
  `backfill_playmat_prices.py` reports the missing days as "archive offline", not as failures.
