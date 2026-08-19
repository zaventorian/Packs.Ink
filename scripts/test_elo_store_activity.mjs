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
  grab("function eloSeasonForDate(iso, seasons){", "\n}"),
  grab("function buildEloStoreActivity(events, matches, aliasMap, seasons, trackedIds){", "\n  return {seasons: seasonList, stores};\n}"),
  grab("function eloStoreTotals(store, seasonKeys){", "\n}"),
  grab("const RPH_ENTRY = {", "};"),
  grab("const RPH_PRORATED = {", "};"),
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
// Shaped like lorcana_events_history rows. The critical property under test is
// that seasons come from the event DATE, not from set_name: most real events
// carry no set_name (a league night belongs to no set) and those are exactly
// the events RPH tiers reward, so name-bucketing would drop ~80% of activity.
const WINTER = "Winterspell";
const WILDS = "Wilds Unknown";
const seasons = [                      // newest-first, as the fetch sorts them
  {name: WILDS,  released_at: "2026-05-15"},
  {name: WINTER, released_at: "2026-01-01"},
];
const SID = {"Collectors Lounge": 1, "Top Choice Gaming": 2};
const ev = (event_id, store_name, start, seats, extra = {}) =>
  ({event_id, store_name, store_id: SID[store_name] ?? null,
    start_datetime: start + "T18:00:00+00:00",
    registered_user_count: seats, kind: "other", set_name: null, ...extra});
const events = [
  // Named set, inside Wilds Unknown.
  ev(10, "Collectors Lounge", "2026-06-01", 12, {kind: "sc", set_name: WILDS}),
  // NO set_name — must still land in Wilds Unknown from its date alone.
  ev(11, "Collectors Lounge", "2026-06-08", 8),
  // Winterspell by date, and again unnamed.
  ev(12, "Collectors Lounge", "2026-01-10", 20),
  // A prerelease, and a second for the same set — Pre counts SETS, not events.
  ev(13, "Collectors Lounge", "2026-05-16", 9, {kind: "prerelease", set_name: WILDS}),
  ev(14, "Collectors Lounge", "2026-05-17", 7, {kind: "prerelease", set_name: WILDS}),
  // Null headcount contributes an event and zero tickets.
  ev(15, "Top Choice Gaming", "2026-01-11", null),
  ev(16, "Top Choice Gaming", "2026-06-09", 5),
  // Predates every tracked set — buckets into the oldest rather than vanishing.
  ev(17, "Top Choice Gaming", "2024-03-03", 4),
  // Storeless: not a venue.
  ev(18, null, "2026-06-02", 30),
  // Two branches of one chain: same NAME, different store_id. They must stay
  // separate stores — merging them reports one location's numbers as both.
  {event_id: 30, store_name: "Fair Game", store_id: 5, city: "Geneva", state: "IL",
   start_datetime: "2026-06-10T18:00:00+00:00", registered_user_count: 11,
   kind: "other", set_name: null},
  {event_id: 31, store_name: "Fair Game", store_id: 6, city: "La Grange", state: "IL",
   start_datetime: "2026-06-11T18:00:00+00:00", registered_user_count: 4,
   kind: "other", set_name: null},
];
const matches = [
  {event_id: 10, player1_id: 1, player2_id: 2},
  {event_id: 12, player1_id: 1, player2_id: 3},
  {event_id: 11, player1_id: 901, player2_id: null},   // 901 merges into 1; bye
  {event_id: 99, player1_id: 4, player2_id: 8},        // event not in history
  {event_id: 18, player1_id: 5, player2_id: 9},        // storeless event
  {event_id: 15, player1_id: 6, player2_id: 7},
];
const aliasMap = new Map([[1, [{player_id: 901, display_name: "zaven", platform: "melee"}]]]);

const out = build(events, matches, aliasMap, seasons, new Set([1, 2, 5, 6]));
const byName = Object.fromEntries(out.stores.map((s) => [s.store + (s.city ? " " + s.city : ""), s]));

