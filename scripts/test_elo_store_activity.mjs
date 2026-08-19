// test_elo_store_activity.mjs — guards the Elo "Stores" tab pivot.
//
//     node scripts/test_elo_store_activity.mjs
//
// The Stores tab is entirely derived: it pivots elo_event_summary_v by
// (store, season) and joins elo_matches for a head count. Three of
// those steps are easy to get quietly wrong and impossible to eyeball on a
// 30-row table:
//
//   1. Distinct players CANNOT be summed across seasons. A regular who plays
//      every set is one player, not four — if this breaks, every store's head
//      count inflates to roughly its attendance and nobody notices. The set
//      filter makes this load-bearing: the head count is re-unioned for
//      whatever window is selected, so the per-season player ids have to
//      survive the pivot.
//   2. elo_matches carries no is_ignored / storeless filter, so a player only
//      counts once their match's event survived the summary-view pass.
//   3. Merged cross-platform identities (melee handle → RPH player) must fold
//      together, or a store's regulars are counted twice.
//
// Reads the real functions out of Index.html rather than restating them, so it
// cannot drift from what ships. Manual — there is no client-side CI.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const MAINLINE_SETS = JSON.parse(
  "[" + grab("const MAINLINE_SETS = [", "];").split("[")[1].split("]")[0]
        .replace(/\n/g, " ").replace(/,\s*$/, "") + "]",
);

const code = [
  grab("function eloSeasonSetLabel(season){", "\n}"),
  grab("const eloEventSeats = (e) =>", "e.rated_players : 0);"),
  grab("function eloCanonicalIdMap(aliasMap){", "\n}"),
  grab("function buildEloStoreActivity(events, matches, aliasMap){", "\n  return {seasons, stores};\n}"),
  grab("function eloStoreTotals(store, seasonKeys){", "\n}"),
  grab("const RPH_TIERS = [", "];"),
  grab("function rphShortfall(t){", "\n}"),
  grab("function rphTierFor(t){", "\n}"),
].join("\n\n");

const [build, totals, tierFor, shortfall] = new Function(
  "MAINLINE_SETS",
  code + "\nreturn [buildEloStoreActivity, eloStoreTotals, rphTierFor, rphShortfall];",
)(MAINLINE_SETS);

let failures = 0;
const eq = (label, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if (g === w) { console.log("  ok   " + label); return; }
  failures++;
  console.log("  FAIL " + label + "\n         got  " + g + "\n         want " + w);
};

// ── Fixture ────────────────────────────────────────────────────────────────
// Two stores across two seasons, plus the three edge cases above.
const WINTER = "Winterspell Winter 2026";
const WILDS = "Wilds Unknown Summer 2026";
const events = [
  // Winterspell came first chronologically but is listed second, so column
  // ordering has to come from the dates, not from row order.
  {event_id: 10, store: "Collectors Lounge", season: WILDS,  event_date: "2026-06-01", num_players: 12, rated_players: 11},
  {event_id: 11, store: "Collectors Lounge", season: WILDS,  event_date: "2026-06-08", num_players: 8,  rated_players: 8},
  {event_id: 12, store: "Collectors Lounge", season: WINTER, event_date: "2026-01-10", num_players: 20, rated_players: 19},
  {event_id: 13, store: "Top Choice Gaming", season: WINTER, event_date: "2026-01-11", num_players: null, rated_players: 7},
  // No store: an online / unattributed event is not a venue.
  {event_id: 14, store: null,                season: WINTER, event_date: "2026-01-12", num_players: 30, rated_players: 30},
  // No headcount at all — contributes an event but zero seats.
  {event_id: 15, store: "Top Choice Gaming", season: WILDS,  event_date: "2026-06-09", num_players: null, rated_players: null},
];
const matches = [
  // Player 1 plays both seasons at Collectors Lounge — one person, not two.
  {event_id: 10, player1_id: 1, player2_id: 2},
  {event_id: 12, player1_id: 1, player2_id: 3},
  // 901 is player 1's merged melee handle: still one person.
  // player2_id null is a bye — no phantom player from it.
  {event_id: 11, player1_id: 901, player2_id: null},
  // event 99 is is_ignored (absent from `events`) — must not invent a store.
  {event_id: 99, player1_id: 4, player2_id: 8},
  // event 14 has no store — must not invent one either.
  {event_id: 14, player1_id: 5, player2_id: 9},
  {event_id: 13, player1_id: 6, player2_id: 7},
];
// aliasMap shape as EloView builds it: canonical_id → [alias rows]
const aliasMap = new Map([[1, [{player_id: 901, display_name: "zaven", platform: "melee"}]]]);

const out = build(events, matches, aliasMap);
const byName = Object.fromEntries(out.stores.map((s) => [s.store, s]));

