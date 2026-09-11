// test_sealed_movers.mjs — guards the home page's Sealed Movers banner and the
// sealed Δ% maths every sealed surface shares.
//
//     node scripts/test_sealed_movers.mjs
//
// Extracts the real code out of Index.html, house pattern, so it can't drift
// from what ships. Two of these failures are silent on the site:
//
//   * computeSealedDeltas measured its windows back from the WALL CLOCK. A
//     snapshot is dated 00:00Z, so for the ~20 hours a day between midnight UTC
//     and the ETL, the newest row was itself "at least a day old" and 1D
//     compared the latest price with itself — every sealed product read 0%, on
//     the Screener's Sealed mode, the collection tiles and this banner alike.
//   * A chip that maps to a display type the Screener doesn't have makes the
//     banner's title jump land on an empty table.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(NL).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const cleanSealedName = "),
  grab("const SEALED_DISPLAY_TYPE_ORDER = [", NL + "];"),
  grab("const SEALED_DISPLAY_TYPE_FOR = {", NL + "};"),
  grab("function isHiddenSealedListing(item){", NL + "}"),
  grab("function deriveSealedDisplayType(item){", NL + "}"),
  grab("function computeSealedDeltas(history){", NL + "}"),
  grab("const MOVER_WINDOWS = [", NL + "];"),
  grabLine("const SEALED_MOVER_KIND_ORDER = "),
  grab("const SEALED_MOVER_KIND_OF_TYPE = {", NL + "};"),
  grab("const SEALED_MOVER_TYPE_SINGULAR = {", NL + "};"),
  grabLine("const SEALED_MOVER_WINDOW_DAYS = "),
  grab("const sealedMoverScreenerTypes = (kinds) =>", "SEALED_MOVER_KIND_OF_TYPE[t]));"),
  grab("function sealedMoverCandidates(sealedPrices){", NL + "}"),
  grab("function sealedMoverRows({", NL + "}"),
  "export {computeSealedDeltas, deriveSealedDisplayType, SEALED_DISPLAY_TYPE_ORDER, MOVER_WINDOWS,",
  "  SEALED_MOVER_KIND_ORDER, SEALED_MOVER_KIND_OF_TYPE, SEALED_MOVER_TYPE_SINGULAR, SEALED_MOVER_WINDOW_DAYS,",
  "  sealedMoverScreenerTypes, sealedMoverCandidates, sealedMoverRows};",
].join(NL)));

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  " + (detail ?? "")));
};
const near = (a, b) => a != null && b != null && Math.abs(a - b) < 1e-9;

// Daily rows for one pid ending on `end`, priced low=fnLow(i), market=fnMkt(i).
const DAY = 86400000;
const series = (pid, end, days, fnLow, fnMkt) => Array.from({length: days}, (_, i) => ({
  tcgplayer_product_id: pid,
  printing: "Normal",
  date: new Date(Date.parse(end + "T00:00:00Z") - (days - 1 - i) * DAY).toISOString().slice(0, 10),
  low_price: fnLow(i),
  market_price: fnMkt ? fnMkt(i) : undefined,
}));

// ── computeSealedDeltas: windows are anchored on the product's own snapshot ──
// The series ends WEEKS ago on purpose: under the old wall-clock rule a 1D
// window found nothing inside it at all. Anchored on the data, it is exact.
{
  const rows = series(7, "2026-08-01", 40, (i) => 100 + i, (i) => 200 + 2 * i);
  const [d] = mod.computeSealedDeltas(rows);
  ok("1D compares the latest snapshot with the one before it", near(d.pct_1d, (139 - 138) / 138 * 100), d.pct_1d);
  ok("1W reaches back exactly seven snapshots", near(d.pct_7d, (139 - 132) / 132 * 100), d.pct_7d);
  ok("1M reaches back thirty", near(d.pct_30d, (139 - 109) / 109 * 100), d.pct_30d);
  ok("a window longer than the history is null, not zero", d.pct_90d === null, d.pct_90d);
  ok("market windows come from market_price", near(d.mkt_pct_1d, (278 - 276) / 276 * 100), d.mkt_pct_1d);
  ok("the row carries its snapshot date", d.price_date === "2026-08-01", d.price_date);
}
{
  // The exact failure: a snapshot dated today at 00:00Z. Whatever the time of
  // day, 1D must compare today's price with yesterday's — not today's with itself.
  const rows = [
    {tcgplayer_product_id: 1, printing: "Normal", date: "2026-09-10", low_price: 100},
    {tcgplayer_product_id: 1, printing: "Normal", date: "2026-09-11", low_price: 110},
  ];
  const [d] = mod.computeSealedDeltas(rows);
  ok("today's snapshot is never its own baseline", near(d.pct_1d, 10), d.pct_1d);
}
{
  // A gap: no snapshot exactly seven days back. The one before the cut stands in.
  const rows = [
    {tcgplayer_product_id: 2, printing: "Normal", date: "2026-09-01", low_price: 50},
    {tcgplayer_product_id: 2, printing: "Normal", date: "2026-09-10", low_price: 60},
  ];
  const [d] = mod.computeSealedDeltas(rows);
  ok("a missing day falls back to the latest snapshot before the cut", near(d.pct_7d, 20), d.pct_7d);
  ok("…and 1D uses it too when nothing sits between", near(d.pct_1d, 20), d.pct_1d);
}
{
  // Without market_price in the history (the collection rollup's default select),
  // the market side is null — never a fake 0 against a missing value.
  const [d] = mod.computeSealedDeltas(series(3, "2026-09-10", 5, (i) => 10 + i));
  ok("no market_price column → market deltas are null", d.mkt_pct_1d === null && d.market_today === null,
    JSON.stringify({m: d.mkt_pct_1d, t: d.market_today}));
  // A sold-out snapshot (null low) must not read as a -100% crash.
  const soldOut = series(4, "2026-09-10", 5, (i) => (i === 4 ? null : 20), (i) => 25);
  const [s] = mod.computeSealedDeltas(soldOut);
  ok("a null low today yields no low delta, not -100%", s.pct_1d === null, s.pct_1d);
}

