// check_index.mjs — refuse to deploy a card index that came out wrong.
//
//   node tools/check_index.mjs
//
// build_index.mjs runs the SITE's catalog transform against live data; if the
// site changes shape under it, or a fetch comes back short, the index can come
// out small or empty without anything throwing. Deploying that would answer
// every lookup with "no match". These floors are far below today's numbers
// (2,600 cards, 150 sealed) and far above anything a broken build produces.
import { readFileSync } from "node:fs";
import { createResolver } from "../src/resolver.js";

const ix = JSON.parse(readFileSync(new URL("../src/card-index.json", import.meta.url), "utf8"));
const problems = [];
if (!(ix.cards && ix.cards.length >= 2000)) problems.push(`only ${ix.cards && ix.cards.length} cards`);
if (!(ix.sealed && ix.sealed.length >= 50)) problems.push(`only ${ix.sealed && ix.sealed.length} sealed products`);
if (!(ix.sets && ix.sets.length >= 15)) problems.push(`only ${ix.sets && ix.sets.length} sets`);
const age = (Date.now() - Date.parse(ix.priceDate + "T00:00:00Z")) / 86400000;
if (!(age < 5)) problems.push(`price date ${ix.priceDate} is ${Math.round(age)} days old`);
const played = ix.cards.filter((c) => c.pl > 0).length;
if (played < 100) problems.push(`only ${played} cards carry tournament play counts`);

const R = createResolver(ix);
for (const [q, kind] of [["elsa", "card"], ["mickey mouse", "card"], ["stitch", "card"], ["booster box", "sealed"]]) {
  const r = R.resolve(q);
  if (r.kind !== kind) problems.push(`"${q}" resolved to ${r.kind}, expected ${kind}`);
}
if (problems.length) {
  console.error("card index looks wrong:\n  " + problems.join("\n  "));
  process.exit(1);
}
console.log(`card index ok: ${ix.cards.length} cards (${played} played), ${ix.sealed.length} sealed, prices as of ${ix.priceDate}`);
