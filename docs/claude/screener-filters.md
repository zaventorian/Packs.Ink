# Screener filters

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

The Screener has parity with the Cards browse filters as of 2026-05-26 via the catalog joinback pattern (`catalogByCardId` Map). Three filter tiers:

### Main (always visible)
- Mode: Raw Prices / Graded (toggle)
- Preset chips: All / Movers / Gainers / Losers / Buyouts / Crashing / Discount / Premium
- Window chips: 1D / 1W / 1M / 3M / 6M / 1Y
- Collection filter (signed-in): All / Owned / Missing
- Signal filter chips: BUY / CRSH / DISC / PREM / TRND
- **Foil / Non-Foil chips** — turn off either to drop those printings from results. Chase rarities (Epic / Enchanted / Iconic / Promo) **bypass** the foil/non-foil filter — they have no foil/non-foil duality and always appear regardless of which chip is on. Persisted in saved views.
- Smart-search input — routes through `matchesCardFilter(catalogRow, chipFilter, parsed)`
- Set dropdown
- Ink multi-select
- Rarity icon chips — **always shows every canonical rarity** (CARDS_RARITIES) regardless of which appear in current results, so users can filter to "commons only" even when commons aren't in the top gainers.

### Advanced panel (collapsed by default — 2026-05-26 expansion)
- Min/Max price (uses `priceMode` to apply to Low vs NM Market)
- Min/Max Δ% in chosen window
- **Type chips** — Character / Action / Item / Location / Song
- **Cost hex chips** — 1-9+
- **Inkable** 3-way (Any / Inkable / Uninkable)
- **Legality** 3-way (Any / Core / Infinity)
- **Strength / Willpower / Lore** numeric bucket chips
- **Keywords** multi-select dropdown (Rush, Evasive, Bodyguard, …)
- **Classifications** multi-select dropdown (Hero, Villain, Princess, …)
- All advanced filters route through `matchesCardFilter` via `chipFilter` and persist in saved views.

### Mobile

- ≤720px: hide the checkbox column (invisible behind sticky NAME anyway), tighten NAME column to 110-135px max. Default no-scroll view fits NAME + Low + NM Market + 1W on a 360px phone. Batch-select via checkbox stays available on tablet/desktop.
- Filter chips wrap to multiple rows naturally.
- **Rarity icon chips fit on one line (2026-05-27):** at ≤720px `.price-db-raritybtns` gap drops to 2px and `.price-db-raritybtn-icon` padding drops to `4px 5px` so all 9 canonical rarity chips fit a single row on a ~375px phone (the 9th, Promo, was wrapping at the desktop `4px 10px`/`3px gap` sizing).
- **The table scrolls with the PAGE — there is no box within the page** (2026-09-28, Zaven: *"I dont like how the screener is stuck in a smaller box … a weird sub scroll"*). It used to be a `max-height: calc(100vh - 280px)` scroll box, because a sticky `thead` only pins inside its nearest scroll container and the table needs one to scroll sideways. That is the "header/body structural split" this note once called deferred, and it is built now. Guarded by section 5 of `node scripts/test_screener_graded_cols.mjs`.
  - **The header is its own sticky strip ABOVE the sideways scroller** (`.price-db-stickyhead`, `top: var(--pdb-top)`), so pinning is plain CSS and never lags the page. `--pdb-top` is MEASURED from `.top-nav` (sticky on phones, ~90px; in flow on a desktop, 0).
  - **⚠ The header row renders TWICE.** The body table keeps an invisible, zero-height SIZER copy (`thead.price-db-sizehead`), so its columns still size to their header text exactly as the one table always did; the pinned copy is `table-layout:fixed` to the sizer's measured, fractional widths (`gripGeom.widths` / `tableW`). Measured aligned within 0.25px in Raw, Graded and Sealed, and after a column drag. `theadRef` is the VISIBLE copy (clicks, keyboard sort, grip height); `sizeHeadRef` is the one measured.
  - **Three things scroll sideways together** (one effect, echo-guarded so a set `scrollLeft` never fights a momentum scroll): the body (`.price-db-tablewrap`), the header strip, and **`.price-db-hscroll`, a scrollbar pinned to the bottom of the window** — the body's own sits under the last row, a page away. The pinned bar shows only on a fine pointer when the table is wider than the page, and the body's own scrollbar is then hidden; touch keeps swiping the table.
  - **⚠ `overflow:clip` on `.price-db-tablebox`, never `hidden`** — hidden makes it a scroll container and the header would pin to it instead of to the window.
  - **⚠ A HIDDEN Browser pane never delivers ResizeObserver callbacks**, so the bar's width and the header's column widths look stuck there. Verify in headless Chromium, not the backgrounded pane.
  - The windowed-rows sentinel observes the viewport, which is now simply right: the wrap only scrolls sideways.

