// test_calendar.mjs — guards the Almanac's pure core.
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
  grabLine("const CALENDAR_KIND_BY_KEY = "),
  grabLine("const LORCANA_ART = "),
  grab("const LORCANA_MARKS = {", NL + "};"),
  grab("const CALENDAR_KIND_LONG = {", NL + "};"),
  grabLine("const SET_RELEASE_LABELS = "),
  grabLine("const SET_RELEASE_PHASES = "),
  grab("const calEventTitle = (ev) => !ev ? \"\"", ": (ev.title || \"\");"),
  grab("const calStoreEventName = (ev) => {", NL + "};"),
  grab("const calEventSubtitle = (ev) => !ev ? null", ": (ev.subtitle || null);"),
  grabLine("const calEventFullLabel = "),
  grab("const CALENDAR_REGIONS = [", NL + "];"),
  grab("const _CAL_REGION_BY_CC = (() => {", NL + "})();"),
  grabLine("const calRegionOf = "),
  grab("const calRegionSet = (region) => {", NL + "};"),
  grab("const calMatchesRegion = (ev, region) => {", NL + "};"),
  grab('const searchNorm = (s) => (s||"")', '/g, "");'),
  grab("const calMatchesQuery = (ev, q) => {", NL + "};"),
  grabLine("const OSM_TILE_PX = "),
  grab("const osmTileLayout = (lat, lng, zoom, w, h) => {", NL + "};"),
  grabLine("const osmTileUrl = "),
  grabLine("const osmViewUrl = "),
  grab("const calendarSetEntries = (releaseDates) => {", NL + "};"),
  grab("const calendarProductEntries = (products) => {", NL + "};"),
  grabLine("const _calSetKey = "),
  grab("const calendarMergeEvents = (derived, rows) => {", NL + "};"),
  grabLine("const _calKindRank = "),
  grab("const _calPhaseRank = (e) => {", NL + "};"),
  grab("const calendarSort = (events) =>", "|| _calPhaseRank(a) - _calPhaseRank(b));"),
  grab("const calendarMergeStore = (followed, near) => {", NL + "};"),
  grab("const calendarCombine = (curated, store) => {", NL + "};"),
  grabLine("const CAL_ART_PREF = "),
  grab("const calendarArtIndex = (sealedRows, names) => {", NL + "};"),
  grab("const calendarEventArt = (ev, artIndex) => {", NL + "};"),
  grabLine("const CAL_SET_PHASE_ICONS = "),
  grab("const _calSetPhase = (ev) => {", NL + "};"),
  grabLine("const CAL_STORE_KIND_ICONS = "),
  grab("const calendarEventIcon = (ev, artIndex) => {", NL + "};"),
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
  grab("const calChipLabel = (ev) => (ev && ev.kind === \"store\")", ": calEventTitle(ev);"),
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
  grabLine("const calMonthOf = "),
  grab("const calMonthLabelShort = (ym) => {", NL + "};"),
  grab("const calShiftMonth = (ym, n) => {", NL + "};"),
  grabLine("const CAL_TL_MONTHS = "),
  grabLine("const CAL_TL_MIN_PX = "),
  grabLine("const CAL_TL_LABEL_PX = "),
  grabLine("const CAL_TL_GAP_PX = "),
  grabLine("const CAL_TL_RELEASE_LANE = "),
  grabLine("const CAL_TL_STORE_PREFIX = "),
  grabLine("const CAL_TL_CIRCUIT_LANE = "),
  grabLine("const CAL_TL_GROUP_MODES = "),
  grabLine("const CAL_TL_NEAR_LANE = "),
  grabLine("const CAL_TL_MAX_STORE_LANES = "),
  grabLine("const CAL_TL_STORE_REST = "),
  grabLine("const CAL_TL_STORE_ROWS = "),
  grab("const calTimelineLane = (ev, group) => {", NL + "};"),
  grab("const CAL_TL_GROUP_OF = (key) =>", '  : "circuit";'),
  grabLine("const CAL_TL_LABELLED_RPH = "),
  grab("const calTimelineLabels = (ev) =>", "CAL_TL_LABELLED_RPH.has(ev.rph_kind);"),
  grab("const _calTlEnd = (ev) => {", NL + "};"),
  grab("const calTlLabelParts = (ev, range, below) => {", NL + "};"),
  grab("const _calTlStack = (items, labelW, maxRows) => {", NL + "};"),
  grab("const calendarTimeline = (events, opts) => {", NL + "};"),
  "export {calAddDays, calTzYmd, calendarSetEntries, calendarProductEntries, calendarEventIcon,",
  " LORCANA_MARKS,",
  " calendarMergeEvents, calendarStoreEntry,",
  " calendarEventDays, calendarMonthGrid, calendarUpcoming, icsEscape, icsFold, buildIcs,",
  " googleCalUrl, calCountdown, calChipLabel, calEventTitle, calEventSubtitle, calEventFullLabel,",
  " calRegionOf, calMatchesRegion, calRegionSet, calMatchesQuery, calendarMergeStore, calTlLabelParts,",
  " osmTileLayout, osmTileUrl, CALENDAR_REGIONS, calendarCombine,",
  " calendarPanelWindow, calShortDay, calStoreKindsOf, calStoreAllows, CAL_STORE_KINDS, CAL_STORE_KIND_KEYS,",
  " calendarHiddenSet, calendarApplyHidden, calendarArtIndex, calendarEventArt,",
  " CALENDAR_KINDS, CALENDAR_KIND_KEYS, CALENDAR_KIND_LONG, SET_RELEASE_LABELS,",
  " calendarTimeline, calTimelineLane, calTimelineLabels, CAL_TL_MONTHS, CAL_TL_MIN_PX,",
  " CAL_TL_GROUP_MODES, CAL_TL_CIRCUIT_LANE, calMonthLabelShort,",
  " CAL_TL_LABEL_PX, CAL_TL_MAX_STORE_LANES, CAL_TL_STORE_ROWS, CAL_TL_STORE_REST};",
].join(NL)));

