// test_collectible_boards.mjs — guards the geometry and repair rules behind
// Collection » Pins & Counters.
//
//     node scripts/test_collectible_boards.mjs
//
// Extracts the real code out of Index.html, house pattern. Every failure here is
// silent on the site: a socket maths slip makes counters that should clip
// together sit a hair apart, a repair rule that throws blanks somebody's board,
// and a tidy that overlaps pins buries the ones underneath.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8").replace(/\r\n/g, "\n");
const NL = "\n";
const grab = (a, b) => {
  const i = src.indexOf(a);
  if (i < 0) throw new Error("missing marker: " + a);
  const j = src.indexOf(b, i);
  if (j < 0) throw new Error("missing end: " + b);
  return src.slice(i, j + b.length);
};
const grabLine = (p) => {
  const l = src.split(NL).find((x) => x.startsWith(p));
  if (!l) throw new Error("missing line: " + p);
  return l;
};

const mod = await import("data:text/javascript," + encodeURIComponent([
  grabLine("const isCollectiblePid = (pid) => "),
  grabLine("const cbClamp = "),
  grab("const COLLECTIBLE_BOARD_BGS = [", NL + "];"),
  grabLine("const COLLECTIBLE_BOARD_DEFAULT_BG = "),
  grabLine("const PIN_BOARD_ASPECT = "),
  grabLine("const PIN_BOARD_BASE = "),
  grabLine("const PIN_TYPICAL_ASPECT = "),
  grabLine("const PIN_BOARD_SCALES = "),
  grab("const pinWidthOf = (aspect, scale) => {", NL + "};"),
  grab("const pinRectOf = (it, aspect, scale) => {", NL + "};"),
  grabLine("const COUNTER_HEX_ASPECT = "),
  grabLine("const COUNTER_BOARD_COLS = "),
  grab("const counterBoardGeom = (count) => {", NL + "};"),
  grab("const counterCellCenter = (g, c, r) => ({", NL + "});"),
  grab("const counterCellAt = (g, x, y) => {", NL + "};"),
  grab("function normalizeCollectibleBoard(kind, raw, knownNs, geom){", NL + "}"),
  grab("function nextFreePinSpot(board, drawnNs, aspectOf, n){", NL + "}"),
  grab("function tidyPins(ns, aspectOf){", NL + "}"),
  grab("function nextFreeCounterCell(board, drawnNs, geom, n){", NL + "}"),
  grab("const tidyCounters = (ns, geom) => {", NL + "};"),
  grab("const collectibleBoardsUnavailable = (err) => {", NL + "};"),
  "export {isCollectiblePid, PIN_BOARD_ASPECT, PIN_BOARD_BASE, PIN_TYPICAL_ASPECT, PIN_BOARD_SCALES, pinWidthOf, pinRectOf,",
  "  COUNTER_BOARD_COLS, counterBoardGeom, counterCellCenter, counterCellAt, normalizeCollectibleBoard,",
  "  nextFreePinSpot, tidyPins, nextFreeCounterCell, tidyCounters, collectibleBoardsUnavailable};",
].join(NL)));

let failed = 0;
const ok = (name, cond, detail) => {
  if (!cond) failed++;
  console.log((cond ? "PASS  " : "FAIL  ") + name + (cond ? "" : "  " + (detail ?? "")));
};
const near = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

// ── Which pids are collectibles ─────────────────────────────────────────────
ok("a pin pid is a collectible", mod.isCollectiblePid(950000001));
ok("a lore counter pid is a collectible", mod.isCollectiblePid(960000021));
ok("a string pid works too (sealedCollection keys are strings)", mod.isCollectiblePid("950000005"));
ok("a puzzle pid is not", !mod.isCollectiblePid(912001621));
ok("a TCGplayer pid is not", !mod.isCollectiblePid(593110));

// ── Pins: equal area, not equal width ───────────────────────────────────────
ok("a typical pin at M is the base width", near(mod.pinWidthOf(mod.PIN_TYPICAL_ASPECT, 1), mod.PIN_BOARD_BASE));
{
  const area = (ar) => { const w = mod.pinWidthOf(ar, 1); return w * (w / ar); };
  ok("a logo pin and a pendant pin cover the same area", near(area(2.3), area(0.7)) && near(area(0.7), area(0.76)),
    [area(2.3), area(0.7), area(0.76)].join(" "));
}
ok("a silly aspect can't make a pin wider than a third of the board", mod.pinWidthOf(50, 1.25) <= 0.32);
ok("a missing aspect falls back to the typical pin", near(mod.pinWidthOf(undefined, 1), mod.PIN_BOARD_BASE));

