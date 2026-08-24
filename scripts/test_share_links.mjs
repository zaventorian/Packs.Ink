// test_share_links.mjs — guards the "copy link to this page" helpers.
//
//     node scripts/test_share_links.mjs
//
// Extracts the real functions out of Index.html rather than restating them, so
// they can't drift from what ships.
//
// Both failure modes here are silent. collectionSectionHref dropping the share
// token produces a link that looks fine and dead-ends on "this collection is
// private" for whoever you sent it to — and you would never see it yourself,
// because you are the owner. shareUrlLabel has a priority order over eight
// params, and every new deep-link param is a chance for a page to start
// claiming it copied something it did not; that label is the only confirmation
// the user gets that the button caught the right thing.
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

// One whole line beginning with `prefix` — for the single-line const tables.
function grabLine(prefix) {
  const line = src.split(/\r?\n/).find((l) => l.startsWith(prefix));
  if (!line) throw new Error("missing line: " + prefix);
  return line;
}

// HOME_PANELS is the source for the panel labels; grab the array and rebuild
// the map the same way Index.html does, so a renamed panel shows up here.
const homePanels = grab("const HOME_PANELS = [", NL + "];");
const homePanelLabels = grabLine("const HOME_PANEL_LABELS = ");
const homePanelKeys = grabLine("const HOME_PANEL_KEYS = ");
const homePopoutKeys = grabLine("const HOME_POPOUT_KEYS = ");
const labels = grab(
  "const VIEW_SHARE_LABELS = {",
  'swiss: "Swiss Odds", dice: "Dice Tray", elo: "Elo",' + NL + "};",
);
const hrefFn = grab("const collectionSectionHref = (key, viewerContext) => {", NL + "};");
const labelFn = grab("const shareUrlLabel = () => {", NL + "};");
const sections = grabLine("const COLLECTION_SECTIONS = ");
const sectionLabels = grabLine("const COLLECTION_SECTION_LABELS = ");

// shareUrlLabel reads window.location + PATH_TO_VIEW; stub both so the real
// body runs unchanged.
const PATH_TO_VIEW = {
  "/": "home", "/screener": "screener", "/price-graphing": "history",
  "/analytics": "market", "/cards": "cards", "/collection": "collection",
  "/decks": "decks", "/how-it-works": "faq", "/elo": "elo",
};

const moduleSrc = [
  "const PATH_TO_VIEW = " + JSON.stringify(PATH_TO_VIEW) + ";",
  sections,
  sectionLabels,
  labels,
  homePanels,
  homePanelKeys,
  homePanelLabels,
  homePopoutKeys,
  hrefFn,
  labelFn,
  "export {collectionSectionHref, shareUrlLabel, COLLECTION_SECTIONS, HOME_PANEL_LABELS, HOME_POPOUT_KEYS};",
].join(NL);

const mod = await import("data:text/javascript," + encodeURIComponent(moduleSrc));
const { collectionSectionHref, shareUrlLabel } = mod;

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(
    (ok ? "PASS  " : "FAIL  ") + name +
    (ok ? "" : "  (got " + JSON.stringify(got) + ", want " + JSON.stringify(want) + ")"),
  );
};

// ── collectionSectionHref ────────────────────────────────────────────────
check("own collection, default section carries no param",
  collectionSectionHref("cards", null), "/collection");
check("own collection, sealed", collectionSectionHref("sealed", null), "/collection?c=sealed");
check("own collection, graded", collectionSectionHref("graded", null), "/collection?c=graded");

const viewer = { ownerId: "abc-123", ownerToken: "tok_xyz" };
check("viewer mode keeps owner + token on the default section",
  collectionSectionHref("cards", viewer), "/collection?collection=abc-123&token=tok_xyz");
check("viewer mode keeps owner + token alongside the section",
  collectionSectionHref("graded", viewer),
  "/collection?collection=abc-123&token=tok_xyz&c=graded");
check("a public collection (no token) omits it",
  collectionSectionHref("sealed", { ownerId: "abc-123" }),
  "/collection?collection=abc-123&c=sealed");

// ── shareUrlLabel ────────────────────────────────────────────────────────
const at = (path, search = "") => {
  globalThis.window = { location: { href: "https://packs.ink" + path + search } };
  return shareUrlLabel();
};

check("home", at("/"), "the home page");
check("cards", at("/cards", "?q=elsa"), "Cards");
check("how it works", at("/how-it-works"), "How it works");

check("decks section", at("/decks", "?s=tournaments"), "Decks · Tournaments");
check("decks default section has no suffix", at("/decks"), "Decks");
check("collection section", at("/collection", "?c=graded"), "your Collection · Graded");
check("screener mode", at("/screener", "?m=sealed"), "the Screener · Sealed");
check("analytics sub-tool", at("/analytics", "?a=swiss"), "Analytics · Swiss Odds");

// A leaf page owns the label even though the section param behind it is still
// in the URL — you opened a deck, so the link is to the deck, not to the tab.
check("an open deck beats the section", at("/decks", "?s=discover&deck=d1"), "this deck");
check("an open tournament beats the section", at("/decks", "?s=discover&tourney=t1"), "this tournament");
check("a creator profile", at("/decks", "?user=u1"), "this creator");
check("a viewed collection", at("/collection", "?collection=u1&c=graded"), "this collection");
check("an open card", at("/cards", "?q=elsa&card=crd_1"), "this card");
check("a shared trade", at("/analytics", "?a=trade&t=abc"), "this trade");
check("a set page names the set", at("/collection", "?set=Fabled"), "Fabled");

// Unknown / unmapped input must not throw, and must not echo itself back as if
// it were a real place.
check("an unmapped path", at("/lab/whatever"), "this page");
check("a bogus section value is ignored", at("/decks", "?s=nonsense"), "Decks");
check("a bogus analytics tool is ignored", at("/analytics", "?a=nonsense"), "Analytics");

// Every section the app can actually be in needs a label — a missing one
// silently degrades to the bare view name, which reads as a bug in the toast.
const EXPECTED = { cards: "Cards", sealed: "Sealed", graded: "Graded" };
for (const k of mod.COLLECTION_SECTIONS) {
  check('collection section "' + k + '" has a label',
    at("/collection", "?c=" + k), "your Collection · " + EXPECTED[k]);
}

// ── ?panel= (a popped-out home section) ──────────────────────────────────
// The pop-out is the only way to link to one box on the home page, and the
// toast is the only confirmation that the right one got copied. A panel key
// with no label would silently degrade to "the home page" — the label of the
// thing you were trying NOT to send.
for(const [key, label] of Object.entries(mod.HOME_PANEL_LABELS)){
  // setChamps is in the label map but has no ?panel= view — Upcoming events
  // expands on its own and carries richer deep links. Labelling it would
  // promise a link that opens nothing, so it must fall through.
  const popsOut = mod.HOME_POPOUT_KEYS.has(key);
  check('panel "' + key + (popsOut ? '" names itself' : '" has no pop-out, so no label'),
    at("/", "?panel=" + key), popsOut ? label : "the home page");
}
check("a bogus panel falls back to the page", at("/", "?panel=nonsense"), "the home page");
check("a panel param elsewhere does not hijack a leaf page",
  at("/decks", "?deck=d1&panel=news"), "this deck");

console.log(failed ? NL + failed + " FAILED" : NL + "all passed");
process.exit(failed ? 1 : 0);
