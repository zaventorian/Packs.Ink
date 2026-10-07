// Guard test for the Swiss simulator engine (swiss.html — /lab/swiss).
//
// Extracts swissEngine / mergeAcc / shardPlan out of swiss.html so it always
// tests the code that ships, same pattern as test_graded_slot_series.mjs.
// Run after touching the engine, the pairing, the ID rule, or the sharding:
//
//   node scripts/test_swiss_engine.mjs
//
// What must hold:
//  1. 64p/6r closed form — the record distribution is the Swiss triangle
//     (1/6/15/20/15/6/1 players) EXACTLY, every sim, because Swiss pairing
//     always pairs equal records when brackets are even. Cut is exactly 8.
//  2. Conservation — players in == players out, cut == min(CUT, N), across
//     odd fields, drops, IDs, tiers.
//  3. Flagship ID behavior — at 64/6/top8 the two 5-0s pair in the final
//     round and always ID: exactly two 5-0-1 finishers per sim, both cut.
//  4. Prize tiers are tie-inclusive: players paid >= placement, monotone.
//  5. Determinism — same (cfg, n, seed) gives byte-identical accumulators,
//     and the fixed shard plan folds to the same result every time. This is
//     the property behind "Copy link reproduces exactly on any device".
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repo = dirname(dirname(fileURLToPath(import.meta.url)));
// ⚠ Normalise the line endings. git here runs core.autocrlf=true, so the blob
// is LF in the index and the working tree is CRLF — and grab()'s markers below
// span lines. Without this the test throws "missing end marker" on every
// Windows checkout while passing on Linux CI, which reads as a broken test
// rather than as the environment difference it is. Same fix as the
// scan-editor search test, which hit this first.
const html = readFileSync(join(repo, "swiss.html"), "utf8").replace(/\r\n/g, "\n");

function grab(startMarker, endMarker) {
  const a = html.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = html.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return html.slice(a, b + endMarker.length);
}

const src = [
  grab("function swissEngine(cfg, nSims, seed, onProgress) {", "\n}\n\n/* Elementwise merge"),
  grab("function mergeAcc(a, b) {", "  a.sims += b.sims;\n  return a;\n}"),
  grab("function shardPlan(total, seed) {", "  return out;\n}"),
].join("\n").replace("\n}\n\n/* Elementwise merge", "\n}");

const { swissEngine, mergeAcc, shardPlan } = await import(
  "data:text/javascript," + encodeURIComponent(src + "\nexport {swissEngine, mergeAcc, shardPlan};"));

let failures = 0;
const check = (name, ok, detail) => {
  console.log((ok ? "  ok   " : "  FAIL ") + name + (ok || detail == null ? "" : "  → " + detail));
  if (!ok) failures++;
};
const rc = (w, l, d) => ((w & 15) << 8) | ((l & 15) << 4) | (d & 15);
const dec = (c) => [(c >> 8) & 15, (c >> 4) & 15, c & 15];

function tally(a) {
  let players = 0, cut = 0, draws = 0;
  for (let c = 0; c < 4096; c++) {
    const n = a.recCount[c];
    if (!n) continue;
    players += n; cut += a.recCut[c]; draws += dec(c)[2] * n;
  }
  return { players: players / a.sims, cut: cut / a.sims, draws: draws / a.sims };
}

const base = { ptsWin: 3, ptsDraw: 1, drawRate: 0, dropAt: 0, allowID: false, tiers: [] };

// ── 1. closed form ─────────────────────────────────────────────────────────
{
  const a = swissEngine({ ...base, players: 64, rounds: 6, cut: 8 }, 2000, 12345);
  const tri = { "6-0": 1, "5-1": 6, "4-2": 15, "3-3": 20, "2-4": 15, "1-5": 6, "0-6": 1 };
  console.log("closed form (64p/6r, no draws):");
  let exact = true;
  for (const [rec, want] of Object.entries(tri)) {
    const [w, l] = rec.split("-").map(Number);
    if (a.recCount[rc(w, l, 0)] !== want * a.sims) { exact = false; break; }
  }
  check("Swiss triangle 1/6/15/20/15/6/1 exact", exact);
  const t = tally(a);
  check("player conservation", t.players === 64, t.players);
  check("cut size exactly 8", t.cut === 8, t.cut);
  check("6-0 and 5-1 always cut", a.recCut[rc(6, 0, 0)] === a.sims && a.recCut[rc(5, 1, 0)] === 6 * a.sims);
  check("cut line always 12 pts", a.cutline[12] === a.sims, a.cutline[12] + " of " + a.sims);
}