### PSA population columns in RAW mode (2026-09-27)

Zaven, from the Screener: *"Should be able to add columns for PSA stuff in raw section."* The
gear offers eight — PSA Pop, PSA 10s, PSA Gem %, PSA 9.5 / 9s / 8s / 7s, PSA Qualified — all
hidden by default (no Pop @ Grade: a raw row has no grade). Every header says PSA, for the reason
the graded ones do: `graded_pop` holds no CGC, BGS, SGC or TAG counts. Guarded by section 9 of
`node scripts/test_graded_pop.mjs`.

- **⚠ `rawPopPick`, not `gradedPopPick`.** A raw row IS one printing, so on a card the catalog
  holds in both finishes (the `_printBadge` index) only that printing's PSA row counts, and no
  match reads "—". gradedPopPick's largest-row fallback put a card's non-foil population on its
  Cold Foil row (and a C1 Prize Wall row would have read the Top Prize count). A one-printing
  card — every Enchanted, most promos — takes the largest row, since PSA's Variety names the
  rarity or the provenance there, not a finish.
- **The pop fields land on COPIES of the filtered rows** — after the filter so only shown rows
  pay, before the sort so the columns order. Raw rows are the shared `price_movers` objects;
  writing onto them would leak pop fields into every other consumer.
- **Fetched only when shown**: a pop column switched on, or a pop sort arriving in a saved view or
  a `?v=` link (`rawPopWanted`). ⚠ It is declared BELOW `colPrefs` because its deps read it — a
  deps array is evaluated at its own declaration point, and above that line it is a TDZ crash.
- **⚠ `colPrefs[mode].known` — why eight new columns didn't appear for everybody.** The saved
  prefs list the HIDDEN columns, so a column added later is "shown" by omission: everyone who had
  ever customised the Raw table would have got all eight PSA columns at once. A column the prefs
  have not KNOWN now takes its own default, and toggling any column writes `known`. Raw prefs
  saved before `known` get it reconstructed WITHOUT the pop keys. **Other modes' legacy prefs
  keep the old rule** (they gained no columns), so a future column added to Graded or Sealed
  wants the same reconstruct line, or it will pop up for every legacy user until their next toggle.

### Graded PRICE columns in RAW mode (2026-09-28)

Zaven, from the Screener: *"add columns for PSA 10 last sold price and last 5 avg price (and I
guess for other graders/grades too … don't add like 5000 columns but maybe a custom ability w/
drop down? main one is just psa 10)"*. So ONE pair — **Last Sold** and **Avg Last 5**
(`RAW_GRADED_COL_KEYS` = `gr_last` / `gr_avg5`, also the row fields) — whose grader + grade is
picked at the top of ⚙ Columns (`packsink:screener:gradedTier`, default `PSA|10`). Both hidden
by default; both headers name the tier. Guarded by `node scripts/test_screener_graded_cols.mjs`.

- **⚠ Priced through THE ladder, `makeGradedPrintingLookup`, over the rollup keyed by card_id**
  (`buildGradedPriceIndex(rollup, null, r => r.card_id)`). A raw row IS one printing, so a C1
  Prize Wall row reads $557.99 and its Top Prize row $5,500 — never each other's. A price from a
  split card's unclassified tier, or from a card sold in both finishes whose sales were never
  split, renders `≈` with the reason in the tooltip (`rawGradedFields`).
- **`buildGradedPriceIndex` is also the Graded collection's `priceByKey` now** (keyed by pid) —
  one two-pass index instead of two copies.
- **Fetched only when shown or sorted by** (`rawGradedWanted`, below `colPrefs` for the TDZ
  reason), sharing Graded mode's rollup state and its one read (`fetchScreenerGradedRollup`).
  Behind the graded-data terms like every graded surface: asking for a column raises the terms
  prompt and shows the compact `GradedTosGate`; cells read "—" with a tooltip saying why.
- **The tier rides a saved view / `?v=` (`gt`) ONLY when the view sorts by one of the columns**
  — then it decides which rows lead. Otherwise it is a column setting like visibility, and
  applying a view leaves the viewer's own pick alone.
- Legacy Raw prefs reconstruct `known` without these two keys, same as the pop columns, so they
  don't appear for everyone who ever customised their table. They ride the CSV when on screen.
