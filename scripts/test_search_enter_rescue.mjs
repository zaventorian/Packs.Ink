// test_search_enter_rescue.mjs — guards three Cards-search fixes (2026-09-25).
//
//     node scripts/test_search_enter_rescue.mjs
//
// 1. Enter on a query the parser found structure in ("amber legendary",
//    "stitch 7", "non promo" — the search box's own placeholder examples)
//    used to commit the whole phrase as a `contains:` chip, which matches no
//    card: the grid was right while typing and went to ZERO on Enter.
//    `parsedHasStructure` is the test that now keeps such a query as text.
// 2. A rarity or ink word inside a card's OWN name hid that card:
//    "ariel on human legs" parsed "legs" as Legendary, "painting the roses red"
//    parsed "red" as Ruby. The matcher now rescues a card whose name holds the
//    typed word as a WHOLE word — never a prefix, or "li shang promo" rescues
//    "Li Shang - Newly Promoted" into a Promo filter.
// 3. The Cards tab rebuilt its query object and dropped four of the five
//    exclusion sets, so "non amber" / "without rush" / "no songs" did nothing
//    there; and a Song's type line is "Action - Song", so an exact-match type
//    exclusion never excluded one anywhere.
//
// Extracts the REAL helpers out of Index.html, same pattern as
// test_scanner_edit_search.mjs, so it measures what ships.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
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
  "const localStorage = { getItem(){ return null; }, setItem(){}, removeItem(){} };",
  grabLine("const COCONUT_CARD_TYPE = "),
  grabLine("const EXTRAS_SET_NAME = "),
  grab("const MAINLINE_SETS = [", NL + "];"),
  grab("const SET_ORDER = [", NL + "];"),
  grab("const SET_PARENT = {", NL + "};"),
  grabLine("let _promoBaseSet"),
  grab("const cardParentSetForFilter = (row) => {", NL + "};"),
  grab("const normalizeRarity = r => {", NL + "};"),
  grab("const INK_COLORS = {", 'return items.filter(g => matchesCardFilter(g, f, {...parsed, nameMatchMode: "any"}));' + NL + "};"),
  grab("const emptyFilter = () => ({", NL + "});"),
  "export { parseSearchQuery, matchesCardFilter, smartSplitSuggestion, parsedHasStructure, queryNamesACard, emptyFilter };",
].join(NL);

const { parseSearchQuery, matchesCardFilter, smartSplitSuggestion, parsedHasStructure, queryNamesACard, emptyFilter } =
  await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) console.log("PASS  " + name);
  else { failed++; console.log("FAIL  " + name + "  (got " + g + ", want " + w + ")"); }
};

// ── 1. structure detection ────────────────────────────────────────────────
console.log("1. parsedHasStructure");
for (const q of ["amber legendary", "stitch 7", "non promo", "cost<=2", "uninkable", "lore>=2", "elsa under $5"]) {
  check(`"${q}" has structure`, parsedHasStructure(parseSearchQuery(q)), true);
}
for (const q of ["go go", "mother gothel", "a whole new world"]) {
  check(`"${q}" is a plain name`, parsedHasStructure(parseSearchQuery(q)), false);
}

