// test_elo_store_activity.mjs — guards the Elo "Stores" tab pivot.
//
//     node scripts/test_elo_store_activity.mjs
//
// The Stores tab is entirely derived: it pivots lorcana_events_history by
// (store, season) and joins rph_event_attendance for tickets and fans. Several
// of those steps are easy to get quietly wrong and impossible to eyeball on a
// 30-row table:
//
//   1. Distinct fans CANNOT be summed across seasons. A regular who plays every
//      set is one person, not four — if this breaks, every store's fan count
//      inflates to roughly its ticket count and nobody notices. The set filter
//      makes this load-bearing: fans are re-unioned for whatever window is
//      selected, so the per-season person keys have to survive the pivot.
//   2. Tickets are one per person per event, off the roster — NOT the event's
//      registered_user_count, which misses walk-ins and counts no-shows. The
//      fixture keeps that column populated and wrong on purpose.
//   3. Attendance rows carry no store/season of their own, so a person only
//      counts once their event survived the history pass (tracked store, not
//      storeless).
//   4. A guest plays without an account, so their person key falls back to the
//      display name and has to fold case, or one regular becomes several.
//   5. An event whose roster hasn't been pulled must be reported as uncovered,
//      not silently counted as a quiet week.
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
  grab("const rphPersonKey = (a) =>", '.toLowerCase();'),
  grab("function eloSeasonForDate(iso, seasons){", "\n}"),
  grab("function buildEloStoreActivity(events, played, scanned, seasons, trackedIds){",
       "\n  return {seasons: seasonList, stores};\n}"),
  grab("function eloStoreTotals(store, seasonKeys){", "\n}"),
  grab("const RPH_ENTRY = {", "};"),
  grab("const RPH_PRORATED = {", "};"),
  grab("const eloProSeasonKey = (seasons) =>", "seasons[0].key);"),
  grab("const RPH_TIERS = [", "];"),
  grab("function rphShortfall(t){", "\n}"),
  grab("function rphTierFor(t){", "\n}"),
].join("\n\n");

