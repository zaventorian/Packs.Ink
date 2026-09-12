// test_calendar.mjs — guards the Lorcana calendar's pure core.
//
//     node scripts/test_calendar.mjs
//
// Extracts the real functions out of Index.html, house pattern, so they cannot
// drift from what ships.
//
// Every case below is a failure that is SILENT: a calendar that is confidently
// wrong by one day, an override that quietly becomes a duplicate, or an .ics
// that imports as nothing at all. None of them throw, and none of them look
// wrong in a screenshot.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
const NL = String.fromCharCode(10);
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(/\r?\n/).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const CAL_D = "),
  grab("const calYmdParts = (s) => {", NL + "};"),
  grabLine("const calYmdToUTC = "),
  grab("const calUTCToYmd = (ms) => {", NL + "};"),
  grabLine("const calAddDays = "),
  grabLine("const calDayDiff = "),
  grab("const calTodayYmd = () => {", NL + "};"),
  grab("const calTzYmd = (iso, tz) => {", NL + "};"),
  grab("const CALENDAR_KINDS = [", NL + "];"),
  grabLine("const CALENDAR_KIND_KEYS = "),
  grab("const CALENDAR_KIND_LONG = {", NL + "};"),
  grabLine("const SET_RELEASE_LABELS = "),
  grabLine("const SET_RELEASE_PHASES = "),
  grab("const calEventTitle = (ev) => !ev ? \"\"", ": (ev.title || \"\");"),
  grabLine("const calEventSubtitle = "),
  grab("const CALENDAR_REGIONS = [", NL + "];"),
  grab("const _CAL_REGION_BY_CC = (() => {", NL + "})();"),
  grabLine("const calRegionOf = "),
  grabLine("const calMatchesRegion = "),
  grabLine("const OSM_TILE_PX = "),
  grab("const osmTileLayout = (lat, lng, zoom, w, h) => {", NL + "};"),
  grabLine("const osmTileUrl = "),
  grabLine("const osmViewUrl = "),
  grab("const calendarSetEntries = (releaseDates) => {", NL + "};"),
  grabLine("const _calSetKey = "),
  grab("const calendarMergeEvents = (derived, rows) => {", NL + "};"),
  grabLine("const _calKindRank = "),
  grab("const calendarSort = (events) =>", "|| String(a.title || \"\").localeCompare(String(b.title || \"\")));"),
  grab("const calendarCombine = (curated, store) => {", NL + "};"),
  grabLine("const CAL_ART_PREF = "),
  grab("const calendarArtIndex = (sealedRows, names) => {", NL + "};"),
  grab("const calendarEventArt = (ev, artIndex) => {", NL + "};"),
  grabLine("const calendarHiddenSet = (subs) =>"),
  grab("const calendarApplyHidden = (events, hidden, saved) => {", NL + "};"),
  grab("const CAL_STORE_KINDS = [", NL + "];"),
  grabLine("const CAL_STORE_KIND_KEYS = "),
  grab("const calStoreKindsOf = (sub) => {", NL + "};"),
  grab("const calStoreAllows = (sub, evKind) => {", NL + "};"),
  grab("const calendarStoreEntry = (ev, extra) => {", NL + "};"),
  grabLine("const CAL_MAX_SPAN_DAYS = "),
  grab("const calendarEventDays = (ev) => {", NL + "};"),
  grab("const calendarMonthGrid = (year, month, events) => {", NL + "};"),
  grab("const calendarUpcoming = (events, fromYmd, limit) => {", NL + "};"),
  grabLine("const CAL_MONTHS = "),   // one line — a block grab here runs on and swallows calShortDay
  grab("const calShortDay = (ymd) => {", NL + "};"),
  grab("const calendarPanelWindow = (pool, todayYmd, size, page) => {", NL + "};"),
  grabLine("const calChipLabel = "),
  grab("const calCountdown = (ev, todayYmd) => {", NL + "};"),
  grabLine("const _calEnc = "),
  grab("const icsEscape = (s) =>", ".replace(/\\r\\n|\\r|\\n/g, \"\\\\n\");"),
  grab("const icsFold = (line) => {", NL + "};"),
  grabLine("const icsDate = "),
  grabLine("const icsStamp = "),
  grabLine("const CAL_DEFAULT_EVENT_HOURS = "),
  grabLine("const calendarIcsUid = "),
  grab("const icsEventLines = (ev, nowMs) => {", NL + "};"),
  grab("const buildIcs = (events, opts) => {", NL + "};"),
  grab("const googleCalUrl = (ev) => {", NL + "};"),
  "export {calAddDays, calTzYmd, calendarSetEntries, calendarMergeEvents, calendarStoreEntry,",
  " calendarEventDays, calendarMonthGrid, calendarUpcoming, icsEscape, icsFold, buildIcs,",
  " googleCalUrl, calCountdown, calChipLabel, calEventTitle, calEventSubtitle,",
  " calRegionOf, calMatchesRegion, osmTileLayout, osmTileUrl, CALENDAR_REGIONS, calendarCombine,",
  " calendarPanelWindow, calShortDay, calStoreKindsOf, calStoreAllows, CAL_STORE_KINDS, CAL_STORE_KIND_KEYS,",
  " calendarHiddenSet, calendarApplyHidden, calendarArtIndex, calendarEventArt,",
  " CALENDAR_KINDS, CALENDAR_KIND_KEYS, CALENDAR_KIND_LONG, SET_RELEASE_LABELS};",
].join(NL)));

const {
  calAddDays, calTzYmd, calendarSetEntries, calendarMergeEvents, calendarStoreEntry,
  calendarEventDays, calendarMonthGrid, calendarUpcoming, icsEscape, icsFold, buildIcs,
  googleCalUrl, calCountdown, calChipLabel, calEventTitle, calEventSubtitle,
  calRegionOf, calMatchesRegion, osmTileLayout, osmTileUrl, CALENDAR_REGIONS, calendarCombine,
  calendarPanelWindow, calShortDay, calStoreKindsOf, calStoreAllows, CAL_STORE_KINDS,
  CAL_STORE_KIND_KEYS, calendarHiddenSet, calendarApplyHidden,
  calendarArtIndex, calendarEventArt,
  CALENDAR_KINDS, CALENDAR_KIND_KEYS, CALENDAR_KIND_LONG, SET_RELEASE_LABELS,
} = mod;

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  → " + (detail ?? "")));
};
const enc = new TextEncoder();

