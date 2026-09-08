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
].join("\n");

const api = new Function(
  code + "\nreturn {detrend,acf,periodCands,gridPhase,halfSpan};",
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

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
