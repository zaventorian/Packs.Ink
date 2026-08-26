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

const mod = await import("data:text/javascript;base64," + Buffer.from(
  block + "\nexport { LORE_WIN, LORE_MAX_PLAYERS, LORE_WIN_MODIFIERS, loreClamp, loreTotals,"
        + " loreTargets, loreWinners, loreNewGame, loreReadGame, loreReadPrefs, loreDefaultName };"
).toString("base64"));

let failed = 0;
const eq = (name, got, want) => {
  const g = JSON.stringify(got), w = JSON.stringify(want);
  if(g === w) return console.log("  ok   " + name);
  failed++; console.log("  FAIL " + name + "\n         got  " + g + "\n         want " + w);
};

const { LORE_WIN, loreTotals, loreTargets, loreWinners, loreNewGame, loreReadGame, loreReadPrefs } = mod;
const game = (events, mods, n = 2) => ({
  ...loreNewGame(Array.from({length: n}, (_, i) => "P" + (i + 1)), mods),
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

console.log(failed ? `\n${failed} FAILED` : "\nall lore-tracker checks passed");
process.exit(failed ? 1 : 0);
