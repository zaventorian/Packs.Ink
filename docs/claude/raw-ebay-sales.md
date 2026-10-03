# Raw eBay sales — the ~24 promos TCGplayer cannot price (2026-09-20)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`card_prices_latest` is an INNER JOIN on a TCGplayer product, so a card TCGplayer
has never recorded a sale for shows **nothing**, and one it froze on shows a
fossil. Measured on the live catalog: promos freeze for **50–181 days** where
Enchanted/Iconic chase cards freeze for 10–18 (packs keep supplying those, so a
flat reading there is a lull, not an absent market). The worst cases are total —
Challenge Promo #5 *Mickey Mouse - Brave Little Tailor* has **never** had a
`market_price`, #7 *Elsa's Ice Palace* likewise, #9 *Baymax* shows the $63
**non-foil** while its foil slabs reach $33,494. Meanwhile a RAW *Rapunzel -
Gifted with Healing* 4/C1 Foil sold on eBay for **$16,406**. For these cards an
eBay sold price is not a second opinion; it is the only honest number there is.

Pipeline: `raw_watchlist.py` (the list) → `raw_topup.py` (scrape) → `raw_match.py`
(attribute) → `raw_load.py` (load + review report) → `raw_sales` →
`raw_sales_rollup` (**migration 163**). Guarded by
`python scripts/test_raw_match.py` (no network, no `.env`).

**Scope is promos only, deliberately.** A promo is a fixed, event-distributed
population, so its market is structurally somewhere other than TCGplayer. Every
Enchanted and Iconic is **out** — TCGplayer is right about those, and a second
source could only disagree with a correct number.

### The Challenge foils with a same-set twin (2026-09-30)

Four cards joined the list at Zaven's call ("high value singles, we'd use ebay as the source of truth"): Challenge Year 3 **#11 Stand Out, #12 Down in New Orleans, #14 Tinker Bell - Insistent Fairy**, and C3 **#13 Mother Knows Best**. Each is the FOIL of a non-foil with the same name in the same set (#15 / #16 / #18, and 1/C3) that TCGplayer prices at $70 to $120, against asks of $775 to $6,500 for the foil.

- **`TWIN_REQUIRE` carries them**: a sale counts only when its title has the foil's own printed number (`11/C2`, `13/C3`) or the word foil with no "non" in front of it. "CCQ Promo" with neither is dropped as `twin`: the cheap side of the trade.
- **`set_hint` reads `C3` and `CCQ` as the C3 set.** Sellers write "CCQ Promo" far more often than "C3". When a C4 season exists, `ccq` alone stops being decisive and has to go.
- **"Non-foil" in the title is a veto, even beside the foil's own number.** A real listing read "13/C3 NON-Foil" at $99.99 against a $600 median.
- **`same_set_twin`**: a title with no collector number that says foil ("Mother Knows Best Foil Top 32 CCQ Promo") ties the matcher between the two twins. When it lands on the non-foil and the title passes the foil's proof, it is the foil. Same set only, so a Fabled "Stand Out Foil" is never promoted to the Challenge prize.
- First pull, 2026-09-30: Mother Knows Best 13/C3 has **19 raw sales, $400 to $1,050, last $478.86, average of the last five $540.77**. Stand Out, Down in New Orleans and Tinker Bell were not pulled: eBay showed a captcha and the run stopped, as it must.
- `terapeak_topup.py` used to put a FIXED checkout path first on `sys.path`, so a worktree ran the main checkout's watchlist and never asked a search added on a branch. It uses its own folder now.
- `SET_NETS` gained `"C3"`. The first pull for a new search is deep on its own, because it has no file yet.
- The one slab sale we already held (PSA 10, $2,225, excluded as `cn-conflict` before the card existed) was attributed by hand the same day.

### The asymmetry that drives every rule

Publishing a wrong number here is far worse than publishing nothing: these cards
are on the watchlist *because* the site shows a dash or a fossil, so anything
shown will be believed — and every mis-attribution available is an order of
magnitude off, in **both** directions. So every gate fails CLOSED and the
residual is reported, never guessed. `raw_load.py` is **dry-run by default**.

- **⚠ A name search is a NET, not an identity.** Every watchlist token nets 2–5
  different catalog cards; "Brave Little Tailor" alone returns The First Chapter
  #115 (a bulk rare), D23 Collection #1, and Promo Set 1 #1, whose graded copies
  pass $14,000.
