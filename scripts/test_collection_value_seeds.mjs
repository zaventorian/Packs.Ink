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
  /Promise\.all\(\[fetchCollectionPriceSeeds\(seedKeys, since\), fetchCollectionPriceHistory\(productIds, since, dates \? \{dates, market: true\} : \{market: true\}\)\]\)\s*\n\s*\.then\(\(\[seeds, hist\]\) => \[\.\.\.\(seeds \|\| \[\]\), \.\.\.hist\]\)/.test(src), true);
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

// "All" used to be 365 days, the same as 1Y (Zaven, 2026-10-06: extend it). It
// reaches back to the first price on file, sampled weekly (the full history
// daily is 3.35M rows for the largest collection), with the last two weeks daily.
console.log("\n== the All range ==");
const { localYmd, localYmdDaysAgo } = new Function(
  grab("const localYmd = (d = new Date()) =>", "const setDataPartial").replace(/const setDataPartial$/, "") +
  "\nreturn {localYmd, localYmdDaysAgo};")();
const rangeSrc = grab("const COLLECTION_RANGES = [", "const collectionRangePhrase = ");
const R = new Function("localYmd", "localYmdDaysAgo", "EARLIEST_DATA_DATE",
  rangeSrc.replace(/const collectionRangePhrase = $/, "") +
  "\nreturn {COLLECTION_RANGES, collectionRangeSince, collectionRangeDates, GRADED_SALES_EARLIEST_DATE};")(
  localYmd, localYmdDaysAgo, "2024-02-08");
check("All reaches back to the first price on file", R.collectionRangeSince("all"), "2024-02-08");
check("...and graded All to the first recorded sale", R.collectionRangeSince("all", R.GRADED_SALES_EARLIEST_DATE), "2023-06-19");
check("1Y is still 365 days", R.collectionRangeSince("1y"), localYmdDaysAgo(365));
check("a daily range fetches every day (no date list)", R.collectionRangeDates("1y", localYmdDaysAgo(365)), null);
const d = R.collectionRangeDates("all", "2024-02-08");
check("the All dates start at the range start", d[0], "2024-02-08");
check("...end today", d[d.length - 1], localYmd());
check("...ascend with no repeats", d.every((x, i) => i === 0 || x > d[i - 1]), true);
check("...are daily for the last two weeks", d.slice(-14), Array.from({length: 14}, (_, i) => localYmdDaysAgo(13 - i)));
const gap = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
check("...weekly before that", d.slice(1, -14).every((x, i, a) => i === 0 || gap(a[i - 1], x) === 7), true);
check("...about 150 dates for the whole history (a URL-sized list)", d.length > 120 && d.length < 200, true);
check("the price fetch filters on the list when given one",
  /date: \(opts && opts\.dates\) \? "in\.\(" \+ opts\.dates\.join\(","\) \+ "\)" : "gte\." \+ sinceDate/.test(src), true);
check("no range still reads a fixed 365 for All", /\{key:"all", label:"All", days:365\}/.test(src), false);

// ── The Low / NM Market switch (2026-10-24, Zaven: "show collection value as the
// market total versus the lowest listed"). One preference for the Home panel, the
// Collection tab and the Sealed / Playmats tabs. The default MUST stay byte for
// byte what every total did before it existed.
console.log("\n== value basis ==");
const compute2 = new Function("parseP",
  grab("function computeCollectionValueHistory(", "\n}") + "\nreturn computeCollectionValueHistory;")(parseP);
const mrows = [
  {tcgplayer_product_id: 7, printing: "Normal", date: "2026-10-01", low_price: 10, low_price_smoothed: null, market_price: 14},
  {tcgplayer_product_id: 7, printing: "Normal", date: "2026-10-02", low_price: 99, low_price_smoothed: 11, market_price: 15},
  {tcgplayer_product_id: 8, printing: "Normal", date: "2026-10-01", low_price: 5, low_price_smoothed: null, market_price: null},
  {tcgplayer_product_id: 8, printing: "Normal", date: "2026-10-02", low_price: 5, low_price_smoothed: null, market_price: null},
];
const mowned = new Map([["7|Normal", 2], ["8|Normal", 1]]);
const vals = (s) => s.map(p => p.value);
check("no basis is exactly the old Low rollup (smoothed Low wins)", vals(compute2(mrows, mowned)), [25, 27]);
check("basis low is identical to no basis", vals(compute2(mrows, mowned, null, null, "low")), vals(compute2(mrows, mowned)));
check("basis market values on NM Market, falling back to Low where there is none", vals(compute2(mrows, mowned, null, null, "market")), [33, 35]);

const pick = new Function(grab("const valueBasisPx = ", ";\n") + "\nreturn valueBasisPx;")();
check("low: Low first, Market only as a fallback", [pick(1, 2, "low"), pick(null, 2, "low"), pick(null, null, "low")], [1, 2, 0]);
check("market: Market first, Low only as a fallback", [pick(1, 2, "market"), pick(1, null, "market"), pick(null, null, "market")], [2, 1, 0]);
check("an unknown basis is Low (a bad stored value cannot break a total)", pick(1, 2, "garbage"), 1);

const tile = new Function(grab("const tileValuePx = ", ";\n") + "\nreturn tileValuePx;")();
check("a tile in Low mode never borrows Market (unchanged: Low or nothing)",
  [tile({"Low Price": 3, "TCGPlayer Market": 4}, "low"), tile({"TCGPlayer Market": 4}, "low")], [3, undefined]);
check("a tile in Market mode shows Market, else Low, else nothing",
  [tile({"Low Price": 3, "TCGPlayer Market": 4}, "market"), tile({"Low Price": 3}, "market"), tile({}, "market"), tile(undefined, "market")], [4, 3, undefined, undefined]);

const keyFn = new Function(grab("function collectionValueCacheKey(", "\n}") + "\nreturn collectionValueCacheKey;")();
check("the Low cache key is unchanged, so nobody's cache is invalidated", keyFn("abcdef12xyz", "h4sh", "1m"), "packsink:colvalue:v3:abcdef12:h4sh:1m");
check("a Market series can never hydrate under a Low headline (or the reverse)",
  keyFn("abcdef12xyz", "h4sh", "1m", "market") !== keyFn("abcdef12xyz", "h4sh", "1m", "low")
  && keyFn("abcdef12xyz", "h4sh", "1m", "low") === keyFn("abcdef12xyz", "h4sh", "1m"), true);

check("the Home chart always asks for market_price, so flipping the switch never refetches",
  /fetchCollectionPriceHistory\(productIds, since, dates \? \{dates, market: true\} : \{market: true\}\)/.test(src), true);
check("the sealed history asks for it too",
  /fetchCollectionPriceHistory\(pids, sinceDate, dates \? \{dates, market: true\} : \{market: true\}\)/.test(src), true);
check("the Home panel, Collection tab, Sealed and Playmats all read the ONE hook",
  (src.match(/useValueBasis\(\)/g) || []).length >= 7
  && !/packsink:sealedColl:priceMode|packsink:playmats:priceMode/.test(src.replace(/\/\/.*$/gm, "")), true);
check("the stored key is not an evictable aux prefix (a wiped preference would silently flip every total)",
  !/AUX_EVICTABLE_PREFIXES = \[[^\]]*"packsink:valueBasis/.test(src), true);
check("migration 199 hands the seeds a market_price",
  /market_price numeric\)/.test(readFileSync(new URL("../supabase/199_latest_raw_prices_before_market.sql", import.meta.url), "utf8")), true);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
