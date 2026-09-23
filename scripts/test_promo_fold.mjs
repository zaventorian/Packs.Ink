// test_promo_fold.mjs — promos folding under the set they belong to.
//
// Run: node scripts/test_promo_fold.mjs
//
// Filtering Cards to a set also shows the promos OF that set's cards, at the
// bottom. Two things decide which set a promo belongs to, and the interaction
// between them is the whole point of this test:
//
//   1. the catalog — the set of the first NON-promo card sharing the name;
//   2. PROMO_PARENT_SET_SEED — a hand-read fact for the reveal-season window
//      where a promo exists but its base card has not been revealed yet.
//
// The seed is, by design, STALE the moment a set finishes landing. So the rule
// that has to hold forever is "a real base card always wins". If that ever
// inverts, a promo silently files under whatever the seed said months ago, and
// nothing anywhere reports it — the promo just sits under the wrong set.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = fs.readFileSync(path.join(ROOT, "Index.html"), "utf8");

function slice(startRe, endRe, label){
  const s = SRC.search(startRe);
  if(s < 0) throw new Error(`start not found: ${label}`);
  const rest = SRC.slice(s);
  const m = rest.match(endRe);
  if(!m) throw new Error(`end not found: ${label}`);
  return rest.slice(0, rest.search(endRe) + m[0].length);
}

const mod = new Function(
  // SET_PARENT is consulted by setPromoBaseSet; slice the real one so a future
  // child-set entry is exercised here rather than stubbed away.
  slice(/^const SET_PARENT = \{/m, /^\};/m, "SET_PARENT") + "\n" +
  slice(/^const PROMO_PARENT_SET_SEED = \{/m, /^\};/m, "seed") + "\n" +
  slice(/^const setPromoBaseSet = /m, /^\};/m, "setPromoBaseSet") + "\n" +
  slice(/^const cardParentSetForFilter = /m, /^\};/m, "cardParentSetForFilter") + `
  return {setPromoBaseSet, cardParentSetForFilter, PROMO_PARENT_SET_SEED,
          peek: () => _promoBaseSet};
`)();
const {setPromoBaseSet, cardParentSetForFilter, PROMO_PARENT_SET_SEED, peek} = mod;

let pass = 0, fail = 0;
const eq = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if(g === w){ pass++; return; }
  fail++;
  console.error(`FAIL ${label}\n  got  ${g}\n  want ${w}`);
};
const row = (name, set, rarity) => ({"Product Name": name, Set: set, Rarity: rarity});

// ── the seed fills a gap ────────────────────────────────────────────────────
setPromoBaseSet([row("Nick Wilde - Inquisitive Harbormaster", "PD1", "Promo")]);
eq("a promo with no base card still finds its set via the seed",
   cardParentSetForFilter(row("Nick Wilde - Inquisitive Harbormaster", "PD1", "Promo")),
   "Hyperia City");

// ── ⚠ the rule that must never invert: a REAL base card wins ───────────────
setPromoBaseSet([
  row("Nick Wilde - Inquisitive Harbormaster", "Some Future Set", "Rare"), // base lands
  row("Nick Wilde - Inquisitive Harbormaster", "PD1", "Promo"),
]);
eq("once the base card exists the catalog overrides the seed",
   cardParentSetForFilter(row("Nick Wilde - Inquisitive Harbormaster", "PD1", "Promo")),
   "Some Future Set");

// ── ordinary behaviour is untouched ─────────────────────────────────────────
setPromoBaseSet([
  row("Belle - Always Reading", "Attack of the Vine!", "Rare"),
  row("Belle - Always Reading", "Promo Set 4", "Promo"),
  row("Elsa - Snow Queen", "The First Chapter", "Legendary"),
]);
eq("a normal promo folds under its base card's set",
   cardParentSetForFilter(row("Belle - Always Reading", "Promo Set 4", "Promo")),
   "Attack of the Vine!");
eq("a NON-promo card is never folded anywhere",
   cardParentSetForFilter(row("Elsa - Snow Queen", "The First Chapter", "Legendary")),
   null);
eq("a promo nothing knows about folds nowhere, it does not throw",
   cardParentSetForFilter(row("Nobody - At All", "Promo Set 4", "Promo")), null);

// ⚠ A promo must never index itself as a base, or the first promo printing of a
// card would claim the promo set as that card's home and the real set could
// never win.
setPromoBaseSet([
  row("Belle - Always Reading", "Promo Set 4", "Promo"),
  row("Belle - Always Reading", "Attack of the Vine!", "Rare"),
]);
eq("promo rows are not indexed as bases, whatever the row order",
   cardParentSetForFilter(row("Belle - Always Reading", "Promo Set 4", "Promo")),
   "Attack of the Vine!");

// ── the seed's own shape ────────────────────────────────────────────────────
const entries = Object.entries(PROMO_PARENT_SET_SEED);
eq("the seed is non-empty while Hyperia City is still revealing", entries.length > 0, true);
// Keyed by "Name - Version" because that is what buildRow puts in Product Name;
// a bare character name would fold every printing of that character.
eq("every seed key is a full Product Name, not a bare character name",
   entries.filter(([k]) => !k.includes(" - ")).map(([k]) => k), []);
// ⚠ A prestage id is temporary (retire_prestaged deletes it); a name is not.
eq("no seed key is a card id",
   entries.filter(([k]) => /^crd_/.test(k)).map(([k]) => k), []);

// Re-running must be idempotent — CardBrowser calls it on every catalog memo.
const rows = [row("Belle - Always Reading", "Attack of the Vine!", "Rare")];
setPromoBaseSet(rows); const a = peek().size;
setPromoBaseSet(rows); const b = peek().size;
eq("setPromoBaseSet is idempotent", a === b, true);
eq("and it REPLACES rather than accumulates across different catalogs",
   (setPromoBaseSet([]), peek().size), entries.length);

console.log(`${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
