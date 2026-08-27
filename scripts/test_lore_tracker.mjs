// Guards the Lore Tracker's pure layer by extracting the REAL functions out of
// Index.html, so a later edit there can't quietly diverge from what's tested.
//
// Why this layer specifically: totals are derived from the event log rather
// than stored, which is what makes undo trivial and keeps the history honest —
// but it also means a bug in the fold silently misreports the score of a live
// game, and a counter that is wrong is worse than no counter. The stored-game
// reader is the other half: it parses whatever localStorage hands back, and it
// must repair or discard, never throw, or a half-written record bricks the tab.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = readFileSync(join(root, "Index.html"), "utf8");

const grab = (startsWith) => {
  const i = src.indexOf(startsWith);
  if(i < 0) throw new Error("could not find in Index.html: " + startsWith);
  return i;
};
// Pull the contiguous block from LORE_PREFS_KEY through loreReadPrefs — every
// pure helper lives there, in source order, with no JSX.
const from = grab('const LORE_PREFS_KEY');
const to   = grab('// Keeps the screen on for the length of a game.');
const block = src.slice(from, to);

const store = new Map();
globalThis.localStorage = {
  getItem: k => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: k => store.delete(k),
};

// The block depends on the site's INKS list (a seat is identified by an ink),
// so that comes out of Index.html too rather than being restated here — a copy
// would let the tracker and the rest of the site disagree about ink names.
const inksLine = src.slice(grab('const INKS = ['));
const INKS_SRC = inksLine.slice(0, inksLine.indexOf("\n") + 1);

const mod = await import("data:text/javascript;base64," + Buffer.from(
  INKS_SRC + block
        + "\nexport { INKS, LORE_WIN, LORE_MAX_PLAYERS, LORE_WIN_MODIFIERS, LORE_SEAT_INKS,"
        + " loreClamp, loreTotals, loreTargets, loreWinners, loreNewGame, loreReadGame, loreWinOf,"
        + " loreReadPrefs, loreDefaultName, loreDefaultInk, loreInkOk, loreArtOk, loreCleanArt };"
).toString("base64"));

let failed = 0;
const eq = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if(g === w) return console.log("  ok   " + name);
  failed++; console.log("  FAIL " + name + "\n         got  " + g + "\n         want " + w);
};

const { INKS, LORE_WIN, LORE_SEAT_INKS, loreTotals, loreTargets, loreWinners,
        loreNewGame, loreReadGame, loreReadPrefs, loreDefaultInk, loreInkOk,
        loreArtOk, loreCleanArt, loreWinOf } = mod;
const newGame = loreNewGame, targets = loreTargets;
const game = (events, mods, n = 2) => ({
  ...loreNewGame(Array.from({length: n}, (_, i) => "P" + (i + 1)), {mods}),
  events: events.map(([p, d], i) => ({t: i, p, d})),
});

console.log("totals fold out of the log");
eq("empty game is all zeros", loreTotals(game([])), [0, 0]);
eq("adds per seat", loreTotals(game([[0,1],[0,1],[1,1]])), [2, 1]);
eq("negatives subtract", loreTotals(game([[0,3],[0,-1]])), [2, 0]);
eq("undo is a pop — dropping the last event drops its effect",
  loreTotals(game([[0,1],[0,1]].slice(0, -1))), [1, 0]);

console.log("\nwin targets");
eq("default target is 20 for everyone", loreTargets(game([])), [LORE_WIN, LORE_WIN]);
// The modifier is recorded against the seat that PLAYED it, and raises the bar
// for everyone else — getting this backwards would hand the game to its caster.
eq("Donald raises OPPONENTS to 25, not its own seat",
  loreTargets(game([], [{id:"donald25", p:0}])), [20, 25]);
eq("caster at seat 1 raises seat 0",
  loreTargets(game([], [{id:"donald25", p:1}])), [25, 20]);
eq("both sides played it — each raises the other",
  loreTargets(game([], [{id:"donald25", p:0}, {id:"donald25", p:1}])), [25, 25]);
eq("unknown modifier id is ignored, not crashed on",
  loreTargets(game([], [{id:"nope", p:0}])), [20, 20]);

console.log("\nwinners respect the per-seat target");
const at = (a, b, mods) => game([[0,a],[1,b]], mods);
eq("20 wins by default", loreWinners(at(20, 0)), [0]);
eq("19 does not", loreWinners(at(19, 0)), []);
eq("under Donald, 20 is NOT a win for the opponent", loreWinners(at(0, 20, [{id:"donald25", p:0}])), []);
eq("under Donald, 25 is", loreWinners(at(0, 25, [{id:"donald25", p:0}])), [1]);
eq("the caster still wins at 20", loreWinners(at(20, 0, [{id:"donald25", p:0}])), [0]);
eq("simultaneous reach is reported, not silently broken", loreWinners(at(20, 20)), [0, 1]);

