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
  "const defaultHomeLayout = () => HOME_PANELS.map(p => ({key:p.key, col:p.col, on:!p.off}));",
);
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
  encodeURIComponent(`${consts}\n${normalize}\n${init}\nexport {initHomeLayout, HOME_PANELS};`)
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

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
