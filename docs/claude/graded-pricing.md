# Graded pricing: legacy vs current

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Two graded price systems coexist. `GradedPremiumContext` selects between them.

**The allowlist is retired — graded is public.** `canViewGradedPremium` is hardcoded `true` (2026-07-14) and `can_view_graded_premium()` / `graded_premium_viewers` (migration 73) are **dead code, called from nowhere**. The provider value is `canViewGradedPremium && gradedTosOk`, so the only live gate is **ToS acceptance** (`GRADED_TOS_VERSION`, surface-triggered — see the tours/ToS notes). Every premium data source (`graded_sales`, `graded_sales_rollup`) is already anon-readable, so nothing server-side gates it either. `is_graded_admin()` is a SEPARATE thing and IS enforced server-side across ~10 RPCs and several RLS policies — don't conflate them.

- **Legacy (frozen, MID-DELETION).** `graded_prices_daily` → `graded_prices_latest`, per `(pid, printing, grader, grade, date)`. Third-party feed **discontinued 2026-06-30**; newest row is forever `2026-06-30`. Display contract is `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d`. Still read only by the pre-ToS graded UI, which stamps a `gradedAsOf` date. **See "Legacy graded deletion — in progress" below before touching any of it.**
- **Current.** `graded_sales` — our own per-sale eBay record (Terapeak scrape; the routine is the **`/graded-scrape` skill**, `.claude/skills/graded-scrape/`, Stages 1–4 driven by `scripts/graded_run.ps1`) → `graded_sales_rollup`. Because it stores individual sales rather than daily aggregates, it supports real **Last Sold** + **Avg of last 5** instead of a rolling average.

### Portfolio chart: printing is part of the key (do NOT regress)

`computeSalesValueHistory` / `computeSalesValueHistoryAvg5` value a slab at its **most recent sale, forward-filled** — so ONE wrong row IS the user's portfolio for days. Two invariants keep that honest, both in `makeGradedSlotSeries`:

1. **Match on printing, not just `(card_id, grader, grade)`.** Challenge Promo (C1) cards share one `card_id` across Top Prize foil and Prize Wall non-foil, which are different markets (Cinderella - Stouthearted PSA 10: **$1,707 foil vs $280 non-foil**). Keying without printing let a $33,493 Top-8 foil sale value a ~$450 non-foil slab — a two-day $67k spike on a $35k collection (2026-07-17). Vocabularies differ between tables (sales say `Foil`/`Non-Foil`/null, owned slots say `Normal`/`Holofoil`/`Cold Foil`), so both sides go through `gradedSlotBucket`, which keeps **unknown distinct from Non-Foil** and leaves version variants (Two Swords / Text Error) exact.
2. **Only enforce the split on cards that actually have two labelled printings.** With ≤1 known printing, every row (including unclassified) values the slot regardless of what it stored — the same fallback `lookupGradedPx` does, because foil-only chase cards have slots stamped `printing='Normal'` by the migration-50 backfill and a strict match would silently zero them.
3. **The split decision comes from the ROLLUP, not from sale labels, whenever the rollup is loaded** (2026-08-12). `gradedKnownBuckets(rollupRows)` builds per-tier bucket sets from `graded_sales_rollup` — whose `printing` column encodes the curated `cards.split_printing` / `foil_split` flags via `graded_sale_pkey()` — and is passed as the `knownBuckets` arg to `makeGradedSlotSeries` / `computeSalesValueHistory*` / `addUnsoldSlabsToSeries` (base series and missing-slab detection MUST share the same map). When present it is **authoritative, not unioned with the window's labels**, because labels fail both ways: a short window misses one side of a real split (C1 at 1M read one-printing → Prize Wall slab valued at Top Prize foil price), and a long window invents splits from stray seller language — "foil" on an all-foil card — which valued 2x Elsa SoW Enchanted PSA 10 at $89.10 against a ~$3,000 market at "All". Same-day sale ties sort by `scraped_at` to mirror the rollup's `rn=1` ordering (`fetchGradedSalesFor` selects it), and `computeSalesValueHistory*` append a forward-filled point at TODAY so every range ends on the same date. Net effect, verified against the largest real collection (224 slots, 34,949 sales): the endpoint is identical to the cent at 1M/3M/6M/1Y/All. Wired on home `CollectionPanel`, Collection-tab `GradedValueChart`, and the home graded movers' `isSplit`.

