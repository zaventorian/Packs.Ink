// test_coconut_legality.mjs — exercises checkDeckLegality against the real
// [Format Coconut] rules, plus regression guards that Core/Infinity are
// unchanged.
//
// Run: node scripts/test_coconut_legality.mjs
//
// There is no build step, so rather than importing we slice the module-scope
// declarations out of Index.html and eval them. That means renaming any of
// the sliced declarations breaks this test loudly (by design) — the slice
// markers are the contract.
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const SRC = fs.readFileSync(path.join(ROOT, "Index.html"), "utf8");

function slice(startRe, endRe, label){
  const s = SRC.search(startRe);
  if(s < 0) throw new Error(`start not found: ${label}`);
  const rest = SRC.slice(s);
  const e = rest.search(endRe);
  if(e < 0) throw new Error(`end not found: ${label}`);
  return rest.slice(0, e + rest.match(endRe)[0].length);
}

const parts = [
  `const SUPABASE_URL = "https://stub.invalid";`,
  slice(/^const SET_PARENT = \{/m, /^\};/m, "SET_PARENT"),
  slice(/^const MAINLINE_SETS = \[/m, /^\];/m, "MAINLINE_SETS"),
  slice(/^const SPECIAL_DECK_LIMITS = \{/m, /^const getFormat = .*$/m, "formats+coconut"),
  slice(/^function checkDeckLegality\(/m, /^\}/m, "checkDeckLegality"),
];

const mod = new Function(parts.join("\n\n") + `
  return {checkDeckLegality, COCONUT_CARDS, coconutDeckLimit, getCoconutCard,
          COCONUT_INK_LIMIT, computeCoreSets, getDeckLimit};
`)();

const {checkDeckLegality, COCONUT_CARDS, coconutDeckLimit, getCoconutCard} = mod;

// ── fixtures ──────────────────────────────────────────────────────────
// Minimal catalog rows keyed the way checkDeckLegality reads them.
const catalog = {};
const setsByProductName = {};
let idc = 0;
function card(productName, ink, set = "Wilds Unknown"){
  const id = `c${++idc}`;
  catalog[id] = [{"Product Name": productName, ink, inks: null, Set: set}];
  (setsByProductName[productName] ||= new Set()).add(set);
  return id;
}
// A distinct 1-of filler generator so decks reach 60 legally.
function filler(n, ink, set = "Wilds Unknown"){
  return Array.from({length: n}, (_, i) => ({card_id: card(`Filler ${ink} ${i} ${set}`, ink, set), quantity: 1}));
}

let pass = 0, fail = 0;
function check(label, got, want){
  const ok = JSON.stringify(got) === JSON.stringify(want);
  console.log(`${ok ? "  ok  " : "  FAIL"} ${label}`);
  if(!ok){ console.log(`        got  ${JSON.stringify(got)}`); console.log(`        want ${JSON.stringify(want)}`); fail++; }
  else pass++;
}

console.log("\n== data integrity ==");
check("18 Coconut cards", COCONUT_CARDS.length, 18);
check("3 per ink", [...new Set(COCONUT_CARDS.map(c=>c.ink))].sort().map(
  i => COCONUT_CARDS.filter(c=>c.ink===i).length), [3,3,3,3,3,3]);
check("slugs unique", new Set(COCONUT_CARDS.map(c=>c.slug)).size, 18);
check("collector numbers 1..18", COCONUT_CARDS.map(c=>c.cn).sort((a,b)=>a-b),
  Array.from({length:18},(_,i)=>i+1));
check("every associated name is '<name> - <version>'",
  COCONUT_CARDS.every(c => c.associated === `${c.name} - ${c.version}`), true);

console.log("\n== copy limits ==");
const nick = getCoconutCard("nick-wilde-wily-fox");
const moana = getCoconutCard("moana-curious-explorer");
check("leader card gets 4", coconutDeckLimit(moana, "Moana - Curious Explorer"), 4);
check("anything else gets 1", coconutDeckLimit(moana, "Pawpsicle"), 1);
check("Nick Wilde grants Pawpsicle 4", coconutDeckLimit(nick, "Pawpsicle"), 4);
check("Nick Wilde still 1-of others", coconutDeckLimit(nick, "Moana - Curious Explorer"), 1);
check("no leader falls back to normal 4", coconutDeckLimit(null, "Whatever - Thing"), 4);
check("no leader honours SPECIAL_DECK_LIMITS", coconutDeckLimit(null, "Microbots"), Infinity);
// Ruling: a card whose OWN text bypasses the 4-copy cap also beats Coconut's
// 1-of default. Card text > format default.
check("Microbots stays unlimited under Coconut", coconutDeckLimit(moana, "Microbots"), Infinity);
check("Dalmatian Puppy stays 99 under Coconut",
  coconutDeckLimit(moana, "Dalmatian Puppy - Tail Wagger"), 99);
check("leader still outranks nothing it collides with",
  coconutDeckLimit(moana, "Moana - Curious Explorer"), 4);

console.log("\n== coconut deck validation ==");
// Legal: 4x Moana leader + 56 distinct Sapphire 1-ofs = 60.
const moanaId = card("Moana - Curious Explorer", "Sapphire");
const legal = {coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:4}, ...filler(56, "Sapphire")]};
let r = checkDeckLegality(legal, catalog, setsByProductName);
check("legal coconut deck -> format coconut", r.format, "coconut");
check("legal coconut deck -> no issues", r.issues, []);
check("result exposes the leader", r.coconut?.slug, "moana-curious-explorer");