const {
  calAddDays, calTzYmd, calendarSetEntries, calendarProductEntries, calendarEventIcon, LORCANA_MARKS,
  calendarMergeEvents, calendarStoreEntry,
  calendarEventDays, calendarMonthGrid, calendarUpcoming, icsEscape, icsFold, buildIcs,
  googleCalUrl, calCountdown, calChipLabel, calEventTitle, calEventSubtitle, calEventFullLabel,
  calRegionOf, calMatchesRegion, calRegionSet, calMatchesQuery, calendarMergeStore, calTlLabelParts,
  osmTileLayout, osmTileUrl, CALENDAR_REGIONS, calendarCombine,
  calendarPanelWindow, calShortDay, calStoreKindsOf, calStoreAllows, CAL_STORE_KINDS,
  CAL_STORE_KIND_KEYS, calendarHiddenSet, calendarApplyHidden,
  calendarArtIndex, calendarEventArt,
  CALENDAR_KINDS, CALENDAR_KIND_KEYS, CALENDAR_KIND_LONG, SET_RELEASE_LABELS,
  calendarTimeline, calTimelineLane, calTimelineLabels, CAL_TL_MONTHS, CAL_TL_MIN_PX,
  CAL_TL_GROUP_MODES, CAL_TL_CIRCUIT_LANE, calMonthLabelShort,
  CAL_TL_LABEL_PX, CAL_TL_MAX_STORE_LANES, CAL_TL_STORE_ROWS, CAL_TL_STORE_REST,
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

// ── A STORE event is named by its STORE ────────────────────────────────────
// Reported from the wild: a row reading "Core Constructed" does not say which
// shop it is, and a calendar built by FOLLOWING STORES is nothing but that
// question. RPH stores the pair the other way round, so this is a display swap
// — and it has to stay a display swap, because ev.subtitle is what the scout
// hand-off reads as the store name.
const locals = {kind: "store", title: "Core Constructed", subtitle: "Dice Dojo"};
ok("a store event leads with the store", calEventTitle(locals) === "Dice Dojo",
  calEventTitle(locals));
ok("the event's own name is the second line",
  calEventSubtitle(locals) === "Core Constructed", calEventSubtitle(locals));
ok("one line names both, store first",
  calEventFullLabel(locals) === "Dice Dojo — Core Constructed", calEventFullLabel(locals));
// A month cell is one line and its ellipsis is at the END, so leading with the
// store is what makes the store the half that survives a narrow column.
ok("a store chip carries the pair, store first",
  calChipLabel(locals) === "Dice Dojo · Core Constructed", calChipLabel(locals));
// ...but ONLY for store rows. A curated subtitle is the category, which the
// kind icon beside the chip already says.
ok("a curated chip does NOT gain its category",
  calChipLabel({kind: "ccq", title: "White Rabbit CCQ", subtitle: "Challenge Championship Qualifier"})
    === "White Rabbit CCQ");
// Printing the store twice down two stacked lines reads as a bug, and RPH event
// names carry the store about as often as not.
ok("a name that is just the store leaves no second line",
  calEventSubtitle({kind: "store", title: "Dice Dojo", subtitle: "Dice Dojo"}) === null);
ok("a store-prefixed name is trimmed to the part that is new",
  calEventSubtitle({kind: "store", title: "Dice Dojo Core Constructed", subtitle: "Dice Dojo"})
    === "Core Constructed",
  calEventSubtitle({kind: "store", title: "Dice Dojo Core Constructed", subtitle: "Dice Dojo"}));
ok("a separator after the store prefix goes with it",
  calEventSubtitle({kind: "store", title: "Dice Dojo - Core Constructed", subtitle: "Dice Dojo"})
    === "Core Constructed");
ok("a store SUFFIX is trimmed too",
  calEventSubtitle({kind: "store", title: "Friday Night Lorcana Dice Dojo", subtitle: "Dice Dojo"})
    === "Friday Night Lorcana",
  calEventSubtitle({kind: "store", title: "Friday Night Lorcana Dice Dojo", subtitle: "Dice Dojo"}));
ok("case does not defeat the trim",
  calEventSubtitle({kind: "store", title: "DICE DOJO Core Constructed", subtitle: "Dice Dojo"})
    === "Core Constructed");
// A row RPH gave no store name for must still say something.
ok("no store name falls back to the event name",
  calEventTitle({kind: "store", title: "Core Constructed", subtitle: ""}) === "Core Constructed");
ok("no store name still reports the event name",
  calEventSubtitle({kind: "store", title: "Core Constructed", subtitle: ""}) === "Core Constructed");
// calendarStoreEntry is what actually builds these, so check the real shape and
// not only hand-written fixtures.
{
  const e = calendarStoreEntry({event_id: 9, name: "Core Constructed", store_name: "Dice Dojo",
    start_datetime: "2026-09-17T23:00:00Z", timezone: "America/Chicago", city: "Chicago", state: "IL"});
  ok("a real store entry renders store over event",
    calEventTitle(e) === "Dice Dojo" && calEventSubtitle(e) === "Core Constructed",
    calEventTitle(e) + " / " + calEventSubtitle(e));
  ok("the scout hand-off still reads the store off ev.subtitle", e.subtitle === "Dice Dojo");
}

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
], {nowMs: NOW, name: "Lorcana Almanac"});

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
// The downloaded entry is read weeks later, in a calendar app full of other
// things, where "Core Constructed" alone names nothing at all.
ok("a store summary names the shop first",
  buildIcs([{kind: "store", title: "Core Constructed", subtitle: "Dice Dojo",
             starts_on: "2026-09-13", id: "ev:1"}], {nowMs: 0})
    .includes("SUMMARY:Dice Dojo — Core Constructed"),
  buildIcs([{kind: "store", title: "Core Constructed", subtitle: "Dice Dojo",
             starts_on: "2026-09-13", id: "ev:1"}], {nowMs: 0})
    .split(String.fromCharCode(13,10)).find(l => l.startsWith("SUMMARY:")));
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

