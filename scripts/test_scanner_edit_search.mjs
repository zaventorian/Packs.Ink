// test_scanner_edit_search.mjs — guards the scan review editor's search box.
//
//     node scripts/test_scanner_edit_search.mjs
//
// Extracts the REAL memo body out of Index.html and replays it over the
// shipped scanner index, so this is a measurement of what ships rather than a
// restatement of it.
//
// The failure this exists for is the one that shipped: the box matched the
// whole typed phrase against Product Name alone, so "heihei epic" — a name
// plus the rarity that tells the two Heiheis apart — answered "No card
// matches". That box is reached precisely BECAUSE the scanner picked the wrong
// card, and a sibling printing is the commonest miss, so the one query most
// worth typing was the one that returned nothing. It failed silently: an empty
// list looks exactly like a card that isn't in the catalog.
//
// It also pins the scan cap, because removing it is invisible in every way
// except frame time on a phone that is simultaneously running the camera and
// both scanner workers.
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

// The memo is a hook body, so it can't be imported as-is. Rewrite only its
// wrapper — `useMemo(() => {` becomes a function of the two things it closes
// over — and leave every statement inside untouched.
const memoSrc = grab("const qaEditMatches = useMemo(() => {", "}, [qaEditQd, qaSearchPool]);");
const memoBody = memoSrc
  .replace("const qaEditMatches = useMemo(() => {", "const qaEditMatches = (qaEditQd, qaSearchPool) => {")
  .replace(/}, \[qaEditQd, qaSearchPool\]\);$/, "};");
if (memoBody.includes("useMemo")) throw new Error("memo wrapper not rewritten");
if (!memoBody.includes("matchesCardFilter")) {
  throw new Error("the editor search no longer routes through matchesCardFilter");
}

const moduleSrc = [
  // Browser globals the extracted code touches.
  "const localStorage = { getItem(){ return null; }, setItem(){}, removeItem(){} };",
  // Dependencies that live above the search helpers.
  grabLine("const COCONUT_CARD_TYPE = "),
  grabLine("const EXTRAS_SET_NAME = "),
  grab("const MAINLINE_SETS = [", NL + "];"),
  grab("const SET_ORDER = [", NL + "];"),
  grab("const SET_PARENT = {", NL + "};"),
  grabLine("let _promoBaseSet"),
  grab("const cardParentSetForFilter = (row) => {", NL + "};"),
  grab("const normalizeRarity = r => {", NL + "};"),
  // The whole smart-search span: aliases, parseSearchQuery, matchesCardFilter.
  grab("const INK_COLORS = {", 'return items.filter(g => matchesCardFilter(g, f, {...parsed, nameMatchMode: "any"}));' + NL + "};"),
  grab("const emptyFilter = () => ({", NL + "});"),
  grabLine("const QA_EDIT_SCAN_CAP = "),
  memoBody,
  "export { qaEditMatches, parseSearchQuery, QA_EDIT_SCAN_CAP };",
].join(NL);

const { qaEditMatches, parseSearchQuery, QA_EDIT_SCAN_CAP } =
  await import("data:text/javascript," + encodeURIComponent(moduleSrc));

let failed = 0;
const check = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  const ok = g === w;
  if (!ok) failed++;
  console.log((ok ? "PASS  " : "FAIL  ") + name + (ok ? "" : "  (got " + g + ", want " + w + ")"));
};

// A catalog row, cut down to what the matcher reads. qaSearchPool builds these
// from `raw`, one per card_id with the Normal printing preferred.
const row = (o) => Object.assign({
  card_id: "crd_" + Math.random().toString(36).slice(2),
  "Product Name": "Heihei - Created by the Vine",
  Rarity: "Rare", Set: "Attack of the Vine!", Number: "114",
  ink: "Amber", inks: ["Amber"], cost: 3, strength: 1, willpower: 3, lore: 1,
  inkable: true, card_type: "Character", classifications: ["Storyborn", "Ally"],
  keywords: null, text: "When you play this character, draw a card.",
  illustrators: ["Some Artist"], tcg_printing: "Normal", variant_label: null,
  "Low Price": 1.5, "TCGPlayer Market": 2.0,
}, o);
const names = (rs) => rs.map((r) => r["Product Name"] + " (" + r.Rarity + ")");

// ── 1. The reported case ─────────────────────────────────────────────────────
// Aaron P, 2026-09-11: the Epic Heihei read as the Rare, and fixing it meant
// searching by name for a card already on screen. "heihei epic" is what a
// person types; before this it matched nothing at all.
const heiheiPool = [
  row({ card_id: "rare", Rarity: "Rare" }),
  row({ card_id: "epic", Rarity: "Epic", Number: "223" }),
  row({ card_id: "other", "Product Name": "Heihei - Boat Snack", Rarity: "Common" }),
];
check("heihei epic → the Epic only", names(qaEditMatches("heihei epic", heiheiPool)), ["Heihei - Created by the Vine (Epic)"]);
check("heihei → every Heihei", qaEditMatches("heihei", heiheiPool).length, 3);
check("heihei rare → the Rare only", names(qaEditMatches("heihei rare", heiheiPool)), ["Heihei - Created by the Vine (Rare)"]);
// The rarity word must not survive into the name query, or it matches nothing.
check("parse splits name from rarity", (() => { const p = parseSearchQuery("heihei epic"); return [p.name, p.filters.rarity]; })(), ["heihei", "Epic"]);

