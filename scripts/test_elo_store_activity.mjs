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
  grab("function buildEloStoreActivity(events, matches, aliasMap, seasons){", "\n  return {seasons: seasonList, stores};\n}"),
  grab("function eloStoreTotals(store, seasonKeys){", "\n}"),
  grab("const RPH_ENTRY = {", "};"),
  grab("const RPH_PRORATED = {", "};"),
  grab("const RPH_PRORATED_WINDOW = {", "};"),
  grab("const RPH_TIERS = [", "];"),
  grab("function rphShortfall(t){", "\n}"),
  grab("function rphTierFor(t){", "\n}"),
].join("\n\n");

const [build, totals, tierFor, shortfall, RPH_PRORATED] = new Function(
  "MAINLINE_SETS",
  code + "\nreturn [buildEloStoreActivity, eloStoreTotals, rphTierFor, rphShortfall, RPH_PRORATED];",
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
const ev = (event_id, store_name, start, seats, extra = {}) =>
  ({event_id, store_name, start_datetime: start + "T18:00:00+00:00",
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
  // Pro-rating window is Sept 1 → Nov 1 2026. Start is inclusive, end exclusive.
  ev(20, "Collectors Lounge", "2026-08-31", 5),                              // day before: out
  ev(21, "Collectors Lounge", "2026-09-01", 6),                              // first day: in
  ev(22, "Collectors Lounge", "2026-10-31", 7, {kind: "prerelease", set_name: "Hyperia City"}),
  ev(23, "Collectors Lounge", "2026-11-01", 8),                              // last day: OUT
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

const out = build(events, matches, aliasMap, seasons);
const byName = Object.fromEntries(out.stores.map((s) => [s.store, s]));

console.log("date bucketing (not set_name)");
eq("newest season first", out.seasons.map((x) => x.key), [WILDS, WINTER]);
const cl = byName["Collectors Lounge"];
eq("an event with NO set_name still lands in the right season by date",
   cl.per[WILDS].events, 8);       // 10, 11, 13, 14 + the four pro-window ones,
                                   // which are all after Wilds Unknown released
eq("Winterspell picks up the unnamed January event", cl.per[WINTER].events, 1);
eq("tickets sum RPH's registered_user_count", cl.per[WINTER].attendance, 20);
eq("an event predating every set buckets into the oldest, not dropped",
   byName["Top Choice Gaming"].per[WINTER].events, 2);
eq("null headcount = event counted, zero tickets",
   byName["Top Choice Gaming"].per[WINTER].attendance, 4);

console.log("scoped rollup");
const all = [WILDS, WINTER];
const t = totals(cl, all);
eq("events + tickets are sums", [t.events, t.attendance], [9, 82]);
eq("players is a UNION, and 901 merges into 1", t.players, 3);
eq("Pre counts distinct SETS, not prerelease events", t.pre, 2);  // Wilds Unknown + Hyperia City
eq("narrowing re-answers the head count", totals(cl, [WINTER]).players, 2);
eq("a set the store never ran contributes nothing",
   totals(cl, ["Nonexistent 2099"]), {events: 0, attendance: 0, players: 0, pre: 0, avg: 0});

console.log("exclusions");
eq("storeless events make no store row",
   out.stores.map((x) => x.store).sort(), ["Collectors Lounge", "Top Choice Gaming"]);
eq("matches on events absent from history are dropped",
   out.stores.reduce((n, x) => n + totals(x, all).players, 0), 5);

// The memo's one-off Sept 1 – Nov 1 2026 offer. Boundary handling matters: a
// store credited for a November 1st event would be told it qualified when it
// didn't.
console.log("pro-rating window");
eq("window bars are the memo's 1/6 of Legendary",
   [RPH_PRORATED.events, RPH_PRORATED.players, RPH_PRORATED.tickets], [8, 8, 80]);
eq("only in-window events count (Sep 1 and Oct 31, not Aug 31 or Nov 1)",
   cl.pro.events, 2);
eq("tickets likewise", cl.pro.attendance, 13);
eq("the Hyperia City prerelease is detected", cl.pro.hyperia, true);
eq("a store with no in-window prerelease doesn't claim one",
   byName["Top Choice Gaming"].pro.hyperia, false);

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
