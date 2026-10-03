// test_quest_cards.mjs — Illumineer's Quest cards are their own thing, not promos.
//
//     node scripts/test_quest_cards.mjs
//
// The scenario decks in an Illumineer's Quest box (Ursula's, Jafar's, the
// Vine's) are board-game pieces. Lorcast filed Q3's 37 cards as Promo, and
// every set the site does not list was forced to Promo too, so they showed up
// as promos everywhere (Zaven, 2026-10-03). Each failure here is silent: the
// cards just drift back into the promo lists. Extracts the real code.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const grab = (start, end) => {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
};

const m = await import("data:text/javascript," + encodeURIComponent([
  grab("const EXTRAS_SET_NAME = ", ";"),
  grab("const QUEST_SETS = [", "\n];"),
  grab("const QUEST_SET_SET = ", ";"),
  grab("const QUEST_RARITY = ", ";"),
  grab("const MAINLINE_SETS = [", "\n];"),
  grab("const SET_ORDER = [", "\n];"),
  grab("const UNIFIED_TILE_SETS = new Set([", "\n]);"),
  grab("const PROMO_RARITY_SETS = new Set([", "\n]);"),
  grab("const SET_DISPLAY_NAMES = {", "\n};"),
  grab("const NUMBERED_PROMO_SETS = ", ";"),
  grab("const REVEAL_EXCLUDED_SETS = ", ";"),
  "export { QUEST_SETS, QUEST_SET_SET, QUEST_RARITY, SET_ORDER, MAINLINE_SETS, UNIFIED_TILE_SETS,",
  "  PROMO_RARITY_SETS, SET_DISPLAY_NAMES, NUMBERED_PROMO_SETS, REVEAL_EXCLUDED_SETS };",
].join("\n")));

let pass = 0, fail = 0;
const ok = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + "\n        got  " + g + "\n        want " + w); }
};

ok("three quests, oldest first", m.QUEST_SETS, [
  "Illumineer's Quest: Deep Trouble",
  "Illumineer's Quest: Palace Heist",
  "Illumineer's Quest: The Great Hunny Rescue",
]);
ok("Lorcast's Q3 name maps to the product name",
   m.SET_DISPLAY_NAMES["Hunny Rescue – Illumineer's Quest"], "Illumineer's Quest: The Great Hunny Rescue");
// The set names Q1/Q2 rows carry are the hand-minted sets of migration 179.
const mig = readFileSync(new URL("../supabase/179_illumineers_quest_sets.sql", import.meta.url), "utf8");
for (const s of m.QUEST_SETS.slice(0, 2)) ok(`migration 179 creates "${s}"`, mig.includes(s.replace("'", "''")), true);

for (const s of m.QUEST_SETS) {
  ok(`${s} is listed (in SET_ORDER)`, m.SET_ORDER.includes(s), true);
  ok(`${s} is not a booster set`, m.MAINLINE_SETS.includes(s), false);
  ok(`${s} is not a promo-rarity set`, m.PROMO_RARITY_SETS.has(s), false);
  ok(`${s} is not a promo tile set`, m.UNIFIED_TILE_SETS.has(s), false);
  ok(`${s} is not a numbered promo set`, m.NUMBERED_PROMO_SETS.has(s), false);
  ok(`${s} stays out of the reveal reel`, m.REVEAL_EXCLUDED_SETS.has(s), true);
}
ok("rarity is Quest", m.QUEST_RARITY, "Quest");

// The transform sets the rarity BEFORE the "unlisted set -> Promo" fallback.
ok("transform gives quest cards the Quest rarity",
   /let rar = normalizeRarity\(c\.rarity\);\n\s*if\(QUEST_SET_SET\.has\(setName\)\) rar = QUEST_RARITY;\n\s*else if\(!SET_ORDER\.includes\(setName\)\) rar = "Promo";/.test(src), true);
ok("an unpriced quest card is one Normal row",
   /else if\(QUEST_SET_SET\.has\(setName\)\)\{\n[^\n]*\n\s*rows\.push\(buildRow\(c, setName, rar, name, "Normal", null\)\);/.test(src), true);
ok("the Collection grid keeps quests out of the promo section",
   src.includes('setsToShow.filter(s => !MAINLINE_SETS.includes(s) && !QUEST_SET_SET.has(s))'), true);
ok("the Collection grid has an Illumineer's Quests section", src.includes("<span>Illumineer's Quests</span>"), true);
ok("quests don't count toward the headline completion %",
   src.includes("if(r.Set !== EXTRAS_SET_NAME && !QUEST_SET_SET.has(r.Set)){"), true);

ok("a Battleground turns upright like a Location",
   /const isLandscapeCard = \(row\) =>\n[^\n]*t === "Location" \|\| t === "Battleground"/.test(src), true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
