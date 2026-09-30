// test_deck_text.mjs — guards the decklist text round trip.
//
//     node scripts/test_deck_text.mjs
//
// deckToText is what the Decklist button copies and parseDeckText is what the
// Import box (and every tournament upload) reads, so the two have to agree —
// and every way they can disagree is silent: a card that quietly isn't there,
// a leader that quietly vanished, a 5-of that quietly became a 4-of.
//
// What is pinned:
//   1. A Coconut deck's leader survives the round trip. It lives OUTSIDE the
//      60, so it is not in deck.cards, and the export used to drop it.
//   2. Two printings of one card export as ONE line — two lines with the same
//      name read as half the copies to a tool that doesn't sum them.
//   3. A card missing from the catalog exports as a comment, never "4 crd_…".
//   4. Accents fold on import ("Te Ka" finds "Te Kā").
//   5. A (set-cn) that names a DIFFERENT card than the line's name loses to
//      the name, and is reported; one that names a printing OF the named card
//      (the Enchanted) still wins, which is the reason the suffix exists.
//   6. A quantity over the copy limit is trimmed AND reported.
//   7. The export is a plain list: no "# " headers and no blank lines, which
//      Discord turns into big headings and gaps. Old "#" lists still import.
//
// Reads the real code out of Index.html rather than restating it.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("marker not found: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("end marker not found after: " + startMarker);
  return src.slice(a, b + endMarker.length);
}

const parts = [
  grab("const MAINLINE_SETS = [", "\n];"),
  grab("const searchNorm = (s) => (s||\"\")", ";\n"),
  grab("function normalizeCardName(s){", "\n}"),
  grab("function squashCardName(s){", "\n}"),
  grab("function foldCardName(s){", "\n}"),
  grab("const SPECIAL_DECK_LIMITS = {", "\n};"),
  grab("const getDeckLimit = (productName) =>", ";\n"),
  grab("const cardFamilyKey = (name) =>", ".toLowerCase();"),
  grab("const SPECIAL_LIMIT_UI_CAP = ", ";\n"),
  grab("const getDeckLimitForUI = (productName) => {", "\n};"),
  grab("const DECK_SECTIONS = [", "\n];"),
  // The Coconut table is large and carries art helpers; two leaders stand in.
  `const COCONUT_CARDS = [
     {slug: "moana-curious-explorer", name: "Moana", version: "Curious Explorer"},
     {slug: "robin-hood-sharpshooter", name: "Robin Hood", version: "Sharpshooter"},
   ];
   const COCONUT_BY_SLUG = Object.fromEntries(COCONUT_CARDS.map(c => [c.slug, c]));`,
  grab("const getCoconutCard = (slug) =>", ";\n"),
  grab("const coconutDisplayName = (c) =>", ";\n"),
  grab("function deckToText(deck, cardById){", "\n}"),
  grab("function parseDeckText(text, raw){", "\n}"),
];
const mod = new Function(parts.join("\n\n") + "\nreturn {deckToText, parseDeckText};")();
const { deckToText, parseDeckText } = mod;

let pass = 0, fail = 0;
const ok = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + "\n        got  " + g + "\n        want " + w); }
};

// A small catalog in the shape transformSupabaseData emits.
const rows = [
  {card_id: "elsa",     "Product Name": "Elsa - Snow Queen",       Set: "The First Chapter",     Number: "42",  Rarity: "Rare",      card_type: "Character", cost: 6},
  {card_id: "elsa-en",  "Product Name": "Elsa - Snow Queen",       Set: "The First Chapter",     Number: "207", Rarity: "Enchanted", card_type: "Character", cost: 6},
  {card_id: "teka",     "Product Name": "Te Kā - The Burning One", Set: "Rise of the Floodborn", Number: "12",  Rarity: "Legendary", card_type: "Character", cost: 7},
  {card_id: "tipo",     "Product Name": "Tipo - Growing Son",      Set: "The First Chapter",     Number: "100", Rarity: "Common",    card_type: "Character", cost: 2},
  {card_id: "sing",     "Product Name": "A Whole New World",       Set: "The First Chapter",     Number: "195", Rarity: "Super Rare", card_type: "Action - Song", cost: 5},
  {card_id: "microbot", "Product Name": "Microbots",               Set: "Rise of the Floodborn", Number: "30",  Rarity: "Common",    card_type: "Character", cost: 1},
];
const cardById = {};
for (const r of rows) (cardById[r.card_id] = cardById[r.card_id] || []).push(r);