console.log("date bucketing (not set_name)");
eq("newest season first", out.seasons.map((x) => x.key), [WILDS, WINTER]);
const cl = byName["Collectors Lounge"];
eq("an event with NO set_name still lands in the right season by date",
   cl.per[WILDS].events, 4);       // ids 10, 11, 13, 14
eq("Winterspell picks up the unnamed January event", cl.per[WINTER].events, 1);
eq("tickets sum RPH's registered_user_count", cl.per[WINTER].attendance, 20);
eq("an event predating every set buckets into the oldest, not dropped",
   byName["Top Choice Gaming"].per[WINTER].events, 2);
eq("null headcount = event counted, zero tickets",
   byName["Top Choice Gaming"].per[WINTER].attendance, 4);

console.log("scoped rollup");
const all = [WILDS, WINTER];
const t = totals(cl, all);
eq("events + tickets are sums", [t.events, t.attendance], [5, 56]);
eq("players is a UNION, and 901 merges into 1", t.players, 3);
eq("Pre counts distinct SETS, not prerelease events", t.pre, 1);
eq("narrowing re-answers the head count", totals(cl, [WINTER]).players, 2);
eq("a set the store never ran contributes nothing",
   totals(cl, ["Nonexistent 2099"]), {events: 0, attendance: 0, players: 0, pre: 0, avg: 0});

console.log("exclusions");
// lorcana_events_history carries every store the global feed listed, so an
// untracked store must not appear at all.
const untracked = build(
  events.concat([{event_id: 90, store_name: "Some Shop In Berlin", store_id: 77,
                  start_datetime: "2026-06-05T18:00:00+00:00",
                  registered_user_count: 40, kind: "other", set_name: null}]),
  matches, aliasMap, seasons, new Set([1, 2]));
eq("an untracked store is dropped entirely",
   untracked.stores.some((x) => x.store === "Some Shop In Berlin"), false);
eq("an empty tracked set means no filter, not no stores",
   build(events, matches, aliasMap, seasons, new Set()).stores.length, 4);
eq("storeless events make no store row",
   out.stores.map((x) => x.store).sort(),
   ["Collectors Lounge", "Fair Game", "Fair Game", "Top Choice Gaming"]);
eq("matches on events absent from history are dropped",
   out.stores.reduce((n, x) => n + totals(x, all).players, 0), 5);

// The memo's one-off Sept 1 – Nov 1 2026 offer. Boundary handling matters: a
// store credited for a November 1st event would be told it qualified when it
// didn't.
console.log("stores are keyed by location, not name");
const fg = out.stores.filter((x) => x.store === "Fair Game");
eq("two branches of one chain stay separate", fg.length, 2);
eq("...with their own numbers", fg.map((x) => x.per[WILDS].attendance).sort((a, b) => a - b), [4, 11]);
eq("...and carry their location", fg.map((x) => x.city).sort(), ["Geneva", "La Grange"]);
eq("each gets a distinct row key", new Set(fg.map((x) => x.key)).size, 2);

console.log("RPH tiers");
const T = (events, players, attendance) => ({events, players, attendance});
eq("clears Legendary exactly at the bar", tierFor(T(50, 50, 500))?.key, "legendary");
eq("one ticket short of Legendary -> Standard", tierFor(T(50, 50, 499))?.key, "standard");
eq("one event short of Legendary -> Standard", tierFor(T(49, 50, 500))?.key, "standard");
eq("clears Standard exactly at the bar", tierFor(T(25, 25, 250))?.key, "standard");
eq("one short of Standard -> no tier (Welcome)", tierFor(T(25, 25, 249)), null);
// Unique Fans is a floor from partial data, so it must NOT gate the verdict —
// requiring it would show stores failing a bar they actually clear.
eq("a low fan floor does NOT block the verdict", tierFor(T(80, 2, 900))?.key, "legendary");
eq("busy but thin attendance -> no tier", tierFor(T(60, 60, 100)), null);
eq("nothing at all -> no tier", tierFor(T(0, 0, 0)), null);

console.log("shortfall wording");
eq("names every missing metric", shortfall(T(20, 20, 200)),
   "Short of Standard by 5 more events, 50 more tickets");
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