// ── 2. conservation across the hard paths ──────────────────────────────────
console.log("conservation:");
for (const [name, cfg, sims] of [
  ["63p odd field", { ...base, players: 63, rounds: 6, cut: 8 }, 800],
  ["37p odd field", { ...base, players: 37, rounds: 6, cut: 8 }, 800],
  ["drops at 3", { ...base, players: 64, rounds: 6, cut: 8, dropAt: 3 }, 800],
  ["IDs + 2% draws", { ...base, players: 64, rounds: 6, cut: 8, allowID: true, drawRate: 0.02 }, 800],
  ["9p top4", { ...base, players: 9, rounds: 4, cut: 4 }, 800],
  ["512p 9r IDs", { ...base, players: 512, rounds: 9, cut: 8, allowID: true }, 150],
]) {
  const a = swissEngine(cfg, sims, 777);
  const t = tally(a);
  check(name, t.players === cfg.players && t.cut === Math.min(cfg.cut, cfg.players),
    "players=" + t.players + " cut=" + t.cut);
}

// ── 3. flagship ID behavior ────────────────────────────────────────────────
{
  const a = swissEngine({ ...base, players: 64, rounds: 6, cut: 8, allowID: true }, 2000, 9);
  console.log("intentional draws (64p/6r/top8):");
  const k = rc(5, 0, 1);
  check("the 5-0 pair always IDs (two 5-0-1 per sim)", a.recCount[k] === 2 * a.sims, a.recCount[k] / a.sims);
  check("both always cut", a.recCut[k] === a.recCount[k]);
  // The pooled conditional: an X-0 after R5 who drew must essentially always cut.
  const ci = (5 * 256 + (5 * 16 + 0)) * 8;
  check("X-0 after R5: draw pool exists and always cuts",
    a.cond[ci + 6] > 0 && a.cond[ci + 7] === a.cond[ci + 6]);
}

// ── 3b. coordinated draws ──────────────────────────────────────────────────
// The ID rule takes tables best-first and lets a table draw only if every
// drawing player still makes it with all the tables above drawing too. At
// 64/6/top8 with no time draws the field is the exact Swiss triangle, so the
// answer is exact: the 5-0 pair draws to 16, then ONE 4-1 table can draw to 13
// (2 at 16 + its own opponent + 4 winners at 15 = 7 ahead of each of them) —
// and a second 4-1 table cannot (8 ahead). The old guarantee rule, which
// assumed all ten 4-1s could win out together, never let a 4-1 draw here; in
// real 33-64 player Top 8 events, 4-1s drew in the last round and 96% made it.
{
  const a = swissEngine({ ...base, players: 64, rounds: 6, cut: 8, allowID: true }, 2000, 9);
  console.log("coordinated draws (64p/6r/top8, no time draws):");
  check("exactly one 4-1 table draws in (two 4-1-1 per sim)", a.recCount[rc(4, 1, 1)] === 2 * a.sims,
    a.recCount[rc(4, 1, 1)] / a.sims);
  check("… and both of them always cut", a.recCut[rc(4, 1, 1)] === a.recCount[rc(4, 1, 1)]);
  const ci = (5 * 256 + (4 * 16 + 1)) * 8;
  check("4-1 after R5: the draw pool always cuts", a.cond[ci + 6] > 0 && a.cond[ci + 7] === a.cond[ci + 6]);
}

// With time draws off, every final-round draw is a planned one, and a planned
// final-round draw assumes only that the tables NOT drawing play their match —
// which, with no time draws, they always do. So it must always land: inside
// the cut, or (drawing into a prize tier) inside the widest tier.
console.log("final-round planned draws always land:");
for (const [name, cfg, sims] of [
  ["24p/5r/top8", { ...base, players: 24, rounds: 5, cut: 8, allowID: true }, 1500],
  ["13p/4r/top4", { ...base, players: 13, rounds: 4, cut: 4, allowID: true }, 1500],
  ["122p/7r/top8", { ...base, players: 122, rounds: 7, cut: 8, allowID: true }, 600],
  ["300p/9r/top32", { ...base, players: 300, rounds: 9, cut: 32, allowID: true }, 200],
  ["200p/9r/top16 + tiers 32/64", { ...base, players: 200, rounds: 9, cut: 16, allowID: true, tiers: [32, 64] }, 300],
  ["120p/7r tiers only 16/32", { ...base, players: 120, rounds: 7, cut: 0, allowID: true, tiers: [16, 32] }, 300],
]) {
  const a = swissEngine(cfg, sims, 4242);
  const r = cfg.rounds - 1, nt = a.tiers.length;
  let drew = 0, landed = 0;
  for (let w = 0; w <= r; w++) for (let l = 0; w + l <= r; l++) {
    const ci = (r * 256 + (w * 16 + l)) * 8;
    drew += a.cond[ci + 6];
    if (cfg.cut > 0 && !nt) landed += a.cond[ci + 7];
    else landed += a.tierCond[((nt - 1) * (cfg.rounds + 1) * 256 + r * 256 + (w * 16 + l)) * 4 + 3];
  }
  check(name + " (" + Math.round(drew / sims * 10) / 10 + " drawing players per event)", drew > 0 && landed === drew,
    landed + " of " + drew);
}

