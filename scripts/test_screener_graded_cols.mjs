// test_screener_graded_cols.mjs — guards two Screener changes from the
// feedback inbox (Zaven, 2026-09-28):
//
//   1. Raw mode's graded PRICE columns: "add columns for PSA 10 last sold price
//      and last 5 avg price … and for other graders/grades too … maybe a custom
//      ability w/ drop down". One pair of columns, its grader + grade picked in
//      the Columns menu.
//   2. The table scrolls with the PAGE: "I dont like how the screener is stuck
//      in a smaller box in the page … a weird sub scroll".
//
//     node scripts/test_screener_graded_cols.mjs
//
// Every way the first one breaks is silent: a foil row quietly priced at the
// non-foil's sales, a column that appears for everyone who ever customised
// their table, a link that sorts by a tier the recipient isn't looking at. So
// the pure helpers run for real (read straight out of Index.html) and the
// wiring is pinned at source.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("not found: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("end not found for: " + startMarker);
  return src.slice(a, b);
}

const code = [
  grab("const GRADED_FOIL_PRINTINGS", "// Screener badge label"),
  grab("const RAW_GRADED_COL_KEYS", "// Is this column switched on"),
  grab("function makeGradedRollupValue", "\n// Fold slabs the per-sale window MISSED"),
].join("\n");

const {
  RAW_GRADED_COL_KEYS, RAW_GRADED_TIER_DEFAULT, parseGradedTier, normGradedTier, gradedTierOptions,
  gradedCatalogBuckets, gradedSplitTiers, makeGradedPrintingLookup, buildGradedPriceIndex, rawGradedFields,
} = new Function("sbFetchAll", code + `
  return {RAW_GRADED_COL_KEYS, RAW_GRADED_TIER_DEFAULT, parseGradedTier, normGradedTier, gradedTierOptions,
    gradedCatalogBuckets, gradedSplitTiers, makeGradedPrintingLookup, buildGradedPriceIndex, rawGradedFields};`)(() => null);

let pass = 0, fail = 0;
const ok = (cond, name) => { if (cond) pass++; else { fail++; console.log("  FAIL: " + name); } };
const eq = (got, want, name) => {
  const same = JSON.stringify(got) === JSON.stringify(want);
  if (!same) console.log(`    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`);
  ok(same, name);
};
const section = (t) => console.log("\n" + t);

// ── 1. the tier ──────────────────────────────────────────────────────────────
section("1. grader + grade tier");
eq(RAW_GRADED_TIER_DEFAULT, "PSA|10", "PSA 10 is the default — 'main one is just psa 10'");
eq(parseGradedTier("PSA|10"), {grader: "PSA", grade: "10", label: "PSA 10"}, "PSA|10 parses");
eq(parseGradedTier("bgs|9.5"), {grader: "BGS", grade: "9.5", label: "BGS 9.5"}, "grader uppercased, half grade kept as text");
eq(parseGradedTier(""), {grader: "PSA", grade: "10", label: "PSA 10"}, "empty falls back to PSA 10");
eq(parseGradedTier("garbage"), {grader: "PSA", grade: "10", label: "PSA 10"}, "a malformed value falls back rather than throwing");
eq(normGradedTier("cgc|10"), "CGC|10", "a hand-typed link value is one option, not a second one");

const rollupForOpts = [];
for (let i = 0; i < 25; i++) rollupForOpts.push({card_id: "c" + i, grader: "CGC", grade: "10"});
for (let i = 0; i < 25; i++) rollupForOpts.push({card_id: "c" + i, grader: "PSA", grade: "9"});
for (let i = 0; i < 25; i++) rollupForOpts.push({card_id: "c" + i, grader: "PSA", grade: "10"});
rollupForOpts.push({card_id: "x", grader: "ACE", grade: "10"});            // one card: too thin to offer
const opts = gradedTierOptions(rollupForOpts, "PSA|10");
eq(opts.map(g => g.grader), ["PSA", "CGC"], "graders in market order, PSA first");
eq(opts[0].tiers.map(t => t.value), ["PSA|10", "PSA|9"], "grades run high to low");
ok(!opts.some(g => g.grader === "ACE"), "a tier on one card is not offered (a column of dashes)");
ok(gradedTierOptions(rollupForOpts, "ACE|10").some(g => g.tiers.some(t => t.value === "ACE|10")),
   "the CURRENT pick is always offered, however thin");
