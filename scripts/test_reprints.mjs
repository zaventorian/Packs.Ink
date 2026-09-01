// test_reprints.mjs — guards the card-detail "is this a reprint?" verdict.
//
//     node scripts/test_reprints.mjs
//
// Why this needs a guard: the verdict is a claim about facts ("this came out
// first"), it is stated in eight words on the busiest surface in the app, and
// every way it can be wrong is silent. The three rules doing the work all look
// like details you could tidy away:
//
//   1. Ordering comes from sets.released_at, NOT SET_ORDER (browse order, which
//      sorts Extras and every promo set above The First Chapter).
//   2. Promo sets are dated to the wave they opened, so Promo Set 1 TIES with
//      The First Chapter. Mainline wins that tie — the promo is a promo OF the
//      booster card. Drop the tiebreak and every set-1 promo reads as an equal
//      "alt printing" of the card it reprints.
//   3. A set's own prerelease promos (SET_PARENT) are the same release, so
//      AotV Promos must not make an Attack of the Vine! card "a reprint".
//   4. A REPRINT IS A SECOND BOOSTER PRINTING AND ONLY THAT. A promo is a
//      variant you may play in place of the original, not a new release of the
//      card — so it can never make a card "a reprint" or "the original", and it
//      does not put a rotated card back in Core. On the live catalog this was
//      the difference between 315 names and 177.
//
// Reads the real code out of Index.html rather than restating it, so it cannot
// drift from what ships. Run after touching setSetReleaseDates,
// cardPrintingsFor, reprintVerdict, MAINLINE_SETS, or SET_PARENT.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const mainline = grab("const MAINLINE_SETS = [", "\n];");
const parents  = grab("const SET_PARENT = {", "\n};");
const display  = grab("const SET_DISPLAY_NAMES = {", "\n};");
const maps     = grab("let _setReleaseById = new Map();", "_setMainlineById = main;\n};");
const fromRows = grab("const printingsFromRows = (rows) => {", "\n};");
const printFn  = grab("const cardPrintingsFor = (catalog, productName) => {", "\n};");
const spansFn  = grab("const spansTwoReleases = (printings) =>", ";");
const spansMain = grab("const spansTwoMainlineReleases = (printings) =>", ";");
const deckFn   = grab("const deckReprintNotes = (catalog, deckCards, cardById) => {", "\n};");
const verdictFn = grab("const reprintVerdict = (printings, curSetId) => {", "\n};");

const { setSetReleaseDates, cardPrintingsFor, reprintVerdict, deckReprintNotes } =
  await import("data:text/javascript," + encodeURIComponent(
    [mainline, parents, display, maps, fromRows, printFn, spansFn, spansMain, deckFn, verdictFn,
     "export {setSetReleaseDates, cardPrintingsFor, reprintVerdict, deckReprintNotes};"].join("\n")));

// The real sets table, trimmed to the rows these cases exercise. Dates are the
// live released_at values — note the three deliberate ties.
setSetReleaseDates([
  {id: "s_tfc",     name: "The First Chapter",        released_at: "2023-08-18"},
  {id: "s_promo1",  name: "Promo Set 1",              released_at: "2023-08-18"},
  {id: "s_rotf",    name: "Rise of the Floodborn",    released_at: "2023-11-17"},
  {id: "s_c1",      name: "Challenge Promo",          released_at: "2024-05-17"},
  {id: "s_fabled",  name: "Fabled",                   released_at: "2025-08-29"},
  {id: "s_witw",    name: "Whispers in the Well",     released_at: "2025-11-07"},
  {id: "s_epcot",   name: "EPCOT Festival of the Arts", released_at: "2026-01-16"},
  {id: "s_c2",      name: "Lorcana Challenge Year 3", released_at: "2026-01-16"},
  {id: "s_aotv",    name: "Attack of the Vine!",      released_at: "2026-07-17"},
  {id: "s_aotvp",   name: "Attack of the Vine! Promos", released_at: "2026-07-17"},
]);

let pass = 0, fail = 0;
const ok = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + "\n        got  " + g + "\n        want " + w); }
};

// row(set_id, setLabel, card_id, extra) — the shape transformSupabaseData emits.
const row = (set_id, set, card_id, extra = {}) => ({
  set_id, Set: set, card_id, "Product Name": "Card", Rarity: "Common",
  Number: "1", "Low Price": 1, ...extra,
});
const verdictFor = (rows, setId) => {
  const v = reprintVerdict(cardPrintingsFor(rows, "Card"), setId);
  return v && [v.kind, v.text];
};