console.log("\nstored game survives whatever localStorage returns");
const bad = (v) => { store.set("packsink:lore:game:v1", v); return loreReadGame(); };
eq("absent", bad(undefined) ?? null, null);
eq("not json", bad("{{{"), null);
eq("wrong version", bad(JSON.stringify({v:9, players:[{}], events:[]})), null);
eq("no players array", bad(JSON.stringify({v:1, players:"x", events:[]})), null);
eq("zero players", bad(JSON.stringify({v:1, players:[], events:[]})), null);
eq("too many players", bad(JSON.stringify({v:1, players:[1,2,3,4,5].map(()=>({})), events:[]})), null);
// A truncated write is the realistic corruption, and the rows that survive it
// must not reference seats that don't exist — that would throw on render.
const salvaged = bad(JSON.stringify({
  v:1, startedAt:5, players:[{name:"A"},{name:"B"}],
  events:[{t:1,p:0,d:1},{t:2,p:9,d:1},{t:3,p:1,d:-1},null,{t:4,p:0,d:"x"}],
  mods:[{id:"donald25",p:0},{id:"bogus",p:1},{id:"donald25",p:7}],
}));
eq("drops events pointing at seats that don't exist", salvaged.events.map(e => e.p), [0, 1]);
eq("drops non-numeric deltas and nulls", salvaged.events.length, 2);
eq("keeps only known modifiers on real seats", salvaged.mods, [{id:"donald25", p:0}]);
eq("totals of a salvaged game still fold", loreTotals(salvaged), [1, -1]);

console.log("\nprefs are repaired, never thrown on");
const prefs = (v) => { store.set("packsink:lore:v1", v); return loreReadPrefs(); };
eq("garbage falls back to two players", prefs("nope").count, 2);
eq("count is clamped up", prefs(JSON.stringify({count:0})).count, 1);
eq("count is clamped down", prefs(JSON.stringify({count:99})).count, 4);
eq("faceOff defaults on", prefs("{}").faceOff, true);
eq("faceOff is respected when off", prefs(JSON.stringify({faceOff:false})).faceOff, false);

console.log("\nseats are identified by ink");
// A duplicate default would put two seats in the same colour at a fresh table,
// which is the one thing the ink scheme exists to prevent.
eq("the four default seat inks are distinct", new Set(LORE_SEAT_INKS).size, 4);
eq("every default seat ink is a real Lorcana ink", LORE_SEAT_INKS.every(i => INKS.includes(i)), true);
eq("defaults are assigned per seat", [0,1,2,3].map(loreDefaultInk), LORE_SEAT_INKS);
eq("a bogus ink is rejected", loreInkOk("Rainbow"), false);
eq("a real ink is accepted", loreInkOk("Sapphire"), true);
eq("new game keeps a chosen ink",
  loreNewGame(["a","b"], {inks:["Steel","Sapphire"]}).players.map(p => p.ink),
  ["Steel", "Sapphire"]);
eq("new game replaces a bogus ink with the seat default",
  loreNewGame(["a","b"], {inks:["Rainbow", "Sapphire"]}).players.map(p => p.ink),
  [loreDefaultInk(0), "Sapphire"]);
// The signature is options-based precisely because it grew twice; pin that a
// bare second argument can no longer be mistaken for the old mods slot.
eq("options are named — a stray array can't land in the wrong slot",
  loreNewGame(["a","b"], {mods:[{id:"donald25", p:0}]}).mods.length, 1);
eq("a stored game with a junk ink is repaired, not discarded",
  bad(JSON.stringify({v:1, players:[{name:"A", ink:"Puce"}], events:[]})).players[0].ink,
  loreDefaultInk(0));
eq("prefs repair a junk ink in place",
  prefs(JSON.stringify({inks:["Ruby","Nope","Steel"]})).inks, ["Ruby", loreDefaultInk(1), "Steel"]);

console.log("\ntimer preferences");
eq("timer defaults to counting up", prefs("{}").timerMode, "up");
eq("a bogus timer mode falls back", prefs(JSON.stringify({timerMode:"sideways"})).timerMode, "up");
eq("a real timer mode is kept", prefs(JSON.stringify({timerMode:"down"})).timerMode, "down");
eq("round length defaults to the 50-minute Lorcana round", prefs("{}").timerMins, 50);
eq("an on-list round length is kept", prefs(JSON.stringify({timerMins:75})).timerMins, 75);
// The preset chips are shortcuts, not the set of legal values. Until 2026-08-27
// this membership-tested and silently reset a custom 45 to 50 on every reload,
// which is the whole failure mode a Custom control has to not have.
eq("a custom round length survives", prefs(JSON.stringify({timerMins:45})).timerMins, 45);
eq("an absurd round length clamps, not resets", prefs(JSON.stringify({timerMins:99999})).timerMins, 600);
eq("a zero round length clamps up", prefs(JSON.stringify({timerMins:0})).timerMins, 1);
eq("a junk round length falls back", prefs(JSON.stringify({timerMins:"soon"})).timerMins, 50);