// ── Calendar days never shift by timezone ───────────────────────────────────
// The bug this guards: `new Date("2026-03-07")` is midnight UTC, which is
// March 6 anywhere west of Greenwich. A set release read a day early is the
// single most embarrassing thing a release calendar can do, and on a US-hosted
// dev machine it is invisible.
ok("day arithmetic crosses a month boundary", calAddDays("2026-02-28", 1) === "2026-03-01",
  calAddDays("2026-02-28", 1));
ok("day arithmetic crosses a leap day", calAddDays("2024-02-28", 1) === "2024-02-29",
  calAddDays("2024-02-28", 1));
ok("day arithmetic crosses a year", calAddDays("2025-12-31", 1) === "2026-01-01");
// US DST begins 2026-03-08. A local-time implementation adding 86400000ms here
// lands back on the 8th, so the day silently repeats.
ok("day arithmetic survives a DST spring-forward", calAddDays("2026-03-08", 1) === "2026-03-09",
  calAddDays("2026-03-08", 1));
ok("day arithmetic survives a DST fall-back", calAddDays("2026-11-01", 1) === "2026-11-02",
  calAddDays("2026-11-01", 1));

// A store event belongs to the day it is in AT THE STORE. 9pm Friday in Los
// Angeles is 04:00 Saturday UTC — a reader in London must still see Friday.
ok("store event keeps the STORE's calendar day, not the reader's",
  calTzYmd("2026-03-07T04:00:00Z", "America/Los_Angeles") === "2026-03-06",
  calTzYmd("2026-03-07T04:00:00Z", "America/Los_Angeles"));
ok("store event east of UTC keeps its own day",
  calTzYmd("2026-03-06T22:00:00Z", "Asia/Tokyo") === "2026-03-07",
  calTzYmd("2026-03-06T22:00:00Z", "Asia/Tokyo"));
// RPH does send malformed zone names; Intl throws on them. Losing the row is
// worse than showing it in the reader's zone.
ok("a bad timezone name degrades instead of throwing",
  typeof calTzYmd("2026-03-07T04:00:00Z", "Not/AZone") === "string");
ok("a null instant is null, not a crash", calTzYmd(null, "UTC") === null);

// ── Set releases derive from SET_RELEASE_DATES ──────────────────────────────
const FIXTURE = {
  "Winterspell":     {lgs: "2026-02-13", retail: "2026-02-20"},
  "Wilds Unknown":   {lgs: "2026-05-08", retail: "2026-05-15"},
  "Attack of the Vine!": {lgs: "2026-07-17", retail: "2026-07-24", prerelease: "2026-07-11"},
};
const derived = calendarSetEntries(FIXTURE);
ok("every dated phase becomes a row", derived.length === 7, derived.length);
ok("all derived rows are kind=set", derived.every(e => e.kind === "set"));
ok("a set with no prerelease date contributes no prerelease row",
  !derived.some(e => e.title === "Winterspell" && e.subtitle === SET_RELEASE_LABELS.prerelease));
ok("a prerelease date is carried when present",
  derived.some(e => e.title === "Attack of the Vine!" && e.starts_on === "2026-07-11"));
ok("a set with no dates at all is skipped", calendarSetEntries({"Ghost Set": {}}).length === 0);
ok("garbage dates are skipped, not rendered",
  calendarSetEntries({"Bad": {lgs: "soon", retail: null}}).length === 0);

// ── The override is an override, not a duplicate ────────────────────────────
// The silent failure: a slipped date is typed in, the merge key does not match,
// and the calendar now shows the set releasing on BOTH days. Both rows look
// right; only the pair is wrong.
const slipped = [{
  id: "row-1", kind: "set", title: "Wilds Unknown", subtitle: "LGS release",
  starts_on: "2026-05-22", set_name: "Wilds Unknown",
}];
const merged = calendarMergeEvents(derived, slipped);
const wuLgs = merged.filter(e => e.set_name === "Wilds Unknown" && e.subtitle === "LGS release");
ok("a table row REPLACES the derived set row", wuLgs.length === 1, `${wuLgs.length} rows`);
ok("the replacement carries the new date", wuLgs[0] && wuLgs[0].starts_on === "2026-05-22",
  wuLgs[0] && wuLgs[0].starts_on);
ok("the set's other phases are untouched",
  merged.some(e => e.set_name === "Wilds Unknown" && e.subtitle === "Retail release" && e.starts_on === "2026-05-15"));
// The subtitle spelling IS the merge key — this is the one that breaks quietly
// if SET_RELEASE_LABELS is reworded without migrating stored rows.
const misspelled = calendarMergeEvents(derived, [{
  id: "row-2", kind: "set", title: "Wilds Unknown", subtitle: "LGS Release",  // capital R
  starts_on: "2026-05-22", set_name: "Wilds Unknown",
}]);
ok("the merge key is case-insensitive, so casing drift still overrides",
  misspelled.filter(e => e.set_name === "Wilds Unknown" && /lgs release/i.test(e.subtitle || "")).length === 1);

// ⚠ Two different CCQs sharing a name must BOTH survive. Keying every kind by
// title would swallow one, and it would read as the scan having missed it.
const twoCcqs = calendarMergeEvents([], [
  {id: "a", kind: "ccq", title: "Lorcana 2K CCQ", starts_on: "2026-10-04", location: "Store A"},
  {id: "b", kind: "ccq", title: "Lorcana 2K CCQ", starts_on: "2026-11-15", location: "Store B"},
]);
ok("two same-named CCQs both survive the merge", twoCcqs.length === 2, twoCcqs.length);
const twoProducts = calendarMergeEvents([], [
  {id: "a", kind: "product", title: "Gift Set", starts_on: "2026-10-04"},
  {id: "b", kind: "product", title: "Gift Set", starts_on: "2027-02-01"},
]);
ok("two same-named products both survive", twoProducts.length === 2, twoProducts.length);