const seeded = gradedTierOptions(null, "PSA|10");
ok(seeded.length >= 4 && seeded.some(g => g.grader === "CGC"),
   "before the rollup loads the picker still offers the common tiers");

// ── 2. pricing a RAW row — THE ladder, keyed by card_id ─────────────────────
section("2. a raw row's graded price never crosses a split");
const R = (card_id, grader, grade, printing, last, avg5, n) =>
  ({card_id, grader, grade, printing, last_sold_price: last, avg_last_5: avg5, sale_count: n, last_sold_date: "2026-09-20"});
const rollup = [
  // Cinderella (C1): genuinely two markets, catalog carries both printings.
  R("cind", "PSA", "10", "Foil", 1707, 1650, 12),
  R("cind", "PSA", "10", "Non-Foil", 280, 300, 30),
  // A Whole New World (C1): one labelled Non-Foil tier + a big unclassified one.
  R("awnw", "PSA", "10", "Non-Foil", 290, 290, 1),
  R("awnw", "PSA", "10", "Unknown", 245, 250, 78),
  // Invited to the Ball: foil-only, but three PSA 9 sales mis-tagged Non-Foil.
  R("itb", "PSA", "9", "Non-Foil", 1390, 1390, 3),
  // A mainline foil_split rare: Normal and Cold Foil are different markets.
  R("rare", "PSA", "10", "Non-Foil", 40, 42, 20),
  R("rare", "PSA", "10", "Foil", 180, 175, 9),
  // An Enchanted: one market, one printing.
  R("ench", "PSA", "10", "", 2858, 2800, 1051),
  R("ench", "CGC", "10", "", 1900, 1850, 40),
  // A card the catalog sells in both finishes whose sales were never split.
  R("goof", "PSA", "10", "", 60, 55, 14),
];
const catalog = [
  {card_id: "cind", tcg_printing: "Holofoil", tcgplayer_product_id: 1},
  {card_id: "cind", tcg_printing: "Normal", tcgplayer_product_id: 1},
  {card_id: "awnw", tcg_printing: "Holofoil", tcgplayer_product_id: 2},
  {card_id: "awnw", tcg_printing: "Normal", tcgplayer_product_id: 2},
  {card_id: "itb", tcg_printing: "Holofoil", tcgplayer_product_id: 3},
  {card_id: "itb", tcg_printing: "Normal", tcgplayer_product_id: null},   // pid-less placeholder
  {card_id: "rare", tcg_printing: "Normal", tcgplayer_product_id: 4},
  {card_id: "rare", tcg_printing: "Cold Foil", tcgplayer_product_id: 5},
  {card_id: "ench", tcg_printing: "Holofoil", tcgplayer_product_id: 6},
  {card_id: "goof", tcg_printing: "Normal", tcgplayer_product_id: 7},
  {card_id: "goof", tcg_printing: "Cold Foil", tcgplayer_product_id: 8},
];
// Exactly what the Screener's rawGradedHit memo does.
const buckets = gradedCatalogBuckets(catalog);
const hitFor = makeGradedPrintingLookup(
  buildGradedPriceIndex(rollup, null, r => r.card_id), gradedSplitTiers(rollup, buckets));
const px = (cardId, printing, tier = "PSA|10") => {
  const t = parseGradedTier(tier);
  return rawGradedFields(hitFor(cardId, cardId, t.grader.toLowerCase(), t.grade, printing), buckets.get(cardId));
};