const [build, totals, tierFor, shortfall, proKey] = new Function(
  "MAINLINE_SETS",
  code + "\nreturn [buildEloStoreActivity, eloStoreTotals, rphTierFor, rphShortfall, eloProSeasonKey];",
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
// registered_user_count is deliberately populated and deliberately wrong — if
// tickets ever come from it again, every ticket assertion below breaks.
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
  ev(15, "Top Choice Gaming", "2026-01-11", null),
  // Roster never pulled — counts as an event, contributes nobody, and is
  // reported as uncovered.
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
// One row per person per event, already filtered server-side to people who
// played. A guest has no account id, so their name is the identity.
const at = (event_id, rph_user_id, best_identifier = "p" + rph_user_id) =>
  ({event_id, rph_user_id, best_identifier});
const played = [
  at(10, 1), at(10, 2), at(10, 3), at(10, null, "guest gus"),
  at(11, 1), at(11, 4), at(11, null, "Guest Gus"),   // same guest, different case
  at(12, 1), at(12, 2),
  at(13, 5),
  at(15, 6), at(15, 7),
  at(17, 6),
  at(30, 10), at(31, 11),
  at(99, 8),                       // event not in history
  at(18, 9),                       // storeless event
];
// Every event has been looked at except 16.
const scanned = new Set(events.map((e) => e.event_id).filter((id) => id !== 16));
const TRACKED = new Set([1, 2, 5, 6]);

const out = build(events, played, scanned, seasons, TRACKED);
const byName = Object.fromEntries(out.stores.map((s) => [s.store + (s.city ? " " + s.city : ""), s]));

console.log("date bucketing (not set_name)");
eq("newest season first", out.seasons.map((x) => x.key), [WILDS, WINTER]);
const cl = byName["Collectors Lounge"];
eq("an event with NO set_name still lands in the right season by date",
   cl.per[WILDS].events, 4);       // ids 10, 11, 13, 14
eq("Winterspell picks up the unnamed January event", cl.per[WINTER].events, 1);
eq("an event predating every set buckets into the oldest, not dropped",
   byName["Top Choice Gaming"].per[WINTER].events, 2);

console.log("tickets are people who played, not registrations");
eq("Wilds tickets = one per person per event", cl.per[WILDS].attendance, 8);
eq("Winter tickets ignore registered_user_count (20)", cl.per[WINTER].attendance, 2);
eq("an event with no roster contributes zero tickets",
   byName["Top Choice Gaming"].per[WILDS].attendance, 0);
eq("...and is reported as uncovered", byName["Top Choice Gaming"].per[WILDS].unscanned, 1);
eq("a covered season reports no gap", cl.per[WILDS].unscanned, 0);
eq("passing null scanned skips coverage tracking",
   build(events, played, null, seasons, TRACKED).stores
     .find((x) => x.store === "Top Choice Gaming").per[WILDS].unscanned, 0);

console.log("scoped rollup");
const all = [WILDS, WINTER];
const t = totals(cl, all);
eq("events + tickets are sums", [t.events, t.attendance], [5, 10]);
eq("fans is a UNION across seasons, not a sum (would be 8)", t.players, 6);
eq("a guest folds by name, case-insensitively", totals(cl, [WILDS]).players, 6);
eq("Pre counts distinct SETS, not prerelease events", t.pre, 1);
eq("narrowing re-answers the head count", totals(cl, [WINTER]).players, 2);
eq("a set the store never ran contributes nothing",
   totals(cl, ["Nonexistent 2099"]),
   {events: 0, attendance: 0, players: 0, pre: 0, unscanned: 0, avg: 0});

console.log("exclusions");
// lorcana_events_history carries every store the global feed listed, so an
// untracked store must not appear at all.
const untracked = build(
  events.concat([{event_id: 90, store_name: "Some Shop In Berlin", store_id: 77,
                  start_datetime: "2026-06-05T18:00:00+00:00",
                  registered_user_count: 40, kind: "other", set_name: null}]),
  played, scanned, seasons, new Set([1, 2]));
eq("an untracked store is dropped entirely",
   untracked.stores.some((x) => x.store === "Some Shop In Berlin"), false);
eq("an empty tracked set means no filter, not no stores",
   build(events, played, scanned, seasons, new Set()).stores.length, 4);
eq("storeless events make no store row",
   out.stores.map((x) => x.store).sort(),
   ["Collectors Lounge", "Fair Game", "Fair Game", "Top Choice Gaming"]);
eq("attendance on events absent from history is dropped",
   out.stores.reduce((n, x) => n + totals(x, all).attendance, 0), 15);

console.log("stores are keyed by location, not name");
const fg = out.stores.filter((x) => x.store === "Fair Game");
eq("two branches of one chain stay separate", fg.length, 2);
eq("...with their own numbers", fg.map((x) => x.per[WILDS].attendance), [1, 1]);
eq("...and carry their location", fg.map((x) => x.city).sort(), ["Geneva", "La Grange"]);
eq("each gets a distinct row key", new Set(fg.map((x) => x.key)).size, 2);

console.log("RPH tiers");
const T = (events, players, attendance) => ({events, players, attendance});
eq("clears Legendary exactly at the bar", tierFor(T(50, 50, 500))?.key, "legendary");
eq("one ticket short of Legendary -> Standard", tierFor(T(50, 50, 499))?.key, "standard");
eq("one event short of Legendary -> Standard", tierFor(T(49, 50, 500))?.key, "standard");
// Fans is a real head count now, so unlike before it DOES gate the verdict.
eq("one fan short of Legendary -> Standard", tierFor(T(50, 49, 500))?.key, "standard");
eq("clears Standard exactly at the bar", tierFor(T(25, 25, 250))?.key, "standard");
eq("one short of Standard -> no tier (Welcome)", tierFor(T(25, 25, 249)), null);
eq("busy but thin attendance -> no tier", tierFor(T(60, 60, 100)), null);
eq("many tickets from very few people -> no tier", tierFor(T(80, 2, 900)), null);
eq("nothing at all -> no tier", tierFor(T(0, 0, 0)), null);

console.log("pro-rated lens picks ONE season");
// Two months is one set season's activity, not four — scoring 8/8/80 over a
// four-set window would clear it for everybody.
// Wilds Unknown is index 0 here, i.e. the set still running — so the lens has
// to reach past it to Winterspell.
eq("the newest COMPLETE season, not the one still running",
   proKey(out.seasons), WINTER);
eq("with only one season on file, that one", proKey([{key: WINTER}]), WINTER);
eq("no seasons at all", proKey([]), null);

console.log("shortfall wording");
eq("names every missing metric", shortfall(T(20, 20, 200)),
   "Short of Standard by 5 more events, 5 more fans, 50 more tickets");
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
