// test_collection_value_seeds.mjs — the home Collection chart and its range pill.
//
//     node scripts/test_collection_value_seeds.mjs
//
// Runs the real computeCollectionValueHistory out of Index.html. Found
// 2026-10-06: the chart fetched prices from the range start only, so an item
// with no price row inside the range (expensive promos are priced rarely) was
// missing from the chart, while the headline counted it at today's price — and
// the pill was "headline minus the chart's first point". Owning a $5,999.99
// Elsa last priced in June plus four $1 commons read "+$5,999.99 (+150,000%)
// past 1M". Two fixes, both pinned here: each owned item is SEEDED with its
// newest price from before the range (migration 186, fetchCollectionPriceSeeds),
// and the pill is the chart's own last point minus its first.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};
const grab = (start, end) => {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing " + start);
  return src.slice(a, src.indexOf(end, a) + end.length);
};

const parseP = new Function(grab("const parseP = ", "\n") + "\nreturn parseP;")();
const compute = new Function("parseP",
  grab("function computeCollectionValueHistory(", "\n}") + "\nreturn computeCollectionValueHistory;")(parseP);

const since = "2026-09-06";
const days = ["2026-09-06", "2026-09-20", "2026-10-05"];
const commons = [1, 2, 3, 4].flatMap(pid => days.map(date => ({tcgplayer_product_id: pid, printing: "Normal", date, low_price: 1})));
const owned = new Map([["454230|Holofoil", 1], ["1|Normal", 1], ["2|Normal", 1], ["3|Normal", 1], ["4|Normal", 1]]);
const elsaSeed = {tcgplayer_product_id: 454230, printing: "Holofoil", date: since, low_price: 5999.99, low_price_smoothed: null};
const ends = (s) => [s[0].value, s[s.length - 1].value];

console.log("== an item not priced inside the range ==");
check("unseeded (the bug): the $6k Elsa is missing from the whole chart", ends(compute(commons, owned)), [4, 4]);
check("seeded: it is in the chart from the first day", ends(compute([elsaSeed, ...commons], owned)), [6003.99, 6003.99]);

console.log("\n== an item priced sparsely joins on its first row, not the range start ==");
const sparse = [{tcgplayer_product_id: 454230, printing: "Holofoil", date: "2026-09-20", low_price: 5999.99}];
check("unseeded: it arrives part-way, so the chart 'gains' $6k", ends(compute([...commons, ...sparse], owned)), [4, 6003.99]);
check("seeded: flat across the range", ends(compute([elsaSeed, ...commons, ...sparse], owned)), [6003.99, 6003.99]);
const moved = [{...sparse[0], low_price: 6500}];
check("seeded: a real move inside the range still shows", ends(compute([elsaSeed, ...commons, ...moved], owned)), [6003.99, 6504]);

console.log("\n== the pre-release guard still wins over a seed ==");
const pre = {tcgplayer_product_id: 99, printing: "Normal", date: since, low_price: 450};
const owned2 = new Map([...owned, ["99|Normal", 1]]);
check("a seed dated before the set's release + 1 day is dropped",
  ends(compute([elsaSeed, pre, ...commons], owned2, {99: "2026-10-17"})), [6003.99, 6003.99]);

console.log("\n== wiring ==");
check("the home cards chart fetches seeds with the history and puts them FIRST",
  /Promise\.all\(\[fetchCollectionPriceSeeds\(seedKeys, since\), fetchCollectionPriceHistory\(productIds, since\)\]\)\s*\n\s*\.then\(\(\[seeds, hist\]\) => \[\.\.\.\(seeds \|\| \[\]\), \.\.\.hist\]\)/.test(src), true);
const sealed = grab("async function fetchSealedValueHistory(", "\n}");
check("both sealed charts seed every sealed item (fetchSealedValueHistory)",
  /fetchCollectionPriceSeeds\(\[\.\.\.new Set\(pids\.map\(Number\)\)\]\.map\(pid => \(\{pid, printing: "Normal"\}\)\), sinceDate\)/.test(sealed)
  && /if\(seeds\) return \[\.\.\.seeds, \.\.\.rows\];/.test(sealed), true);
const seedsFn = grab("async function fetchCollectionPriceSeeds(", "\n}");
check("seeds ask in batches small enough for the anon statement timeout", /const PRICE_SEED_BATCH = 250;/.test(src), true);
check("seeds are re-dated to the range start", /date: sinceDate/.test(seedsFn), true);
check("a failure to ask is null, not an empty answer", /if\(failed\) return null;/.test(seedsFn), true);
const panel = grab("const CollectionPanel = ", "const deltaColor =");
check("the pill is the chart's own change (last point minus first)",
  /const rangeDelta = \(combinedStartValue != null && combinedStartValue > 0\) \? \(combinedEndValue - combinedStartValue\)/.test(panel), true);
check("...never the headline minus the chart", /combinedCurrentValue - combinedStartValue/.test(panel), false);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