// ── One icon per kind of thing that happens ─────────────────────────────────
// The reported bug was that a Set Championship and a Tuesday league night drew
// the same shopfront, and all three of a set's dates drew the same booster
// pack. Both are "the icon came from the CHIP, not from the event", so what
// these check is that no two DIFFERENT things can end up looking the same.
const icoOf = (ev) => { const r = calendarEventIcon(ev); return `${r.icon}|${r.hue}|${r.img || ""}`; };

const setPhaseIcons = ["Prerelease", "LGS release", "Retail release"]
  .map(sub => icoOf({kind: "set", title: "Hyperia City", subtitle: sub}));
ok("a set's three dates get three different icons",
  new Set(setPhaseIcons).size === 3, setPhaseIcons.join(" / "));

const storeIcons = ["sc", "prerelease", "other"]
  .map(k => icoOf({kind: "store", title: "X", rph_kind: k}));
ok("an SC, a store prerelease and a league night get three different icons",
  new Set(storeIcons).size === 3, storeIcons.join(" / "));
// ...but they stay ONE family, or "at a shop I follow" stops being readable
// as a group at a glance.
ok("all three store kinds keep the store hue",
  new Set(["sc", "prerelease", "other"].map(k =>
    calendarEventIcon({kind: "store", rph_kind: k}).hue)).size === 1);
ok("an unknown rph_kind falls back to the store glyph, never to a blank",
  calendarEventIcon({kind: "store", rph_kind: "wat"}).icon === "store");

ok("a DLC and a CCQ carry different official marks",
  calendarEventIcon({kind: "dlc"}).img === LORCANA_MARKS.challengeBadge &&
  calendarEventIcon({kind: "ccq"}).img === LORCANA_MARKS.lorcanaHex);

// ⚠ The regression this guards: every set date resolved the same booster-pack
// photo, which sat ON TOP of the glyph and made the three phases identical
// again however different their glyphs were.
const artIdx = new Map([["hyperia city", "https://cdn/pack.png"]]);
ok("a set date resolves no automatic photo at icon size",
  calendarEventIcon({kind: "set", title: "Hyperia City", subtitle: "Prerelease",
                     set_name: "Hyperia City"}, artIdx).img === null);
ok("a product still resolves its own photo",
  calendarEventIcon({kind: "product", title: "Hyperia City"}, artIdx).img === "https://cdn/pack.png");
ok("a curated image_url still overrides everything",
  calendarEventIcon({kind: "set", title: "Hyperia City", subtitle: "Prerelease",
                     image_url: "https://cdn/curated.png"}, artIdx).img === "https://cdn/curated.png");
// The phase is read out of the SUBTITLE, which is the merge key against
// calendar_events — so a curated row that spells it differently still lands on
// the right glyph rather than silently dropping to the category default.
ok("the phase is matched case- and wording-insensitively",
  calendarEventIcon({kind: "set", subtitle: "PRE-RELEASE"}).icon ===
  calendarEventIcon({kind: "set", subtitle: "Prerelease"}).icon);
ok("a set row with no subtitle still gets an icon",
  !!calendarEventIcon({kind: "set", title: "Fabled"}).icon);

// ⚠ Every recent Lorcana set opens its prerelease weekend on the SAME Friday the
// shops may first sell it, so two rows share a day AND a title — and the title
// tiebreak is then a coin flip decided by whether a phase came from the const or
// from calendar_events. They have to read in the order they happen.
const sameDay = calendarMergeEvents([], [
  {id: "r", kind: "set", title: "Hyperia City", subtitle: "Retail release", starts_on: "2026-10-16"},
  {id: "l", kind: "set", title: "Hyperia City", subtitle: "LGS release", starts_on: "2026-10-16"},
  {id: "p", kind: "set", title: "Hyperia City", subtitle: "Prerelease", starts_on: "2026-10-16"},
]).map(e => e.subtitle);
ok("two of a set's dates on one day sort prerelease → LGS → retail",
  sameDay.join(" < ") === "Prerelease < LGS release < Retail release", sameDay.join(" < "));

// ── Derived product releases ────────────────────────────────────────────────
const PRODUCTS = [
  {title: "Illumineer's Quest: The Great Hunny Rescue", on: "2026-10-02", notes: "n"},
  {title: "Hyperia City Beast Gift Box", on: "2026-11-13"},
  {title: "Broken", on: "soon"},
];
const prods = calendarProductEntries(PRODUCTS);
ok("a product with an unparseable date is skipped", prods.length === 2, prods.length);
ok("derived products are kind=product and flagged derived",
  prods.every(p => p.kind === "product" && p.derived === true));
ok("a derived product keeps its notes", prods[0].notes === "n");
ok("product entries tolerate null", calendarProductEntries(null).length === 0);

// ⚠ ASYMMETRIC, and both halves have a failure mode. A curated row must
// SUPERSEDE the const's copy (or fixing a date in the table leaves the old one
// sitting beside it), while two curated rows sharing a name must both survive
// (or two years of the same annual gift set collapse into one).
const supersede = calendarMergeEvents(prods, [
  {id: "t", kind: "product", title: "Hyperia City Beast Gift Box", starts_on: "2026-12-04"},
]);
ok("a curated product supersedes the derived one of the same name",
  supersede.filter(e => /Beast Gift Box/.test(e.title)).length === 1, supersede.length);
ok("and the surviving one is the curated row",
  supersede.find(e => /Beast Gift Box/.test(e.title)).starts_on === "2026-12-04");