ok("merged output is sorted by date", merged.every((e, i) =>
  i === 0 || merged[i - 1].starts_on <= e.starts_on));
ok("merge tolerates null inputs", calendarMergeEvents(null, null).length === 0);

// ── Multi-day spans ─────────────────────────────────────────────────────────
ok("a one-day event occupies one day",
  calendarEventDays({starts_on: "2026-08-28"}).length === 1);
ok("a three-day championship occupies three days",
  calendarEventDays({starts_on: "2026-08-28", ends_on: "2026-08-30"}).length === 3,
  calendarEventDays({starts_on: "2026-08-28", ends_on: "2026-08-30"}).join(","));
ok("a span ending before it starts falls back to one day",
  calendarEventDays({starts_on: "2026-08-28", ends_on: "2026-08-01"}).length === 1);
// A typo'd year is the realistic version of this: 2260 instead of 2026 would
// try to paint ~85,000 cells and hang the grid with no error.
ok("an absurd span is capped rather than hanging the grid",
  calendarEventDays({starts_on: "2026-08-28", ends_on: "2260-08-30"}).length === 60,
  calendarEventDays({starts_on: "2026-08-28", ends_on: "2260-08-30"}).length);

// ── Month grid ──────────────────────────────────────────────────────────────
// Feb 2026 starts on a Sunday and has 28 days → exactly 4 weeks, no padding.
const feb = calendarMonthGrid(2026, 2, []);
ok("a 28-day month starting Sunday is exactly 4 weeks", feb.length === 4, feb.length);
ok("every week has 7 days", feb.every(w => w.length === 7));
ok("Feb 2026 grid starts on the 1st with no lead-in", feb[0][0].date === "2026-02-01");
// Mar 2026: starts Sunday, 31 days → 5 weeks with 4 trailing days from April.
const mar = calendarMonthGrid(2026, 3, []);
ok("a 31-day month starting Sunday is 5 weeks", mar.length === 5, mar.length);
ok("trailing days are marked out-of-month",
  mar[4][mar[4].length - 1].inMonth === false);
// Aug 2026 starts on a Saturday — 6 lead-in days, the worst case.
const aug = calendarMonthGrid(2026, 8, []);
ok("a month starting Saturday pads 6 lead-in days",
  aug[0].filter(d => !d.inMonth).length === 6, aug[0].filter(d => !d.inMonth).length);
ok("the grid always starts on a Sunday",
  [feb, mar, aug].every(g => new Date(g[0][0].date + "T00:00:00Z").getUTCDay() === 0));
ok("no month emits an entirely empty trailing week",
  [feb, mar, aug].every(g => g[g.length - 1].some(d => d.inMonth)));

// A three-day event paints a cell in every day it covers.
const augEvents = calendarMonthGrid(2026, 8, [
  {id: "x", kind: "dlc", title: "NA Championship", starts_on: "2026-08-28", ends_on: "2026-08-30"},
]);
const painted = augEvents.flat().filter(d => d.events.length > 0);
ok("a 3-day event paints 3 cells", painted.length === 3, painted.length);
ok("it paints the right cells",
  painted.map(d => d.date).join(",") === "2026-08-28,2026-08-29,2026-08-30",
  painted.map(d => d.date).join(","));
// An event that starts in the previous month must still paint this month's cells.
const spillover = calendarMonthGrid(2026, 9, [
  {id: "y", kind: "dlc", title: "Spillover", starts_on: "2026-08-30", ends_on: "2026-09-02"},
]);
const sepPainted = spillover.flat().filter(d => d.inMonth && d.events.length > 0);
ok("an event spanning into this month paints it", sepPainted.length === 2, sepPainted.length);

// ── Upcoming ────────────────────────────────────────────────────────────────
const upcomingPool = [
  {id: "past",   kind: "set",     title: "Past",   starts_on: "2026-01-01"},
  {id: "live",   kind: "dlc",     title: "Live",   starts_on: "2026-09-11", ends_on: "2026-09-13"},
  {id: "soon",   kind: "product", title: "Soon",   starts_on: "2026-09-20"},
  {id: "later",  kind: "ccq",     title: "Later",  starts_on: "2026-10-04"},
];
const up = calendarUpcoming(upcomingPool, "2026-09-12", 10);
ok("a finished event drops out of upcoming", !up.some(e => e.id === "past"));
// The one people get wrong: day 2 of a 3-day championship is not "past".
ok("an event happening RIGHT NOW is still upcoming", up.some(e => e.id === "live"),
  up.map(e => e.id).join(","));
ok("upcoming is ordered soonest-first", up[0].id === "live" && up[1].id === "soon");
ok("the limit is honoured", calendarUpcoming(upcomingPool, "2026-09-12", 2).length === 2);
ok("limit 0 means no limit", calendarUpcoming(upcomingPool, "2026-09-12", 0).length === 3);

// ── Countdown ───────────────────────────────────────────────────────────────
// The bug this guards shipped and was visible in one screenshot: a start-date
// comparison called every past event "NOW", so The First Chapter's 2023 release
// sat in the list labelled as happening right now.
const TODAY = "2026-09-12";
const cd = (o) => calCountdown(o, TODAY);
ok("today reads today", cd({starts_on: "2026-09-12"}) === "today", cd({starts_on: "2026-09-12"}));
ok("tomorrow reads tomorrow", cd({starts_on: "2026-09-13"}) === "tomorrow");
ok("this week counts days", cd({starts_on: "2026-09-15"}) === "in 3 days", cd({starts_on: "2026-09-15"}));
ok("a month out reads in weeks", /^in \d+ wk$/.test(cd({starts_on: "2026-10-04"})), cd({starts_on: "2026-10-04"}));
ok("yesterday reads yesterday", cd({starts_on: "2026-09-11"}) === "yesterday", cd({starts_on: "2026-09-11"}));
ok("last week reads days ago", cd({starts_on: "2026-09-08"}) === "4 days ago", cd({starts_on: "2026-09-08"}));
ok("a 2023 release is NOT 'now'", cd({starts_on: "2023-08-18"}) !== "now", cd({starts_on: "2023-08-18"}));
ok("a 2023 release reads in years", cd({starts_on: "2023-08-18"}) === "3 yr ago", cd({starts_on: "2023-08-18"}));
// ⚠ The reason it takes the event: day 2 of a 3-day championship STARTED
// yesterday but is happening while you read it.
ok("day 2 of a multi-day event reads 'now'",
  cd({starts_on: "2026-09-11", ends_on: "2026-09-13"}) === "now",
  cd({starts_on: "2026-09-11", ends_on: "2026-09-13"}));
