// test_printing_badge.mjs — guards the one rule that decides whether a card's
// PRINTING is worth a word on a tile.
//
//     node scripts/test_printing_badge.mjs
//
// Extracts the real helpers out of Index.html rather than restating them.
//
// This bug has shipped several times over, once per surface, because each
// surface asked `printing !== "Normal"` on its own. An Enchanted is cold foil
// BY DEFINITION — it has exactly one printing and nothing to be distinguished
// from — so that test stamps "ENCHANTED · FOIL" on every card in the Chase
// Movers banner and "PSA 10 (FOIL)" on every tile in the Graded Market strip.
// Nothing errors. The badge is simply a statement about a difference that does
// not exist, and it goes out in the shareable PNG exports too.
//
// It is NOT enough to special-case chase rarities. The live catalog holds two
// counterexamples in the OTHER direction, both rarity "Promo":
//   · the 8 Challenge Promo (C1) cards, whose Top Prize foil and Prize Wall
//     non-foil are two genuinely different markets ($1,707 vs $280 for one
//     PSA 10), and which must be labelled with the Challenge words;
//   · PD1's Beast - Snowfield Troublemaker, which splits Normal / Cold Foil
//     like an ordinary booster card.
// So the question is whether a SECOND PRINTING EXISTS, which only the catalog
// can answer — hence the _printBadge index rather than a rarity list.
//
// The last section is the part that makes this stick: it fails when a render
// site grows its own copy of the predicate again.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);

const grab = (start, end) => {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
};
const grabLine = (prefix) => {
  const line = src.split(/\r?\n/).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
};

const moduleSrc = [
  grabLine("const SPLIT_BY_PRINTING_SETS_GLOBAL = "),
  grabLine("const PRINTING_VARIANT_LABEL = "),
  grabLine("const VARIANT_BADGE_HIDE = "),
  grabLine("const variantBadge = "),
  grabLine("const GRADED_FOIL_PRINTINGS = "),
  grabLine("const gradedFoilBucket = "),
  grab("const VERSION_FINISH_WORDS = new Set([", "]);"),
  grabLine("const isFinishOnlyPrinting = "),
  grabLine("let _printBadge = "),
  grab("const setPrintingBadges = (rows) => {", NL + "};"),
  grab("const printingBadge = (printing, cardId) => {", NL + "};"),
  "export {setPrintingBadges, printingBadge};",
].join(NL);

const { setPrintingBadges, printingBadge } = await import(
  "data:text/javascript," + encodeURIComponent(moduleSrc)
);

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(
    (ok ? "PASS  " : "FAIL  ") + name +
      (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")")
  );
};

// A catalog shaped like the real one. Every printing distribution below was
// measured against the live catalog (5,896 rows) on 2026-09-13, so these are
// the actual cases rather than invented ones.
const row = (card_id, Set, tcg_printing, Rarity) => ({ card_id, Set, tcg_printing, Rarity });
const CATALOG = [
  // Chase: ONE printing each, foil by definition. 224 Enchanteds are Holofoil,
  // 90 Epics, 10 Iconics — none has a non-foil sibling anywhere.
  row("crd_ench", "Into the Inklands", "Holofoil", "Enchanted"),
  row("crd_epic", "Fabled", "Holofoil", "Epic"),
  row("crd_iconic", "Whispers in the Well", "Holofoil", "Iconic"),
  // The single Enchanted the catalog stores as Cold Foil rather than Holofoil —
  // still one printing, so still nothing to say.
  row("crd_ench_cf", "The First Chapter", "Cold Foil", "Enchanted"),
  // Promo, foil-only (Gaston - Arrogant Hunter 24/P1 is this shape; 162 are).
  row("crd_promo1", "Promo Set 1", "Holofoil", "Promo"),
  // Promo, non-foil-only (28 are).
  row("crd_promo_n", "Promo Set 2", "Normal", "Promo"),
  // Ordinary booster card: a real Normal / Cold Foil split.
  row("crd_rare", "Azurite Sea", "Normal", "Rare"),
  row("crd_rare", "Azurite Sea", "Cold Foil", "Rare"),
  // Challenge Promo (C1): rarity Promo, and its split IS load-bearing.
  row("crd_c1", "Lorcana Challenge Promo (C1)", "Normal", "Promo"),
  row("crd_c1", "Lorcana Challenge Promo (C1)", "Holofoil", "Promo"),
  // PD1 Beast - Snowfield Troublemaker: rarity Promo, splits like a booster card.
  row("crd_pd1", "PD1", "Normal", "Promo"),
  row("crd_pd1", "PD1", "Cold Foil", "Promo"),
];
setPrintingBadges(CATALOG);