// ── Which products the banner may ever show ─────────────────────────────────
const P = (pid, name, product_type, extra) => ({
  tcgplayer_product_id: pid, name, product_type, printing: "Normal", set_id: "s1",
  image_url: "https://img/" + pid, low_price: 100, market_price: 110, ...extra,
});
const catalog = [
  P(1,  "Disney Lorcana: Fabled - Booster Box", "Booster Box"),
  P(2,  "Disney Lorcana: Fabled - Illumineer's Trove", "Trove"),
  P(3,  "Disney Lorcana: Stitch Collector's Gift Set", "Gift Set"),
  P(4,  "Disney Lorcana: D23 Collection", "Sealed"),
  P(5,  "Disney Lorcana: Gateway", "Sealed"),
  P(6,  "Disney Lorcana: Fabled Collection Starter Set", "Starter Deck"),
  P(7,  "Disney Lorcana: Fabled - Booster Pack", "Booster Pack"),
  P(8,  "Disney Lorcana: Fabled - Starter Deck", "Starter Deck"),
  P(9,  "Disney Lorcana: Fabled - Prerelease Pack", "Prerelease Pack"),
  P(10, "Disney Lorcana: Fabled - Booster Box Case", "Booster Box"),
  P(11, "Disney Lorcana: Starter Deck [Set of 2]", "Starter Deck"),
  P(12, "Disney Lorcana: Mickey Promo", "Promo Single"),
  P(13, "Disney Lorcana: Azurite Sea - Booster Box", "Booster Box", {is_stale: true}),
  P(14, "Disney Lorcana: Fabled - Booster Box", "Booster Box", {printing: "Foil"}),
  P(15, "Disney Lorcana: The Great Illumineer's Quest", "Quest"),
  P(16, "Pin", "Pin", {is_collectible: true}),
];
const cands = mod.sealedMoverCandidates(catalog);
const kindOf = Object.fromEntries(cands.map((c) => [c.product.tcgplayer_product_id, c.kind]));
ok("booster boxes are Boxes", kindOf[1] === "boxes", kindOf[1]);
ok("troves are Troves", kindOf[2] === "troves", kindOf[2]);
ok("gift sets are Specials", kindOf[3] === "specials", kindOf[3]);
ok("a D23 collection (product_type Sealed) is a Special", kindOf[4] === "specials", kindOf[4]);
ok("the Gateway box (product_type Sealed) is a Special", kindOf[5] === "specials", kindOf[5]);
ok("a Collection Starter Set is a Special (a bundle, not a deck)", kindOf[6] === "specials", kindOf[6]);
ok("quests are Specials", kindOf[15] === "specials", kindOf[15]);
for (const [pid, why] of [[7, "packs"], [8, "starter decks"], [9, "prerelease packs"], [10, "cases"],
  [11, "[Set of N] bundles"], [12, "promo singles"], [13, "stale rows"], [14, "a non-Normal printing"],
  [16, "collectibles"]]) {
  ok(why + " never reach the banner", !(pid in kindOf), kindOf[pid]);
}

// ── The rows: floor, direction, sort, chips, cap ────────────────────────────
const hist = [];
const move = {1: 0.10, 2: -0.30, 3: 0.05, 4: 0.50, 5: 0.02, 6: -0.08, 15: 0};
for (const [pid, m] of Object.entries(move)) {
  hist.push({tcgplayer_product_id: +pid, printing: "Normal", date: "2026-09-09", low_price: 100, market_price: 120});
  hist.push({tcgplayer_product_id: +pid, printing: "Normal", date: "2026-09-10", low_price: 100 * (1 + m), market_price: 120});
}
const rows = (o) => mod.sealedMoverRows({candidates: cands, history: hist, kinds: mod.SEALED_MOVER_KIND_ORDER,
  pctKey: "pct_1d", showUp: true, showDown: true, setNameById: {s1: "Fabled"}, ...o});
