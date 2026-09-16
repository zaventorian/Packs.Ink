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
          COCONUT_INK_LIMIT, computeCoreSets, getDeckLimit,
          coconutFreshCards, coconutRowId, COCONUT_REVEAL_NEWS_DAYS,
          COCONUT_REVEAL_MAX_THUMBS};
`)();

const {checkDeckLegality, COCONUT_CARDS, coconutDeckLimit, getCoconutCard,
       coconutFreshCards, coconutRowId, COCONUT_REVEAL_NEWS_DAYS,
       COCONUT_REVEAL_MAX_THUMBS} = mod;

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
// Cards land in waves during the beta, so the exact count is a tripwire: it
// fails on purpose when one is added, which is the prompt to check the rest of
// this block still describes the set. Beta 1 was 18, 3 per ink; Beta 2 opened
// with a 4th Steel leader, so the per-ink split is no longer even.
const COCONUT_INKS = ["Amber","Amethyst","Emerald","Ruby","Sapphire","Steel"];
check("19 Coconut cards", COCONUT_CARDS.length, 19);
// The durable half of the old "3 per ink" check. A typo'd ink ("Steal") would
// leave the card out of CoconutLeaderPicker entirely — it renders one group per
// canonical ink — and nothing else would notice.
check("every ink is canonical",
  [...new Set(COCONUT_CARDS.map(c=>c.ink))].sort(), [...COCONUT_INKS].sort());
check("every ink has a leader",
  COCONUT_INKS.every(i => COCONUT_CARDS.some(c => c.ink === i)), true);
check("per-ink counts", COCONUT_INKS.map(
  i => COCONUT_CARDS.filter(c=>c.ink===i).length), [3,3,3,3,3,4]);
check("slugs unique", new Set(COCONUT_CARDS.map(c=>c.slug)).size, 19);
check("collector numbers 1..19", COCONUT_CARDS.map(c=>c.cn).sort((a,b)=>a-b),
  Array.from({length:19},(_,i)=>i+1));
check("every associated name is '<name> - <version>'",
  COCONUT_CARDS.every(c => c.associated === `${c.name} - ${c.version}`), true);

// ── home news tile ────────────────────────────────────────────────────
// A reveal is announced on the home news feed for COCONUT_REVEAL_NEWS_DAYS.
// Every way this breaks is SILENT — the tile just stops appearing, or starts
// announcing a card nobody has seen — so both directions are pinned.
console.log("\n== reveal news window ==");
const DAY = 864e5;
const dated = COCONUT_CARDS.filter(c => c.revealed);
check("at least one card carries a reveal date", dated.length > 0, true);
check("every reveal date is a real ISO day",
  dated.every(c => /^\d{4}-\d{2}-\d{2}$/.test(c.revealed)
                && Number.isFinite(Date.parse(c.revealed + "T00:00:00Z"))), true);

const vine = getCoconutCard("the-vine-towering-stalk");
const vineAt = (offsetDays) =>
  coconutFreshCards(Date.parse(vine.revealed + "T00:00:00Z") + offsetDays * DAY)
    .map(c => c.slug);
check("fresh on its reveal day", vineAt(0).includes("the-vine-towering-stalk"), true);
check("still fresh just inside the window",
  vineAt(COCONUT_REVEAL_NEWS_DAYS - 1).includes("the-vine-towering-stalk"), true);
check("stale once the window passes",
  vineAt(COCONUT_REVEAL_NEWS_DAYS + 1).includes("the-vine-towering-stalk"), false);
// The guard against a typo'd year announcing a card nobody has seen.
check("a reveal in the future is not announced", vineAt(-1).includes("the-vine-towering-stalk"), false);
// Beta 1 shipped as one PDF with no reveal day, so it must never fire this.
check("undated Beta 1 cards never announce",
  coconutFreshCards(Date.parse("2026-01-01T00:00:00Z")).length, 0);
check("newest first",
  coconutFreshCards(Date.now()).every((c, i, a) => i === 0 || a[i-1].revealed >= c.revealed), true);

// The home tile checks the row reached `raw` by this id, and transformSupabaseData
// mints it. A drifted prefix fails silently, so one accessor builds both.
check("coconutRowId matches the documented shape",
  coconutRowId("the-vine-towering-stalk"), "coconut::the-vine-towering-stalk");
check("the catalog transform mints the id through it",
  /"card_id":\s*coconutRowId\(cc\.slug\)/.test(SRC), true);
// Exactly one occurrence: the accessor's own body. A second is a call site
// that went around it, which is the drift this guards.
check("nothing else builds the prefix by hand",
  (SRC.match(/`coconut::\$\{/g) || []).length, 1);
// "Dated things first": the reveal is news with an end date, the format notice
// is the standing one. Ordering is just push order, so nothing else catches a
// swap.
check("the reveal tile is pushed above the standing Format tile",
  SRC.indexOf('key="coconut-new"') < SRC.indexOf('key="coconut"')
  && SRC.indexOf('key="coconut-new"') > 0, true);

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

