// test_deck_image.mjs — guards the deck-poster lattice maths in scanner.js.
//
//     node scripts/test_deck_image.mjs
//
// A deck poster is a regular lattice of full card faces, and scanDeckImage
// recovers that lattice by autocorrelating a detail profile. Two things break
// silently there and both cost real cards:
//
//   1. Autocorrelation peaks just as hard at 2x and 3x the true pitch. Without
//      the sub-multiple candidates a 7-wide poster reads as 3 columns of
//      double-width cells and every crop is half of two different cards.
//   2. Candidate lattices must be scored by ESTIMATED CARD YIELD, not by mean
//      or median cosine — empty trailing cells drag a median down, so the
//      lattice finding MORE cards scores WORSE. That bug made a 3-row poster
//      import as its middle row only (8 of 17 cards), silently.
//
// These are pure numeric helpers, so they are read straight out of scanner.js
// and exercised here without a canvas. Run after touching the lattice code.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../scanner.js", import.meta.url), "utf8");

function grab(startMarker, endMarker) {
  const a = src.indexOf(startMarker);
  if (a < 0) throw new Error("missing start marker: " + startMarker);
  const b = src.indexOf(endMarker, a);
  if (b < 0) throw new Error("missing end marker: " + endMarker);
  return src.slice(a, b + endMarker.length);
}

const code = [
  grab("  function detrend(p) {", "\n  }"),
  grab("  function acf(p, lo, hi) {", "\n  }"),
  grab("  function periodCands(ac) {", "\n  }"),
  grab("  function gridPhase(p, pitch) {", "\n  }"),
  grab("  function halfSpan(v) {", "\n  }"),
  grab("  function sweepPitches(rw, maxCols, minCols) {", "\n  }"),
  grab("  function components(mask, w, h) {", "\n  }"),
  grab("  function fitBox(g, w, h) {", "\n  }"),
  grab("  function splitWide(c, gw) {", "\n  }"),
  "var QTW = 20, QTH = 22;",
].join("\n");

const api = new Function(
  code + "\nreturn {detrend,acf,periodCands,gridPhase,halfSpan,sweepPitches,components,fitBox,splitWide};",
)();

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log("  ok   " + name); }
  else { fail++; console.log("  FAIL " + name + (extra ? "  -> " + extra : "")); }
};

// A poster profile: `cards` plateaus of `card` px separated by `gap` px gutters.
function posterProfile(n, card, gap, lead) {
  const pitch = card + gap, out = new Float32Array(lead + n * pitch + lead);
  for (let c = 0; c < n; c++)
    for (let i = 0; i < card; i++) out[lead + c * pitch + i] = 0.85;
  return { p: out, pitch };
}

console.log("lattice period recovery");
for (const [cols, card, gap] of [[7, 120, 14], [8, 96, 10], [6, 150, 22], [3, 220, 30]]) {
  const { p, pitch } = posterProfile(cols, card, gap, 40);
  const cands = api.periodCands(api.acf(p, 30, Math.floor(p.length / 2)));
  const hit = cands.some((c) => Math.abs(c - pitch) <= 3);
  ok(`${cols} cols @ pitch ${pitch} is a candidate`, hit, "got " + cands.join(","));
}

// The regression: the strongest peak is often a MULTIPLE of the true pitch.
// periodCands must still offer the true pitch via the sub-multiple pass.
{
  // Alternating busy/quiet cards (a row of light art next to dark art) makes the
  // 2x-pitch peak the STRONGEST one. The true pitch has to survive anyway.
  const cols = 8, card = 96, gap = 10, pitch = card + gap, lead = 40;
  const p = new Float32Array(lead + cols * pitch + lead);
  for (let c = 0; c < cols; c++)
    for (let i = 0; i < card; i++) p[lead + c * pitch + i] = c % 2 ? 0.95 : 0.45;
  const ac = api.acf(p, 30, Math.floor(p.length / 2));
  const cands = api.periodCands(ac);
  const best = cands.slice().sort((a, b) => ac[b] - ac[a])[0];
  ok("top autocorrelation peak really is a multiple here",
    Math.abs(best - 2 * pitch) <= 4, `top peak ${best}, pitch ${pitch}`);
  ok("sub-multiples rescue the true pitch",
    cands.some((c) => Math.abs(c - pitch) <= 3),
    `top peak ${best}, true pitch ${pitch}, cands ${cands.join(",")}`);
}