console.log("season columns");
eq("NEWEST first, labelled with the set half",
   out.seasons, [{key: WILDS, label: "Wilds Unknown"}, {key: WINTER, label: "Winterspell"}]);

console.log("per-season pivot");
const cell = (s, k) => ({events: byName[s].per[k].events, attendance: byName[s].per[k].attendance});
eq("Collectors Lounge Winterspell", cell("Collectors Lounge", WINTER), {events: 1, attendance: 20});
eq("Collectors Lounge Wilds Unknown", cell("Collectors Lounge", WILDS), {events: 2, attendance: 20});
eq("attendance falls back to rated_players", cell("Top Choice Gaming", WINTER), {events: 1, attendance: 7});
eq("no headcount at all counts the event, zero seats", cell("Top Choice Gaming", WILDS), {events: 1, attendance: 0});
eq("date span", [byName["Collectors Lounge"].first_date, byName["Collectors Lounge"].last_date], ["2026-01-10", "2026-06-08"]);

// This is what the set filter calls on every render.
console.log("scoped rollup");
const all = [WILDS, WINTER];
eq("both sets: events + tickets are sums", (({events, attendance}) => ({events, attendance}))(totals(byName["Collectors Lounge"], all)),
   {events: 3, attendance: 40});
eq("both sets: players is a UNION, not a sum (1/901, 2, 3 → 3)", totals(byName["Collectors Lounge"], all).players, 3);
eq("avg seats per event", totals(byName["Collectors Lounge"], all).avg, 13.3);
eq("Top Choice Gaming players", totals(byName["Top Choice Gaming"], all).players, 2);

// Narrowing the window has to re-answer every number, not slice a pre-baked one.
eq("Wilds only: events + tickets", (({events, attendance}) => ({events, attendance}))(totals(byName["Collectors Lounge"], [WILDS])),
   {events: 2, attendance: 20});
eq("Wilds only: player 1 and their merged 901 handle are one person", totals(byName["Collectors Lounge"], [WILDS]).players, 2);
eq("Winterspell only: players", totals(byName["Collectors Lounge"], [WINTER]).players, 2);
eq("a set the store never ran contributes nothing", totals(byName["Collectors Lounge"], ["Nonexistent Set 2099"]),
   {events: 0, attendance: 0, players: 0, avg: 0});

console.log("exclusions");
eq("storeless events make no store row", out.stores.map((s) => s.store).sort(), ["Collectors Lounge", "Top Choice Gaming"]);
eq("players on ignored / storeless events are dropped",
   out.stores.reduce((n, s) => n + totals(s, all).players, 0), 5);

// RPH's published thresholds over the 4 most recent set seasons. Getting these
// wrong tells a store owner they qualify for an allocation they don't.
console.log("RPH tiers");
const T = (events, players, attendance) => ({events, players, attendance});
eq("clears Legendary exactly at the bar", tierFor(T(50, 50, 500))?.key, "legendary");
eq("one ticket short of Legendary -> Standard", tierFor(T(50, 50, 499))?.key, "standard");
eq("one fan short of Legendary -> Standard", tierFor(T(50, 49, 500))?.key, "standard");
eq("one event short of Legendary -> Standard", tierFor(T(49, 50, 500))?.key, "standard");
eq("clears Standard exactly at the bar", tierFor(T(25, 25, 250))?.key, "standard");
eq("one short of Standard -> no tier (Welcome)", tierFor(T(25, 25, 249)), null);
eq("plenty of events but too few people -> no tier", tierFor(T(80, 12, 900)), null);
eq("busy singles scene, thin attendance -> no tier", tierFor(T(60, 60, 100)), null);
eq("nothing at all -> no tier", tierFor(T(0, 0, 0)), null);

console.log("shortfall wording");
eq("names every missing metric", shortfall(T(20, 20, 200)),
   "Short of Standard by 5 more events, 5 more unique fans, 50 more tickets");
eq("names only what's missing", shortfall(T(30, 30, 200)),
   "Short of Standard by 50 more tickets");

console.log("season labels");
const label = new Function("MAINLINE_SETS", grab("function eloSeasonSetLabel(season){", "\n}") + "\nreturn eloSeasonSetLabel;")(MAINLINE_SETS);
eq("strips the tag", label("Fabled Fall 2025"), "Fabled");
eq("multi-word set name survives", label("Whispers in the Well Spring 2026"), "Whispers in the Well");
eq("unknown label passes through", label("Some Other Circuit"), "Some Other Circuit");
eq("null season", label(null), "Unsorted");

console.log(failures ? `\n${failures} failure(s)` : "\nall passed");
process.exit(failures ? 1 : 0);
