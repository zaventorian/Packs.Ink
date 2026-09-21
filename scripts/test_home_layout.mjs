// test_home_layout.mjs — guards the home-page layout preference migrations.
//
//     node scripts/test_home_layout.mjs
//
// The regression this locks down: `packsink:homeLayout` is persisted on EVERY
// page load, and normalizeHomeLayout keeps any stored column that is still a
// valid column name. So changing a panel's default `col` never reaches a
// browser that has visited before. The news feed defaulted to the full-width
// `announce` strip until 2026-08-12; long-lived profiles kept rendering it as a
// lone 420px card under the search box with the whole grid shoved below.
//
// Run this after touching HOME_PANELS / normalizeHomeLayout / App's homeLayout
// init in Index.html. There is no client-side CI, so it is manual — but it
// reads the real code out of Index.html rather than duplicating it, so it
// cannot silently drift from what ships.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const consts = grab(
  "const HOME_COLUMNS = [",
  "  ({key:p.key, col:p.col, on:!p.off, ...normalizeHomePair({key:p.key})}));",
);
// normalizeHomeLayout delegates the pairing fields; normalizeHomePair is
// defined further down the file, so grab it separately and emit it first.
const pairNorm = grab("const normalizeHomePair = (p) => {", "\n};");
const normalize = grab("const normalizeHomeLayout = (val) => {", "\n};");
// The App initializer, rewritten only enough to be callable outside React.
const init = grab("  const [homeLayout, setHomeLayout] = useState(() => {", "\n  });")
  .replace("const [homeLayout, setHomeLayout] = useState(() => {", "const initHomeLayout = (() => {");

let store = {};
globalThis.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
};

const { initHomeLayout, HOME_PANELS } = await import(
  "data:text/javascript," +
  encodeURIComponent(`${consts}\n${pairNorm}\n${normalize}\n${init}\nexport {initHomeLayout, HOME_PANELS};`)
);

const NEWS_DEFAULT = HOME_PANELS.find((p) => p.key === "news").col;
const colOf = (list, key) => list.find((p) => p.key === key)?.col;
// A browser carrying the pre-2026-08-12 layout, where news sat in `announce`.
const stale = () =>
  HOME_PANELS.map((p) => ({ key: p.key, col: p.key === "news" ? "announce" : p.col, on: true }));