// ── 2. Every dimension the tester can read off the card in hand ──────────────
const wide = [
  row({ card_id: "a", "Product Name": "Elsa - Snow Queen", Rarity: "Legendary", ink: "Amethyst", inks: ["Amethyst"], Set: "The First Chapter", cost: 8 }),
  row({ card_id: "b", "Product Name": "Elsa - Spirit of Winter", Rarity: "Enchanted", ink: "Amethyst", inks: ["Amethyst"], Set: "Rise of the Floodborn", cost: 9 }),
  row({ card_id: "c", "Product Name": "Elsa - Gloves Off", Rarity: "Common", ink: "Ruby", inks: ["Ruby"], Set: "Attack of the Vine!", cost: 2 }),
];
check("rarity prefix (ench)", names(qaEditMatches("elsa ench", wide)), ["Elsa - Spirit of Winter (Enchanted)"]);
check("ink word", names(qaEditMatches("elsa ruby", wide)), ["Elsa - Gloves Off (Common)"]);
check("set nickname", names(qaEditMatches("elsa tfc", wide)), ["Elsa - Snow Queen (Legendary)"]);
check("cost", names(qaEditMatches("elsa cost 2", wide)), ["Elsa - Gloves Off (Common)"]);
check("bare dimension, no name", qaEditMatches("amethyst", wide).length, 2);

// ── 3. What must NOT change ─────────────────────────────────────────────────
// The collector-number branch is the affordance for a tester holding the card:
// "154" or "154/204" reads straight off the bottom line. parseSearchQuery would
// treat a bare number as name text, so this has to keep beating it.
const cnPool = [row({ card_id: "n1", Number: "223" }), row({ card_id: "n2", "Product Name": "Mickey Mouse - Brave Little Tailor", Number: "114" })];
check("collector number", names(qaEditMatches("223", cnPool)), ["Heihei - Created by the Vine (Rare)"]);
check("collector number N/M", names(qaEditMatches("114/204", cnPool)), ["Mickey Mouse - Brave Little Tailor (Rare)"]);
// Plain name search, diacritics and apostrophes folded, still works.
const folded = [row({ card_id: "t", "Product Name": "Te Kā - Heartless" }), row({ card_id: "m", "Product Name": "Madam Mim - Purple Dragon" })];
check("diacritics folded", names(qaEditMatches("te ka", folded)), ["Te Kā - Heartless (Rare)"]);
check("apostrophes folded", qaEditMatches("madam mims", folded).length, 1);
// Under two characters is not a search.
check("one character is not a query", qaEditMatches("h", heiheiPool).length, 0);
// A genuine miss still reads as a miss rather than as everything.
check("no match stays no match", qaEditMatches("zzzzqq", heiheiPool).length, 0);

// ── 4. AND first, OR only as a fallback ─────────────────────────────────────
// Two name words must both land ("elsa snow" is the Snow Queen, not every
// Elsa); if AND finds nothing the OR pass keeps the box useful.
check("multi-word name ANDs", names(qaEditMatches("elsa snow", wide)), ["Elsa - Snow Queen (Legendary)"]);
check("OR fallback when AND is empty", qaEditMatches("frozen elsa", wide).length, 3);

// ── 5. Ranking ──────────────────────────────────────────────────────────────
// A prefix of the residual NAME leads. Sorting on the raw input would rank
// "heihei epic" against names that can never start with it, so the ordering
// would be decided by name length alone.
const rank = [
  row({ card_id: "long", "Product Name": "Prince Eric - Expert Helmsman", Rarity: "Epic" }),
  row({ card_id: "short", "Product Name": "Eric - Ruler of Seas", Rarity: "Epic" }),
];
check("name prefix leads", names(qaEditMatches("eric epic", rank))[0], "Eric - Ruler of Seas (Epic)");
check("at most 12 rows render", qaEditMatches("anna", Array.from({ length: 200 }, (_, i) => row({ card_id: "x" + i, "Product Name": "Anna - Take " + i }))).length, 12);

// ── 6. The scan cap ─────────────────────────────────────────────────────────
check("scan cap is a number", typeof QA_EDIT_SCAN_CAP, "number");
check("scan cap leaves room to rank", QA_EDIT_SCAN_CAP >= 12, true);
if (!/hits\.length >= QA_EDIT_SCAN_CAP/.test(memoBody)) {
  failed++;
  console.log("FAIL  the candidate scan is uncapped — a one-letter query runs the body-text haystack over the whole catalog per keystroke");
} else {
  console.log("PASS  the candidate scan is capped");
}

