// test_dreamborn_import.mjs — guards the collection CSV importer.
//
//     node scripts/test_dreamborn_import.mjs
//
// The regression this locks down: Dreamborn's current collection export is a
// LONG format — one row per card+variant with Set Number / Card Number /
// Variant / Count / Name columns — while the importer originally demanded the
// wide Normal/Foil shape and rejected every real Dreamborn file with
// "missing required column" (reported 2026-08-23). The long format also
// writes promo collector numbers as printed ("14/P1", "10/C1", "5/PD1")
// under the MAINLINE set's number, so suffix routing is what keeps promo
// copies off the base printing.
//
// Run after touching parseDreambornCsv / buildImportNameIndex / the name
// normalizers in Index.html. Manual (no client-side CI), but it extracts the
// real code out of Index.html so it cannot drift from what ships.
import { readFileSync } from "node:fs";

// Normalize CRLF -> LF before slicing. The repo stores LF, but git's
// core.autocrlf=true (the default on Zaven's Windows checkout) hands this
// script a CRLF working copy, and the multi-line end markers below are
// written with "\n" — so every grab() threw "missing end marker" and the
// guard could only ever pass in an LF checkout. Extraction is the whole
// point of this test, so it has to survive both.
const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8")
  .replace(/\r\n/g, "\n");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const mainlineSets = grab("const MAINLINE_SETS = [", "];");
const searchNorm = grab("const searchNorm = (s) => (s||\"\")", "´]/g, \"\");");
const parseCsv = grab("function parseCsvText(text){", "  return rows;\n}");
const importer = grab(
  "const FOIL_PRINTING_PREF = [",
  "  return {entries, matchedCards, unmatched, totalNormal, totalFoil};\n}",
);

const { parseDreambornCsv, buildImportNameIndex } = await import(
  "data:text/javascript," +
  encodeURIComponent(
    `${mainlineSets}\n${searchNorm}\n${parseCsv}\n${importer}\n` +
    `export {parseDreambornCsv, buildImportNameIndex};`,
  )
);

// --- synthetic catalog ------------------------------------------------------
const R = (card_id, tcg_printing, name, Set, Number, Rarity) =>
  ({ card_id, tcg_printing, "Product Name": name, Set, Number, Rarity });
const CATALOG = [
  R("queen-cp", "Normal", "The Queen - Commanding Presence", "Rise of the Floodborn", "26", "Super Rare"),
  R("queen-cp", "Cold Foil", "The Queen - Commanding Presence", "Rise of the Floodborn", "26", "Super Rare"),
  // base + promo share a name; the /P1 suffix must pick the promo
  R("cind-base", "Normal", "Cinderella - Knight in Training", "The First Chapter", "7", "Common"),
  R("cind-base", "Cold Foil", "Cinderella - Knight in Training", "The First Chapter", "7", "Common"),
  R("cind-promo", "Cold Foil", "Cinderella - Knight in Training", "Promo Set 1", "14", "Promo"),
  // foil-only promo that Dreamborn labels variant "normal"
  R("jafar-promo", "Holofoil", "Jafar - High Sultan of Lorcana", "Promo Set 2", "32", "Promo"),
  R("pup-a", "Normal", "Dalmatian Puppy - Tail Wagger", "Into the Inklands", "4a", "Common"),
  R("pup-a", "Cold Foil", "Dalmatian Puppy - Tail Wagger", "Into the Inklands", "4a", "Common"),
  R("pup-e", "Normal", "Dalmatian Puppy - Tail Wagger", "Into the Inklands", "4e", "Common"),
  R("teka", "Normal", "Te Kā - The Burning One", "The First Chapter", "130", "Legendary"),
  R("teka", "Cold Foil", "Te Kā - The Burning One", "The First Chapter", "130", "Legendary"),
  // C1 split-printing card + the base-set song of the same name
  R("c1-awnw", "Normal", "A Whole New World", "Lorcana Challenge Promo (C1)", "10", "Promo"),
  R("c1-awnw", "Holofoil", "A Whole New World", "Lorcana Challenge Promo (C1)", "10", "Promo"),
  R("awnw-base", "Normal", "A Whole New World", "Shimmering Skies", "196", "Super Rare"),
  R("awnw-base", "Cold Foil", "A Whole New World", "Shimmering Skies", "196", "Super Rare"),
  R("ench", "Cold Foil", "Elsa - Spirit of Winter", "Rise of the Floodborn", "205", "Enchanted"),
  // P4 promo absent from the catalog — only the mainline card exists
  R("morph-base", "Normal", "Morph - Little Imitator", "Attack of the Vine!", "40", "Common"),
  R("morph-base", "Cold Foil", "Morph - Little Imitator", "Attack of the Vine!", "40", "Common"),
];
const index = buildImportNameIndex(CATALOG);