ok("a derived product with no curated twin survives",
  supersede.some(e => /Hunny Rescue/.test(e.title)));


// ── Timeline mode ───────────────────────────────────────────────────────────
// On a timeline distance IS time, which is the whole reason to draw one — so
// every failure here is a chart that looks completely normal and is lying about
// when something happens. None of them throw.
const TL_OPTS = {fromMonth: "2026-09", months: 12, today: "2026-09-14"};
const tlEv = (id, kind, starts_on, extra) =>
  ({id, kind, title: id, starts_on, ...(extra || {})});
const season = [
  tlEv("kobe", "dlc", "2026-09-06", {country: "JP"}),
  tlEv("bangkok", "dlc", "2026-10-30", {ends_on: "2026-11-01", country: "TH"}),
  tlEv("london", "dlc", "2026-11-13", {ends_on: "2026-11-15", country: "GB"}),
  tlEv("tampa", "dlc", "2026-12-18", {ends_on: "2026-12-20", country: "US"}),
  tlEv("raleigh", "ccq", "2026-09-26", {ends_on: "2026-09-27", country: "US"}),
  tlEv("hyperia", "set", "2026-10-23", {subtitle: "Retail release"}),
  tlEv("quest", "product", "2026-10-02"),
  // Two shops: one you follow that runs an SC AND weeklies, and a second shop.
  tlEv("league", "store", "2026-10-08", {country: "US", store_id: "7", subtitle: "Dice Dojo", rph_kind: "other"}),
  tlEv("league2", "store", "2026-10-15", {country: "US", store_id: "7", subtitle: "Dice Dojo", rph_kind: "other"}),
  tlEv("dojo-sc", "store", "2026-11-07", {country: "US", store_id: "7", subtitle: "Dice Dojo", rph_kind: "sc"}),
  tlEv("gng-pre", "store", "2026-10-16", {country: "US", store_id: "9", subtitle: "Griffonest", rph_kind: "prerelease"}),
  // Not followed — found inside the finder's radius, so its own lane.
  tlEv("far-sc", "store", "2026-11-14", {country: "US", store_id: "22", subtitle: "Far Shop", rph_kind: "sc", near: true}),
];
const tl = calendarTimeline(season, TL_OPTS);
const lane = (k) => tl.lanes.find(l => l.key === k);
// ⚠ THE DEFAULT IS ONE PACKED TRACK, not one row per region — the swimlane
// shape is a global announcement graphic's, drawn for readers it knows nothing
// about, and it spends a third of the chart on two lanes that are near-empty
// all season while asking the same question the region CHIPS already ask.
const tlR = calendarTimeline(season, {...TL_OPTS, group: "region"});
const laneR = (k) => tlR.lanes.find(l => l.key === k);

ok("the window is exactly the months asked for",
  tl.from === "2026-09-01" && tl.to === "2027-08-31", `${tl.from}..${tl.to}`);
ok("one month column per month, in order",
  tl.months_.length === 12 && tl.months_[0].ym === "2026-09" && tl.months_[11].ym === "2027-08");
ok("month widths tile the window exactly",
  Math.abs(tl.months_.reduce((a, m) => a + m.w, 0) - 1) < 1e-9,
  tl.months_.reduce((a, m) => a + m.w, 0));
// Months are not equal thirty-day blocks. A chart that spaces them evenly puts
// every event in a long month up to a day and a half off its true position.
ok("February is drawn narrower than January",
  tl.months_.find(m => m.ym === "2027-02").w < tl.months_.find(m => m.ym === "2027-01").w);