ok("day 1 of a multi-day event reads 'today'",
  cd({starts_on: "2026-09-12", ends_on: "2026-09-14"}) === "today");
ok("the day after a multi-day event ends, it is past",
  cd({starts_on: "2026-09-08", ends_on: "2026-09-11"}) === "yesterday",
  cd({starts_on: "2026-09-08", ends_on: "2026-09-11"}));
ok("an undated event has no countdown", cd({title: "x"}) === "");

// ── A set event is named by BOTH halves ─────────────────────────────────────
// Two failures, opposite directions, both shipped. The title alone gives a month
// two identical "Attack of the Vine!" chips a week apart. The phase alone gives
// a cell reading "Prerelease", which says something is happening without saying
// what. Only the pair identifies it.
ok("a set event is named set + phase",
  calEventTitle({kind: "set", title: "Hyperia City", subtitle: "Prerelease"}) === "Hyperia City Prerelease",
  calEventTitle({kind: "set", title: "Hyperia City", subtitle: "Prerelease"}));
ok("a month chip uses that same name",
  calChipLabel({kind: "set", title: "Attack of the Vine!", subtitle: "LGS release"}) === "Attack of the Vine! LGS release");
ok("a non-set event keeps its own name",
  calEventTitle({kind: "dlc", title: "DLC London", subtitle: "Disney Lorcana Challenge"}) === "DLC London");
ok("a set with no phase falls back to its name",
  calEventTitle({kind: "set", title: "Some Set"}) === "Some Set");
// The phase is folded into the title, so repeating it in the meta line would
// print it twice in the same row.
ok("a set event reports no separate subtitle",
  calEventSubtitle({kind: "set", title: "Hyperia City", subtitle: "Prerelease"}) === null);
ok("a DLC still reports its subtitle",
  calEventSubtitle({kind: "dlc", title: "DLC London", subtitle: "Disney Lorcana Challenge"})
    === "Disney Lorcana Challenge");

// ── Regions ─────────────────────────────────────────────────────────────────
ok("US is North America", calRegionOf("US") === "na");
ok("lowercase still resolves", calRegionOf("gb") === "eu");
ok("Japan and Australia share Asia-Pacific",
  calRegionOf("JP") === "apac" && calRegionOf("AU") === "apac");
ok("Brazil is Latin America", calRegionOf("BR") === "latam");
// ⚠ An ungeocoded row must stay REACHABLE. Dropping unknowns would make a row
// we simply have not placed yet invisible under every region, including "all".
ok("an unknown country falls into Elsewhere", calRegionOf("ZZ") === "other");
ok("a missing country falls into Elsewhere", calRegionOf(null) === "other");
ok("no country appears in two regions", (() => {
  const seen = new Set();
  for (const r of CALENDAR_REGIONS) for (const c of r.cc) { if (seen.has(c)) return false; seen.add(c); }
  return true;
})());
ok("'all' matches everything", calMatchesRegion({country: "JP"}, "all")
  && calMatchesRegion({country: null}, "all"));
ok("a region filter excludes other regions", !calMatchesRegion({country: "JP"}, "na"));
ok("a region filter keeps its own", calMatchesRegion({country: "CA"}, "na"));

// ── The mini map ────────────────────────────────────────────────────────────
// Web-Mercator, checked against the known tile for a known place: Greenwich at
// zoom 1 sits at the seam between the four world tiles.
const gm = osmTileLayout(0, 0, 1, 256, 256);
ok("zoom 1 at the origin spans the four world tiles", gm.tiles.length === 4, gm.tiles.length);
ok("the pin is the centre of the box", gm.pinLeft === 128 && gm.pinTop === 128);
const ldn = osmTileLayout(51.5074, -0.1278, 12, 400, 150);
ok("London at z12 lands on the documented tile",
  ldn.tiles.some(t => t.x === 2047 && t.y === 1362),
  ldn.tiles.map(t => `${t.x}/${t.y}`).join(" "));
ok("the tile box is covered with no gaps", (() => {
  const xs = new Set(ldn.tiles.map(t => t.x)), ys = new Set(ldn.tiles.map(t => t.y));
  return ldn.tiles.length === xs.size * ys.size;
})());
ok("every tile overlaps the viewport", ldn.tiles.every(t =>
  t.left > -256 && t.left < 400 && t.top > -256 && t.top < 150));
// ⚠ x WRAPS at the antimeridian — a box straddling it must fetch from the other
// edge of the world, not from a tile index that does not exist.
const fiji = osmTileLayout(-17.7, 179.98, 8, 400, 150);
ok("tile x wraps at the antimeridian instead of overflowing",
  fiji.tiles.every(t => t.x >= 0 && t.x < 256), fiji.tiles.map(t => t.x).join(","));
ok("tile y is never outside the world",
  osmTileLayout(85, 0, 3, 400, 400).tiles.every(t => t.y >= 0 && t.y < 8));
ok("a null position yields no map", osmTileLayout(null, null, 11, 400, 150) === null);
ok("NaN coordinates yield no map", osmTileLayout(NaN, 12, 11, 400, 150) === null);
ok("tile urls point at openstreetmap over https",
  osmTileUrl(ldn.tiles[0]).startsWith("https://tile.openstreetmap.org/"),
  osmTileUrl(ldn.tiles[0]));