console.log("-- the reported bug: a chase card never wears a finish --");
check("Enchanted (Holofoil)", printingBadge("Holofoil", "crd_ench"), null);
check("Epic (Holofoil)", printingBadge("Holofoil", "crd_epic"), null);
check("Iconic (Holofoil)", printingBadge("Holofoil", "crd_iconic"), null);
check("Enchanted stored as Cold Foil", printingBadge("Cold Foil", "crd_ench_cf"), null);
check("foil-only promo", printingBadge("Holofoil", "crd_promo1"), null);
check("non-foil-only promo", printingBadge("Normal", "crd_promo_n"), null);

console.log(NL + "-- a graded sale's printing is whatever an eBay title said --");
// Three sales saying "foil" were once enough to grow Peter Pan - Pirate's Bane
// a third version tab. The same words reach the Graded Market strip, and the
// reported screenshot is exactly this: Gramma Tala, an Enchanted, wearing FOIL
// because the sale row said so.
check("Enchanted, sale says 'Foil'", printingBadge("Foil", "crd_ench"), null);
check("Enchanted, sale says 'holo'", printingBadge("holo", "crd_ench"), null);
check("Enchanted, sale says 'Non-Foil'", printingBadge("Non-Foil", "crd_ench"), null);
check("Enchanted, sale printing unknown", printingBadge("Unknown", "crd_ench"), null);

console.log(NL + "-- but a card that really splits still gets labelled --");
check("booster foil", printingBadge("Cold Foil", "crd_rare"), "Foil");
check("booster non-foil is the base, no label", printingBadge("Normal", "crd_rare"), null);
check("PD1 promo that really splits", printingBadge("Cold Foil", "crd_pd1"), "Foil");
check("PD1 promo, base printing", printingBadge("Normal", "crd_pd1"), null);

console.log(NL + "-- C1 keeps the Challenge vocabulary, and BOTH sides --");
// Two different markets. Losing the label here is as wrong as inventing one on
// an Enchanted, and costs more.
check("C1 foil", printingBadge("Holofoil", "crd_c1"), "Top Prize");
check("C1 non-foil", printingBadge("Normal", "crd_c1"), "Prize Wall");
check("C1 sale titled 'Foil'", printingBadge("Foil", "crd_c1"), "Top Prize");
check("C1 sale titled 'Non-Foil'", printingBadge("Non-Foil", "crd_c1"), "Prize Wall");
check("C1 never says the word Foil", printingBadge("Cold Foil", "crd_c1") === "Foil", false);

console.log(NL + "-- a NAMED version is a different card, not a finish --");
check("Two Swords", printingBadge("Two Swords", "crd_ench"), "Two Swords");
check("Text Error", printingBadge("Text Error", "crd_ench"), "Text Error");

console.log(NL + "-- degenerate inputs never throw or invent a badge --");
check("null printing", printingBadge(null, "crd_rare"), null);
check("empty printing", printingBadge("", "crd_rare"), null);
check("null card", printingBadge("Cold Foil", null), null);
check("card not in catalog", printingBadge("Cold Foil", "crd_nope"), null);
// An index that was never stamped must fall silent rather than label everything.
setPrintingBadges([]);
check("unstamped index says nothing", printingBadge("Cold Foil", "crd_rare"), null);
setPrintingBadges(CATALOG);
check("re-stamping restores it", printingBadge("Cold Foil", "crd_rare"), "Foil");

console.log(NL + "-- every render site routes through the one helper --");
// The whole point. Each of these shipped its own foil test and each was wrong
// the same way; a new one must fail here rather than in a screenshot.
const callers = [
  ["MoverTile (Chase / Rare-Leg / Promo / Valuable tiles)",
    "const prBadge = printingBadge(card.printing, card.card_id);"],
  ["paintMoverTile (banner + single-tile PNG export)",
    '(card.rarity||"") + (prBadge?" · "+prBadge:"")'],
  ["Graded Market tile badge",
    '<span class="gmover-foil">${c.prBadge}</span>'],
  ["paintGradedTile (Graded Market PNG export)",
    '(c.prBadge?" · "+c.prBadge:"")'],
  ["Your Top Movers row",
    "const prBadge = printingBadge(row.tcg_printing, row.card_id);"],
  ["Graded bulk-add row",
    "printingBadge(c.printing, c.card_id)"],
  ["stamped during App's render, before any child",
    "useMemo(() => setPrintingBadges(raw), [raw]);"],
];
for (const [name, needle] of callers) check("wired: " + name, src.includes(needle), true);

// The predicate that caused this, in the forms it has actually taken. A render
// site deriving foil-ness itself is the regression, whatever it gets called.
const BANNED = [
  ['card.printing !== "Normal"', /card\.printing\s*!==\s*"Normal"/],
  ["isFoilPrinting(", /\bisFoilPrinting\b/],
  ['row.tcg_printing === "Cold Foil"', /row\.tcg_printing\s*===\s*"Cold Foil"/],
];
for (const [label, re] of BANNED) check("no re-derivation: " + label, re.test(src), false);

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