console.log("phase + span");
{
  const { p, pitch } = posterProfile(6, 100, 20, 37);
  const off = api.gridPhase(p, pitch);
  // A grid line must land in a gutter, never inside a card.
  const inGutter = [];
  for (let i = off; i < p.length; i += pitch) inGutter.push(p[i]);
  ok("gridPhase puts every lattice line on a gutter",
    inGutter.every((v) => v < 0.2), "values " + inGutter.join(","));
}
{
  const v = new Float32Array(50);
  for (let i = 12; i < 38; i++) v[i] = 1;
  const s = api.halfSpan(v);
  ok("halfSpan finds the plateau", s[0] === 12 && s[1] === 38, s.join(".."));
}
{
  const v = new Float32Array(20).fill(0.5);
  const s = api.halfSpan(v);
  ok("halfSpan on a flat profile returns the whole span", s[0] === 0 && s[1] === 20, s.join(".."));
}

console.log("pitch sweep fallback");
{
  // The rescue case: a poster whose strongest periodicity is 2.58x the card
  // pitch, so no integer sub-multiple can reach the truth. The sweep must.
  const sw = api.sweepPitches(1023, 16, 2);
  ok("sweep covers the true pitch of a 1023px 8-wide poster",
    sw.some((p) => Math.abs(p - 128) <= 4), "nearest " + sw.reduce((a,b)=>Math.abs(b-128)<Math.abs(a-128)?b:a));
  ok("sweep steps finely enough to hit any pitch within 2%",
    sw.every((p, i) => i === 0 || p / sw[i-1] <= 1.05), "steps " + sw.slice(0,5).join(","));
  ok("sweep stays inside the column bounds",
    sw[0] >= Math.floor(1023/16) && sw[sw.length-1] <= Math.floor(1023/2) + 1,
    `${sw[0]}..${sw[sw.length-1]}`);
}

console.log("glyph plumbing");
{
  const w = 9, h = 5, m = new Uint8Array(w * h);
  const on = (x, y) => { m[y * w + x] = 1; };
  on(1,1); on(2,1); on(1,2);  on(6,1); on(7,1); on(7,2);  on(4,3);
  const cs = api.components(m, w, h);
  ok("components separates 3 blobs (4-connected, no diagonal merge)", cs.length === 3, "got " + cs.length);
  const b0 = cs.find((c) => c.x0 === 1);
  ok("component bbox is right", b0 && b0.x1 === 2 && b0.y0 === 1 && b0.y1 === 2,
    b0 ? [b0.x0,b0.y0,b0.x1,b0.y1].join(",") : "none");
}
{
  // Width is what separates a "1" from a "4"; fitBox must not clamp it away.
  const tall = new Float32Array(4 * 40).fill(255);        // aspect 0.10
  const wide = new Float32Array(33 * 40).fill(255);       // aspect 0.83
  const inkCols = (b) => {
    let lo = 99, hi = -1;
    for (let x = 0; x < 20; x++) for (let y = 0; y < 22; y++)
      if (b[y*20+x] > 10) { if (x < lo) lo = x; if (x > hi) hi = x; }
    return hi - lo + 1;
  };
  const a = inkCols(api.fitBox(tall, 4, 40)), c = inkCols(api.fitBox(wide, 33, 40));
  ok("fitBox preserves a narrow glyph's width", a <= 4, "narrow filled " + a + " of 20");
  ok("fitBox preserves a wide glyph's width", c >= 15, "wide filled " + c + " of 20");
  ok("fitBox keeps them distinguishable", c - a >= 10, `narrow ${a} vs wide ${c}`);
}
{
  // "2x" merging into one blob is what made a real cell unreadable.
  const gw = 20, gh = 10, lab = new Int32Array(gw*gh).fill(-1);
  for (let y = 1; y < 9; y++) { for (let x = 2; x < 8; x++) lab[y*gw+x] = 0; }
  for (let y = 3; y < 8; y++) { for (let x = 11; x < 16; x++) lab[y*gw+x] = 0; }
  lab[5*gw+8] = 0; lab[5*gw+9] = 0; lab[5*gw+10] = 0;      // the bridge
  const c = {id:0, lab, x0:2, y0:1, x1:15, y1:8};
  const pair = api.splitWide(c, gw);
  ok("splitWide returns two halves", !!pair && pair.length === 2, pair ? "ok" : "null");
  if (pair) {
    ok("left half is the taller glyph", (pair[0].y1-pair[0].y0) > (pair[1].y1-pair[1].y0),
      `${pair[0].y1-pair[0].y0} vs ${pair[1].y1-pair[1].y0}`);
    ok("halves do not overlap", pair[0].x1 < pair[1].x0, `${pair[0].x1} < ${pair[1].x0}`);
  }
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