// ── One event, one row ──────────────────────────────────────────────────────
// A curated CCQ the linker matched to its Ravensburger Play listing carries that
// listing's event_id. Follow the shop running it and the same tournament arrives
// twice — once as a CCQ, once as a store event. Seven curated rows already carry
// an event_id, so this is not hypothetical.
{
  const curated = [
    {id: "c1", kind: "ccq", title: "Brainwash Cards 2K", starts_on: "2026-09-19", event_id: 853992},
    {id: "c2", kind: "dlc", title: "DLC London", starts_on: "2026-11-13"},
  ];
  const store = [
    {id: "ev:853992", kind: "store", title: "Lorcana X Brainwash Cards 2K CCQ",
     starts_on: "2026-09-19", event_id: 853992},
    {id: "ev:999", kind: "store", title: "GNG Weekly", starts_on: "2026-09-16", event_id: 999},
  ];
  const merged = calendarCombine(curated, store);
  ok("a matched listing is not shown twice", merged.length === 3, merged.length);
  ok("the CURATED row is the one kept — it has the checked name and the venue",
    merged.some(e => e.id === "c1") && !merged.some(e => e.id === "ev:853992"));
  ok("an unmatched store event still shows", merged.some(e => e.id === "ev:999"));
  ok("the result is sorted", merged.every((e, i) => i === 0 || merged[i - 1].starts_on <= e.starts_on));
  // A string id vs a numeric one must still count as the same event.
  ok("event ids compare across string and number",
    calendarCombine([{id: "c", kind: "ccq", title: "x", starts_on: "2026-09-19", event_id: "853992"}],
                    [{id: "s", kind: "store", title: "y", starts_on: "2026-09-19", event_id: 853992}]).length === 1);
  ok("a curated row with no event_id claims nothing",
    calendarCombine([{id: "c", kind: "dlc", title: "x", starts_on: "2026-09-19"}],
                    [{id: "s", kind: "store", title: "y", starts_on: "2026-09-19", event_id: 7}]).length === 2);
  ok("combine tolerates nulls", calendarCombine(null, null).length === 0);
}

// ── The home panel's list pager ─────────────────────────────────────────────
// ⚠ Page 0 must mean NOW, not the head of the list. The pool is sorted oldest
// first and contains years of past set releases, so anchoring on index 0 would
// open the panel on 2023 the moment past events are in scope.
{
  const day = (d) => ({id: "e" + d, kind: "dlc", title: "E" + d, starts_on: d});
  const pool = ["2023-01-01","2024-01-01","2026-09-01","2026-09-20","2026-10-04",
                "2026-11-13","2026-12-18","2027-02-19"].map(day);
  const T = "2026-09-12";
  const w0 = calendarPanelWindow(pool, T, 3, 0);
  ok("page 0 starts at the first unfinished event",
    w0.rows.map(r => r.starts_on).join(",") === "2026-09-20,2026-10-04,2026-11-13",
    w0.rows.map(r => r.starts_on).join(","));
  ok("page 0 is not the head of the pool", w0.start === 3, w0.start);
  ok("page 0 can go back (there IS a past)", w0.canPrev === true);
  ok("page 0 can go forward", w0.canNext === true);
  const w1 = calendarPanelWindow(pool, T, 3, 1);
  ok("paging forward advances by a full page",
    w1.rows.map(r => r.starts_on).join(",") === "2026-12-18,2027-02-19",
    w1.rows.map(r => r.starts_on).join(","));
  ok("the last page cannot go further", w1.canNext === false);
  const wb = calendarPanelWindow(pool, T, 3, -1);
  ok("paging back walks into the past",
    wb.rows.map(r => r.starts_on).join(",") === "2023-01-01,2024-01-01,2026-09-01",
    wb.rows.map(r => r.starts_on).join(","));
  ok("a wholly-past window is flagged so the caller can label it", wb.past === true);
  ok("a window containing the future is not flagged past", w0.past === false);
  ok("the first page cannot go further back", wb.canPrev === false);
  // Overshooting in either direction clamps instead of emptying the box.
  ok("overshooting forward clamps to the last page, short as it is",
    calendarPanelWindow(pool, T, 3, 99).rows.map(r => r.starts_on).join(",") === "2026-12-18,2027-02-19",
    calendarPanelWindow(pool, T, 3, 99).rows.map(r => r.starts_on).join(","));
  // ⚠ No row may appear on two consecutive pages — that is what makes › read as
  // "one page on" rather than "one row on".
  ok("consecutive pages do not overlap", (() => {
    const a = new Set(calendarPanelWindow(pool, T, 3, 0).rows.map(r => r.id));
    return calendarPanelWindow(pool, T, 3, 1).rows.every(r => !a.has(r.id));
  })());
  ok("overshooting backward clamps to the first page",
    calendarPanelWindow(pool, T, 3, -99).start === 0);
  // Nothing ahead: show the most recent instead of going blank.
  const allPast = ["2026-01-01","2026-02-01","2026-03-01"].map(day);
  const wp = calendarPanelWindow(allPast, T, 2, 0);
  ok("with nothing ahead it shows the most recent, not nothing",
    wp.rows.map(r => r.starts_on).join(",") === "2026-02-01,2026-03-01",
    wp.rows.map(r => r.starts_on).join(","));
  ok("and says it is past", wp.past === true);
  // An in-progress multi-day event is NOT past — same rule as the countdown.
  const live = [{id: "l", kind: "dlc", title: "L", starts_on: "2026-09-11", ends_on: "2026-09-13"}];
  ok("an event running right now anchors page 0",
    calendarPanelWindow(live, T, 3, 0).rows.length === 1 &&
    calendarPanelWindow(live, T, 3, 0).past === false);
  ok("an empty pool yields an empty window",
    calendarPanelWindow([], T, 3, 0).rows.length === 0);
  ok("a pool shorter than a page has no paging",
    calendarPanelWindow([day("2026-10-01")], T, 3, 0).canNext === false &&
    calendarPanelWindow([day("2026-10-01")], T, 3, 0).canPrev === false);
}
ok("the pager label is compact", calShortDay("2026-09-12") === "Sep 12", calShortDay("2026-09-12"));
ok("a bad date has no label", calShortDay("nope") === "");

