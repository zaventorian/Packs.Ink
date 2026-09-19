// test_promo_single_printing.mjs — a single-printing promo gets ONE row.
//
//     node scripts/test_promo_single_printing.mjs
//
// A card in a promo set like PD1 or Promo Set 3 exists in exactly one version,
// so it must render one add box. It rendered two (Non-Foil + Foil) for every
// unpriced PD1 card on 2026-09-18 (Zaven: "only 1 version exists ... ensure it
// doesn't happen in the future"), and TCGCSV can publish one promo pid under
// two printings, which would do the same to a priced card.
// collapsePromoPrintings is the backstop that runs last in
// transformSupabaseData. Extracts the real code out of Index.html.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const grab = (start, end) => {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
};

const { collapsePromoPrintings, UNIFIED_TILE_SETS } = await import("data:text/javascript," + encodeURIComponent([
  grab("const UNIFIED_TILE_SETS = new Set([", "\n]);"),
  grab("const PROMO_PRINTING_PREF = ", ";"),
  grab("const collapsePromoPrintings = (rows) => {", "\n};"),
  "export { collapsePromoPrintings, UNIFIED_TILE_SETS };",
].join("\n")));

let pass = 0, fail = 0;
const ok = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + "\n        got  " + g + "\n        want " + w); }
};
const row = (Set, card_id, tcg_printing, price) =>
  ({ Set, card_id, tcg_printing, "Market Price": price ?? null, "Low Price": price ?? null });
const printings = (rows, id) => collapsePromoPrintings(rows).filter(r => r.card_id === id).map(r => r.tcg_printing);

// Every promo set the Collection shows as one "Promos" counter is covered.
for (const s of ["Promo Set 1", "Promo Set 2", "Promo Set 3", "Promo Set 4", "PD1",
                 "D23 Collection", "Magical Places Promos", "Curator's Collection: Heroines"]) {
  ok(`${s} is a single-printing set`, UNIFIED_TILE_SETS.has(s), true);
}
// The Challenge promos genuinely split (Top Prize foil vs Prize Wall non-foil).
ok("C1 is NOT collapsed", UNIFIED_TILE_SETS.has("Lorcana Challenge Promo (C1)"), false);
ok("C2 is NOT collapsed", UNIFIED_TILE_SETS.has("Lorcana Challenge Promo (C2)"), false);

ok("unpriced placeholder pair -> one row",
   printings([row("PD1", "a", "Normal"), row("PD1", "a", "Cold Foil")], "a"), ["Cold Foil"]);
ok("the priced printing wins over an unpriced one",
   printings([row("PD1", "a", "Holofoil"), row("PD1", "a", "Normal", 3)], "a"), ["Normal"]);
ok("two priced printings -> the foil one",
   printings([row("Promo Set 4", "a", "Normal", 2), row("Promo Set 4", "a", "Holofoil", 5)], "a"), ["Holofoil"]);
ok("a single row is untouched",
   printings([row("Promo Set 3", "a", "Normal", 1)], "a"), ["Normal"]);
ok("two card_ids in one set both survive (an SC participant/champion pair)",
   collapsePromoPrintings([row("Promo Set 3", "p", "Normal", 1), row("Promo Set 3", "c", "Holofoil", 9)]).length, 2);
ok("a booster card keeps both printings",
   printings([row("Fabled", "a", "Normal", 1), row("Fabled", "a", "Cold Foil", 4)], "a"), ["Normal", "Cold Foil"]);
ok("a C1 card keeps both printings",
   printings([row("Lorcana Challenge Promo (C1)", "a", "Normal", 1),
              row("Lorcana Challenge Promo (C1)", "a", "Holofoil", 9)], "a"), ["Normal", "Holofoil"]);
ok("row order is preserved for everything else",
   collapsePromoPrintings([row("Fabled", "x", "Normal"), row("PD1", "a", "Normal"),
                           row("PD1", "a", "Cold Foil"), row("Fabled", "y", "Normal")]).map(r => r.card_id),
   ["x", "a", "y"]);

// It has to actually run: the transform's return goes through it.
ok("transformSupabaseData returns collapsePromoPrintings(rows)",
   /const out = collapsePromoPrintings\(rows\);\n\s*setPromoBaseSet\(out\);\n\s*return out;\n\};/.test(src), true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