// ── 7. Replay over the shipped scanner index ────────────────────────────────
// 3,210 real cards. The point is that a realistic pool still answers in one
// digit of milliseconds and that the version families the chips refuse (the
// ones this box exists to catch) are reachable by typing.
const idx = JSON.parse(readFileSync(new URL("../scanner/index.json", import.meta.url), "utf8"));
const real = idx.cards.map((c, i) => row({
  card_id: c.id, "Product Name": c.version ? c.name + " - " + c.version : c.name,
  Rarity: c.rarity, Number: String((i % 204) + 1), Set: "Attack of the Vine!",
}));
check("shipped index replays", real.length > 3000, true);
const epics = qaEditMatches("epic", real);
check("bare rarity over the real index", epics.length > 0 && epics.every((r) => r.Rarity === "Epic"), true);
// Every multi-version family the chip row refuses is reachable by typing the
// rarity — that refusal is exactly why this box has to understand one. The
// property that matters is that it never answers with the WRONG rarity: an
// empty list reads as "not in the catalog", but a confident wrong row is what
// gets filed into somebody's collection.
const byName = new Map();
for (const r of real) {
  const k = r["Product Name"].toLowerCase();
  if (!byName.has(k)) byName.set(k, []);
  byName.get(k).push(r);
}
let fams = 0, resolved = 0, wrong = 0;
for (const [, rs] of byName) {
  if (rs.length < 2) continue;
  const rar = new Set(rs.map((r) => r.Rarity));
  if (rar.size !== rs.length) continue;          // colliding labels: the editor's art list answers those
  fams++;
  const first = rs[0];
  const q = first["Product Name"].split(" - ")[0].toLowerCase() + " " + String(first.Rarity).toLowerCase();
  const hits = qaEditMatches(q, real);
  if (hits.length && hits.every((h) => h.Rarity === first.Rarity)) resolved++;
  else if (hits.some((h) => h.Rarity !== first.Rarity)) wrong++;
}
check("multi-version families exist in the shipped index", fams > 100, true);
check("typing the rarity never answers with another one", wrong, 0);
// The handful that come back empty are names whose own words are search
// dimensions in their own right — Alien, Tigger and Coconut are real
// classifications and Violet is an ink alias, so the strict pass wants a
// declared value these index-shaped rows don't carry. In the catalog they do.
check("typing the rarity resolves the rest", resolved >= fams - 8, true);

// ── 8. The exclusion pre-pass matches a WHOLE token ─────────────────────────
// Routing this box through parseSearchQuery means it inherits the parser's
// quirks, and one of them answered with the wrong cards rather than none:
// "non "/"no " were found by a bare indexOf, so "bruno madrigal" held a "no "
// and "last cannon" a "non ". Bruno parsed as name "bru" with the Madrigal
// classification EXCLUDED — a search for Bruno that could not return a Bruno.
// Measured over this same card list: 43 corrupted queries, now 0. Both
// directions are pinned, because over-tightening silently kills the real
// exclusion syntax instead.
const exclOf = (q) => { const p = parseSearchQuery(q);
  return [...p.excludeRarities, ...p.excludeInks, ...p.excludeKeywords, ...p.excludeClassifications, ...p.excludeTypes]; };
check("bruno keeps his name", parseSearchQuery("bruno madrigal").name, "bruno");
check("bruno excludes nothing", exclOf("bruno madrigal"), []);
check("cannon keeps its name", parseSearchQuery("last cannon").name, "last cannon");
check("rhino keeps its name", parseSearchQuery("madam mim rhino").name, "madam mim rhino");
check("bad-anon excludes nothing", exclOf("bad-anon enchanted"), []);
check("real exclusion: non", exclOf("elsa non enchanted"), ["Enchanted"]);
check("real exclusion: no", exclOf("elsa no amber"), ["Amber"]);
check("real exclusion: not", exclOf("not rush"), ["rush"]);
check("real exclusion: without", exclOf("without evasive"), ["evasive"]);
check("real exclusion: exclude", exclOf("exclude enchanted"), ["Enchanted"]);
check("real exclusion: two-word", exclOf("no super rare"), ["Super Rare"]);
check("real exclusion: leading hyphen", exclOf("elsa -enchanted"), ["Enchanted"]);
// The sweep the number above came from, re-run so it stays a measurement.
let corrupted = 0;
for (const r of real) {
  for (const suffix of ["", " enchanted", " rush", " amber", " promo"]) {
    if (exclOf((r["Product Name"] + suffix).toLowerCase()).length) corrupted++;
  }
}
check("no card name parses as an exclusion", corrupted, 0);

const t0 = process.hrtime.bigint();
for (let i = 0; i < 10; i++) qaEditMatches("heihei", real);
const ms = Number(process.hrtime.bigint() - t0) / 10 / 1e6;
console.log("      (" + real.length + " rows, " + ms.toFixed(1) + "ms per query)");

console.log(failed ? failed + " FAILED" : "all passed");
process.exit(failed ? 1 : 0);