// ── 3c. two-day events (Challenges: 8 rounds, 18+ points play 4 more) ──────
{
  const cfg = { ...base, players: 600, rounds: 12, cut: 32, allowID: true, drawRate: 0.03, day2After: 8, day2Pts: 18 };
  const a = swissEngine(cfg, 300, 2026);
  console.log("two-day event (600p, 8+4 rounds, 18 pts, top32):");
  const t = tally(a);
  check("conservation", t.players === 600 && t.cut === 32, "players=" + t.players + " cut=" + t.cut);
  let elimRows = 0, elimCut = 0, shortPts = 0, d2 = 0;
  for (let c = 0; c < 4096; c++) {
    if (!a.recCount[c]) continue;
    const [w, l, d] = dec(c);
    if (w + l + d === 8) { elimRows += a.recCount[c]; elimCut += a.recCut[c]; if (w * 3 + d >= 18) shortPts++; }
    if (w + l + d === 12) d2 += a.recCount[c];
  }
  check("players cut after day one finish on 8 rounds, all under 18", elimRows > 0 && shortPts === 0);
  check("nobody cut after day one ever makes the top cut", elimCut === 0);
  check("about 1 in 7 plays day two", d2 / a.sims > 60 && d2 / a.sims < 110, (d2 / a.sims).toFixed(1));
  // 5-2 after round 7: a loss ends the event at 15 points. Those players must
  // still be in the pool, or 'If you lose' reads off nobody.
  const ci = (7 * 256 + (5 * 16 + 2)) * 8;
  check("5-2 after R7: the losers (out at 15) stay in the pool", a.cond[ci + 4] > 0 && a.cond[ci + 5] === 0);
  check("… and the winners (on 18) can still cut", a.cond[ci + 3] > 0);
}

// ── 4. tie-inclusive prize tiers ───────────────────────────────────────────
{
  const tiers = [16, 32, 64];
  const a = swissEngine({ ...base, players: 136, rounds: 8, cut: 16, allowID: true, drawRate: 0.015, tiers }, 400, 31337);
  console.log("prize tiers (136p/8r, 16/32/64):");
  const paid = tiers.map((_, t) => {
    let s = 0;
    for (let c = 0; c < 4096; c++) s += a.tierRec[t * 4096 + c];
    return s / a.sims;
  });
  check("every tier pays at least its placement (ties included)",
    paid.every((p, t) => p >= tiers[t] - 1e-9), paid.map(x => x.toFixed(1)).join("/"));
  check("tiers are monotone", paid[0] <= paid[1] && paid[1] <= paid[2]);
  const t = tally(a);
  check("conservation with tiers on", t.players === 136 && t.cut === 16);
}

// ── 5. determinism ─────────────────────────────────────────────────────────
{
  console.log("determinism:");
  const cfg = { ...base, players: 64, rounds: 6, cut: 8, allowID: true, drawRate: 0.015 };
  const a1 = swissEngine(cfg, 500, 42), a2 = swissEngine(cfg, 500, 42);
  const same = (x, y) => x.length === y.length && x.every((v, i) => v === y[i]);
  check("same (cfg,n,seed) → identical counts", same([...a1.recCount], [...a2.recCount]));
  check("… identical float accumulators", same([...a1.recOmw], [...a2.recOmw]));

  // The shard plan itself must be stable, and folding it must reproduce.
  const p1 = shardPlan(10000, 1), p2 = shardPlan(10000, 1);
  check("shard plan stable", JSON.stringify(p1) === JSON.stringify(p2) &&
    p1.reduce((s, x) => s + x.n, 0) === 10000 && p1.length === 16);
  const fold = (plan) => {
    let acc = null;
    for (const sh of plan) { const r = swissEngine(cfg, sh.n, sh.seed); acc = acc ? mergeAcc(acc, r) : acc = r; }
    return acc;
  };
  const f1 = fold(shardPlan(2000, 7)), f2 = fold(shardPlan(2000, 7));
  check("in-order shard fold reproduces exactly", same([...f1.recOmw], [...f2.recOmw]) && f1.sims === 2000);
  check("tiny totals shard sanely", shardPlan(5, 1).reduce((s, x) => s + x.n, 0) === 5);
}

console.log(failures === 0 ? "\nAll swiss-engine guards hold." : "\n" + failures + " FAILURES");
process.exit(failures === 0 ? 0 : 1);