// ── the reveal tile's card art ────────────────────────────────────────
// The tile pictures the card it announces. Every failure here is SILENT —
// a broken-image icon in the feed, or art that loads on screen and then
// comes back blank on a canvas — so each one is pinned.
console.log("\n== reveal tile art ==");
const CSS = fs.readFileSync(path.join(ROOT, "styles.css"), "utf8");
const tile = SRC.slice(SRC.indexOf('key="coconut-new"'), SRC.indexOf('key="coconut"'));
check("the reveal tile pictures the card", /class="home-news-cards"/.test(tile), true);
// ⚠ The FULL card, not the 52px character crop it used to show (2026-09-15) —
// a reveal is about what the card looks like. The crop still exists and is
// still right for chips; it is just not what this tile is for.
check("it uses the full card render", /src=\$\{coconutArtUrl\(/.test(tile), true);
check("it caps how many it pictures",
  /slice\(0,\s*COCONUT_REVEAL_MAX_THUMBS\)/.test(tile), true);
check("the cap is a small number", COCONUT_REVEAL_MAX_THUMBS >= 1 && COCONUT_REVEAL_MAX_THUMBS <= 4, true);
// ⚠ The documented Chrome trap: a no-cors response for this URL is cached
// separately, and a later canvas-bound request for the SAME url reuses it and
// fails with naturalWidth 0. Every <img> on coconut art carries this, even the
// ones that never touch a canvas.
check("the art is requested with CORS", /crossOrigin="anonymous"/.test(tile), true);
// ⚠ A Beta 1.1 re-render rewrites the card's RULES TEXT at the same bucket
// path, and packsink-img-v1 survives deploys — so without the rev an existing
// visitor keeps the pre-rebalance wording forever. It was on the thumb (the
// crop least likely to change) and missing from the full card (the only one
// that shows the text), which is exactly backwards.
check("the full art carries the cache-bust rev",
  /const coconutArtUrl[\s\S]{0,240}?COCONUT_ART_REV\[cn\]/.test(SRC), true);
// Art is uploaded separately from the card entry, so "no photo yet" is a real
// steady state that recurs with every weekly Beta card. ⚠ It is the BUTTON that
// hides, not the <img>: hiding the image alone leaves an empty bordered box
// that is still a click target.
check("a missing render hides its whole button",
  /closest\("button"\)[\s\S]{0,40}hidden\s*=\s*true/.test(tile), true);
check("[hidden] beats the card's own display:block",
  /\.home-news-card\[hidden\]\{display:none;?\}/.test(CSS), true);
check("the row collapses when every render failed",
  /\.home-news-cards:not\(:has\(\.home-news-card:not\(\[hidden\]\)\)\)\{display:none;?\}/.test(CSS), true);
// ⚠ The floor is what keeps this honest. Below ~96px a grayscale beta render
// stops reading as a card at all — the reason the 52px thumbs existed — so
// three reveals in one window must WRAP, never shrink to share a row.
check("the card has a min-width floor", /\.home-news-card\{[^}]*min-width:96px/.test(CSS), true);
check("and the row wraps rather than squeezing",
  /\.home-news-cards\{[^}]*flex-wrap:wrap/.test(CSS), true);

// Two click targets, and BOTH land on the Coconut-filtered Cards page with the
// card open (Zaven, 2026-09-15). The art used to call openCardsWithSearch, which
// opens the card against the UNFILTERED catalog - so a click from a tile headed
// "New Coconut card" dropped you on the whole 5,900-row browse with one card
// open and the format you came for nowhere in sight. Pinned in both directions:
// the art must reach the filtered page, and it must not go back to the
// unfiltered one, which is the half that fails silently.
check("the art opens that card on the Coconut page",
  /openCardsFilteredBySet\(COCONUT_SET_NAME,\s*coconutRowId\(c\.slug\)\)/.test(tile), true);
check("the art does not open the unfiltered catalog",
  /openCardsWithSearch\(/.test(tile), false);
check("the title opens the set with the card already open",
  /openCardsFilteredBySet\(COCONUT_SET_NAME,\s*coconutRowId\(/.test(tile), true);
// ⚠ A nested button's stopPropagation does NOT cancel the anchor's own default
// navigation — without navCapture, clicking the art ALSO navigates the tile.
check("the tile guards its nested button", /onClickCapture=\$\{navCapture\}/.test(tile), true);
// ⚠ And the Cards view has to be able to open a card with no pid, or both of
// the above land on the tab with nothing open. Every Coconut row has none.
check("a pid-less card can be grouped for the modal",
  /row\.tcgplayer_product_id[\s\S]{0,120}groupCards\(\[row\]\)/.test(SRC), true);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