- **⚠ So the searches pair a name with a PROMO token, and they were MEASURED
  (2026-09-27).** The first deep run of bare `"Lorcana" "Brave Little Tailor"`
  hit the 60-page cap on bulk #115s and never reached the 2022 sales. Now: 8
  set-wide nets (`C1`, `Top Prize`, `Prize Wall`, `Side Event`, `C2`,
  `D23`+`2022`, `Expo`+`2022`, `Cruise`) plus per-card `<name>`+`Challenge` /
  `D23` / `2022` / `P3`, 45 in all. Replayed against all 3,225 evidence-bearing
  titles we hold for the 24 cards, they catch **3,201**, and every one of the 24
  misses is a graded row on the wrong card or a typo. The old subtitle-only list
  was WORSE on recall, not just noisier: of 184 Captain Hook P1 #7 sales only 41
  say "Forceful Duelist". **Terapeak also matches item specifics** (a "Lorcana"
  search returns PSA auto-titles with no "Lorcana" in them), so a title-only
  replay is a floor. **⚠ A per-card search that is a subset of a net is
  redundant** (`"Rapunzel" "C1"` ⊂ `"C1"`) and just adds ~67s of anti-captcha
  wait; `test_raw_match.py` pins that every search names its card and that no
  one-term search on a base-card name comes back.
- **⚠ `terapeak_match.match_one` stays the ONLY matcher.** Measured over the
  8,253 corpus titles carrying a watchlist token, stripping every grading token
  out of a title (which is what a raw title looks like) changed the attributed
  card in **0 of 8,182** cases. Don't write a second matcher; `raw_match` adds
  gates on top of that one.
- **⚠ PRICE MAY NEVER ATTRIBUTE A SALE.** Using "too cheap to be the promo" to
  reject a row, or "$16,000 must be it" to accept one, makes the published price
  a function of the assumption — we would be choosing which sales count by
  whether they already agree with the answer, then publishing that answer as
  evidence. Price flags a row for a human; it decides nothing.
  `test_raw_match.py` fails if `raw_verdict` ever grows a price argument.

### The three gates, and what each cost to learn

1. **A slab is not a raw sale.** A name sweep returns that card's slabs, which
   are already in `graded_sales`. `tc.parse_grade` needs a grader AND a number,
   so **23 slabs leaked** the first cut — the dearest a **$17,500** "Gem Mint 10"
   whose title never says PSA. Gate 1 is three tests: a full parse, a bare grader
   NAME ("PSA Authentic", "TAG Score 942"), and grader-less grading language
   (`gem mint`, `graded`, `Grade 9`, `pristine`, `pop 90`). **⚠ Every word was
   cleared against card names** — bare `badge` hits *Detective's Badge*, bare
   `pop` hits *Gazelle - Pop Star*, bare `slab` hits *Vision Slab*, and a bare
   `mint` would eat the "Near Mint" most raw listings say about themselves.