ok("the year is stamped on January and on the first column only",
  /'26$/.test(tl.months_[0].label) && /'27$/.test(tl.months_.find(m => m.ym === "2027-01").label)
  && !/'/.test(tl.months_[1].label), tl.months_.map(m => m.label).join(" "));

// ⚠ Positions are FRACTIONS, never pixels — the same layout has to hold at the
// 1120px floor and at 2400px.
const allItems = [...tl.lanes.flatMap(l => l.items), ...tl.release.items];
ok("every position is a fraction inside the window",
  allItems.every(i => i.x >= 0 && i.x <= 1 && i.w >= 0 && i.x + i.w <= 1 + 1e-9));
ok("a later event sits further right",
  laneR("apac").items[0].x < laneR("eu").items[0].x);
ok("a three-day event is drawn wider than a one-day one",
  laneR("eu").items[0].w > laneR("apac").items.find(i => i.ev.id === "kobe").w);

// ⚠ A set release is not in a PLACE. Its country is null, so a lane assignment
// that just asks calRegionOf files every release under "Elsewhere" — which is
// both wrong and the one lane nobody would think to look in.
ok("a set release goes on the release rail, not into a region lane",
  calTimelineLane({kind: "set"}) === "release" && calTimelineLane({kind: "product"}) === "release");
ok("and the rail holds both releases", tl.release.items.length === 2,
  tl.release.items.map(i => i.ev.id).join(","));
ok("no release leaks into a region lane",
  !tl.lanes.some(l => l.items.some(i => i.ev.kind === "set" || i.ev.kind === "product")));
ok("a Challenge joins the one circuit track by default",
  calTimelineLane({kind: "dlc", country: "GB"}) === "circuit"
  && calTimelineLane({kind: "ccq", country: "JP"}) === "circuit");
ok("and is filed by its country only when asked",
  calTimelineLane({kind: "dlc", country: "GB"}, "region") === "eu"
  && calTimelineLane({kind: "ccq", country: "JP"}, "region") === "apac");
// ⚠ The grouping never reaches the personal lanes or the release rail: a shop
// is a subject, not a category, and a release is in no place at all.
ok("grouping never moves a shop, a near-me SC or a release",
  ["packed", "region"].every(g =>
    calTimelineLane({kind: "store", store_id: "7"}, g) === "store:7"
    && calTimelineLane({kind: "store", near: true}, g) === "near"
    && calTimelineLane({kind: "set"}, g) === "release"));

// ⚠ Nothing may be silently dropped or drawn twice — the failure a chart cannot
// show you, because an absent marker looks exactly like a quiet month.
ok("every event in the window is placed exactly once",
  allItems.length === season.length && new Set(allItems.map(i => i.ev.id)).size === season.length,
  `${allItems.length} vs ${season.length}`);
ok("total counts what was placed", tl.total === season.length);

// ⚠ ONE LANE PER SHOP. A followed store is a place you drive to, so the reason
// to put it on a season chart at all is to see WHICH shop runs what and when —
// an anonymous strip of ticks says only "somebody near me plays on Saturdays".
const dojo = lane("store:7"), gng = lane("store:9");
ok("each followed shop gets its own lane", dojo && gng && dojo.count === 3 && gng.count === 1,
  tl.lanes.map(l => `${l.key}=${l.count}`).join(" "));
ok("a shop's lane is named by the SHOP, off its own first entry",
  dojo.label === "Dice Dojo" && gng.label === "Griffonest", `${dojo.label} / ${gng.label}`);
ok("a shop lane is never a region filter", dojo.region === false && dojo.store === true);
ok("a shop lane draws no gap chips — 7 days, all year, answering nothing",
  dojo.gaps.length === 0 && gng.gaps.length === 0);
ok("store events stay out of their country's region lane",
  !laneR("na").items.some(i => i.ev.kind === "store"));

// ⚠ THE LABEL IS A PER-ITEM QUESTION. Labelling every store event buries the
// one Set Championship under fifty league nights; labelling none of them loses
// the Set Championship entirely. Both directions are the whole feature.
ok("the shop's Set Championship is labelled",
  dojo.items.find(i => i.ev.id === "dojo-sc").label === true);
ok("its league nights are ticks", dojo.items.filter(i => i.ev.id.startsWith("league"))
  .every(i => i.label === false && i.row === null));
ok("a prerelease is labelled too", gng.items[0].label === true);
ok("calTimelineLabels is the one rule, and it only ever demotes store events",
  calTimelineLabels({kind: "store", rph_kind: "sc"}) === true
  && calTimelineLabels({kind: "store", rph_kind: "other"}) === false
  && calTimelineLabels({kind: "dlc"}) === true
  && calTimelineLabels({kind: "set"}) === true
  && calTimelineLabels(null) === true);

// ⚠ "SCs near me" is a DIFFERENT question from "my shops" — not where do I
// play, but where is the season being played — so it never joins a shop lane.
ok("a nearby SC gets the near lane, not a store lane",
  lane("near") && lane("near").count === 1 && lane("near").items[0].ev.id === "far-sc");
// ⚠ Named for the CHIP that produced it, not for the concept. The gutter is
// 128px in the DOM and clips at 94px on the canvas: "Set Champs near me"
// does not fit either, and a lane reading "Set Champs ne…" in a shared
// picture names nothing.
ok("the near lane is named for the chip that switched it on",
  lane("near").label === "SCs near me");
ok("a near SC is labelled and is treated as personal, not regional",
  lane("near").items[0].label === true && lane("near").store === true);
ok("calTimelineLane keys a followed shop by its store id",
  calTimelineLane({kind: "store", store_id: "7"}) === "store:7"
  && calTimelineLane({kind: "store", store_id: "7", near: true}) === "near");
ok("a store event with no store id still lands in one bucket",
  calTimelineLane({kind: "store"}) === "store:");

// ⚠ The gap is measured END to START. Measuring start to start counts a
// three-day Challenge's own length as part of the wait for the next one.
const naGaps = laneR("na").gaps;
ok("the gap to the next event is measured end to start",
  naGaps.length === 1 && naGaps[0].days === 82, JSON.stringify(naGaps));
ok("a gap chip sits between the two markers it describes",
  naGaps[0].x > laneR("na").items[0].x && naGaps[0].x < laneR("na").items[1].x);

// Label de-collision. Two markers closer than a label's width cannot share a
// row, or the later title is drawn on top of the earlier one.
const labelW = CAL_TL_LABEL_PX / CAL_TL_MIN_PX;
const tight = calendarTimeline([
  tlEv("a", "dlc", "2026-09-05", {country: "US"}),
  tlEv("b", "dlc", "2026-09-08", {country: "US"}),
  tlEv("c", "dlc", "2027-06-05", {country: "US"}),
], TL_OPTS);
const tightNa = tight.lanes.find(l => l.key === "circuit");
ok("two events three days apart stack onto different rows",
  tightNa.items[0].row !== tightNa.items[1].row, JSON.stringify(tightNa.items.map(i => i.row)));
ok("an event nine months later reuses the first row",
  tightNa.items[2].row === 0, tightNa.items[2].row);
ok("the lane is as tall as its deepest stack", tightNa.rows === 2, tightNa.rows);
ok("no two labels on one row overlap", tightNa.items.every(i =>
  tightNa.items.every(j => i === j || j.row !== i.row
    || Math.abs(i.x - j.x) >= labelW - 1e-9)));

// ⚠ A label at the right-hand end must anchor RIGHT, or the last event of the
// season is drawn past the edge of the chart and clipped with nothing on screen
// to say it was ever there.
const edge = calendarTimeline([tlEv("last", "dlc", "2027-08-28", {country: "US"})], TL_OPTS);
ok("a label at the end of the window anchors right",
  edge.lanes[0].items[0].anchor === "right", edge.lanes[0].items[0].anchor);
ok("and one at the start anchors left", lane("circuit").items[0].anchor === "left");

// ⚠ A right-anchored label is drawn BACKWARDS from its marker, so the row it is
// packed into has to reserve that span and not the one in front of it. Getting
// this wrong leaves a label-wide hole to its left that the previous title is
// free to be drawn into — two names on top of each other, at the one end of the
// chart where there is no room to notice.
// ⚠ "early" has to sit far enough from the right edge to anchor LEFT at the
// current label width, or the pair tests nothing — both would anchor right and
// the overlap being checked would be the trivial one. It moved in when the
// label grew from 126px to 140px.
const back = calendarTimeline([
  tlEv("early", "dlc", "2027-06-20", {country: "US"}),
  tlEv("late", "dlc", "2027-08-29", {country: "US"}),
], TL_OPTS);
const backItems = back.lanes[0].items;
ok("the label at the end anchors backwards from its marker",
  backItems[1].anchor === "right" && backItems[0].anchor === "left");
ok("and the one it would have been drawn over is pushed to another row",
  backItems[0].row !== backItems[1].row,
  JSON.stringify(backItems.map(i => [i.ev.id, i.x.toFixed(3), i.anchor, i.row])));
// The same pair, far enough apart that the backwards label clears it, must NOT
// stack — over-reserving is just as wrong, and costs a row on every lane.
const backOk = calendarTimeline([
  tlEv("early", "dlc", "2027-04-01", {country: "US"}),
  tlEv("late", "dlc", "2027-08-29", {country: "US"}),
], TL_OPTS).lanes[0].items;
ok("a backwards label that clears its predecessor shares the row",
  backOk[0].row === 0 && backOk[1].row === 0);

// ⚠ One season line per SET, never per phase. A set puts two or three dates in
// the window a week apart; three lines that close together is a smear, and the
// one drawn has to be the LGS date — when the set is generally on sale — not the
// prerelease weekend that happens to sort first.
const seasonTl = calendarTimeline([
  tlEv("pre", "set", "2026-10-16", {ends_on: "2026-10-18", subtitle: "Prerelease", set_name: "Hyperia City"}),
  tlEv("lgs", "set", "2026-10-16", {subtitle: "LGS release", set_name: "Hyperia City"}),
  tlEv("ret", "set", "2026-10-23", {subtitle: "Retail release", set_name: "Hyperia City"}),
  tlEv("next", "set", "2027-01-29", {subtitle: "LGS release", set_name: "Into the Inkdark"}),
  tlEv("gift", "product", "2026-11-13", {title: "Beast Gift Box"}),
], TL_OPTS);
ok("one season line per set", seasonTl.seasons.length === 2,
  JSON.stringify(seasonTl.seasons.map(x => x.label)));
ok("the line lands on the LGS date, not the prerelease",
  Math.abs(seasonTl.seasons[0].x - seasonTl.release.items.find(i => i.ev.id === "lgs").x) < 1e-9);
ok("a product draws no season line", !seasonTl.seasons.some(x => /Gift/.test(x.label)));
// Retail-only is the normal shape for a set whose LGS date is out of the window.
ok("retail stands in when there is no LGS date in the window",
  calendarTimeline([tlEv("r", "set", "2027-03-01", {subtitle: "Retail release", set_name: "X"})],
    TL_OPTS).seasons.length === 1);
ok("a calendar with no set releases draws no season lines",
  calendarTimeline([tlEv("d", "dlc", "2026-10-01", {country: "US"})], TL_OPTS).seasons.length === 0);

// The window boundary, both sides. Off by one here hides an event entirely.
const edges = calendarTimeline([
  tlEv("in", "dlc", "2027-08-31", {country: "US"}),
  tlEv("out", "dlc", "2027-09-01", {country: "US"}),
  tlEv("was", "dlc", "2026-08-31", {country: "US"}),
  tlEv("straddles", "dlc", "2026-08-30", {ends_on: "2026-09-02", country: "GB"}),
], TL_OPTS);
ok("the last day of the window is inside it",
  edges.lanes.find(l => l.key === "circuit").items.some(i => i.ev.id === "in"));
ok("the day after it is counted as later", edges.after === 1, edges.after);
ok("the day before it is counted as earlier", edges.before === 1, edges.before);
// An event that started before the window but is still running belongs ON the
// chart — it is the one thing a reader might be standing in.
ok("an event straddling the start is drawn, not counted as past",
  edges.lanes.find(l => l.key === "circuit").items.some(i => i.ev.id === "straddles"),
  JSON.stringify(edges.before));

ok("today is a fraction when it is in the window",
  tl.today > 0.03 && tl.today < 0.06, tl.today);
ok("and null when it is not",
  calendarTimeline(season, {...TL_OPTS, today: "2029-01-01"}).today === null);

ok("an empty calendar lays out without throwing",
  calendarTimeline([], TL_OPTS).total === 0 && calendarTimeline(null, TL_OPTS).lanes.length === 0);
ok("a row with no usable date is skipped rather than placed at day zero",
  calendarTimeline([tlEv("bad", "dlc", null, {country: "US"}),
                    tlEv("bad2", "dlc", "soon", {country: "US"})], TL_OPTS).total === 0);
ok("a junk window falls back to this month rather than NaN",
  /^\d{4}-\d{2}$/.test(calendarTimeline(season, {fromMonth: "nope"}).fromMonth));
ok("the default window is one competitive season", CAL_TL_MONTHS === 12);

// Lanes come out in the region picker's own order, so the chart and the filter
// can never describe two different worlds.
ok("packed is the default, and it is ONE circuit track",
  tl.group === "packed" && lane("circuit") && lane("circuit").count === 5
  && !tl.lanes.some(l => CALENDAR_REGIONS.some(r => r.key === l.key)),
  tl.lanes.map(l => l.key).join(","));
ok("the circuit track packs into as many rows as it needs",
  lane("circuit").rows >= 1 && lane("circuit").items.every(i => i.label && i.row < lane("circuit").rows));
// Its row count IS the density read, so it is the one lane that must never cap.
ok("and it is never capped", (() => {
  const many = [];
  for(let i = 0; i < 12; i++) many.push(tlEv("d" + i, "dlc", `2026-11-${String(i + 1).padStart(2, "0")}`, {country: "US"}));
  return calendarTimeline(many, TL_OPTS).lanes.find(l => l.key === "circuit").rows > CAL_TL_STORE_ROWS;
})());
ok("a circuit lane is not offered as a region filter", lane("circuit").region === false);
// Region rows stay REACHABLE — comparing two regions' runs is a real question,
// just not the one most readers arrive with.
ok("region mode still lays out one row per region, in the picker's order",
  JSON.stringify(tlR.lanes.map(l => l.key)) === JSON.stringify(["na", "eu", "apac", "near", "store:7", "store:9"]),
  tlR.lanes.map(l => l.key).join(","));
ok("only region mode offers a lane as a filter",
  laneR("na").region === true && tl.lanes.every(l => !l.region));
ok("both modes are declared, and junk falls back to packed",
  JSON.stringify(CAL_TL_GROUP_MODES) === JSON.stringify(["packed", "region"])
  && calendarTimeline(season, {...TL_OPTS, group: "nonsense"}).group === "packed");
// ⚠ Nothing may be lost or gained by the grouping — it is a re-arrangement.
ok("the two modes place exactly the same events",
  tl.total === tlR.total && tl.total === season.length);
// Three blocks, ruled apart: general, then yours, then the release context.
ok("lanes carry their group, and the first of each is marked",
  lane("circuit").group === "circuit" && lane("near").group === "yours"
  && lane("circuit").first === true && lane("near").first === true
  && lane("store:9").first === false);
// Busiest shop first: the one you actually go to leads, rather than whichever
// store id sorts lowest.
ok("shop lanes are ordered busiest first",
  tl.lanes.filter(l => /^store:/.test(l.key)).map(l => l.count).join(",") === "3,1");
ok("only region lanes offer themselves as a filter",
  tl.lanes.filter(l => l.region).every(l => CALENDAR_REGIONS.some(r => r.key === l.key)));
ok("every region lane key resolves to a label the picker also shows",
  tl.lanes.filter(l => l.region).every(l =>
    l.label === CALENDAR_REGIONS.find(r => r.key === l.key).label));


// ── The expanded filters ────────────────────────────────────────────────────
// ⚠ Every stored pref and every link already in the wild carries a BARE region
// key. Widening the filter to a set is only safe if those keep parsing exactly
// as they did — a silently-ignored `?cr=eu` shows the whole world instead.
ok("a bare region key still filters to that region",
  calMatchesRegion({country: "GB"}, "eu") && !calMatchesRegion({country: "US"}, "eu"));
ok("'all', empty and null all mean everywhere",
  ["all", "", null, undefined].every(v => calMatchesRegion({country: "JP"}, v)));
ok("a csv holds both", calMatchesRegion({country: "US"}, "na,eu")
  && calMatchesRegion({country: "IT"}, "na,eu") && !calMatchesRegion({country: "JP"}, "na,eu"));
ok("junk in the csv is dropped, not honoured",
  calRegionSet("na,nonsense").size === 1 && calRegionSet("nonsense") === null);
ok("an ungeocoded row falls into Elsewhere rather than out of the list",
  calMatchesRegion({country: null}, "other") && !calMatchesRegion({country: null}, "na"));

ok("an empty query matches everything",
  ["", "   ", null].every(q => calMatchesQuery({title: "x"}, q)));
ok("the search reads name, place and note", calMatchesQuery({title: "DLC Turin"}, "turin")
  && calMatchesQuery({title: "x", location: "Elgin, IL"}, "elgin")
  && calMatchesQuery({title: "x", notes: "packs for prizes"}, "prizes"));
// This season alone holds Düsseldorf, Malmö and Senigallia, and nobody types
// those with the diacritics.
ok("it folds diacritics both ways", calMatchesQuery({title: "DLC Düsseldorf"}, "dusseldorf")
  && calMatchesQuery({title: "Malmö Game Week"}, "malmo"));
ok("it does not match the kind or the date",
  !calMatchesQuery({kind: "dlc", title: "Turin", starts_on: "2027-03-05"}, "dlc")
  && !calMatchesQuery({kind: "dlc", title: "Turin", starts_on: "2027-03-05"}, "2027"));

// ── Following a shop vs finding one near you ────────────────────────────────
// ⚠ A shop you FOLLOW wins over the same shop turning up in your radius, so the
// event lands in that shop's own named lane and never in both — which on a
// chart reads as a duplicate-rows bug rather than as a merge that went wrong.
const followedRows = [
  {id: "ev:1", kind: "store", event_id: 1, subtitle: "Dice Dojo"},
  {id: "ev:2", kind: "store", event_id: 2, subtitle: "Dice Dojo"},
];
const nearRows = [
  {id: "ev:2", kind: "store", event_id: 2, subtitle: "Dice Dojo", near: true},
  {id: "ev:9", kind: "store", event_id: 9, subtitle: "Far Shop", near: true},
];
const mergedStore = calendarMergeStore(followedRows, nearRows);
ok("a followed event is not duplicated by the same one found near you",
  mergedStore.length === 3 && mergedStore.filter(e => e.event_id === 2).length === 1,
  mergedStore.map(e => e.id).join(","));
ok("and the FOLLOWED copy is the one that survives",
  !mergedStore.find(e => e.event_id === 2).near);
ok("an event only found near you comes through",
  mergedStore.some(e => e.event_id === 9 && e.near === true));
ok("either side missing is empty, not a throw",
  calendarMergeStore(null, null).length === 0
  && calendarMergeStore(followedRows, null).length === 2
  && calendarMergeStore(null, nearRows).length === 2);

// ⚠ Past the cap a label DEMOTES to a tick rather than growing the lane. SCs
// cluster — a whole season lands inside one four-week window — so an uncapped
// near-me lane is a twenty-row stack over one weekend and a flat empty band
// either side of it, unreadable in both directions at once.
const crowd = [];
for(let i = 0; i < 9; i++)
  crowd.push(tlEv("sc" + i, "store", `2026-11-0${i + 1}`,
    {store_id: "3", subtitle: "Busy Shop", rph_kind: "sc"}));
const crowdTl = calendarTimeline(crowd, TL_OPTS);
const crowdLane = crowdTl.lanes.find(l => l.key === "store:3");
ok("a crowded personal lane caps its rows", crowdLane.rows === CAL_TL_STORE_ROWS,
  `${crowdLane.rows} vs ${CAL_TL_STORE_ROWS}`);
ok("the overflow becomes ticks rather than more rows",
  crowdLane.items.filter(i => i.label).length < crowd.length
  && crowdLane.items.every(i => !i.label || i.row < CAL_TL_STORE_ROWS));
ok("every crowded event is still PLACED — only its title is dropped",
  crowdLane.count === crowd.length && crowdLane.items.every(i => i.x >= 0 && i.x <= 1));
// The Challenge track is uncapped in BOTH modes: capping it would demote the
// back half of a busy month to unlabelled dots, which is the one thing the
// chart exists to carry.
const wide = crowd.map((e, i) => ({...e, kind: "dlc", country: "US", store_id: undefined,
  rph_kind: undefined, id: "d" + i}));
ok("a Challenge lane is not capped, packed or by region",
  calendarTimeline(wide, TL_OPTS).lanes.find(l => l.key === "circuit").rows > CAL_TL_STORE_ROWS
  && calendarTimeline(wide, {...TL_OPTS, group: "region"}).lanes.find(l => l.key === "na").rows > CAL_TL_STORE_ROWS);

// ⚠ Past the shop cap the tail rolls into ONE lane rather than growing the
// chart without limit — six named lanes is already 300px of chart.
const manyShops = [];
for(let i = 0; i < CAL_TL_MAX_STORE_LANES + 3; i++)
  manyShops.push(tlEv("s" + i, "store", "2026-11-0" + ((i % 8) + 1),
    {store_id: String(100 + i), subtitle: "Shop " + i, rph_kind: "sc"}));
const manyTl = calendarTimeline(manyShops, TL_OPTS);
const shopLanes = manyTl.lanes.filter(l => l.store);
ok("the shop lanes are capped", shopLanes.length === CAL_TL_MAX_STORE_LANES + 1,
  shopLanes.map(l => l.key).join(","));
ok("the tail rolls into one named lane",
  shopLanes[shopLanes.length - 1].key === CAL_TL_STORE_REST
  && shopLanes[shopLanes.length - 1].label === "Other shops");
ok("and nothing is lost to the roll-up",
  manyTl.total === manyShops.length
  && new Set(manyTl.lanes.flatMap(l => l.items.map(i => i.ev.id))).size === manyShops.length);

// ── The release rail's two-line label ───────────────────────────────────────
// ⚠ Both failures here are SILENT and look like a rendering glitch rather than
// a rule that stopped firing: the rail's names are long and several are long in
// the same way, so on one line they clip mid-word into near-identical strings
// whose clipped-off half was the only thing telling them apart.
const lpSet = calTlLabelParts(
  {kind: "set", title: "Hyperia City", set_name: "Hyperia City", subtitle: "Retail release"},
  "Oct 23", true);
ok("a set release puts its PHASE on the second line",
  lpSet.title === "Hyperia City" && lpSet.qual === "Retail release" && lpSet.range === "Oct 23");

const lpProdSub = calTlLabelParts(
  {kind: "product", title: "Attack of the Vine! Collection Starter Set", subtitle: "Rapunzel Edition"},
  "Sep 4", true);
ok("a product uses its own subtitle as the qualifier",
  lpProdSub.title === "Attack of the Vine! Collection Starter Set"
  && lpProdSub.qual === "Rapunzel Edition");

const lpProdColon = calTlLabelParts(
  {kind: "product", title: "Illumineer's Quest: The Great Hunny Rescue"}, "Oct 2", true);
ok("a product with no subtitle splits at its colon",
  lpProdColon.title === "Illumineer's Quest" && lpProdColon.qual === "The Great Hunny Rescue");

const lpProdPlain = calTlLabelParts({kind: "product", title: "Hyperia City Beast Gift Box"}, "Nov 13", true);
ok("a name with neither keeps its ellipsis rather than an invented break",
  lpProdPlain.title === "Hyperia City Beast Gift Box" && !lpProdPlain.qual);

// ⚠ The split is the RELEASE RAIL's rule and nowhere else. A Challenge lane's
// label is a name and a date; giving it a second line would restate the kind
// the glyph beside it already draws.
const lpAbove = calTlLabelParts(
  {kind: "set", title: "Hyperia City", set_name: "Hyperia City", subtitle: "Retail release"},
  "Oct 23", false);
ok("above the rail the label stays one line",
  lpAbove.title === calEventTitle({kind: "set", title: "Hyperia City", subtitle: "Retail release"})
  && !lpAbove.qual);

// ⚠ The DATE is a field of its own, never concatenated into the qualifier —
// that is what lets the renderer pin it and shrink the qualifier instead. As one
// string it was the date that got eaten ("The Great Hunny Rescue · O…"), and the
// date is the one thing a timeline label cannot do without.
ok("the date is always its own field",
  [lpSet, lpProdSub, lpProdColon, lpProdPlain, lpAbove].every(
    lp => lp.range && !String(lp.qual || "").includes(lp.range)));

console.log(failed ? `\n${failed} FAILED` : "\nall calendar checks passed");
process.exit(failed ? 1 : 0);