// ── 1. The plain case, both directions ───────────────────────────────
{
  const rows = [row("s_rotf", "Rise of the Floodborn", "a"), row("s_fabled", "Fabled", "b")];
  ok("the later printing is the reprint", verdictFor(rows, "s_fabled"),
     ["reprint", "First printed in Rise of the Floodborn"]);
  ok("the earlier printing is the original", verdictFor(rows, "s_rotf"),
     ["original", "Reprinted in Fabled"]);
}

// ── 2. Release date decides, not catalog/SET_ORDER position ──────────
{
  // Fabled first in the array, and above every promo set in SET_ORDER.
  const rows = [row("s_fabled", "Fabled", "b"), row("s_tfc", "The First Chapter", "a")];
  ok("order comes from the release date, not the row order", verdictFor(rows, "s_fabled"),
     ["reprint", "First printed in The First Chapter"]);
  ok("...and the list is sorted oldest-first",
     cardPrintingsFor(rows, "Card").map(e => e.set),
     ["The First Chapter", "Fabled"]);
}

// ── 3. A promo of a booster card is a PROMO, not a reprint ───────────
{
  const rows = [row("s_tfc", "The First Chapter", "a"), row("s_promo1", "Promo Set 1", "b")];
  ok("a promo is a promo, never a reprint", verdictFor(rows, "s_promo1"),
     ["promo", "Promo of the The First Chapter card"]);
  ok("...and the booster card is not 'the original' because of it", verdictFor(rows, "s_tfc"),
     ["promo", "Also printed as a promo in Promo Set 1"]);
}

// ── 4. A set's own prerelease promos are not a reprint of it ─────────
{
  const rows = [row("s_aotv", "Attack of the Vine!", "a"),
                row("s_aotvp", "Attack of the Vine! Promos", "b")];
  ok("SET_PARENT folds the promo onto its parent set", verdictFor(rows, "s_aotv"), null);
  ok("...from the promo's side too", verdictFor(rows, "s_aotvp"), null);
}

// ── 5. Two printings in ONE set is not a reprint ─────────────────────
{
  const rows = [row("s_witw", "Whispers in the Well", "a"),
                row("s_witw", "Whispers in the Well", "b", {Rarity: "Enchanted", Number: "220"})];
  ok("base + Enchanted in one set: no verdict", verdictFor(rows, "s_witw"), null);
  ok("...but both still list, so the Enchanted is reachable",
     cardPrintingsFor(rows, "Card").map(e => e.rarity), ["Common", "Enchanted"]);
}

// ── 6. A genuine tie stays a tie ─────────────────────────────────────
{
  // EPCOT and C2 both released 2026-01-16 and neither is mainline.
  const rows = [row("s_epcot", "EPCOT Festival of the Arts", "a"),
                row("s_c2", "Lorcana Challenge Promo (C2)", "b")];
  ok("neither promo set is claimed as the original", verdictFor(rows, "s_epcot"),
     ["promo", "Also printed in Lorcana Challenge Promo (C2)"]);
}

// ── 7. Reprinted more than once ──────────────────────────────────────
{
  const rows = [row("s_tfc", "The First Chapter", "a"),
                row("s_c1", "Lorcana Challenge Promo (C1)", "b"),
                row("s_witw", "Whispers in the Well", "c"),
                row("s_c2", "Lorcana Challenge Promo (C2)", "d")];
  ok("the original names later BOOSTER sets only — promos are not reprints",
     verdictFor(rows, "s_tfc"), ["original", "Reprinted in Whispers in the Well"]);
  ok("the booster reprint names the first booster print, skipping the promo between",
     verdictFor(rows, "s_witw"), ["reprint", "First printed in The First Chapter"]);
  ok("standing on a promo of a reprinted card still reads as a promo",
     verdictFor(rows, "s_c2"), ["promo", "Promo of the The First Chapter card"]);
}

// ── 8. Extras rows carry their origin set, so they can't fake one ────
{
  const rows = [row("s_witw", "Whispers in the Well", "a"),
                row("s_witw", "Extras & Oddities", "extras:9", {variant_label: "Deep Trouble"})];
  ok("an Extras entry is not a second set", verdictFor(rows, "s_witw"), null);
  ok("...but it still lists, under its own label",
     cardPrintingsFor(rows, "Card").map(e => e.set),
     ["Whispers in the Well", "Extras & Oddities"]);
}