**`fetchGradedSalesFor` MUST filter `excluded: "is.false"`.** It didn't until 2026-07-29, so the chart rendered 8.3k quarantined rows (foreign-language, autographs, lots) that `graded_sales_rollup` and the card-detail scatter both correctly skip. Every other `graded_sales` read path filters it; audited 2026-07-29.

Guarded by `node scripts/test_graded_slot_series.mjs`, which extracts the real function text out of Index.html so it can't drift from what ships. Run it after touching any of these three functions.

### Bad-sale defences

Attribution is title-based, so wrong rows are inevitable. Three layers, in pipeline order:

1. **`terapeak_load.py`** — `exclude_reason_for()` (foreign / troll / auto) + `is_nonsingle()` (lot / set / pack / demo) decide `excluded` at load. `printing_of()` also reads the Challenge prize tiers: `Top Prize`/`Top N`/`Continentals` → Foil, `Prize Wall`/`Side Event` → Non-Foil. The foil side additionally requires C1/C2/challenge context because **Set Championship promos also say "Top Prize"** and aren't C1 foils.
2. **`scripts/backfill_graded_printing.py`** — re-derives `printing` + `exclude_reason` on existing rows from their titles. Only ever ADDS a printing where NULL (never overwrites a hand-corrected value). New exclusions are gated behind `--apply-exclusions` because hiding a sale is user-visible and the foreign-language rule can strand a regional-only card (Mickey - True Friend #25ja) with no sales at all.
3. **`scripts/flag_graded_outliers.py`** — the ingest guard; the graded analogue of `smooth_low_prices.py`. Per `(card_id, printing bucket, grader, grade)`, compares each sale to the **median of its ≤12 nearest-in-time neighbours within ±120 days** and quarantines beyond 6x / ÷6. Median not mean, and neighbours-in-time not whole-series, so a genuine ramp (Baymax $180 → $500 in two months) is not flagged. Needs ≥5 neighbours or it has no opinion, which also means it can never strand a card. Has a `--self-test` that runs automatically and **refuses to touch real data if it fails**; `--unflag` reverses every outlier decision in bulk.

**`graded_sales.exclude_reason`** (migration 111) is what makes that reversible: before it, `excluded` was a bare boolean, so a mis-set threshold couldn't be undone without also undoing every hand-reviewed exclusion. Values: `outlier`, `lot`, `foreign`, `auto`, `troll`, `cn-conflict`, `nomatch`, `manual`; NULL for rows excluded before 111.

### An unattributed sale is invisible FOREVER unless something re-asks (2026-09-20)

`terapeak_load.py --new-only` is `ON CONFLICT DO NOTHING` and has to be (it is what
makes manual `excluded` / `card_id` / grade fixes survive a re-load). The undocumented
consequence: **every improvement to the matcher is invisible to rows already in the
table.** A sale that failed attribution the day it was scraped stays failed, and it
fails silently twice over — an unmatched row is also auto-flagged `excluded`, so it
appears on no surface and in no report.

Found when Zaven asked why a **$39,100 PSA 10 sale was missing** (eBay item
298340921150, "Gold Mickey - Brave Little Tailor ... DLC Top Prize", scraped
2026-06-22). Nothing was broken at the time: the title covers 4 of that card's 5 name
tokens because it says "Gold Mickey" and never "Mickey Mouse", giving **overlap 0.80
against the 0.85 no-other-evidence gate** — the `match_confidence: 0.8` stored on the
row is literally that number, fossilised. The matcher has since learned `DLC` as a set
hint and resolves the same title at score 1.20, onto the right card. It was simply
never asked again. Meanwhile that card's PSA 10 tier showed **$3,760 and "−79%"** when
its real latest PSA 10 sale was ten times that.

- **`scripts/rematch_graded_unmatched.py` is the answer, and it is NOT
  `reattribute_graded_sales.py`** (which the graded-scrape skill rightly forbids: that
  one walks every row and excludes anything the matcher cannot place, hand-made
  attributions included). The scoping is the entire safety argument: it fetches **only
  `card_id IS NULL`** and skips any row carrying a concrete `exclude_reason`, so it can
  only act on rows that have **never been attributed** — which means they have never
  appeared on the site, so **there is no human decision about them to clobber.** That is
  what makes un-excluding them safe, and it is the one claim to re-check before widening
  the query by so much as a column.
- **⚠ It un-excludes only a row that can actually reach the rollup.** The matview's gate
  is `card_id AND grade AND sale_price AND NOT excluded`, so a gradeless row is
  attributed but deliberately **left excluded** and reported for the slab-OCR pass.
  Clearing the flag there would report a fix that fixed nothing.
- **The straggler report is half the point.** Every run names every still-unattributed
  sale at or above **$500** (`LOUD_USD`). The reason this went three months unnoticed is
  that nothing ever said "we are holding a five-figure sale we cannot place"; a dry run
  today names 741 of them, worth re-reading rather than re-deriving.
- Wired into `graded_run.ps1` as **Stage 4b**, right after the load. Guarded by
  `python scripts/test_rematch_unmatched.py` (no network — it builds a mini catalog index
  and drives the real `decide()`), which pins BOTH directions: loosening the scoping is
  silent data loss, tightening it goes back to losing the sales.
- **⚠ `CHALLENGE_CTX_RE` now includes `dlc`**, because `terapeak_match`'s `SET_ALIASES`
  always did and this regex was the one place that didn't — so a "DLC Top Prize" title
  scored a set hint and **no printing**, which would file it in a different
  `graded_sale_pkey` bucket from the same card's other sales. Measured over all 88,912
  stored titles: 225 say DLC, 180 already carry another Challenge token, and the token
  flips exactly **4** rows `None → Foil` — **three of which someone had already corrected
  to Foil by hand**, which is the argument for it. Set Championship promos ("Top Prize
  Promo 38/P1") still correctly resolve to `None`.

**Counting `#NNN` occurrences does NOT detect multi-card lots** — sellers append PSA cert and inventory numbers in the same form, so the rule flagged 574 ordinary single-card sales against 1 real lot. Don't reintroduce it; the note is in `terapeak_match.py`.

### A named VARIANT is a printing, not a card_id (2026-09-20)

Two cards' graded sales split on a **variant** rather than a finish: Peter Pan -
Pirate's Bane (Enchanted #215) *Text Error* and Genie - On the Job (Enchanted
#209) *Two Swords*. The design is already right and is easy to mis-read:

- the **`::variant::` catalog tile is RAW-ONLY and has no graded market** — it
  exists because TCGCSV has no separate SKU, so it carries null prices;
- the **graded sales live on the BASE `card_id` under a distinct `printing`**
  (`"Text Error"` / `"Two Swords"`), which `graded_sale_pkey` keeps in its own
  rollup bucket because `cards.split_printing` is true;
- `canonicalGradedSlot` maps an owned slot keyed on the clone back to
  (base, variant printing), so nothing lands on a dead id.

**So do NOT add a `cards` row for a `::variant::` id** to "make graded work" —
it already works, and a real row would duplicate the client's clone.

**⚠ Nothing in the ETL set that printing, so every such sale landed as `Normal`
or NULL.** Measured on Peter Pan #215: 19 rows filed Normal and 21 with no
printing at all, blurring a real **~49% premium** (PSA 10 avg-of-5 **$400 Text
Error vs $269 Normal**). `VARIANT_PRINTING_BY_CARD` + `variant_printing_for()`
in `terapeak_load.py` now decide it, and returning **`"Normal"` rather than NULL
when the title is silent is deliberate** — NULL parks the row in an "Unknown"
tier belonging to neither market.

**⚠ The TITLE is only ~93% reliable here, and the SLAB LABEL is the truth.** The
error is a single stray `}` after "Peter Pan" in the Shift reminder text
(corrected on a later print run), so sellers routinely miss it. Measured by
OCR-ing 280 slab labels against their titles: **14 rows whose seller never wrote
"text error" carry PSA's own `ENCHANTED-TEXT ERROR` designation, and 6 that
claim it are labelled plain.** Verified independently by reading the brace off
four cards — the OCR label agreed with the card every time, including both
silent ones.

For a GRADED card the label *is* the product identity, and it is also the most
legible thing in a listing photo, which is what makes this decidable at all:
`pytesseract` on the top 45% of the image reads `ENCHANTED-TEXT ERROR` cleanly
in ~0.4s (point it at `C:\Program Files\Tesseract-OCR\tesseract.exe`).
`terapeak_ocr_reconcile.py` is where that correction belongs long-term; the
title rule is a floor, not the last word.

**⚠ The Genie half is NOT detectable and must not be assumed to be.** Its
variant is the *double sword error* (the first print shows two swords in a
background detail, corrected to one). PSA does not designate it — 12 slabs we
already call Two Swords all read a plain `GENIE ENCHANTED` label — **no title in
the table has ever contained the words**, and the detail is too small to read in
a listing photo. Its entry in `VARIANT_PRINTING_BY_CARD` exists only to stop the
finish-reader filing Genie sales as `Foil`/NULL; the 28 rows marked Two Swords
were curated by hand and a new one lands as `Normal` until somebody says
otherwise. Separating Genie properly needs an art pass at high zoom on that one
background region, which is a different job from reading a label.

Guarded by `python scripts/test_variant_printing.py`, which also pins that the
**same two card ids and the same printing STRINGS appear on both sides** —
`VARIANT_PRINTING_BY_CARD` in Python and `SPLIT_PRINTING_CARD_IDS` /
`SPLIT_CARD_PRINTING_OPTIONS` in Index.html. Drift there is silent: the sales
just pile into the wrong bucket.

### The DISPLAYED price never crosses a split — `makeGradedPrintingLookup` (2026-09-21)

Reported by a beta user (via Zaven): adding the **foil** A Whole New World came up
at the **non-foil's** price. Six surfaces each carried their own copy of the same
ladder — try the stored printing, then `Normal` → `Holofoil` → `Cold Foil`. That
ladder is REQUIRED on an ordinary card (a foil-only chase card's slots are stamped
`Normal` by the migration-50 backfill, and a strict match drops them to $0) and
WRONG on a split card, where the rungs are two different markets. There is now ONE
ladder and every read-side caller goes through it: the header total, the owned
grid, the value chart, set-goal completion value, the tracked-tile quick-add, the
owned-slot pills and the add modal. (`gradedOwnedDeltaIndex` and `priceByKey` are
the WRITE side — two-pass and already split-aware; leave them.)

- **⚠ The split test is the rollup's printing VOCABULARY, not a count of labelled
  buckets.** `gradedKnownBuckets` needs ≥2 labelled printings, which is right for
  the portfolio chart and misses this card entirely: AWNW PSA 10 is ONE labelled
  tier (`Non-Foil`, 1 sale, $290) beside **78 unclassified sales** ($245), so the
  count says "not split" — and `priceByKey`'s pass 2 writes that $290 row under
  BOTH `Non-Foil` and `Normal`, which is the exact hop the user hit. The rollup
  already says it outright: `""` = one market, `"Unknown"` = split but
  unclassified, anything else = split and classified.
- **⚠ But the curated flag is OVER-BROAD, so the CATALOG has to corroborate it.**
  `cards.split_printing` is `true` on all TEN Challenge Promo (C1) cards and only
  **FOUR** have both printings (Kuzco, Baymax, Cinderella, Rapunzel). Invited to
  the Ball, Elsa's Ice Palace, Gold Mickey, Dragon Fire and Let It Go exist **only
  as the Top Prize foil** (Zaven, 2026-09-21) — and Invited to the Ball has three
  PSA 9 sales mis-tagged `Non-Foil`, so trusting the flag alone made a foil-only
  card "split" and then refused to price the only printing it has. Two real slabs
  went to $0. Same failure CLAUDE.md already records in the other direction (2x
  Elsa SoW Enchanted PSA 10 read $89.10 against a ~$3,000 market off a mislabelled
  handful), so it gets the same answer: a single-market card is single-market
  whatever a seller wrote in a title.
- **⚠ That catalog test is the FOIL AXIS ONLY.** A variant split (Genie *Two
  Swords*, Peter Pan *Text Error*) lives entirely inside ONE catalog printing — the
  card's single Enchanted foil — so requiring two printings there would un-split
  two genuinely different markets ($400 Text Error vs $269 Normal). A variant label
  is its own evidence; `Foil`/`Non-Foil` is the one a seller can type by mistake.
- **⚠ Only raw rows with a real `tcgplayer_product_id` count as a printing.** The
  transform emits a pid-less placeholder for some cards, and on C1 that is exactly
  the wrong signal: Dragon Fire and Let It Go each get a synthetic `Normal` row
  with `pid: null`, and both are foil-only.
- **A price taken from the unclassified tier is LABELLED, not passed off as this
  printing's.** Rows carry `rollup_printing` as provenance; `gradedPriceNote()`
  turns that into "blended across printings — N sales were never labelled". Where
  a split card has no tier for the slot's printing at all, the add modal says **"No
  Top Prize sales recorded at PSA 9"** rather than borrowing the other side's
  number, and the slot tooltip says the same.
- **⚠ Do NOT synthesise the missing side of a split set in the add modal's picker.**
  Tried and reverted the same day: offering both printings for anything in
  `SPLIT_BY_PRINTING_SETS_GLOBAL` invents a Prize Wall option on the five C1 cards
  that are foil-only. The catalog already knows which printings exist.

Guarded by `node scripts/test_graded_slot_series.mjs` (26 → 54 assertions), which
pins the foil-only case in BOTH directions — over-tightening zeroes real slabs as
surely as under-tightening mis-prices them.

### ⚠ C1 has TWO prize vocabularies, and only one was readable (2026-09-21)

`printing_of()` reads `Top Prize` / `Prize Wall`, and that covers most of the set —
but **A Whole New World uses a completely different pair and is the only card that
does**, which is why 78 of its PSA 10 sales sat unclassified while Cinderella's and
Rapunzel's classified cleanly. Meanwhile Kuzco (135), Baymax (176), Dragon Fire
(360) and Invited to the Ball (23) carry **no printing token at all** — 694 sales
with nothing to read, and for the two genuinely two-sided ones that is still open.

- **`INFINITY_WEEKEND_RE` → Non-Foil.** PSA prints `INFINITY WEEKEND` as the
  sub-designation on that card's non-foil slabs (label photographed), and sellers
  copy the line into titles — so the distribution name is the finish, exactly as
  `Prize Wall` is. Measured over all 88,912 stored titles: **41 say it, all 41 are
  this one card, and NONE already carries a printing**, so it can only fill NULLs
  and can never overwrite a hand correction. At PSA 10 it separates what it should:
  $213 tagged vs $396 untagged.
- **⚠ The foil counterpart is deliberately NOT a rule.** CGC labels the foil
  `World Championship - Rainbow Foil`, and it is tempting to read the event name —
  but only the "Rainbow Foil" half is evidence, and that already contains "foil" so
  the existing test catches it. All 9 bare `World Championship` titles are CGC 10s
  at **$145–$200 (the CHEAP side)** and one is **already tagged `Non-Foil`**.
  Adding it would guess, and on a split card a wrong finish files the sale in the
  wrong market.
- It sits beside `PRIZE_WALL_RE`, below the explicit finish words, so an explicit
  "foil"/"non-foil" in the title still wins — the token only decides a title that
  names no finish at all, which is every one of the 41.
- Apply to stored rows with `python scripts/backfill_graded_printing.py --commit`
  (dry run by default; only ever fills NULLs). Both directions are pinned in
  `python scripts/test_printing_of.py` (23 → 29 cases).

### Price Graphing "By Graded" mode

Ported off the frozen legacy feed onto `graded_sales` 2026-07-29 (it had been graphing lines that all flat-lined at 2026-06-30 for every user).

- **Picker** reads `graded_sales_rollup`, joined to the catalog by **`card_id`** — not `tcgplayer_product_id`, which is null or wrong for a chunk of promos. Rows show `last_sold_price` + `sale_count` + the C1 `Top Prize`/`Prize Wall` variant label.
- **Series** are per-sale from `graded_sales`, filtered `excluded=is.false` **and on printing** — same trap as the portfolio chart: C1 cards share a `card_id` across two very different markets, and unfiltered they plot as one zig-zag. The rollup stores an unclassified printing as `""` while the sales table stores `NULL`, so the fetch maps `""` → `printing=is.null`.
- **The Low / NM Market toggle is repurposed**, because a slab has neither: `low` = each individual sale, `market` = the rolling mean of that sale and the 4 before it. Both the toggle buttons and `priceLabel` relabel to **Sale price / Avg of last 5** when `mode === "graded"`, and revert for every other mode.
- **`gradedCompareId(g)` is the single source of truth for the compare-list key.** The picker's selected-state test and the built item's `card_id` used to be computed independently and disagreed about whether printing was in the key — so a graded tier could never be un-checked and clicking twice added a duplicate line. Never inline that template string again.

### Legacy graded feed — DELETED 2026-07-29

The third-party TCGPriceLookup feed (discontinued 2026-06-30) and everything that read it are gone. `graded_sales` → `graded_sales_rollup` is now the ONLY graded price source.

**Client:** deleted `fetchGradedPrices`, `fetchGradedHistoryFor`, `computeGradedValueHistory`, `computeGradedDeltas`, `GradedPricesTab` (~260 lines), `buildGradedSeries`, both `gradedAsOf` staleness stamps, and the orphans that fell out (`latestPrices`, `gradedSynth`, `gradedByPid`, `gradedHistoryRows`, `ownedGradedSlotsByKey`, `tileHistory`, `gradedCurrentValue`). Every `gradedPremium ? new : legacy` collapsed to the new side. 28 + 6 dead `.graded-*` CSS rules removed from styles.css.

**The ToS gate stays.** `gradedPremium` resolves to `gradedTosOk`, so where the legacy UI used to render, `<GradedTosGate/>` now does — a compact "Review terms" card that re-fires `signalGradedSurface()`. Live on the card-detail Graded tab and the Screener in graded mode. Collapsing the gate instead would have shown licensed data to users who never accepted the terms.

**DB:** `supabase/112_drop_legacy_graded_feed.sql` — **APPLIED 2026-08-22** (all three legacy relations verified 404 via REST). All 70,990 rows archived to `Desktop/graded_prices_daily_archive_20260729.jsonl` beforehand, because `graded_sales` is wider (2023-06-19..present, 7,704 tiers vs 1,761) but **not a superset — 103 legacy tiers have no rows in it** (their last reference price lives only in that archive).

**Scripts:** all 8 retired helpers deleted; `etl.yml` + the `etl-debug` skill de-referenced (the skill had advertised `job=graded` as valid long after that job ceased to exist).

Things that survived the cull and must NOT be "cleaned up" later:

- **`gradedRowValue` and its `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d` chain.** Those are the field names `priceByKey`'s synthesizer emits (`rowOf` sets `ebay_avg_1d = avg_last_5`), NOT columns on any table. Deleting them breaks premium valuation and the Last/Avg-5 toggle. `GradedCollectionAddModal` was the last place poking them directly and now goes through `gradedRowValue(row, "avg5")`.
- **`.graded-tab`, `.graded-tab-explain`, `.graded-qty-btn`, `.graded-printing-toggle`** — look legacy, still used by `GradedSalesTab` / the owned-copies panel.
- **`!premiumGraded` in the Screener is NOT a legacy signal.** `premiumGraded = showGraded && gradedPremium`, so it is also true in Raw and Sealed mode; the signal chips and Non-Foil/Foil chips are gated on it and must keep rendering there. Left untouched deliberately.

**One-shot IDB eviction shipped.** The old code mirrored legacy prices to `offlineMirrorWrite("gradedprices")` and read them back whenever the fetch came up empty — after the drop that would have served frozen June prices from IndexedDB forever. The fetch, the write and the read are gone, plus a guarded `idbDel("mirror:gradedprices")` behind `packsink:evictedGradedPricesMirror`. `graded:` / `gradedgoals:` / `gradedown:` are separate buckets — don't wipe those.

Verified in-browser: app boots clean, no console errors; Screener graded shows the rollup columns (Last Sold / Avg Last 5 / Sold / Raw Low / Raw Mkt) with ToS accepted and `<GradedTosGate/>` without; card-detail graded renders the per-sale scatter; Price Graphing graded plots identical coordinates to its pre-rip baseline. `node scripts/test_graded_slot_series.mjs` passes.
