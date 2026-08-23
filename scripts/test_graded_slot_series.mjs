// test_graded_slot_series.mjs — guards the graded portfolio-chart valuation rules.
//
//     node scripts/test_graded_slot_series.mjs
//
// The regression this locks down: the chart used to key owned slabs on
// (card_id, grader, grade) only. Challenge Promo (C1) cards share ONE card_id
// across their Top Prize foil and Prize Wall non-foil printings, which are
// different markets, so a $33,493 Top-8 foil sale valued a ~$450 non-foil slab
// and put a two-day $67k spike on a $35k collection.
//
// Run this after touching gradedSlotBucket / makeGradedSlotSeries /
// computeSalesValueHistory* in Index.html. There is no client-side CI, so it is
// manual — but it reads the function text straight out of Index.html rather than
// duplicating it, so it cannot silently drift from what ships.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("not found: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("end not found for: " + startMarker);
  return src.slice(a, b);
}

const code = [
  grab("const GRADED_FOIL_PRINTINGS", "// Screener badge label"),
  grab("function makeGradedSlotSeries", "\n// Roll up individual graded sales"),
  grab("function computeSalesValueHistory(sales", "\n// Avg-of-last-5 variant"),
  grab("function makeGradedRollupValue", "\n// Fold slabs the per-sale window MISSED"),
  grab("function addUnsoldSlabsToSeries", "\n// Range start / today"),
].join("\n");

const mod = new Function(code + "\nreturn {gradedSlotBucket, makeGradedSlotSeries, gradedKnownBuckets, computeSalesValueHistory, makeGradedRollupValue, addUnsoldSlabsToSeries};")();
const { gradedSlotBucket, makeGradedSlotSeries, gradedKnownBuckets, computeSalesValueHistory, makeGradedRollupValue, addUnsoldSlabsToSeries } = mod;

let fails = 0;
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) { fails++; console.log(`  FAIL ${name}\n    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`); }
  else console.log(`  ok   ${name}`);
};

// ── bucket normalisation ──
eq("bucket Normal->Non-Foil", gradedSlotBucket("Normal"), "Non-Foil");
eq("bucket Non-Foil", gradedSlotBucket("Non-Foil"), "Non-Foil");
eq("bucket Holofoil->Foil", gradedSlotBucket("Holofoil"), "Foil");
eq("bucket Cold Foil->Foil", gradedSlotBucket("Cold Foil"), "Foil");
eq("bucket null->null (unknown stays distinct)", gradedSlotBucket(null), null);
eq("bucket Unknown->null", gradedSlotBucket("Unknown"), null);
eq("bucket variant kept exact", gradedSlotBucket("Two Swords"), "two swords");

const S = (card_id, printing, price, sold_date) =>
  ({card_id, printing, grader: "PSA", grade: "10", sale_price: price, sold_date});

// ── THE REGRESSION: Baymax C1. Non-Foil slab must not see the Top-8 foil sale ──
const baymax = [
  S("b", "Non-Foil", 450, "2026-07-11"),
  S("b", "Foil",  33493.66, "2026-07-17"),   // Top 8 Prize foil — a different card
  S("b", "Non-Foil", 480, "2026-07-17"),
  S("b", null,     5000, "2026-07-19"),      // unclassified, card has BOTH -> dropped
  S("b", "Non-Foil", 452.50, "2026-07-19"),
];
const nonFoilSlot = {card_id:"b", printing:"Normal", grader:"psa", grade:"10", qty:1};
const foilSlot    = {card_id:"b", printing:"Foil",   grader:"psa", grade:"10", qty:1};

const seriesFor = makeGradedSlotSeries(baymax);
eq("split card: non-foil slot sees only non-foil sales",
   seriesFor(nonFoilSlot).map(r => r.price), [450, 480, 452.5]);
eq("split card: foil slot sees only the foil sale",
   seriesFor(foilSlot).map(r => r.price), [33493.66]);

const hist = computeSalesValueHistory(baymax, [nonFoilSlot]);
const on17 = hist.find(p => p.date === "2026-07-17");
eq("non-foil portfolio on the spike day is the non-foil price", on17.value, 480);
eq("no date in the non-foil series exceeds $500",
   hist.every(p => p.value <= 500), true);

// ── chase-card fallback: foil-only card, slot stored 'Normal' (migration-50) ──
const ench = [
  S("e", "Foil", 900, "2026-07-01"),
  S("e", "Foil", 950, "2026-07-08"),
];
const enchSlot = {card_id:"e", printing:"Normal", grader:"psa", grade:"10", qty:1};
const enchSeries = makeGradedSlotSeries(ench)(enchSlot);
eq("foil-only card still values a 'Normal'-stamped slot (no silent $0)",
   enchSeries && enchSeries.map(r => r.price), [900, 950]);

// ── unclassified-only card: every row usable ──
const plain = [S("p", null, 40, "2026-07-01"), S("p", null, 44, "2026-07-08")];
eq("unclassified-only card is fully usable",
   makeGradedSlotSeries(plain)({card_id:"p", printing:"Normal", grader:"psa", grade:"10", qty:1})
     .map(r => r.price), [40, 44]);

