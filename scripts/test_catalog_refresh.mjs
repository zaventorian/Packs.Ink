// test_catalog_refresh.mjs — guards what a catalog refresh owes the rest of the page.
//
//     node scripts/test_catalog_refresh.mjs
//
// Extracts the real code out of Index.html rather than restating it. Both
// failures this pins are silent, which is why they shipped (found 2026-10-06):
//
//   * A saved catalog past its 24h TTL skips the freshness probe and refetches,
//     and only the probe bumped priceEpoch — the key the home movers memo is
//     read under. An installed app resumed after a day refetched the catalog
//     and kept yesterday's movers for the rest of the page's life, with nothing
//     on screen to say so. The fix bumps on the refetch path too, but ONLY when
//     the movers on screen predate it: bumping regardless fetched all ~6 pages
//     of movers twice for every visitor back after a day (measured 12 vs 6).
//
//   * A /cards?card=<id> link to a card newer than the SAVED catalog found
//     nothing on the replayed rows, the id was consumed anyway, and the fresh
//     catalog that landed seconds later had nothing left to open — so a shared
//     link to a just-revealed card opened no card.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");

let failed = 0;
const check = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}`);
  if (!ok) console.log(`        got  ${JSON.stringify(got)}\n        want ${JSON.stringify(want)}`);
};
function grab(start, end) {
  const a = src.indexOf(start);
  if (a < 0) throw new Error("missing start marker: " + start);
  const b = src.indexOf(end, a);
  if (b < 0) throw new Error("missing end marker: " + end);
  return src.slice(a, b + end.length);
}

// ── staleCatalogRefresh: the decision itself ───────────────────────────────
const helperSrc = grab("const staleCatalogRefresh = ", "\n};");
const staleCatalogRefresh = new Function(helperSrc + "\nreturn staleCatalogRefresh;")();

const rows = [{}];
const T = 1_000_000;
const stale = (latestDate) => ({rows, stale: true, latestDate});
const memAt = (at) => ({rows: [{}], epoch: 0, at});

console.log("== a full refetch that brought newer prices ==");
check("movers fetched BEFORE the refetch: wipe and bump",
  staleCatalogRefresh(stale("2026-10-04"), "2026-10-05", memAt(T - 1), T), {wipe: true, bump: true});
check("movers fetched AFTER it started (Home loaded them meanwhile): wipe, no second fetch",
  staleCatalogRefresh(stale("2026-10-04"), "2026-10-05", memAt(T + 5), T), {wipe: true, bump: false});
check("no movers fetched yet this page life: nothing to refresh",
  staleCatalogRefresh(stale("2026-10-04"), "2026-10-05", null, T), {wipe: true, bump: false});
check("a stored-copy memo with no write time counts as old",
  staleCatalogRefresh(stale("2026-10-04"), "2026-10-05", {rows: [{}], epoch: 0}, T), {wipe: true, bump: true});
check("a saved catalog with no latestDate (legacy) is treated as older",
  staleCatalogRefresh(stale(null), "2026-10-05", memAt(T - 1), T), {wipe: true, bump: true});

console.log("\n== and every case that must do nothing ==");
check("same prices as the saved copy",
  staleCatalogRefresh(stale("2026-10-05"), "2026-10-05", memAt(T - 1), T), {wipe: false, bump: false});
check("a saved catalog within its TTL (the probe already handled it)",
  staleCatalogRefresh({rows, stale: false, latestDate: "2026-10-04"}, "2026-10-05", memAt(T - 1), T), {wipe: false, bump: false});
check("no saved catalog at all (a first visit)",
  staleCatalogRefresh(null, "2026-10-05", memAt(T - 1), T), {wipe: false, bump: false});
check("an empty saved catalog",
  staleCatalogRefresh({rows: [], stale: true, latestDate: "2026-10-04"}, "2026-10-05", memAt(T - 1), T), {wipe: false, bump: false});
check("the refetch found no price date",
  staleCatalogRefresh(stale("2026-10-04"), null, memAt(T - 1), T), {wipe: false, bump: false});

// ── the wiring: a correct helper that nothing calls protects nothing ───────
console.log("\n== wiring ==");
const app = grab("function App(){", "\n}\n");
const fetchStart = app.indexOf("const catalogFetchAt = Date.now();");
const refreshAt = app.indexOf("staleCatalogRefresh(cached, maxPriceDate, _homeMoversMem, catalogFetchAt)");
check("the full refetch notes when it started", fetchStart > 0, true);
check("...and consults the helper after it", refreshAt > fetchStart, true);
const after = app.slice(refreshAt, refreshAt + 400);
check("...wiping on its word", /refreshed\.wipe\)\s*wipePriceDerivedAuxCaches\(\)/.test(after), true);
check("...and bumping priceEpoch on its word", /refreshed\.bump\)\s*setPriceEpoch\(/.test(after), true);
check("...BEFORE the fresh catalog is written over the saved one",
  refreshAt < app.indexOf("writeCache(allRows, maxPriceDate"), true);

const home = grab("const HomeView = (", "\n};\n");
const memoWrites = home.match(/_homeMoversMem = \{[^}]*\}/g) || [];
check("every home movers memo write records `at`", memoWrites.length >= 2 && memoWrites.every(m => /\bat:/.test(m)), true);
check("the network write records when the fetch STARTED", /_homeMoversMem = \{rows, epoch: priceEpoch, at: fetchedAt\}/.test(home)
  && /const fetchedAt = Date\.now\(\);\s*\n\s*sbFetchAll\("price_movers"/.test(home), true);
check("the movers effect still re-runs on priceEpoch", /\},\[priceEpoch\]\);/.test(home), true);

const rjc = grab("function readJsonCacheIdb(key, ttlMs){", "\n}");
const readJsonCacheIdb = new Function("idbGet", "IDB_JSONCACHE_PREFIX", rjc + "\nreturn readJsonCacheIdb;")(
  async () => ({t: 1234, data: [1]}), "jsoncache:");
const got = await readJsonCacheIdb("k", 10);
check("readJsonCacheIdb hands back the record's write time", got.t, 1234);

// ── the card link ───────────────────────────────────────────────────────────
console.log("\n== a ?card= link to a card the saved catalog lacks ==");
const cards = grab("const CardsView = (", "// ── Shareable card URLs");
check("a card the replayed rows lack is remembered, not dropped",
  /if\(g\) setSelectedGroup\(g\);\s*\n\s*else missingCardRef\.current = \{id: incomingOpenCardId, until: Date\.now\(\) \+ \d+\};/.test(cards), true);
const retry = cards.slice(cards.indexOf("const m = missingCardRef.current;"));
check("...and tried again whenever the rows change", /\}, \[raw\]\);/.test(retry.slice(0, 600)), true);
check("...for a bounded time", /Date\.now\(\) > m\.until/.test(retry.slice(0, 600)), true);
check("...never over a card someone has since opened", /setSelectedGroup\(prev => prev \|\| g\)/.test(retry.slice(0, 600)), true);
check("the ref is declared above the effect that writes it",
  cards.indexOf("const missingCardRef = useRef(null)") < cards.indexOf("else missingCardRef.current"), true);

console.log(failed ? `\n${failed} FAILED` : "\nall passed");
process.exit(failed ? 1 : 0);