// ── Counters: the honeycomb ────────────────────────────────────────────────
{
  const g = mod.counterBoardGeom(21);
  ok("21 counters get a 7 × 6 board (spare sockets to rearrange into)", g.cols === 7 && g.rows === 6, g.cols + "x" + g.rows);
  ok("the board grows with the catalog", mod.counterBoardGeom(40).rows === 9, mod.counterBoardGeom(40).rows);
  let roundTrip = true;
  for (let r = 0; r < g.rows; r++) for (let c = 0; c < g.cols; c++) {
    const p = mod.counterCellCenter(g, c, r);
    const back = mod.counterCellAt(g, p.x, p.y);
    if (!back || back.c !== c || back.r !== r) roundTrip = false;
  }
  ok("every socket's centre resolves back to that socket", roundTrip);
  // The property that makes counters clip together: every neighbouring pair of
  // sockets — same row or adjacent rows — sits exactly one socket-width apart.
  const dist = (a, b) => Math.hypot((a.x - b.x) * g.W, (a.y - b.y) * g.H);
  const c00 = mod.counterCellCenter(g, 2, 2);
  ok("side-by-side sockets are one width apart", near(dist(c00, mod.counterCellCenter(g, 3, 2)), 1));
  ok("sockets in the next row are one width apart too (the honeycomb closes)",
    near(dist(c00, mod.counterCellCenter(g, 2, 3)), 1) && near(dist(c00, mod.counterCellCenter(g, 1, 3)), 1),
    [dist(c00, mod.counterCellCenter(g, 2, 3)), dist(c00, mod.counterCellCenter(g, 1, 3))].join(" "));
  ok("the socket is the counters' shape: 0.866 wide-to-tall", near(1 / g.h, Math.sqrt(3) / 2));
  const edge = mod.counterCellAt(g, 0.99, 0.99);
  ok("a drop in the corner still finds a socket", !!edge && edge.r === g.rows - 1, JSON.stringify(edge));
}

// ── normalizeCollectibleBoard never throws, and repairs ──────────────────────
{
  const known = [1, 2, 3, 4, 5];
  const g = mod.counterBoardGeom(21);
  const blank = mod.normalizeCollectibleBoard("pins", null, known);
  ok("no record → a cork board at medium size, empty", blank.bg === "cork" && blank.scale === 1 && Object.keys(blank.items).length === 0,
    JSON.stringify(blank));
  ok("counters default to felt", mod.normalizeCollectibleBoard("counters", undefined, known, g).bg === "felt");
  for (const junk of ["x", 42, [], [1, 2], {items: "no"}, {items: [1]}]) {
    let threw = false, out;
    try { out = mod.normalizeCollectibleBoard("pins", junk, known); } catch { threw = true; }
    ok("junk " + JSON.stringify(junk) + " is repaired, not thrown", !threw && out && Object.keys(out.items).length === 0);
  }
  const pins = mod.normalizeCollectibleBoard("pins", {bg: "lava", scale: 3, items: {
    1: {x: 0.5, y: 0.5, r: 12.6, z: 3},
    2: {x: 1.7, y: -2, r: 999, z: -4},
    3: {x: "nope", y: 0.2},
    99: {x: 0.1, y: 0.1},
  }}, known);
  ok("an unknown background falls back to the default", pins.bg === "cork", pins.bg);
  ok("an unknown size falls back to medium", pins.scale === 1, pins.scale);
  ok("a good placement survives, rounded", JSON.stringify(pins.items["1"]) === JSON.stringify({x: 0.5, y: 0.5, r: 13, z: 3}),
    JSON.stringify(pins.items["1"]));
  ok("an off-board placement is clamped onto the board", pins.items["2"].x === 1 && pins.items["2"].y === 0 && pins.items["2"].r === 180 && pins.items["2"].z === 0,
    JSON.stringify(pins.items["2"]));
  ok("a placement with no position is dropped", !("3" in pins.items));
  ok("a number the catalog doesn't have is dropped", !("99" in pins.items));
  ok("a valid size is kept", mod.normalizeCollectibleBoard("pins", {scale: 1.25}, known).scale === 1.25);

  const counters = mod.normalizeCollectibleBoard("counters", {bg: "midnight", items: {
    4: {c: 1, r: 1},
    2: {c: 1, r: 1},
    3: {c: 7, r: 0},
    5: {c: 2.5, r: 1},
    1: {c: 0, r: 5},
  }}, known, g);
  ok("a chosen background is kept", counters.bg === "midnight");
  ok("two counters can't share a socket — the earlier release keeps it",
    counters.items["2"] && !("4" in counters.items), JSON.stringify(counters.items));
  ok("a socket off the grid is dropped", !("3" in counters.items));
  ok("a fractional socket is dropped", !("5" in counters.items));
  ok("the last row is on the grid", JSON.stringify(counters.items["1"]) === JSON.stringify({c: 0, r: 5}));
}

// ── Placement ───────────────────────────────────────────────────────────────
// The 41 real pin photos, natural width / height (measured 2026-09-11).
const ASPECTS = [1.07, 2.19, 0.77, 0.77, 2.22, 0.76, 2.30, 0.76, 2.32, 0.76, 0.77, 0.76, 0.76, 2.28, 0.93, 0.77,
  2.30, 0.77, 2.31, 0.78, 0.78, 0.70, 0.87, 0.76, 0.76, 0.92, 0.80, 0.80, 0.76, 0.75, 0.89, 0.76, 0.75, 0.76,
  0.92, 0.91, 0.72, 0.72, 0.72, 0.72, 0.87];
