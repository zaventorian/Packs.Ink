// test_card_versions.mjs — guards how a card's VERSIONS are named and counted.
//
//     node scripts/test_card_versions.mjs
//
// Extracts the real helpers out of Index.html rather than restating them.
//
// Both failure modes here are silent and both have already shipped once.
//
//   1. "Top Prize" and "Prize Wall" are CHALLENGE PROMO words. Applied
//      globally they put a "Top Prize" version tab on Peter Pan - Pirate's
//      Bane, an Into the Inklands enchanted that has no such thing. Nothing
//      errors; the tab is just a lie.
//
//   2. A card whose versions are NAMED (Two Swords, Text Error) has exactly
//      two. Every other printing string that reaches it is a finish, and on an
//      enchanted — cold foil by definition — "Foil" distinguishes nothing.
//      Three eBay sales whose titles said "foil" were enough to grow that card
//      a third version tab out of nowhere.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);

function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

function grabLine(prefix) {
  const line = src.split(/\r?\n/).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
}

const moduleSrc = [
  // The C1 set list is what makes the Challenge vocabulary conditional.
  'const SPLIT_BY_PRINTING_SETS_GLOBAL = new Set(["LCP (C1)"]);',
  grabLine("const PRINTING_VARIANT_LABEL = "),
  grabLine("const VARIANT_BADGE_HIDE = "),
  grabLine("const variantBadge = "),
  // End marker is "]);" — the next "};" belongs to gradedSlotBucket.
  grab("const VERSION_FINISH_WORDS = new Set([", "]);"),
  grabLine("const isFinishOnlyPrinting = "),
  grab("const gradedVariantLabel = (printing, setName) => {", NL + "};"),
  "export {gradedVariantLabel, isFinishOnlyPrinting, variantBadge};",
].join(NL);

const mod = await import("data:text/javascript," + encodeURIComponent(moduleSrc));
const { gradedVariantLabel, isFinishOnlyPrinting } = mod;

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(
    (ok ? "PASS  " : "FAIL  ") + name +
    (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"),
  );
};

// ── the Challenge vocabulary is Challenge-only ───────────────────────────
check("C1 foil is Top Prize", gradedVariantLabel("Foil", "LCP (C1)"), "Top Prize");
check("C1 non-foil is Prize Wall", gradedVariantLabel("Non-Foil", "LCP (C1)"), "Prize Wall");

// The regression. Every one of these is a real set that has no prize wall.
for (const set of ["Into the Inklands", "The First Chapter", "Fabled", "Winterspell"]) {
  check('"' + set + '" foil is NOT Top Prize', gradedVariantLabel("Foil", set), "Foil");
  check('"' + set + '" non-foil is NOT Prize Wall', gradedVariantLabel("Non-Foil", set), "Non-Foil");
}

// ── named versions survive everywhere; baseline is never badged ──────────
check("Text Error keeps its name", gradedVariantLabel("Text Error", "Into the Inklands"), "Text Error");
check("Two Swords keeps its name",
  gradedVariantLabel("Two Swords Variant", "The First Chapter"), "Two Swords Variant");
check("the base print gets no badge", gradedVariantLabel("Normal", "Into the Inklands"), null);
// A bare foil finish reads "Foil", not the C1 name — that is the Screener's
// foil-split badge and is correct. What matters for a named-version card is
// that its BASE version key ("Normal", which every finish folds into) carries
// no badge at all.
check("a bare foil finish reads Foil, never Top Prize",
  gradedVariantLabel("Cold Foil", "Into the Inklands"), "Foil");
check("holofoil likewise", gradedVariantLabel("Holofoil", "Into the Inklands"), "Foil");
check("no printing at all", gradedVariantLabel(null, "Into the Inklands"), null);

// ── a finish word is not a version ───────────────────────────────────────
for (const p of ["Normal", "Non-Foil", "nonfoil", "Foil", "Cold Foil", "Holofoil",
                 "holo", "Unknown", "", "  FOIL  ", null, undefined]) {
  check("finish-only: " + JSON.stringify(p), isFinishOnlyPrinting(p), true);
}
for (const p of ["Text Error", "Two Swords Variant", "Prize Wall", "Top Prize"]) {
  check("a real version is NOT finish-only: " + p, isFinishOnlyPrinting(p), false);
}

// The specific shape that produced the phantom tab: Peter Pan's sales carry
// Normal x176, Text Error x87, null x11 and Foil x3. Folding finishes into the
// base has to leave exactly two versions.
const peterPanSales = [
  ...Array(176).fill("Normal"), ...Array(87).fill("Text Error"),
  ...Array(11).fill(null), ...Array(3).fill("Foil"),
];
const versions = new Set(["Normal"]);
for (const p of peterPanSales) if (p && !isFinishOnlyPrinting(p)) versions.add(p);
check("Pirate's Bane has exactly two versions", [...versions].sort().join(","), "Normal,Text Error");
check("...and none of them is Top Prize", versions.has("Top Prize"), false);

console.log(failed ? NL + failed + " FAILED" : NL + "all passed");
process.exit(failed ? 1 : 0);