// ── Per-store event-kind toggles ────────────────────────────────────────────
// A shop's weeklies outnumber its Set Championships ~10:1, so a blanket follow
// buried the events people follow shops FOR. These decide what a follow delivers.
{
  const sub = (kinds) => kinds === undefined ? {kind: "store", ref: "1", meta: {}}
                                             : {kind: "store", ref: "1", meta: {kinds}};
  // ⚠ Backwards compatibility is the whole reason "absent" means "everything":
  // every follow made before this shipped has no meta.kinds.
  ok("a follow with no selection delivers everything",
    calStoreAllows(sub(), "sc") && calStoreAllows(sub(), "prerelease") && calStoreAllows(sub(), "other"));
  ok("so does a follow with no meta at all",
    calStoreAllows({kind: "store", ref: "1"}, "other"));
  ok("an empty array is treated as unset, not as 'nothing'",
    calStoreAllows(sub([]), "other"));
  ok("a narrowed follow keeps what it names", calStoreAllows(sub(["sc"]), "sc"));
  ok("and drops what it does not", !calStoreAllows(sub(["sc"]), "other"));
  ok("two kinds keep both", calStoreAllows(sub(["sc","prerelease"]), "prerelease")
    && !calStoreAllows(sub(["sc","prerelease"]), "other"));
  // RPH only sets sc / prerelease / other, but an unrecognised kind must not
  // vanish silently — it falls in with the catch-all, as the feed itself does.
  ok("an unknown kind rides with the catch-all",
    calStoreAllows(sub(["other"]), "weird-new-kind") && !calStoreAllows(sub(["sc"]), "weird-new-kind"));
  ok("a null kind rides with the catch-all", calStoreAllows(sub(["other"]), null));

  ok("an unset follow reports every kind",
    calStoreKindsOf(sub()).join(",") === CAL_STORE_KIND_KEYS.join(","), calStoreKindsOf(sub()).join(","));
  // Stored order must not leak into the UI, or the chips reorder themselves.
  ok("the reported order is the canonical one, not the stored one",
    calStoreKindsOf(sub(["other","sc"])).join(",") === "sc,other",
    calStoreKindsOf(sub(["other","sc"])).join(","));
  ok("junk in the stored array is dropped",
    calStoreKindsOf(sub(["sc","nonsense"])).join(",") === "sc");
  ok("the catch-all is last, so the noisiest toggle is the easy one to find",
    CAL_STORE_KIND_KEYS[CAL_STORE_KIND_KEYS.length - 1] === "other");
  ok("every store kind has a short label and a long one",
    CAL_STORE_KINDS.every(k => k.label && k.long && k.label.length <= 12));
}

// -- Hiding one event -------------------------------------------------------
// ⚠ The graded view's per-card Hide was KILLED because a hidden thing became
// invisible with no way back. These pin the defences that stop a repeat.
{
  const ev = (id) => ({id, kind: "ccq", title: "E" + id, starts_on: "2026-10-04"});
  const pool = ["a", "ev:12", "set:Hyperia City:prerelease"].map(ev);
  const subs = [
    {kind: "hide", ref: "ev:12"},
    {kind: "store", ref: "2308"},
  ];
  const hidden = calendarHiddenSet(subs);
  ok("only hide rows make the hidden set", hidden.size === 1 && hidden.has("ev:12"));
  ok("a hidden event is dropped",
    calendarApplyHidden(pool, hidden, new Set()).map(e => e.id).join(",") === "a,set:Hyperia City:prerelease");
  ok("everything else survives", calendarApplyHidden(pool, hidden, new Set()).length === 2);
  ok("no hides means no filtering", calendarApplyHidden(pool, new Set(), new Set()).length === 3);

  // ⚠ THE STRUCTURAL BYPASS. "Add this to my calendar" is a clearer statement of
  // intent than a hide you may not remember making. Without this rule a stale
  // hide silently defeats a deliberate add -- precisely the bug that killed the
  // graded version.
  ok("an explicitly saved event is never hidden",
    calendarApplyHidden(pool, hidden, new Set(["ev:12"])).length === 3);
  ok("the bypass is per-event, not a blanket off-switch",
    calendarApplyHidden(pool, new Set(["a", "ev:12"]), new Set(["ev:12"])).map(e => e.id).join(",")
      === "ev:12,set:Hyperia City:prerelease");

  // Every id shape the calendar renders has to be hideable.
  ok("a derived set release can be hidden",
    calendarApplyHidden(pool, new Set(["set:Hyperia City:prerelease"]), new Set()).length === 2);
  ok("a curated uuid can be hidden", calendarApplyHidden(pool, new Set(["a"]), new Set()).length === 2);
  ok("hidden ids compare as strings", calendarApplyHidden([{id: 12, kind: "ccq", title: "x", starts_on: "2026-10-04"}],
    new Set(["12"]), new Set()).length === 0);
  ok("applyHidden tolerates nulls", calendarApplyHidden(null, null, null).length === 0);
  // ⚠ The bypass is defence in depth, not the primary mechanism: add() keeps
  // saved and hidden mutually exclusive, so both rows should never coexist. If
  // they ever do (stale storage, a half-synced device), THIS is what decides —
  // and it decides in favour of the thing the user asked to see.
  ok("if both rows somehow exist, the save wins",
    calendarApplyHidden([ev("z")], new Set(["z"]), new Set(["z"])).length === 1);
}