// ── 2. the whole-word name rescue ─────────────────────────────────────────
console.log("2. name rescue");
const ariel = { "Product Name": "Ariel - On Human Legs", Rarity: "Uncommon", ink: "Amber", inks: ["Amber"], card_type: "Character" };
const roses = { "Product Name": "Painting the Roses Red", Rarity: "Common", ink: "Amber", inks: ["Amber"], card_type: "Action - Song" };
const cruella = { "Product Name": "Cruella De Vil - Style Icon", Rarity: "Rare", ink: "Steel", inks: ["Steel"], card_type: "Character" };
const shang = { "Product Name": "Li Shang - Newly Promoted", Rarity: "Rare", ink: "Steel", inks: ["Steel"], card_type: "Character" };
const legendary = { "Product Name": "Some Hero - Legendary Thing", Rarity: "Legendary", ink: "Ruby", inks: ["Ruby"], card_type: "Character" };
const f = emptyFilter();
check("ariel on human legs finds the Uncommon card", matchesCardFilter(ariel, f, parseSearchQuery("ariel on human legs")), true);
check("painting the roses red finds the Amber song", matchesCardFilter(roses, f, parseSearchQuery("painting the roses red")), true);
check("cruella style icon finds the Rare card", matchesCardFilter(cruella, f, parseSearchQuery("cruella style icon")), true);
check("li shang promo does NOT rescue 'Promoted' (prefix)", matchesCardFilter(shang, f, parseSearchQuery("li shang promo")), false);
check("bare 'legendary' stays strict (no name query)", matchesCardFilter(ariel, f, parseSearchQuery("legendary")), false);
check("bare 'legendary' still finds a Legendary", matchesCardFilter(legendary, f, parseSearchQuery("legendary")), true);
check("bare 'red' stays strict", matchesCardFilter(roses, f, parseSearchQuery("red")), false);

// ── 2b. the Enter split is skipped for a real card's name ─────────────────
console.log("2b. split skip");
const names = ["Ariel - On Human Legs", "Painting the Roses Red", "Mickey Mouse - Amber Champion", "Li Shang - Newly Promoted"];
check("queryNamesACard: ariel on human legs", queryNamesACard("ariel on human legs", names), true);
check("queryNamesACard: li shang promo is not a name (whole words)", queryNamesACard("li shang promo", names), false);
check("queryNamesACard: mickey amber is not a name", queryNamesACard("mickey amber", ["Mickey Mouse - Brave Little Tailor"]), false);
check("no split for a card's own name", smartSplitSuggestion("ariel on human legs", names), null);
check("still splits without the name list", (smartSplitSuggestion("ariel on human legs") || {}).kind, "split");
check("still splits an ordinary name + rarity", (smartSplitSuggestion("elsa promo", names) || {}).kind, "split");

// ── 3. exclusions ─────────────────────────────────────────────────────────
console.log("3. exclusions");
const song = { "Product Name": "Part of Your World", Rarity: "Rare", ink: "Amber", inks: ["Amber"], card_type: "Action - Song" };
const action = { "Product Name": "Dragon Fire", Rarity: "Uncommon", ink: "Ruby", inks: ["Ruby"], card_type: "Action" };
check("'no songs' excludes a song", matchesCardFilter(song, f, parseSearchQuery("no songs")), false);
check("'no songs' keeps a plain action", matchesCardFilter(action, f, parseSearchQuery("no songs")), true);
check("'non amber' excludes an Amber card", matchesCardFilter(song, f, parseSearchQuery("non amber")), false);

// ── 4. wiring (source-level: these live inside a component) ───────────────
console.log("4. wiring");
check("Enter keeps a structured query as text",
  /const structured = !exactDim && !split && parsedHasStructure\(parseSearchQuery\(filter\.search \|\| ""\)\);/.test(src), true);
check("home handoff only phrase-chips a plain name",
  /else if\(q && !q\.includes\(":"\) && !parsedHasStructure\(parseSearchQuery\(q\)\)\)\{/.test(src), true);
const merged = grab("const parsed = useMemo(() => {\n    // Every exclusion set rides along", "}, [parsedFromInput, smartChips, filter.matchMode]);");
for (const k of ["excludeRarities", "excludeInks", "excludeKeywords", "excludeClassifications", "excludeTypes", "dimTok"]) {
  check(`Cards query carries ${k}`, merged.includes(k + ":"), true);
}
check("a rarity chip retires the typed word's rescue", merged.includes("delete p.dimTok.rarity"), true);

if (failed) { console.log(`\n${failed} FAILED`); process.exit(1); }
console.log("\nall passed");
