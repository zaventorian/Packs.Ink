// test_stale_low.mjs — a fossil Low never reaches a tile, a sort or a total.
//
//     node scripts/test_stale_low.mjs
//
// Found in the 2026-11-01 audit: Mickey - Brave Little Tailor's foil topped Price
// high->low at a stale $200,000, Cruella De Vil D23 read $0.25 beside $944 of eBay
// sales, and a $1.00 Hyperia City box Low made its EV +10867%. Extracts the real
// helpers out of Index.html (house pattern) and replays those rows.
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const mod = await import("data:text/javascript," + encodeURIComponent([
  "const GRADED_FOIL_PRINTINGS = new Set(['foil','holofoil','cold foil']);",
  "const GRADED_NONFOIL_PRINTINGS = new Set(['normal','non-foil']);",
  grab("const gradedSlotBucket = (p) => {", NL + "};"),
  grab("const parseP = s =>", NL),
  grab("const staleLowPx = (rollupRows, printing, market) => {", NL + "};"),
  grab("const SEALED_LOW_MIN_RATIO =", NL),
  grab("const fixSealedLows = (rows) => rows.map(r => {", NL + "});"),
  "export { staleLowPx, fixSealedLows };",
].join(NL)));
const { staleLowPx, fixSealedLows } = mod;

// One-printing card: the empty bucket prices it. Cruella, not $0.25.
assert.equal(staleLowPx([{ printing: "", avg_last_5: "944.398" }], "Holofoil", null), 944.398);
// Split card: the foil read the foil's sales, never the Prize Wall's.
const rapunzel = [
  { printing: "Foil", avg_last_5: "6561.25" },
  { printing: "Unknown", avg_last_5: "132.60" },
  { printing: "Non-Foil", avg_last_5: "113.73" },
];
assert.equal(staleLowPx(rapunzel, "Holofoil", null), 6561.25);
// 'Unknown' never prices a printing, so Mickey's $200,000 becomes no price at all.
assert.equal(staleLowPx([{ printing: "Unknown", avg_last_5: "9800" }], "Holofoil", null), null);
// No eBay row: the last NM Market. Neither: nothing.
assert.equal(staleLowPx(undefined, "Holofoil", 3500), 3500);
assert.equal(staleLowPx(undefined, "Cold Foil", null), null);

const row = (low_price, market_price) => ({ low_price, market_price });
assert.equal(fixSealedLows([row("1.00", "136.46")])[0].low_price, "136.46"); // Hyperia box
assert.equal(fixSealedLows([row("4.69", "10.22")])[0].low_price, "4.69");    // ordinary cheap Low
assert.equal(fixSealedLows([row("499.67", "205.61")])[0].low_price, "499.67");// high Low is untouched
assert.equal(fixSealedLows([row("9.99", null)])[0].low_price, "9.99");       // no Market to compare
assert.equal(fixSealedLows([row(null, "20")])[0].low_price, null);           // no Low stays no Low

// Every path the rows take into the catalog.
assert.ok(src.includes("price_date,is_stale\""), "PRICE_COLS must fetch is_stale");
assert.ok(src.includes("{rows: fixSealedLows(rows), stale}"), "the sealed cache read must fix Lows");
assert.ok(src.includes("const sealedRows = fixSealedLows(sealedRowsRaw);"), "the catalog sealed fetch must fix Lows");
assert.ok(src.includes("const fixed = fixSealedLows(rows);"), "the independent sealed fetch must fix Lows");
console.log("test_stale_low: ok");