check("legal coconut deck -> legal flag", r.legal, true);

// WARN-ONLY is deliberate (see checkDeckLegality): a rule-breaking Coconut deck
// keeps format "coconut" and reports issues, rather than collapsing to
// "invalid". People build lists with placeholders for cards that aren't in the
// catalog yet, and those decks must keep the leader showcase + poster.
console.log("\n== warn-only, not blocked ==");
const dupId = card("Some Rare - Thing", "Sapphire");
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:4}, {card_id:dupId, quantity:2}, ...filler(54,"Sapphire")]},
  catalog, setsByProductName);
check("2-of a non-leader still reads coconut", r.format, "coconut");
check("...but is flagged not-legal", r.legal, false);
check("...and says limit is 1", r.issues.some(s=>/limit is 1$/.test(s)), true);

// 5 of the leader exceeds its own allowance.
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:5}, ...filler(55,"Sapphire")]}, catalog, setsByProductName);
check("5-of the leader warns", r.issues.some(s=>/limit is 4$/.test(s)), true);
check("...and keeps the format", r.format, "coconut");

// 3 inks legal when one matches the leader.
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:4}, ...filler(20,"Sapphire"), ...filler(18,"Amber"), ...filler(18,"Steel")]},
  catalog, setsByProductName);
check("3 inks incl. leader ink is legal", r.format, "coconut");

// 4 inks illegal.
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:4}, ...filler(14,"Sapphire"), ...filler(14,"Amber"),
         ...filler(14,"Steel"), ...filler(14,"Ruby")]}, catalog, setsByProductName);
check("4 inks illegal", r.issues.some(s=>/limit is 3$/.test(s)), true);

// 3 inks but none is the leader's ink.
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[...filler(20,"Amber"), ...filler(20,"Steel"), ...filler(20,"Ruby")]},
  catalog, setsByProductName);
check("missing leader ink flagged", r.issues.some(s=>/No Sapphire cards/.test(s)), true);

// Empty deck should NOT nag about the leader ink.
r = checkDeckLegality({coconut_card:"moana-curious-explorer", cards:[]}, catalog, setsByProductName);
check("empty deck: only the 60-card issue", r.issues, ["0 / 60 cards — need 60 more"]);

// Nick Wilde's Pawpsicle exception end-to-end.
const nickId = card("Nick Wilde - Wily Fox", "Sapphire");
const pawpId = card("Pawpsicle", "Sapphire");
r = checkDeckLegality({coconut_card:"nick-wilde-wily-fox",
  cards:[{card_id:nickId, quantity:4}, {card_id:pawpId, quantity:4}, ...filler(52,"Sapphire")]},
  catalog, setsByProductName);
check("Nick Wilde + 4x Pawpsicle is legal", r.format, "coconut");
// Same 4x Pawpsicle under a different leader must warn.
r = checkDeckLegality({coconut_card:"moana-curious-explorer",
  cards:[{card_id:moanaId, quantity:4}, {card_id:pawpId, quantity:4}, ...filler(52,"Sapphire")]},
  catalog, setsByProductName);
check("4x Pawpsicle under Moana is flagged", r.legal, false);
check("...limit reported as 1", r.issues.some(s=>/4× Pawpsicle .* limit is 1$/.test(s)), true);

// Unknown slug must not silently become Infinity and re-permit 4-ofs.
r = checkDeckLegality({coconut_card:"not-a-real-leader",
  cards:[...filler(60,"Sapphire")]}, catalog, setsByProductName);
check("unknown slug stays coconut", r.format, "coconut");
check("unknown slug -> not legal", r.legal, false);
check("unknown slug -> named issue", r.issues.some(s=>/Unknown Coconut card/.test(s)), true);

console.log("\n== non-coconut decks unchanged ==");
const oldCard = card("Old Thing - Ancient", "Amber", "The First Chapter");
r = checkDeckLegality({cards:[{card_id:oldCard, quantity:4}, ...filler(56,"Amber","The First Chapter")]},
  catalog, setsByProductName);
check("4-of still legal without a leader", r.format, "infinity");
const newCard = card("New Thing - Fresh", "Amber", "Wilds Unknown");
r = checkDeckLegality({cards:[{card_id:newCard, quantity:4}, ...filler(56,"Amber","Wilds Unknown")]},
  catalog, setsByProductName);
check("modern deck still derives core", r.format, "core");
r = checkDeckLegality({cards:[...filler(20,"Amber"), ...filler(20,"Steel"), ...filler(20,"Ruby")]},
  catalog, setsByProductName);
check("3 inks still illegal without a leader", r.issues.some(s=>/limit is 2$/.test(s)), true);
check("no leader -> coconut is null", r.coconut, null);
// Core/Infinity keep collapsing to "invalid" — warn-only is scoped to the
// declared format, where the leader gives the deck an identity to preserve.
check("no leader -> broken deck still 'invalid'", r.format, "invalid");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