console.log("== export ==");
const deck = {coconut_card: "moana-curious-explorer", cards: [
  {card_id: "elsa", quantity: 2}, {card_id: "elsa-en", quantity: 2},
  {card_id: "sing", quantity: 3}, {card_id: "tipo", quantity: 4},
  {card_id: "gone", quantity: 1},
]};
const text = deckToText(deck, cardById);
const lines = text.split("\n");
ok("leader is the first line", lines[0], "// Coconut leader: Moana - Curious Explorer");
ok("two printings of one card are one line", lines.filter(l => /Elsa - Snow Queen$/.test(l)), ["4 Elsa - Snow Queen"]);
// Discord renders a line starting "# " as a heading and a blank line as a gap,
// which turned a pasted 16-card list into a screenful of big type.
ok("no line is a markdown heading", lines.filter(l => /^#/.test(l)), []);
ok("no blank lines", lines.filter(l => !l.trim()), []);
ok("every line is a card or a // comment", lines.filter(l => !/^\d+ \S/.test(l) && !l.startsWith("// ")), []);
ok("still grouped by type: characters, then songs", lines.filter(l => /^\d/.test(l)),
   ["4 Tipo - Growing Son", "4 Elsa - Snow Queen", "3 A Whole New World"]);
ok("a card missing from the catalog is a comment", lines.includes("// 1 × gone (not in the catalog)"), true);
ok("no raw card_id is ever a card line", lines.some(l => /^\d+ gone$/.test(l)), false);
ok("a 0-quantity row is not exported", deckToText({cards: [{card_id: "tipo", quantity: 0}]}, cardById), "");

console.log("\n== round trip ==");
const back = parseDeckText(text, rows);
ok("leader reads back", back.coconut, "moana-curious-explorer");
ok("every card reads back", back.entries.map(e => e.card_id + ":" + e.quantity).sort(),
   ["elsa:4", "sing:3", "tipo:4"]);
ok("the missing-card comment is not an unmatched line", back.unmatched, []);
ok("a leader named by slug also reads", parseDeckText("// coconut: robin-hood-sharpshooter", rows).coconut, "robin-hood-sharpshooter");
ok("an unknown leader is ignored, not guessed", parseDeckText("# Coconut leader: Nobody - At All", rows).coconut, null);
ok("an ordinary section header is not a leader", parseDeckText("# Coconut\n4 Tipo - Growing Son", rows).coconut, null);
// Lists copied before 2026-09-29 carry "# Characters" headers and a "#" leader.
const legacy = parseDeckText("# Coconut leader: Moana - Curious Explorer\n\n# Characters\n4 Tipo - Growing Son\n\n# Songs\n3 A Whole New World\n", rows);
ok("an old #-headed list still imports", legacy.entries.map(e => e.card_id + ":" + e.quantity).sort(), ["sing:3", "tipo:4"]);
ok("...with its leader", legacy.coconut, "moana-curious-explorer");
ok("...and no header lines left over", legacy.unmatched, []);

console.log("\n== import ==");
ok("accents fold", parseDeckText("2 Te Ka - The Burning One", rows).entries, [{card_id: "teka", quantity: 2}]);
ok("a bare name prefers the base printing", parseDeckText("4 Elsa - Snow Queen", rows).entries, [{card_id: "elsa", quantity: 4}]);
ok("(set-cn) of a printing OF the named card wins", parseDeckText("2 Elsa - Snow Queen (1-207)", rows).entries,
   [{card_id: "elsa-en", quantity: 2}]);
ok("(set-cn) with the version left off still wins", parseDeckText("2 Elsa (1-207)", rows).entries,
   [{card_id: "elsa-en", quantity: 2}]);
const clash = parseDeckText("3 Tipo - Growing Son (1-42)", rows);
ok("(set-cn) naming a DIFFERENT card loses to the name", clash.entries, [{card_id: "tipo", quantity: 3}]);
ok("...and is reported", clash.mismatched, ["3 Tipo - Growing Son (1-42)"]);
ok("(set-cn) is trusted when the name matches nothing", parseDeckText("1 Snow Queen Elsa (1-42)", rows).entries,
   [{card_id: "elsa", quantity: 1}]);
const over = parseDeckText("5 Tipo - Growing Son\n2 Tipo - Growing Son", rows);
ok("over the limit is trimmed", over.entries, [{card_id: "tipo", quantity: 4}]);
ok("...and reported once, with the asked total", over.trimmed, ["7× Tipo - Growing Son → 4"]);
ok("a card whose text lifts the cap is not trimmed", parseDeckText("12 Microbots", rows).entries,
   [{card_id: "microbot", quantity: 12}]);

console.log(`\n${pass} passed, ${fail} failed`);
if (fail) process.exit(1);