2. **No evidence means no attribution.** `match_one` matches on name tokens alone
   (its `ov >= 0.85` branch), and same-named cards have IDENTICAL token sets, so
   they tie and the winner is arbitrary. **700 corpus titles carry neither a
   collector number nor a set hint**, and that tiebreak put **$1.75 on Let It Go
   (C1 #41, a $1,350 promo)** and $13.50 on Stouthearted. Undecidable, so dropped.
3. **Off-watchlist sales are dropped.** A sale attributing to TFC #115 is real,
   and that card has a live TCGplayer price which is the authority for it.

### Things that wear a card's NAME and beat every identity gate

These satisfy gates 1–3 completely, because they genuinely *are* "the D23 Mickey
Brave Little Tailor". Only a product-type rule stops them.

- **PINS need a BROADER rule here than in the graded pipeline, and the two must
  not be merged.** `tc.ACC_RE` is narrow on purpose — a bare `\bpins?\b` matches
  ~30 active graded rows that are real card sales merely mentioning a bundled pin
  (one $8,500). The raw sweep inverts that trade: those all say PSA so gate 1 has
  them, while **17 actual pins survived at $7.00–$14.99** against a card whose
  graded copies pass $14,000. `raw_match.RAW_PIN_RE` is raw-only; the test fails
  if that breadth migrates into `ACC_RE`.
- **MERCH**: a 13x19 **poster** of Elsa - Snow Queen sold at $34–$100 and
  attributed cleanly. `proxy`/`custom`/`replica` matter more here than anywhere —
  a counterfeit of a $1 common isn't worth making. **⚠ bare `print` is NOT
  matched** (367 corpus hits are legitimate "1st Print"), and `custom` is safe
  only because `\bcustom\b` cannot match "Customer".
- **⚠ "EXTENDED ART" IS A DIFFERENT CARD.** The 2024 D23 Collection printings are
  the Rainbow Foil / Extended Art ones at **$16–$316**; the 2022 Promo Set 1
  cards tracked here run **$700–$1,900**. They share a character, a collector
  number (#01) and the token "D23", so it lands on the 2022 card and drags its
  price down 10x.

### The backfill — real data before a single page is scraped

`graded_sales` **already holds raw sales**. The grader sweeps search "Lorcana"
"PSA", eBay returns listings whose titles never say PSA, and those land grade-null
— which the graded rollup ignores by design, so they have been invisible since
the day they were scraped. **113 of them are real raw sales of watchlist cards**,
spanning 2023-10 to 2026-09 across 19 of the 24 cards, including the $16,406
Rapunzel. `raw_load.py --backfill-graded` recovers them.

- **⚠ `grade is null` is a HARD prerequisite, not an optimisation.** Four rows
  carry a stored grade (filled later by slab-OCR or by hand) while their titles
  say nothing about grading — gate 1 reads titles and cannot see that, so this is
  the one piece of evidence only the backfill has.
- **A backfilled row keeps its item_id and so exists in BOTH tables.** Correct:
  `graded_sales` is the scrape LEDGER, `raw_sales` is the price SOURCE. **Never
  delete from `graded_sales`** — the row is grade-null so the graded rollup
  already ignores it, and deleting it makes the next `--new-only` grader load
  re-insert it.

### Storage, rollup and the client

- **⚠ Output goes to `scripts/raw_output/`, NEVER `scripts/terapeak_output/`.**
  `terapeak_clean.load_all_dedup()` globs `terapeak_output/lorcana_*.jsonl` and
  its filename filter would not reject a raw file: `classify()` returns
  NEEDS_GRADE for any title with no grade token, so every raw sale would be
  inserted into `graded_sales` under a grader invented from the filename. Nothing
  errors; the rollup just gains a grader called TAILOR. Pinned by the test.
- **The rollup reuses `graded_sale_pkey`**, so raw and graded can never disagree
  about which bucket a printing is in. **⚠ An empty-string bucket means the card
  has ONE printing** (every Promo Set 1/3 and C2 card here); the Challenge (C1)
  cards DO split, and there the buckets are Top Prize foil vs Prize Wall non-foil
  — markets ~50x apart, so a mismatch is the most expensive bug available.
  `rawSaleMatch` in Index.html mirrors it via the existing `gradedSlotBucket`.
- **⚠ NO `pct_*` delta columns**, unlike the graded rollup. Migration 85 had to
  retrofit a window guard there because sparse data produced honest-looking
  nonsense ("+884% (1W)" off a nine-month-old reference). This is sparser still —
  19 of 24 cards have fewer than ten known sales *ever* — so every window would
  be null or misleading. Sale count and date carry the uncertainty instead.
- **⚠ `quantity_sold` matters more than it does for graded.** A slab is unique so
  Terapeak's "avg sold price" collapses to the single sale; a raw card is
  fungible, so one listing can sell several copies and the price is a per-unit
  AVERAGE with only the LAST date. Kept (it is a fair price point) but reported,
  because a multi-quantity sale of a card with a handful of copies is also a
  mis-attribution hint.
### On a raw-priced card the hierarchy INVERTS (2026-09-20, Zaven)

*"instead of normal low/market, lets use last sold/avg last 5, as the main
indicators for these raw cards, as if they were graded … lets still include the
tcgp prices too, but those are secondary."* On these cards TCGplayer's number is
the fossil and the eBay sales are the market, so the card page says so:

- **`*` after the printing label** (`.raw-star`), the site's existing
  footnote mark — the same one set-release dates use. A `.cd-raw-note` under the
  Price-changes list explains it, and is rendered only when a row carries one.
- **`Last sold · Avg N` takes `.cd-stat-px`'s own size and the accent colour;
  `TCGplayer Low · Mkt` drops to a muted line underneath.** Everywhere else the
  plain `.cd-stat-px` rule is untouched. **⚠ "Avg N", not "Avg 5"** — it is
  `last_5_count`, so a card with three sales says `Avg 3` rather than claiming
  five. The sale count and latest date sit under it because one sale of a card
  with five known copies is a data point, not a market.
- **Individual sales are DOTS on the price history**, never a line
  (`scatter: true`, handled in `LineChart` AND `drawPosterChart` so the copied
  PNG is the same document as the screen). ⚠ Joining twelve sales spread over
  three years would draw a price path that never happened; the TCGplayer series
  are genuinely daily and stay lines.
- **⚠ A raw card opens the chart on NM Market, not Low, and that is a
  correctness fix rather than a preference.** Low is a published aggregate one
  listing can move, and on exactly these thinly-listed promos it throws phantom
  spikes — Promo Set 1 #1's Low reaches **$10,000** against real sales of
  $518–$1,550, which flattens every dot onto the axis. Market is the accurate
  side (median ratio 1.000 against real sales). Applied once per card; both
  checkboxes stay live. **⚠ It is SYMMETRIC** — this modal does not remount
  between cards, so without restoring the default, one raw promo would leave Low
  switched off for every ordinary card opened afterwards.
- **⚠ The chart plots only the printings the card actually HAS**, never a
  defaulted "Normal". A Challenge card opened on its Top Prize foil has no
  non-foil side, and defaulting the missing one pulled the Prize Wall sales
  ($70–$150) onto the foil chart ($16,406) — the two markets on one axis, the
  exact conflation `graded_sale_pkey` exists to prevent.
- **⚠ The sales fetch filters `excluded=is.false`.** The table deliberately
  keeps every row it rejected, so plotting unfiltered would put a $16,406 PSA 10
  and an $8 pin on the card's chart.

- **Client plumbing**: the whole table is under a hundred rows, so the rollup and
  the individual sales are fetched **together, once per session** into module
  scope (`fetchRawSales()` → `{rollup, sales}`). A missing table 404s, is cached
  as empty Maps and asked once; the card page then renders exactly as it does
  today. **⚠ `RAW_SALE_COLOR` is a literal hex, not `var(--accent)`** — these
  series are consumed by the canvas poster, which cannot resolve a CSS variable.

### Running it — DAILY since 2026-09-26

`powershell -File scripts\graded_run.ps1 -Raw [-Deep]` — the SAME driver as the
graded scrape, because stages 1a–1c hold the stale-Chrome and captcha knowledge
and a second copy would drift. `-Deep` (first run) pulls each query to
exhaustion; after that a query is bounded by its own file's max date. It stops at
the DRY-RUN load: read the review report, then `--commit` yourself.

**⚠ Until 2026-09-26 the raw scrape had NEVER RUN.** `scripts/raw_output/` was
empty: all 78 raw sales on the site came from the one-time `--backfill-graded`
on 9/20, and nothing was keeping them current while the graded scrape ran daily
beside it. It is now **step 5 of the `graded-scrape` scheduled task** (the daily
Claude task, ~12:11 local), after the graded stages, in the same Chrome:
`graded_run.ps1 -Raw -SkipLoad`, then `raw_load.py --from-jsonl --commit-if-clean`
and `raw_load.py --backfill-graded --commit-if-clean`.

- **`--commit-if-clean` is the unattended mode, and it keeps the one judgement
  the dry-run report was for.** It writes every NEW row except a NEW price
  outlier, which is HELD (not written) and printed with its item_id for a person
  to open. Price still never DECIDES identity — a held row is a question, not a
  rejection; plain `--commit` after a look writes it. Rows already in the table
  are skipped by the insert-only upsert, so an old outlier nobody ruled on cannot
  block a day's run forever.
- The unattended run must never pass plain `--commit` or `--merge`.

### On the card page (reworked 2026-09-26, Zaven: "use the last sold/avg 5 as the main metric. have the sales graph be more like the one for graded")

- **The Price changes row** leads with a graded-style pair — LAST SOLD (with its
  date) and AVG OF LAST N (with the sale count) — as big accent numbers. TCGplayer
  Low/Mkt is one small line under it, its six-window % grid folds behind a
  "TCGplayer changes" toggle, and the `priceStanding` chip is hidden on a raw row
  (it judges TCGplayer's Market, the price nobody is paying).
- **The history section opens on "eBay sales"** (`RawSalesPanel`, beside
  `GradedSalesTab`), with "TCGplayer history" as the other half of a toggle. The
  panel is the graded tab's shape: a per-sale ScatterChart, a click-to-pin sale
  detail with the listing + photo, and a sale-rows table (Date / Listing / Qty /
  Price / Type / ↗). TCGplayer Low and Mkt are OPTIONAL overlay lines, off by
  default. A split Challenge card's printings are chips (one at a time; Ctrl/⌘
  to overlay) plus a summary table, and the Unknown bucket is never shown as
  either printing.
- **⚠ No Last Sold / Avg headline inside the panel** — the Price changes row right
  above already shows that pair, and the same two numbers twice on one screen read
  as two different prices. The panel's summary line is range + date span.
- **⚠ Headline numbers come from the ROLLUP row**, never recomputed client-side,
  so the card page cannot disagree with anything else reading `raw_sales_rollup`.
- The `raw_sales` fetch now also selects `item_id` (ScatterChart selection),
  `image_url` and `listing_type`. `ScatterChart`'s tooltip takes an optional
  `tipLabel` so a raw dot says "Raw" instead of an empty grader/grade.
- `rawView` resets to "ebay" on every card — the modal does not remount between
  cards, same reason as the Low/Market nudge above it.