// -- Event art -------------------------------------------------------------
// A coloured dot said which filter something came from, not what it is. Where
// real art exists we show it; where it does not, a drawn glyph. Nothing here
// reaches for an official Disney/Ravensburger mark.
{
  const sealed = [
    {name: "Disney Lorcana: Hyperia City Booster Box Case", image_url: "case.jpg"},
    {name: "Disney Lorcana: Hyperia City Booster Box",      image_url: "box.jpg"},
    {name: "Disney Lorcana: Hyperia City Booster Pack",     image_url: "pack.jpg"},
    {name: "Disney Lorcana: Hyperia City Illumineer's Trove", image_url: "trove.jpg"},
    {name: "Rapunzel Collector's Gift Set",                 image_url: "gift.jpg"},
    {name: "Disney Lorcana: Winterspell Booster Pack",      image_url: "winter.jpg"},
    {name: "Some Product With No Picture",                  image_url: null},
  ];
  const idx = calendarArtIndex(sealed, ["Hyperia City", "Winterspell", "Rapunzel Collector's Gift Set",
                                        "Some Product With No Picture", "Nothing At All"]);
  // ⚠ The plain Booster Pack IS the set's art, and it is the one product every
  // set has. A Case is a distributor carton - a photo of cardboard.
  ok("a set resolves to its booster pack, not its box or case",
    idx.get("hyperia city") === "pack.jpg", idx.get("hyperia city"));
  ok("a case is never chosen", [...idx.values()].every(v => v !== "case.jpg"));
  ok("a product resolves to its own photo",
    idx.get("rapunzel collector's gift set") === "gift.jpg");
  ok("a product with no image is absent rather than null",
    !idx.has("some product with no picture"));
  ok("an unmatched name is absent", !idx.has("nothing at all"));
  ok("one set does not borrow another set's art", idx.get("hyperia city") !== "winter.jpg");

  const ev = (k, extra) => ({id: "x", kind: k, title: "Hyperia City", starts_on: "2026-10-16", ...extra});
  ok("a set event finds its art", calendarEventArt(ev("set"), idx) === "pack.jpg");
  ok("a set event prefers set_name over title",
    calendarEventArt(ev("set", {set_name: "Winterspell"}), idx) === "winter.jpg");
  // ⚠ The curated override always wins - it is the only way to correct a wrong
  // automatic match, and a wrong picture is worse than no picture.
  ok("a curated image_url beats the automatic match",
    calendarEventArt(ev("set", {image_url: "mine.png"}), idx) === "mine.png");
  ok("a curated image_url works on a kind that resolves nothing",
    calendarEventArt(ev("dlc", {image_url: "mine.png"}), idx) === "mine.png");
  // A Challenge or a qualifier has no product behind it and must not inherit a
  // set's pack art just because its title mentions the set.
  ok("a dlc does not borrow set art", calendarEventArt(ev("dlc"), idx) === null);
  ok("a ccq does not borrow set art", calendarEventArt(ev("ccq"), idx) === null);
  ok("a store event does not borrow set art", calendarEventArt(ev("store"), idx) === null);
  ok("no index means no art", calendarEventArt(ev("set"), null) === null);
  ok("art tolerates nulls", calendarEventArt(null, idx) === null
    && calendarArtIndex(null, null).size === 0);
}
ok("the kinds with no product behind them use drawn glyphs", (() => {
  const by = Object.fromEntries(CALENDAR_KINDS.map(k => [k.key, k.icon]));
  return by.dlc === "trophy" && by.ccq === "medal" && by.product === "gift" && by.store === "store";
})());

// ── Store entries ───────────────────────────────────────────────────────────
const storeEv = calendarStoreEntry({
  event_id: 853992, name: "Lorcana X Brainwash Cards 2K CCQ", store_name: "Brainwash Cards",
  store_id: 42, start_datetime: "2026-09-19T15:00:00+00:00", timezone: "America/New_York",
  city: "Philadelphia", state: "PA", kind: "other", url: "https://tcg.ravensburgerplay.com/events/853992",
});
ok("a store entry lands on its local day", storeEv.starts_on === "2026-09-19", storeEv.starts_on);
ok("a store entry is kind=store", storeEv.kind === "store");
ok("a store entry keeps its instant for the .ics", !!storeEv.starts_at);
ok("a store entry names the store and the town",
  /Brainwash Cards/.test(storeEv.location) && /Philadelphia, PA/.test(storeEv.location), storeEv.location);
ok("a nameless store event still has a title",
  calendarStoreEntry({event_id: 1, name: "", store_name: "Shop", start_datetime: "2026-09-19T15:00:00Z"}).title === "Shop");
ok("an undated store event is dropped",
  calendarStoreEntry({event_id: 1, name: "x", start_datetime: null}) === null);

// ── .ics ────────────────────────────────────────────────────────────────────
const NOW = Date.parse("2026-09-12T12:00:00Z");
const ics = buildIcs([
  {id: "set:Winterspell:lgs", kind: "set", title: "Winterspell", subtitle: "LGS release", starts_on: "2026-02-13"},
  {id: "dlc-na", kind: "dlc", title: "NA Championship", subtitle: "Disney Lorcana Challenge",
   starts_on: "2026-08-28", ends_on: "2026-08-30", location: "Disneyland Hotel, Anaheim, CA",
   url: "https://example.test/na"},
  storeEv,
], {nowMs: NOW, name: "Lorcana calendar"});

ok("the file uses CRLF line endings", ics.includes("\r\n") && !/[^\r]\n/.test(ics));
ok("it opens and closes a VCALENDAR",
  ics.startsWith("BEGIN:VCALENDAR\r\n") && ics.trimEnd().endsWith("END:VCALENDAR"));
ok("VERSION comes before the events", ics.indexOf("VERSION:2.0") < ics.indexOf("BEGIN:VEVENT"));
ok("every event opens and closes",
  (ics.match(/BEGIN:VEVENT/g) || []).length === 3 &&
  (ics.match(/END:VEVENT/g) || []).length === 3);
ok("every event carries a DTSTAMP", (ics.match(/DTSTAMP:/g) || []).length === 3);
ok("every event carries a UID", (ics.match(/\r\nUID:/g) || []).length === 3);

// ⚠ THE classic .ics bug. DTEND is exclusive: a one-day event on the 13th ends
// on the 14th. Emit 20260213 for both and Google renders it while Apple
// Calendar silently drops the event.
ok("a one-day all-day event ends on the NEXT day",
  ics.includes("DTSTART;VALUE=DATE:20260213") && ics.includes("DTEND;VALUE=DATE:20260214"),
  (ics.match(/DTEND;VALUE=DATE:2026021\d/) || [])[0]);
ok("a three-day event ends the day after the last day",
  ics.includes("DTSTART;VALUE=DATE:20260828") && ics.includes("DTEND;VALUE=DATE:20260831"),
  (ics.match(/DTEND;VALUE=DATE:202608\d\d/) || [])[0]);
ok("a timed event is stamped, not all-day",
  ics.includes("DTSTART:20260919T150000Z"), (ics.match(/DTSTART:\S+/) || [])[0]);
