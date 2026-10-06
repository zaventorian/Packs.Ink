// test_starter_deck_foils.mjs — the Starter Deck Foil tiles carry the Holofoil printing.
//
//     node scripts/test_starter_deck_foils.mjs
//
// A Starter Deck Foil's TCGplayer product carries THREE printings: Normal and
// the ordinary in-pack Cold Foil (the base card's tile) plus Holofoil, the
// starter-deck foil itself. The Extras tile took the first foil it found, Cold
// Foil, so it showed the in-pack foil's price (Jessie $3.02 against $7.89) and
// every collection entry on it was saved as Cold Foil (review, 2026-10-06;
// migration 187 moves those). Runs the real EXTRAS_MAP and the real emission
// loop out of Index.html with stubbed inputs.
import { readFileSync } from "node:fs";

const src = readFileSync(process.env.INDEX_HTML || new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
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

const mapSrc = grab("const STARTER_DECK_FOIL = ", "\n};");
const { STARTER_DECK_FOIL, EXTRAS_MAP } = new Function(mapSrc + "\nreturn {STARTER_DECK_FOIL, EXTRAS_MAP};")();
const loopSrc = grab("  for(const [pidStr, info] of Object.entries(EXTRAS_MAP)){", "\n    rows.push(row);\n  }");

const run = (cardsRows, pricesByProduct) => {
  const rows = [];
  const buildRow = (c, setName, rar, name, printing, priceRow) =>
    ({card_id: c.id, Set: setName, Rarity: rar, "Product Name": name, tcg_printing: printing,
      low: priceRow ? priceRow.low_price : null});
  new Function("EXTRAS_MAP", "cardsRows", "pricesByProduct", "buildRow", "EXTRAS_SET_NAME", "rows", loopSrc)
    (EXTRAS_MAP, cardsRows, pricesByProduct, buildRow, "Extras & Oddities", rows);
  return rows;
};

const SDF_PIDS = [678236, 678237, 678238, 690204, 647652, 647681, 649224, 650077, 653916, 657892, 657893, 657894];

console.log("== the map ==");
check("the label is Starter Deck Foil", STARTER_DECK_FOIL, {variantLabel: "Starter Deck Foil", printing: "Holofoil"});
check("all 12 Starter Deck Foils use it",
  SDF_PIDS.every(p => EXTRAS_MAP[p] && EXTRAS_MAP[p].variantLabel === "Starter Deck Foil" && EXTRAS_MAP[p].printing === "Holofoil"), true);
check("no entry still says Starter Deck Exclusive Foil", /Starter Deck Exclusive/.test(src), false);
check("nothing else is a Starter Deck Foil",
  Object.keys(EXTRAS_MAP).filter(p => EXTRAS_MAP[p].variantLabel === "Starter Deck Foil").map(Number).sort(), [...SDF_PIDS].sort());

console.log("\n== the emitted tile ==");
const jessie = [{id: "crd_jessie", name: "Jessie", version: "Lively Cowgirl", tcgplayer_product_id: 690204}];
const three = {690204: [
  {printing: "Normal", low_price: 0.01}, {printing: "Cold Foil", low_price: 1.99}, {printing: "Holofoil", low_price: 5.54}]};
const pick = (rows, pid) => rows.find(r => r.card_id === "extras:" + pid) || {};
const row = pick(run(jessie, three), 690204);
check("the tile is the Holofoil printing", row.tcg_printing, "Holofoil");
check("...at the Holofoil price, not the in-pack Cold Foil's", row.low, 5.54);
check("...labelled Starter Deck Foil", row.Rarity, "Starter Deck Foil");
check("...under the synthetic extras id the collection keys on", row.card_id, "extras:690204");
const unpriced = pick(run(jessie, {}), 690204);
check("unpriced, it still names the Holofoil printing (so the collection key holds)", unpriced.tcg_printing, "Holofoil");

console.log("\n== the other buckets are untouched ==");
const dt = [{id: "crd_hex", name: "Half Hexwell Crown", tcgplayer_product_id: 557538}];
check("a Holofoil-only Extras product still takes its Holofoil",
  run(dt, {557538: [{printing: "Holofoil", low_price: 9}]}).find(r => r["Product Name"] === "Half Hexwell Crown").tcg_printing, "Holofoil");
const mickey = [{id: "crd_mk", name: "Mickey Mouse", version: "Playful Sorcerer", tcgplayer_product_id: 544485}];
check("a Cold Foil Extras product still takes its Cold Foil",
  run(mickey, {544485: [{printing: "Cold Foil", low_price: 4}, {printing: "Holofoil", low_price: 9}]}).find(r => r["Product Name"] === "Mickey Mouse - Playful Sorcerer").tcg_printing, "Cold Foil");

console.log("\n== the stored entries move with it ==");
const mig = readFileSync(new URL("../supabase/187_starter_deck_foil_rekey.sql", import.meta.url), "utf8");
check("migration 187 re-keys exactly these 12 ids",
  [...mig.matchAll(/'extras:(\d+)'/g)].map(m => Number(m[1])).sort(), [...SDF_PIDS].sort());
check("...from Cold Foil to Holofoil", /set printing = 'Holofoil'[\s\S]*printing = 'Cold Foil'/.test(mig), true);
check("...without adding two counts of the same card", /greatest\(h\.quantity, c\.quantity\)/.test(mig), true);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