let failures = 0;
const check = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { console.log("  ok  " + label); return; }
  failures++;
  console.error("FAIL  " + label + "\n  got  " + g + "\n  want " + w);
};
const entryMap = (report) => {
  const m = {};
  for (const e of report.entries) m[e.cardId + ":" + e.printing] = e.qty;
  return m;
};

// --- 1. Dreamborn long format ----------------------------------------------
{
  const csv = [
    "Set Number,Card Number,Variant,Count,Name,Color,Rarity",
    '002,26,normal,3,"The Queen - Commanding Presence",Amber,Super Rare',
    '002,26,foil,2,"The Queen - Commanding Presence",Amber,Super Rare',
    '001,14/P1,foil,2,"Cinderella - Knight in Training",Steel,Promo',
    '008,32/P2,normal,2,"Jafar - High Sultan of Lorcana",Amethyst Steel,Promo',
    '003,4a,normal,1,"Dalmatian Puppy - Tail Wagger",Amber,Common',
    '003,4e,normal,1,"Dalmatian Puppy - Tail Wagger",Amber,Common',
    '001,130,normal,4,"Te Ka - Burning One",Ruby,Legendary',
    '002,205,foil,1,"Elsa - Spirit of Winter",Amethyst,Enchanted',
    '001,10/C1,normal,3,"A Whole New World",Steel,Promo',
    '013,9/P4,foil,1,"Morph - Little Imitator",Amethyst,Promo',
  ].join("\r\n");
  const rep = parseDreambornCsv(csv, index, CATALOG);
  check("long: no error", rep.error || null, null);
  check("long: entries", entryMap(rep), {
    "queen-cp:Normal": 3, "queen-cp:Cold Foil": 2,   // rows aggregate per card
    "cind-promo:Cold Foil": 2,                        // /P1 suffix beats the base printing
    "jafar-promo:Holofoil": 2,                        // "normal" folds into the only printing
    "pup-a:Normal": 1, "pup-e:Normal": 1,             // letter-suffix numbers stay distinct
    "teka:Normal": 4,                                 // garbled name rescued by set+cn
    "ench:Cold Foil": 1,
    "c1-awnw:Normal": 3,                              // /C1 suffix + real Normal printing
    "morph-base:Cold Foil": 1,                        // unknown promo wave → base fallback
  });
  check("long: matched/unmatched", [rep.matchedCards, rep.unmatched.length], [9, 0]);
  check("long: totals by written printing", [rep.totalNormal, rep.totalFoil], [12, 8]);
}

// --- 2. wide format (our own export) round-trips unchanged ------------------
{
  const csv = [
    "Normal,Foil,Name,Set,Card Number,Rarity",
    "3,2,The Queen - Commanding Presence,Rise of the Floodborn,26,Super Rare",
    "0,1,Te Kā - The Burning One,The First Chapter,130,Legendary",
    "1,0,Te Ka - The Burning One,,,",                 // no cn → diacritic-fold tier
    "4,0,Unknown Card Nobody Has,Nowhere,1,Common",
  ].join("\n");
  const rep = parseDreambornCsv(csv, index, CATALOG);
  check("wide: entries", entryMap(rep), {
    "queen-cp:Normal": 3, "queen-cp:Cold Foil": 2,
    "teka:Cold Foil": 1, "teka:Normal": 1,
  });
  check("wide: unmatched carries quantities", rep.unmatched, [{ name: "Unknown Card Nobody Has", normal: 4, foil: 0 }]);
}

// --- 3. duplicate targets merge (commitImport applies entries independently) —
{
  const csv = [
    "Set Number,Card Number,Variant,Count,Name,Color,Rarity",
    '013,9/P4,foil,1,"Morph - Little Imitator",Amethyst,Promo',
    '013,40,foil,2,"Morph - Little Imitator",Amethyst,Common',
  ].join("\n");
  const rep = parseDreambornCsv(csv, index, CATALOG);
  check("merge: one summed entry", rep.entries, [{ cardId: "morph-base", printing: "Cold Foil", qty: 3, name: "Morph - Little Imitator" }]);
  check("merge: both wants matched", rep.matchedCards, 2);
}

// --- 4. unrecognizable header errors out, naming both shapes ----------------
{
  const rep = parseDreambornCsv("Foo,Bar\n1,2", index, CATALOG);
  check("error: mentions expected formats", !!(rep.error && /Dreamborn/.test(rep.error) && /Normal\/Foil/.test(rep.error)), true);
}

if (failures) { console.error("\n" + failures + " failure(s)"); process.exit(1); }
console.log("\nall dreamborn import tests passed");
