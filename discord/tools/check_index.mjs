// check_index.mjs — refuse to deploy a card index that came out wrong.
//
//   node tools/check_index.mjs
//
// build_index.mjs runs the SITE's catalog transform against live data; if the
// site changes shape under it, or a fetch comes back short, the index can come
// out small or empty without anything throwing. Deploying that would answer
// every lookup with "no match". These floors are far below today's numbers
// (2,600 cards, 150 sealed) and far above anything a broken build produces.
import { readFileSync, existsSync } from "node:fs";
import { createResolver } from "../src/resolver.js";
import { tileFile } from "../src/tile.js";

const ix = JSON.parse(readFileSync(new URL("../src/card-index.json", import.meta.url), "utf8"));
const problems = [];
if (!(ix.cards && ix.cards.length >= 2000)) problems.push(`only ${ix.cards && ix.cards.length} cards`);
if (!(ix.sealed && ix.sealed.length >= 50)) problems.push(`only ${ix.sealed && ix.sealed.length} sealed products`);
if (!(ix.sets && ix.sets.length >= 15)) problems.push(`only ${ix.sets && ix.sets.length} sets`);
const age = (Date.now() - Date.parse(ix.priceDate + "T00:00:00Z")) / 86400000;
if (!(age < 5)) problems.push(`price date ${ix.priceDate} is ${Math.round(age)} days old`);
const played = ix.cards.filter((c) => c.pl > 0).length;
if (played < 100) problems.push(`only ${played} cards carry tournament play counts`);

// Card art: a picture the index points at must be one Discord can show, and a
// baked one must actually be in public/art/ (wrangler uploads that folder).
// A printing with no picture at all is a warning, not a failure: it means a
// download failed, and holding back the whole day's index over it is worse.
const SAFE_IMG = /^https:\/\/[^?#]+\.(?:jpe?g|png|webp|gif)(?:[?#].*)?$/i;
const artDir = new URL("../public/art/", import.meta.url);
let blind = 0;
for (const c of ix.cards) {
  for (const p of c.p) {
    const img = p.img || "";
    if (img.startsWith("/art/")) {
      const file = img.slice("/art/".length).split("?")[0];
      if (!existsSync(new URL(file, artDir))) problems.push(`${c.n}: ${img} is not in public/art/`);
    } else if (img && !SAFE_IMG.test(img)) {
      problems.push(`${c.n}: an image Discord can't show (${img.slice(0, 60)})`);
    } else if (!img && !p.f.some((f) => f[1])) {
      blind++;
    }
  }
}
if (blind) console.log(`::warning::${blind} printing(s) have no picture (no TCGplayer listing and no baked art)`);

// Card tiles: every finish the index says has one must have its file in
// public/tile/, or /card would point Discord at a 404 and show nothing. Too
// few tiles is only a warning — a reply without one still has a picture.
const tileDir = new URL("../public/tile/", import.meta.url);
let tiles = 0;
for (const c of ix.cards) {
  for (const p of c.p) {
    for (const code of p.tl || "") {
      tiles++;
      if (!existsSync(new URL(tileFile(p.id, code), tileDir))) problems.push(`${c.n} [${code}]: tile ${tileFile(p.id, code)} is not in public/tile/`);
    }
  }
}
if (tiles < 1000) console.log(`::warning::only ${tiles} card tiles — /card shows the plain card picture for the rest`);

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