console.log("\nthe base win target");
// The target is a whole-table format choice and lives on the GAME, so a stored
// game replays at the target it was played at rather than at whatever the
// settings say now.
eq("target defaults to 20", prefs("{}").win, 20);
eq("Pack Rush is stored", prefs(JSON.stringify({win:15})).win, 15);
eq("Coconut is stored", prefs(JSON.stringify({win:25})).win, 25);
eq("a custom target is stored", prefs(JSON.stringify({win:13})).win, 13);
eq("an out-of-range target clamps", prefs(JSON.stringify({win:1000})).win, 99);
eq("a new game carries the target", newGame(["a","b"], {win:15}).win, 15);
eq("a new game with no target plays to 20", newGame(["a","b"]).win, 20);
eq("a game stored before the setting existed reads as 20", loreWinOf({}), 20);
// A modifier may only RAISE a seat's target, so Donald asking for 25 is a
// no-op at a Coconut table that is already playing to 25.
{
  const g = {...newGame(["a","b"], {win:15}), mods:[{id:"donald25", p:0}]};
  eq("Donald raises the opponent's target", targets(g)[1], 25);
  eq("...and not the seat that played it", targets(g)[0], 15);
  const c = {...newGame(["a","b"], {win:25}), mods:[{id:"donald25", p:0}]};
  eq("Donald is a no-op at a Coconut table", targets(c)[1], 25);
}

console.log("\nseat background art");
// The art URL is written straight into an <img src>, and a stored preference is
// the one input a page can't vouch for — so anything that isn't plainly an
// http(s) or root-relative URL is dropped rather than rendered.
eq("a normal proxied art path is kept", loreArtOk({id:"c", img:"/img-proxy/a.png"}), true);
eq("an https art URL is kept", loreArtOk({id:"c", img:"https://cards.lorcast.io/a.png"}), true);
eq("javascript: is rejected", loreArtOk({id:"c", img:"javascript:alert(1)"}), false);
eq("data: is rejected", loreArtOk({id:"c", img:"data:image/svg+xml,<svg onload=alert(1)>"}), false);
eq("a protocol-relative URL is rejected", loreArtOk({id:"c", img:"//evil.example/a.png"}), false);
eq("a missing img is rejected", loreArtOk({id:"c"}), false);
eq("a non-string id is rejected", loreArtOk({id:7, img:"/a.png"}), false);
eq("clean art keeps only id, img and name",
  Object.keys(loreCleanArt({id:"c", img:"/a.png", name:"X", evil:1})).sort(), ["id","img","name"]);
eq("clean art of junk is null", loreCleanArt({id:"c", img:"javascript:x"}), null);
eq("a game carries the chosen art",
  loreNewGame(["a"], {arts:[{id:"c", img:"/a.png", name:"X"}]}).players[0].art.id, "c");
eq("a game drops unsafe art rather than rendering it",
  loreNewGame(["a"], {arts:[{id:"c", img:"javascript:x"}]}).players[0].art, null);
eq("a stored game with unsafe art loads with none",
  bad(JSON.stringify({v:1, players:[{name:"A", ink:"Ruby", art:{id:"c", img:"javascript:x"}}], events:[]}))
    .players[0].art, null);
eq("prefs drop unsafe art too",
  prefs(JSON.stringify({arts:[{id:"c", img:"javascript:x"}, {id:"d", img:"/ok.png"}]})).arts,
  [null, {id:"d", img:"/ok.png", name:""}]);

console.log("\ndropping a seat drops its events with it");
// Events are keyed by seat INDEX, so a stored event pointing past the end of a
// shrunken table would silently re-attach that score to whoever sits there
// next. loreReadGame is the backstop for that on the way in.
const shrunk = bad(JSON.stringify({
  v:1, players:[{name:"A", ink:"Ruby"}],
  events:[{t:1,p:0,d:3},{t:2,p:1,d:9}],
  mods:[{id:"donald25", p:1}],
}));
eq("events for a seat that no longer exists are dropped", shrunk.events.map(e => e.p), [0]);
eq("its score does not leak into the surviving seat", loreTotals(shrunk), [3]);
eq("a modifier on a dropped seat goes too", shrunk.mods, []);

console.log(failed ? `\n${failed} FAILED` : "\nall lore-tracker checks passed");
process.exit(failed ? 1 : 0);