eq(px("cind", "Holofoil").last, 1707, "C1 Top Prize row reads the FOIL tier");
eq(px("cind", "Normal").last, 280, "C1 Prize Wall row reads the NON-FOIL tier — not $1,707");
eq(px("cind", "Normal").note, null, "a printing's own tier carries no blend note");
eq(px("awnw", "Normal").last, 290, "AWNW non-foil reads its own $290 tier");
eq(px("awnw", "Holofoil").last, 245, "AWNW foil is NOT priced at the non-foil's $290 (the 2026-09-20 report)");
ok(!!px("awnw", "Holofoil").note, "…and the unclassified tier it falls back to is LABELLED a blend");
eq(px("itb", "Holofoil", "PSA|9").last, 1390, "a foil-only C1 card still prices off its only (mislabelled) sales");
eq(px("rare", "Normal").avg5, 42, "mainline Normal row reads the Non-Foil tier");
eq(px("rare", "Cold Foil").avg5, 175, "mainline Cold Foil row reads the Foil tier");
eq(px("rare", "Normal", "CGC|10"), null, "no sale at the chosen tier → null (the cell reads —)");
eq(px("ench", "Holofoil").last, 2858, "a single-market chase card prices");
eq(px("ench", "Holofoil", "cgc|10").last, 1900, "the tier's grader is case-insensitive");
eq(px("ench", "Holofoil").note, null, "a one-printing card is its own market — no note");
ok(!!px("goof", "Cold Foil").note && px("goof", "Cold Foil").last === 60,
   "a two-finish card whose sales were never split still prices, marked as both finishes blended");
eq(px("ench", "Holofoil").n, 1051, "the sale count rides along for the tooltip");
eq(px("nope", "Normal"), null, "a card with no graded sales at all → null");

// ── 3. the shared index is the Collection's old priceByKey, unchanged ────────
section("3. buildGradedPriceIndex keeps the Collection's shape");
const cardById = new Map(catalog.filter(c => c.tcgplayer_product_id).map(c => [c.card_id, c]));
const byPid = buildGradedPriceIndex(rollup, cardById, (r, meta) => meta && meta.tcgplayer_product_id ? meta.tcgplayer_product_id : null);
ok(byPid.has("1|Holofoil|psa|10") && byPid.get("1|Holofoil|psa|10").last_sold_price === 1707,
   "a labelled Foil row is written under Holofoil");
ok(byPid.get("1|Normal|psa|10").last_sold_price === 280, "a labelled Non-Foil row is written under Normal");
ok(byPid.get("2|Cold Foil|psa|10").rollup_printing === "Unknown",
   "an Unknown row is written under every printing, and carries its provenance");
ok(byPid.get("2|Normal|psa|10").last_sold_price === 290, "pass 2 lets the labelled row override pass 1");
ok(byPid.get("6|Normal|psa|10").ebay_avg_1d === 2800, "ebay_avg_1d is the avg-of-5 (gradedRowValue reads it)");
ok(byPid.get("6|Normal|psa|10").grader === "psa", "grader lowercased to match graded_collection_items");
ok(!Array.from(byPid.keys()).some(k => k.startsWith("undefined|") || k.startsWith("null|")),
   "a rollup row with no pid is skipped, never keyed as 'null'");
const collectionSrc = grab("const priceByKey = useMemo(", "const gradedHit = useMemo(");
ok(collectionSrc.includes("buildGradedPriceIndex(rollup, cardById,"),
   "the Graded collection builds its index through the same helper (one ladder, one index)");

// ── 4. the Screener wiring ────────────────────────────────────────────────────
section("4. Screener wiring");
eq(RAW_GRADED_COL_KEYS, ["gr_last", "gr_avg5"], "two columns — not one per grade");
ok(src.includes("colDefs.map(c=>c.key).filter(k=>!RAW_POP_COL_KEYS.includes(k) && !RAW_GRADED_COL_KEYS.includes(k))"),
   "legacy Raw prefs reconstruct `known` WITHOUT the graded columns, so they don't appear for everyone");
const prefsAt = src.indexOf("const [colPrefs, setColPrefs] = useState(");
const wantAt = src.indexOf("const rawGradedWanted = ");
ok(prefsAt > 0 && wantAt > prefsAt, "rawGradedWanted sits BELOW colPrefs (its deps read it; above is a TDZ crash)");
ok(/if\(!gradedPremium\)\{ signalGradedSurface\(\); return; \}/.test(src),
   "asking for a graded column without the graded-data terms raises the terms prompt, not a fetch");