// ── quantity + acquired_date still respected ──
const q = computeSalesValueHistory(
  [S("q", null, 100, "2026-07-01"), S("q", null, 100, "2026-07-08")],
  [{card_id:"q", printing:"Normal", grader:"psa", grade:"10", qty:3,
    acquired_date:"2026-07-08"}]);
eq("acquired_date gates the earlier date", q.find(p=>p.date==="2026-07-01").value, 0);
eq("qty multiplies after acquisition",  q.find(p=>p.date==="2026-07-08").value, 300);

// ── today-anchoring: every range's series ends on the same date ──
const todayYMD = new Date().toISOString().slice(0,10);
eq("series is anchored at today", hist[hist.length-1].date, todayYMD);
eq("today's value = last sale forward-filled", hist[hist.length-1].value, 452.5);

// ── range-independence: split knowledge comes from the rollup, not the window ──
// The regression: a 1M fetch that caught only the foil side of a split card
// read as "one printing", so a non-foil slab was valued at the foil price —
// and the portfolio headline changed whenever the chart range changed.
const kbRollup = [
  {card_id:"b", grader:"PSA", grade:"10", printing:"Foil",     last_sold_price: 33493.66, last_sold_date:"2026-07-17"},
  {card_id:"b", grader:"PSA", grade:"10", printing:"Non-Foil", last_sold_price: 452.50,   last_sold_date:"2026-07-19"},
];
const kb = gradedKnownBuckets(kbRollup);
const foilOnlyWindow = [S("b", "Foil", 33493.66, "2026-07-17")];
eq("foil-only window + rollup buckets: non-foil slot is NOT valued off the foil sale",
   makeGradedSlotSeries(foilOnlyWindow, kb)(nonFoilSlot), null);
eq("without rollup buckets the same window mis-values it (the pre-fix behavior)",
   makeGradedSlotSeries(foilOnlyWindow)(nonFoilSlot).map(r => r.price), [33493.66]);
eq("unclassified rollup rows add no bucket",
   gradedKnownBuckets([{card_id:"z", grader:"PSA", grade:"10", printing:""}]).size, 0);

const valueOf = makeGradedRollupValue(kbRollup);
eq("rollup prices the non-foil slab at its own printing", valueOf(nonFoilSlot), 452.5);
eq("rollup prices the foil slab at the foil sale", valueOf(foilSlot), 33493.66);

// Headline = last point of the series. Must be identical whether the fetch
// window caught one sale or every sale.
const endpoint = (sales) => {
  const s = addUnsoldSlabsToSeries(
    computeSalesValueHistory(sales, [nonFoilSlot, foilSlot], kb),
    sales, [nonFoilSlot, foilSlot], valueOf,
    ["2026-06-19", todayYMD], kb);
  return s[s.length - 1].value;
};
eq("headline (endpoint) is identical for the short and the full window",
   endpoint(foilOnlyWindow), endpoint(baymax));

// ── stray labels must not split a single-market card when kb is authoritative ──
// Sellers write "foil" on cards that are ALL foil (Enchanteds, promos). With the
// rollup loaded (printing='' → no labelled buckets), those labels are ignored;
// this exact shape valued 2x Elsa SoW Enchanted PSA 10 at $89.10 against a
// ~$3,000 market whenever the range reached the mislabelled rows.
const strayRollup = [{card_id:"m", grader:"PSA", grade:"10", printing:"", last_sold_price: 719.99, last_sold_date:"2026-08-09"}];
const strayKb = gradedKnownBuckets(strayRollup);
const straySales = [
  S("m", "Non-Foil", 44.55,  "2023-09-01"),   // ancient mislabel
  S("m", null,       700,    "2026-07-01"),
  S("m", "Foil",     405,    "2026-07-27"),   // seller wrote "foil" on an all-foil card
  S("m", null,       719.99, "2026-08-09"),
];
const straySlot = {card_id:"m", printing:"Holofoil", grader:"psa", grade:"10", qty:1};
eq("single-market card: stray labels don't split it (kb authoritative)",
   makeGradedSlotSeries(straySales, strayKb)(straySlot).map(r => r.price), [44.55, 700, 405, 719.99]);
eq("without kb the stray labels still split it (legacy window heuristic)",
   makeGradedSlotSeries(straySales)(straySlot).map(r => r.price), [405]);

// ── same-day ties resolve by scraped_at, matching the rollup's rn=1 ordering ──
const tieSales = [
  {...S("t", null, 36.04, "2026-07-11"), scraped_at: "2026-07-11T01:00:00Z"},
  {...S("t", null, 16.01, "2026-07-11"), scraped_at: "2026-07-12T09:00:00Z"},
];
const tieSlot = {card_id:"t", printing:"Normal", grader:"psa", grade:"10", qty:1};
const tieSeries = makeGradedSlotSeries(tieSales)(tieSlot);
eq("same-day tie: later-scraped sale is the last", tieSeries[tieSeries.length-1].price, 16.01);

console.log(fails ? `\n${fails} FAILURE(S)` : "\nall assertions pass");
process.exit(fails ? 1 : 0);