// ── 9. Degenerate inputs must not throw or invent a verdict ──────────
{
  ok("no catalog", cardPrintingsFor(null, "Card"), []);
  ok("no name", cardPrintingsFor([row("s_tfc", "The First Chapter", "a")], ""), []);
  ok("single printing", verdictFor([row("s_tfc", "The First Chapter", "a")], "s_tfc"), null);
  ok("a set we have no date for still lists",
     cardPrintingsFor([row("s_tfc", "The First Chapter", "a"),
                       row("s_unknown", "Some New Set", "b")], "Card").length, 2);
  // Coconut leaders are synthetic rows that must never enter the list.
  ok("coconut rows are skipped",
     cardPrintingsFor([row("s_tfc", "The First Chapter", "a"),
                       row("s_c2", "Format Coconut", "b", {isCoconut: true})], "Card").length, 1);
}

// ── 10. The cheapest printing is what a row quotes ───────────────────
{
  const rows = [row("s_tfc", "The First Chapter", "a", {"Low Price": 12, tcg_printing: "Normal"}),
                row("s_tfc", "The First Chapter", "a", {"Low Price": 3, tcg_printing: "Cold Foil"})];
  ok("normal + foil collapse to one entry at the lower price",
     cardPrintingsFor(rows, "Card").map(e => [e.card_id, e.price]), [["a", 3]]);
}

// ── 11. The deck footnote: which cards here exist in more than one set ──
//
// Same three rules as the verdict, applied per deck card. What makes this
// worth guarding separately: it takes its names from `cardById` (deck rows
// carry card_ids, not names), and both failure modes are silent — a deck that
// lists nothing looks like a deck with no reprints, and one that lists a card
// printed once sends the player hunting through a binder for a set that
// doesn't exist.
{
  const named = (set_id, set, card_id, name, extra = {}) =>
    ({...row(set_id, set, card_id, extra), "Product Name": name});
  const catalog = [
    named("s_tfc",    "The First Chapter",     "elsa_tfc",   "Elsa"),
    named("s_fabled", "Fabled",                "elsa_fab",   "Elsa"),
    named("s_witw",   "Whispers in the Well",  "belle_witw", "Belle"),
    named("s_witw",   "Whispers in the Well",  "belle_ench", "Belle", {Rarity: "Enchanted", Number: "220"}),
    named("s_aotv",   "Attack of the Vine!",   "stitch_a",   "Stitch"),
    named("s_aotvp",  "Attack of the Vine! Promos", "stitch_p", "Stitch"),
    named("s_tfc",    "The First Chapter",     "ariel_tfc",  "Ariel"),
    named("s_promo1", "Promo Set 1",           "ariel_promo","Ariel"),
  ];
  const cardById = {};
  for (const r of catalog) (cardById[r.card_id] ||= []).push(r);
  const notes = (cards) => deckReprintNotes(catalog, cards, cardById)
    .map(n => [n.name, n.printings.map(p => p.set + (p.inDeck ? "*" : ""))]);

  ok("a reprinted card lists every set, marking the one the deck uses",
     notes([{card_id: "elsa_fab", quantity: 4}]),
     [["Elsa", ["The First Chapter", "Fabled*"]]]);
  ok("...and from the original's side the mark moves, not the list",
     notes([{card_id: "elsa_tfc", quantity: 4}]),
     [["Elsa", ["The First Chapter*", "Fabled"]]]);
  ok("base + Enchanted in one set is not a reprint, so Belle stays out",
     notes([{card_id: "belle_witw", quantity: 4}]), []);
  ok("a set's own prerelease promo is not a reprint either",
     notes([{card_id: "stitch_a", quantity: 4}]), []);
  ok("a deck holding BOTH printings marks both",
     notes([{card_id: "elsa_tfc", quantity: 2}, {card_id: "elsa_fab", quantity: 2}]),
     [["Elsa", ["The First Chapter*", "Fabled*"]]]);
  ok("cards are listed alphabetically, reprinted ones only",
     deckReprintNotes(catalog,
       [{card_id: "elsa_fab", quantity: 4}, {card_id: "belle_witw", quantity: 4},
        {card_id: "stitch_a", quantity: 4}], cardById).map(n => n.name),
     ["Elsa"]);
  ok("a card with a PROMO second printing is not a reprint — the live case that "
     + "put 138 extra cards in this list (Ariel - Spectacular Singer, TFC + "
     + "Curator's Collection)",
     notes([{card_id: "ariel_tfc", quantity: 4}]), []);
  ok("...not from the promo's side either",
     notes([{card_id: "ariel_promo", quantity: 4}]), []);
  ok("an unknown card_id is skipped, not thrown on",
     notes([{card_id: "nope", quantity: 4}]), []);
  ok("empty deck", deckReprintNotes(catalog, [], cardById), []);
  ok("no catalog", deckReprintNotes(null, [{card_id: "elsa_fab", quantity: 4}], cardById), []);
}

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