let failed = 0;
const check = (name, got, want) => {
  const ok = got === want;
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}  (got ${got}, want ${want})`);
};

store = { "packsink:homeLayout": JSON.stringify(stale()) };
check("stale announce layout migrates to the rail", colOf(initHomeLayout(), "news"), NEWS_DEFAULT);
check("migration stamp written", store["packsink:homeLayoutNewsRail"], "1");

// Stamped, not coerced: `announce` is still an offered column, so a deliberate
// re-pick of Top must survive the next load.
store["packsink:homeLayout"] = JSON.stringify(stale());
check("deliberate Top pick survives a later load", colOf(initHomeLayout(), "news"), "announce");

store = {
  "packsink:homeLayout": JSON.stringify(
    stale().map((p) => (p.key === "collection" ? { ...p, col: "left", on: false } : p)),
  ),
};
const migrated = initHomeLayout();
check("unrelated panel keeps its column", colOf(migrated, "collection"), "left");
check("unrelated panel keeps its off state", migrated.find((p) => p.key === "collection").on, false);
check("news still migrated alongside", colOf(migrated, "news"), NEWS_DEFAULT);

store = {};
check("fresh browser gets the default", colOf(initHomeLayout(), "news"), NEWS_DEFAULT);

store = { "packsink:homePanels": JSON.stringify({ following: false }) };
const legacy = initHomeLayout();
check("legacy visibility map: news at default", colOf(legacy, "news"), NEWS_DEFAULT);
check("legacy visibility map: hidden panel respected", legacy.find((p) => p.key === "following").on, false);

store = { "packsink:homeLayout": "{not json" };
check("corrupt layout falls back to the default", colOf(initHomeLayout(), "news"), NEWS_DEFAULT);

// Opt-in panels (HOME_PANELS `off:true`) must start hidden BOTH on a fresh
// browser and when appended to a layout that predates them — otherwise
// shipping one silently switches it on for everyone who has ever visited.
const optIn = HOME_PANELS.filter((p) => p.off).map((p) => p.key);
if (!optIn.length) console.log("SKIP  no opt-in panels declared");
for (const key of optIn) {
  store = {};
  check(`opt-in ${key}: off for a fresh browser`, initHomeLayout().find((p) => p.key === key).on, false);
  store = {
    "packsink:homeLayout": JSON.stringify(
      HOME_PANELS.filter((p) => p.key !== key).map((p) => ({ key: p.key, col: p.col, on: true })),
    ),
  };
  check(`opt-in ${key}: off when appended to an older layout`,
    initHomeLayout().find((p) => p.key === key).on, false);
  store = {
    "packsink:homeLayout": JSON.stringify(
      HOME_PANELS.map((p) => ({ key: p.key, col: p.col, on: true })),
    ),
  };
  check(`opt-in ${key}: a deliberate ON survives`,
    initHomeLayout().find((p) => p.key === key).on, true);
}

// -- pairing a panel with a movers banner ---------------------------------
// A stored pairing has to survive a reload, and a bad one has to collapse to
// "not paired" rather than render a panel next to nothing. Both failures are
// silent: the panel simply isn't where the user put it.
const layoutWith = (patch) => JSON.stringify(
  HOME_PANELS.map((p) => ({ key: p.key, col: p.col, on: true, ...(patch[p.key] || {}) })),
);
const pairOf = (key) => {
  const p = initHomeLayout().find((x) => x.key === key);
  return p.pair + "|" + p.pairSide;
};

store = {};
check("fresh browser: nothing is paired", pairOf("news"), "null|right");

store = { "packsink:homeLayout": layoutWith({ tournaments: { pair: "chase", pairSide: "left" } }) };
check("a stored pairing survives", pairOf("tournaments"), "chase|left");

store = { "packsink:homeLayout": layoutWith({ news: { pair: "rareLeg" } }) };
check("pairSide defaults to right", pairOf("news"), "rareLeg|right");

store = { "packsink:homeLayout": layoutWith({ news: { pair: "nonsense", pairSide: "sideways" } }) };
check("an unknown banner collapses to unpaired", pairOf("news"), "null|right");

// Only the three narrow list boxes are pairable. A wide panel squeezed into a
// 32% column is unreadable, so a stored pairing on one must be dropped.
store = { "packsink:homeLayout": layoutWith({ collection: { pair: "chase" } }) };
check("a non-pairable panel cannot be paired",
  initHomeLayout().find((p) => p.key === "collection").pair, null);

// -- the rail swap (2026-09-15) -------------------------------------------
// The calendar moved to the 360px right rail; the Toolbox and Set EV dropped to
// the foot of the 240px left one. Every failure here is silent — a stamp that
// never fires just leaves the old arrangement in place, and one that fires too
// eagerly silently relocates a panel the user positioned by hand.
//
// The layout as it stood BEFORE the swap: calendar top-of-left, the two compact
// panels in the right rail.
const preSwap = () => [
  { key: "calendar", col: "left", on: true },
  { key: "news", col: "left", on: true },
  { key: "following", col: "left", on: true },
  { key: "tournaments", col: "left", on: true },
  { key: "tools", col: "right", on: true },
  { key: "setEv", col: "right", on: true },
  { key: "collection", col: "right", on: true },
];
const idxOf = (list, key) => list.findIndex((p) => p.key === key);

store = { "packsink:homeLayout": JSON.stringify(preSwap()) };
const swapped = initHomeLayout();
check("calendar moves to the right rail", colOf(swapped, "calendar"), "right");
check("toolbox moves to the left rail", colOf(swapped, "tools"), "left");
check("set EV moves to the left rail", colOf(swapped, "setEv"), "left");
check("rail-swap stamp written", store["packsink:homeLayoutRailSwap"], "1");
// Position matters as much as column: the calendar is the scanning surface and
// belongs ABOVE the collection chart, not under it.
check("calendar leads the right rail",
  swapped.filter((p) => p.col === "right")[0].key, "calendar");
// ...and the two compact panels land at the FOOT of the left rail, in order,
// below the three list boxes that were already there.
check("toolbox sits below the list boxes",
  idxOf(swapped, "tools") > idxOf(swapped, "tournaments"), true);
check("left rail ends tools, setEv",
  swapped.filter((p) => p.col === "left").slice(-2).map((p) => p.key).join(","), "tools,setEv");

// Stamped, not coerced: run it again and nothing moves a second time.
store["packsink:homeLayout"] = JSON.stringify(swapped);
const twice = initHomeLayout();
check("re-running the init is a no-op",
  twice.map((p) => p.key + ":" + p.col).join("|"),
  swapped.map((p) => p.key + ":" + p.col).join("|"));

// A deliberate placement is left alone. Someone who dragged the calendar to the
// centre column meant it; the swap must not reach in and undo that.
store = {
  "packsink:homeLayout": JSON.stringify(
    preSwap().map((p) => (p.key === "calendar" ? { ...p, col: "main" } : p)),
  ),
};
check("a hand-placed calendar is not moved", colOf(initHomeLayout(), "calendar"), "main");
store = {
  "packsink:homeLayout": JSON.stringify(
    preSwap().map((p) => (p.key === "tools" ? { ...p, col: "main" } : p)),
  ),
};
check("a hand-placed toolbox is not moved", colOf(initHomeLayout(), "tools"), "main");

// The gap a column-ONLY move would have left: a browser that never saw the
// calendar stamp had the panel APPENDED carrying today's default ("right"),
// which is the right COLUMN but the bottom of it. Re-seating has to be by
// position too, or it renders under the collection chart forever.
store = {
  "packsink:homeLayout": JSON.stringify([
    { key: "news", col: "left", on: true },
    { key: "collection", col: "right", on: true },
    { key: "calendar", col: "right", on: true },
  ]),
};
check("an appended calendar is re-seated to the top of its rail",
  initHomeLayout().filter((p) => p.col === "right")[0].key, "calendar");

// A fresh browser gets the new arrangement straight from HOME_PANELS.
store = {};
const fresh = initHomeLayout();
check("fresh browser: calendar on the right", colOf(fresh, "calendar"), "right");
check("fresh browser: toolbox on the left", colOf(fresh, "tools"), "left");
check("fresh browser: set EV on the left", colOf(fresh, "setEv"), "left");
check("fresh browser: calendar leads the right rail",
  fresh.filter((p) => p.col === "right")[0].key, "calendar");

// -- The mobile movers picker's chip labels -------------------------------
// Below 1100px the banner stack renders as ONE banner plus a chip strip, and
// a chip takes its text from HOME_BANNER_SHORT. A key missing there is not an
// error -- it falls back to HOME_BANNER_LABELS, a full title like
// "Newest set - Most Valuable" -- so the strip silently blows its width out
// and the chips go half-clipped. Nothing on screen says which key was missed.
const shortSrc = grab("const HOME_BANNER_SHORT = {", "\n};");
const keysSrc = grab("const HOME_BANNER_KEYS = [", "];");
const labelsSrc = grab("const HOME_BANNER_LABELS = {", "\n};");
const rarSrc = grab("const HOME_BANNER_RARITIES = {", "\n};");
const iconSrc = grab("const RARITY_ICONS = {", "\n};");
const { HOME_BANNER_SHORT, HOME_BANNER_KEYS, HOME_BANNER_LABELS,
        HOME_BANNER_RARITIES, RARITY_ICONS } = await import(
  "data:text/javascript," + encodeURIComponent(
    [keysSrc, shortSrc, labelsSrc, rarSrc, iconSrc,
     "export { HOME_BANNER_SHORT, HOME_BANNER_KEYS, HOME_BANNER_LABELS,",
     "         HOME_BANNER_RARITIES, RARITY_ICONS };"].join("\n")));

for (const k of HOME_BANNER_KEYS) {
  check('banner "' + k + '" has a short chip label',
    typeof HOME_BANNER_SHORT[k] === "string" && HOME_BANNER_SHORT[k].length > 0, true);
}
check("no short label is left over from a removed banner",
  Object.keys(HOME_BANNER_SHORT).filter((k) => !HOME_BANNER_KEYS.includes(k)).join(",") || "none",
  "none");
// The three rarity-group chips draw RARITY_ICONS instead of a word. A name
// that is not a canonical rarity renders NOTHING — no error, and no fallback
// to the word, just an empty chip — so the two maps have to agree.
for (const [k, rars] of Object.entries(HOME_BANNER_RARITIES)) {
  check(`rarity chip "${k}" is a real banner`, HOME_BANNER_KEYS.includes(k), true);
  for (const r of rars) {
    check(`"${k}" rarity "${r}" has an icon`, typeof RARITY_ICONS[r] === "string", true);
  }
  // An icon chip has no text node, so its accessible name comes from the full
  // label alone. Losing that entry leaves a screen reader with just "button".
  check(`icon chip "${k}" has a full label to name it`,
    typeof HOME_BANNER_LABELS[k] === "string", true);
}

// "All" shares the one localStorage key with the banner keys, so a banner
// named "all" would make the sentinel unreadable from a stored value: the
// strip would come back on the wrong chip and there would be no way to tell
// which the user meant. Nothing enforces the namespace but this.
const allSentinel = /const MOVERS_PICK_ALL = "([^"]+)";/.exec(src);
check("MOVERS_PICK_ALL is declared", !!allSentinel, true);
check("the All sentinel collides with no banner key",
  allSentinel && HOME_BANNER_KEYS.includes(allSentinel[1]), false);

// The strip is ~347px on a 375px phone; a chip is roughly 7px per character
// plus 22px of padding. Anything past ~14 characters is a title, not a chip.
for (const [k, v] of Object.entries(HOME_BANNER_SHORT)) {
  check('short label "' + v + '" is chip-sized', v.length <= 14, true);
}

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