ok("a timed event with no end gets a 2h default",
  ics.includes("DTEND:20260919T170000Z"), (ics.match(/DTEND:\d\S+/) || [])[0]);
ok("the summary uses the display name",
  ics.includes("SUMMARY:Winterspell LGS release"),
  ics.split(String.fromCharCode(13,10)).find(l => l.startsWith("SUMMARY:Winterspell")));
ok("a DLC summary keeps both halves",
  ics.includes("SUMMARY:NA Championship — Disney Lorcana Challenge"),
  ics.split(String.fromCharCode(13,10)).find(l => l.startsWith("SUMMARY:NA")));
ok("a location is carried", ics.includes("LOCATION:Disneyland Hotel"));
ok("a url is carried", ics.includes("URL:https://example.test/na"));
ok("an undated row is skipped rather than emitting a broken VEVENT",
  (buildIcs([{id: "bad", title: "No date"}], {nowMs: NOW}).match(/BEGIN:VEVENT/g) || []).length === 0);

// Escaping: RFC 5545 reserves \ ; , and newline inside a TEXT value. A store
// called "Cards, Comics & Games" unescaped truncates the summary at the comma
// in some clients and corrupts the property in others.
ok("commas are escaped", icsEscape("Cards, Comics") === "Cards\\, Comics");
ok("semicolons are escaped", icsEscape("a;b") === "a\\;b");
ok("backslashes are escaped FIRST", icsEscape("a\\b") === "a\\\\b");
ok("newlines become \\n", icsEscape("a\nb") === "a\\nb");
ok("escaping order does not double-escape a comma",
  icsEscape("a\\,b") === "a\\\\\\,b", icsEscape("a\\,b"));

// ⚠ Folding is measured in OCTETS, and a fold inside a multi-byte character
// makes the whole file unreadable rather than merely ugly.
const longAscii = "SUMMARY:" + "x".repeat(200);
const foldedAscii = icsFold(longAscii);
ok("a long line is folded", foldedAscii.includes("\r\n"));
ok("every folded segment is <= 75 octets",
  foldedAscii.split("\r\n").every(l => enc.encode(l).length <= 75),
  foldedAscii.split("\r\n").map(l => enc.encode(l).length).join(","));
ok("continuation lines begin with a space",
  foldedAscii.split("\r\n").slice(1).every(l => l.startsWith(" ")));
ok("unfolding restores the original",
  foldedAscii.split("\r\n").map((l, i) => i ? l.slice(1) : l).join("") === longAscii);
const longUtf8 = "SUMMARY:" + "日本語のイベント".repeat(12);
const foldedUtf8 = icsFold(longUtf8);
ok("a multi-byte line folds within 75 octets",
  foldedUtf8.split("\r\n").every(l => enc.encode(l).length <= 75),
  foldedUtf8.split("\r\n").map(l => enc.encode(l).length).join(","));
ok("no multi-byte character is split by a fold",
  foldedUtf8.split("\r\n").map((l, i) => i ? l.slice(1) : l).join("") === longUtf8);
ok("a short line is left alone", icsFold("SUMMARY:hi") === "SUMMARY:hi");
ok("the built file folds nothing over 75 octets",
  ics.split("\r\n").every(l => enc.encode(l).length <= 75),
  ics.split("\r\n").filter(l => enc.encode(l).length > 75)[0]);

// ── Google Calendar handoff ─────────────────────────────────────────────────
const g = googleCalUrl({title: "NA Championship", subtitle: "Disney Lorcana Challenge",
  starts_on: "2026-08-28", ends_on: "2026-08-30", location: "Anaheim", url: "https://example.test/na"});
ok("google url points at the template endpoint",
  g.startsWith("https://calendar.google.com/calendar/render?"));
// Same exclusive-end rule as .ics — and the same silent failure if it is wrong.
ok("google all-day range uses an exclusive end",
  decodeURIComponent(new URL(g).searchParams.get("dates")) === "20260828/20260831",
  new URL(g).searchParams.get("dates"));
ok("google url carries the joined title",
  new URL(g).searchParams.get("text") === "NA Championship — Disney Lorcana Challenge");
ok("google url carries location and details",
  new URL(g).searchParams.get("location") === "Anaheim" &&
  /example\.test/.test(new URL(g).searchParams.get("details")));
const gTimed = googleCalUrl(storeEv);
ok("google timed range is stamped",
  /^\d{8}T\d{6}Z\/\d{8}T\d{6}Z$/.test(new URL(gTimed).searchParams.get("dates")),
  new URL(gTimed).searchParams.get("dates"));
ok("an undated event yields no google url", googleCalUrl({title: "x"}) === null);

// ── The kind table is the contract ──────────────────────────────────────────
ok("the four curated kinds plus stores are offered",
  CALENDAR_KIND_KEYS.join(",") === "set,product,dlc,ccq,store", CALENDAR_KIND_KEYS.join(","));
ok("every kind has an icon key and a hue",
  CALENDAR_KINDS.every(k => k.icon && k.hue));
// A chip saying "CCQ" with no explanation anywhere is the reason this exists.
ok("every kind has a long-form explanation",
  CALENDAR_KIND_KEYS.every(k => (CALENDAR_KIND_LONG[k] || "").length > 12));
ok("DLC and CCQ are spelled out somewhere",
  /Disney Lorcana Challenge/.test(CALENDAR_KIND_LONG.dlc) &&
  /Challenge Championship Qualifier/.test(CALENDAR_KIND_LONG.ccq));
// No emoji in the UI — the icons rule. A pictograph must come from UI_ICON_PATHS.
ok("no kind smuggles in an emoji",
  !CALENDAR_KINDS.some(k => /\p{Extended_Pictographic}/u.test(k.label + k.icon)));
ok("every kind icon exists in UI_ICON_PATHS",
  CALENDAR_KINDS.every(k => new RegExp("^\\s*" + k.icon + ":\\s", "m").test(src)),
  CALENDAR_KINDS.filter(k => !new RegExp("^\\s*" + k.icon + ":\\s", "m").test(src)).map(k => k.icon).join(","));

console.log(failed ? `\n${failed} FAILED` : "\nall calendar checks passed");
process.exit(failed ? 1 : 0);