const hitAt = src.indexOf("const rawGradedHit = useMemo(");
const filteredAt = src.indexOf("const filtered = useMemo(", src.indexOf("const catalogByCardId = useMemo("));
ok(hitAt > 0 && hitAt < filteredAt, "the price lookup is declared ABOVE the filter memo that reads it");
ok(src.includes("o.gr_last = g ? g.last : null;") && src.includes("const o = {...r};"),
   "graded fields land on COPIES of the rows, not on the shared price_movers objects");
ok(src.includes("rawGradedHit, rawGradedTier, watchOnly"), "the filter memo re-runs when the tier or the lookup changes");
ok(src.includes('["gradedTier","gt","nstr",null]'), "?v= links can carry the tier");
ok(src.includes("gradedTier: [sortKey, sortKey2].some(k => RAW_GRADED_COL_KEYS.includes(k)) ? rawGradedTier : null"),
   "a view carries the tier ONLY when it sorts by a graded column");
ok(src.includes("if(v.gradedTier) setRawGradedTier(normGradedTier(v.gradedTier));"),
   "applying a view without a tier leaves the viewer's own pick alone");
ok(src.includes("const rawGradedCols = (showGraded || showSealed) ? [] : ["),
   "the graded price columns are Raw-only — never on the Sealed table");
ok((src.match(/fetchScreenerGradedRollup\(\)/g) || []).length >= 2,
   "Graded mode and the Raw columns share ONE rollup read");

// ── 5. the table scrolls with the page ───────────────────────────────────────
section("5. page scroll, pinned header");
const ruleOf = (sel) => {
  const i = css.indexOf("\n" + sel + "{");
  if (i < 0) return null;
  return css.slice(i + 1, css.indexOf("}", i) + 1);
};
const wrapRule = ruleOf(".price-db-tablewrap");
ok(!!wrapRule && !/max-height/.test(wrapRule), "the table body has no max-height — no box within the page");
ok(!/\.price-db-tablewrap\{[^}]*max-height/.test(css), "…and no other rule gives it one back");
const boxRule = ruleOf(".price-db-tablebox") || "";
ok(/overflow:clip/.test(boxRule) && !/overflow:hidden/.test(boxRule),
   "the box clips with `clip`, never `hidden` (hidden is a scroll container; the header would pin to it)");
const headRule = ruleOf(".price-db-stickyhead") || "";
ok(/position:sticky/.test(headRule) && /top:var\(--pdb-top/.test(headRule),
   "the header strip is CSS-sticky under the measured nav, so it never lags a frame behind the page");
ok(/position:sticky/.test(ruleOf(".price-db-hscroll") || "") && /bottom:0/.test(ruleOf(".price-db-hscroll") || ""),
   "a scrollbar pinned to the bottom of the window — the body's own is a page away");
const render = grab('<div class="price-db-tablebox" ref=${setTableBoxEl}>', '<div class="price-db-hscroll"');
const headAt = render.indexOf('<div class="price-db-stickyhead">');
const wrapAt = render.indexOf('<div class="price-db-tablewrap">');
ok(headAt >= 0 && wrapAt > headAt, "the pinned header sits OUTSIDE (above) the sideways scroller");
ok(render.includes('<thead ref=${sizeHeadRef} class="price-db-sizehead" aria-hidden="true">${headRow()}</thead>'),
   "the body table keeps an invisible sizer header, so its columns still size to their header text");
ok(render.includes('<thead ref=${theadRef} onKeyDown=${onTheadKey}>${headRow()}</thead>'),
   "the visible, clickable header is the pinned one (keyboard sort included)");
ok(/\.price-db-sizehead th\{[^}]*visibility:hidden[^}]*height:0/.test(css),
   "the sizer is invisible and zero-height, so rows sit straight under the pinned strip");
ok(!/\.price-db-table thead\{[^}]*position:sticky/.test(css),
   "no thead is sticky any more — inside the sideways scroller it could only pin to that");
ok(src.includes('{sel:".price-db-tablebox", title:"Sort like a terminal"'),
   "the Screener tour spotlights the whole table, header included");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