const both = rows();
ok("both directions sort by magnitude", both.map((r) => r.tcgplayer_product_id).join(",") === "4,2,1,6,3,5",
  both.map((r) => r.tcgplayer_product_id).join(","));
ok("a 0% product is not a mover", !both.some((r) => r.tcgplayer_product_id === 15));
ok("gainers only, biggest first", rows({showDown: false}).map((r) => r.tcgplayer_product_id).join(",") === "4,1,3,5",
  rows({showDown: false}).map((r) => r.tcgplayer_product_id).join(","));
ok("droppers only, biggest drop first", rows({showUp: false}).map((r) => r.tcgplayer_product_id).join(",") === "2,6",
  rows({showUp: false}).map((r) => r.tcgplayer_product_id).join(","));
ok("the chips narrow the pool", rows({kinds: ["troves"]}).map((r) => r.tcgplayer_product_id).join(",") === "2",
  rows({kinds: ["troves"]}).map((r) => r.tcgplayer_product_id).join(","));
ok("the cap is taken AFTER the chips narrow", rows({kinds: ["specials"], limit: 2}).map((r) => r.tcgplayer_product_id).join(",") === "4,6",
  rows({kinds: ["specials"], limit: 2}).map((r) => r.tcgplayer_product_id).join(","));
const r4 = both.find((r) => r.tcgplayer_product_id === 4);
ok("a row names its type and set", r4.type_label === "Collector's Edition" && r4.set_name === "Fabled",
  JSON.stringify({t: r4.type_label, s: r4.set_name}));
ok("the Disney Lorcana prefix is stripped", r4.name === "D23 Collection", r4.name);
ok("a row keeps the product for the detail modal", r4._sealedProduct && r4._sealedProduct.tcgplayer_product_id === 4);
ok("row keys are unique and prefixed", new Set(both.map((r) => r.key)).size === both.length && r4.key === "sealed:4", r4.key);
ok("a Map works for set names too", rows({setNameById: new Map([["s1", "Fabled"]])})[0].set_name === "Fabled");

// The $5 floor is on the PRIOR low for the window, same as the card banners.
const cheap = [
  {tcgplayer_product_id: 1, printing: "Normal", date: "2026-09-09", low_price: 4, market_price: 5},
  {tcgplayer_product_id: 1, printing: "Normal", date: "2026-09-10", low_price: 9, market_price: 10},
  {tcgplayer_product_id: 2, printing: "Normal", date: "2026-09-09", low_price: 6, market_price: 7},
  {tcgplayer_product_id: 2, printing: "Normal", date: "2026-09-10", low_price: 3, market_price: 4},
];
const floored = mod.sealedMoverRows({candidates: cands, history: cheap, kinds: mod.SEALED_MOVER_KIND_ORDER,
  pctKey: "pct_1d", showUp: true, showDown: true});
ok("a product that started under $5 is not a mover, however far it jumped",
  !floored.some((r) => r.tcgplayer_product_id === 1), floored.map((r) => r.tcgplayer_product_id).join(","));
ok("a product that started over $5 is, even if it fell below",
  floored.some((r) => r.tcgplayer_product_id === 2));
ok("no history → no rows, no throw",
  mod.sealedMoverRows({candidates: cands, history: null, kinds: ["boxes"], pctKey: "pct_1d", showUp: true, showDown: true}).length === 0);

// ── Contracts with the rest of the app ─────────────────────────────────────
for (const t of Object.keys(mod.SEALED_MOVER_KIND_OF_TYPE)) {
  ok('"' + t + '" is a display type the Screener can filter on', mod.SEALED_DISPLAY_TYPE_ORDER.includes(t));
  ok('"' + t + '" has a singular label', !!mod.SEALED_MOVER_TYPE_SINGULAR[t]);
}
for (const k of mod.SEALED_MOVER_KIND_ORDER) {
  ok('chip "' + k + '" stands for at least one type', mod.sealedMoverScreenerTypes([k]).length > 0);
}
ok("the Boxes jump lands on Booster Boxes only",
  JSON.stringify(mod.sealedMoverScreenerTypes(["boxes"])) === JSON.stringify(["Booster Boxes"]));
for (const w of mod.MOVER_WINDOWS) {
  ok("window " + w.label + " has a history horizon", Number.isFinite(mod.SEALED_MOVER_WINDOW_DAYS[w.pctLow]),
    w.pctLow);
}

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