const aspectOf = (n) => ASPECTS[Number(n) - 1] || mod.PIN_TYPICAL_ASPECT;
const overlaps = (a, b) => !(a.x1 <= b.x0 || b.x1 <= a.x0 || a.y1 <= b.y0 || b.y1 <= a.y0);
const checkTidy = (ns) => {
  const t = mod.tidyPins(ns, aspectOf);
  const rects = ns.map((n) => mod.pinRectOf(t.items[String(n)], aspectOf(n), t.scale));
  let clash = null;
  for (let i = 0; i < rects.length && !clash; i++)
    for (let j = i + 1; j < rects.length; j++) if (overlaps(rects[i], rects[j])) { clash = [ns[i], ns[j]]; break; }
  const inside = rects.every((r) => r.x0 >= -1e-9 && r.x1 <= 1 + 1e-9 && r.y0 >= -1e-9 && r.y1 <= 1 + 1e-9);
  return {t, clash, inside};
};
{
  const all = ASPECTS.map((_, i) => i + 1);
  const full = checkTidy(all);
  ok("tidying all 41 pins overlaps none of them", !full.clash, JSON.stringify(full.clash));
  ok("…and keeps every one on the board", full.inside);
  ok("…at the size that fits (small)", full.t.scale === 0.8, full.t.scale);
  const few = checkTidy([2, 3, 23]);
  ok("a handful of pins tidy at the large size", few.t.scale === 1.25 && !few.clash && few.inside, JSON.stringify(few.t));
  ok("tidy places every pin it is given", Object.keys(full.t.items).length === 41);

  const board = {scale: 1, items: {1: {x: 0.2, y: 0.3, r: 0, z: 1}, 2: {x: 0.5, y: 0.5, r: 0, z: 2}}};
  const spot = mod.nextFreePinSpot(board, ["1", "2", "7"], aspectOf, "7");
  const me = mod.pinRectOf(spot, aspectOf(7), 1);
  ok("a placed pin clears the pins already up", !overlaps(me, mod.pinRectOf(board.items[1], aspectOf(1), 1))
    && !overlaps(me, mod.pinRectOf(board.items[2], aspectOf(2), 1)), JSON.stringify(spot));
  ok("…and sits on the board", me.x0 >= 0 && me.x1 <= 1 && me.y0 >= 0 && me.y1 <= 1);
  ok("a pin you don't own anymore doesn't block the spot", (() => {
    const s = mod.nextFreePinSpot({scale: 1, items: {9: {x: 0.03, y: 0.05}}}, ["5"], aspectOf, "5");
    return s.y < 0.2;
  })());
}
{
  const g = mod.counterBoardGeom(21);
  const board = {items: {1: {c: 0, r: 0}, 2: {c: 1, r: 0}, 8: {c: 2, r: 0}}};
  ok("the next counter takes the first empty socket", JSON.stringify(mod.nextFreeCounterCell(board, ["1", "2", "3"], g, "3")) === JSON.stringify({c: 2, r: 0}),
    JSON.stringify(mod.nextFreeCounterCell(board, ["1", "2", "3"], g, "3")));
  ok("…where a counter you don't own doesn't hold a socket", !!mod.nextFreeCounterCell(board, ["1", "2", "3"], g, "3"));
  const full = {items: {}};
  const ns = [];
  for (let i = 0; i < g.cols * g.rows; i++) { full.items[String(i + 1)] = {c: i % g.cols, r: Math.floor(i / g.cols)}; ns.push(String(i + 1)); }
  ok("a full board reports no socket", mod.nextFreeCounterCell(full, [...ns, "999"], g, "999") === null);
  const tidy = mod.tidyCounters(["3", "7", "11"], g);
  ok("tidy fills sockets in reading order", JSON.stringify(tidy) === JSON.stringify({3: {c: 0, r: 0}, 7: {c: 1, r: 0}, 11: {c: 2, r: 0}}),
    JSON.stringify(tidy));
  ok("tidy never overflows the grid", Object.keys(mod.tidyCounters(Array.from({length: 99}, (_, i) => String(i)), g)).length === g.cols * g.rows);
}

// ── The pre-migration fallback ─────────────────────────────────────────────
ok("a missing table reads as unavailable", mod.collectibleBoardsUnavailable({code: "PGRST205", message: "Could not find the table"}));
ok("…as does a bare 42P01", mod.collectibleBoardsUnavailable({code: "42P01"}));
ok("…and a missing RPC", mod.collectibleBoardsUnavailable({code: "PGRST202"}));
ok("a network failure is NOT 'unavailable' (it must not write)", !mod.collectibleBoardsUnavailable({message: "Failed to fetch"}));

console.log(NL + (failed ? failed + " FAILED" : "all passed"));
process.exit(failed ? 1 : 0);
