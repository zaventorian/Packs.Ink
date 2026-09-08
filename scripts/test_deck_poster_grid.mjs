// test_deck_poster_grid.mjs — guards the deck poster's card grid against the
// blown-out-column bug.
//
//     node scripts/test_deck_poster_grid.mjs
//
// The regression this locks down (reported from the wild 2026-09-08, a Discord
// screenshot of a Ruby/Amber deck with 4 Locations): the grid was
// `repeat(N, 1fr)`. A bare `1fr` is `minmax(auto, 1fr)`, so a track can never be
// narrower than the min-content of its widest cell -- and a LANDSCAPE cell
// declares `aspect-ratio: 7/5` on the cell itself, because its image is
// absolutely positioned and the cell would otherwise have no height.
//
// Those two facts are in tension, and that is the whole bug. Measured in
// Chromium at 7 columns on a 1000px poster: the row is 188px tall (the portrait
// cards set it), so the 7/5 cell demands 188 * 7/5 = 263px of width. That demand
// became the track's automatic minimum, froze the Location's whole COLUMN at
// ~2x, and starved the other columns -- in the reproduction, three of them to
// literally 0px. Every card sharing a hijacked column rendered oversized,
// including the rows ABOVE the Location, which is why the reporter saw two giant
// cards stacked in one column with the rest of the poster shrunken.
//
// Locations sort last, so the cell that poisons a column is usually below the
// fold of a cropped preview -- there is nothing at the blowout to look at. And
// whether it bites at all depends on which column the Locations happen to land
// in, which is why it read as "not sure if it's just me".
//
// Both halves are pinned here, because removing EITHER brings the bug back:
//   - the track must stay minmax(0, 1fr), or the 7/5 cell hijacks its column;
//   - the landscape cell must keep aspect-ratio 7/5, or it collapses to zero
//     height (the reason it was added -- see CLAUDE.md "Location cards read
//     landscape where you're READING one").
//
// There is no client-side CI, so it is manual — but it reads the real markup out
// of Index.html rather than restating it, so it cannot drift from what ships.
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("../Index.html", import.meta.url), "utf8");
let failures = 0;
const check = (name, ok, detail) => {
  if (ok) { console.log("  ok   " + name); return; }
  failures++;
  console.log("  FAIL " + name + (detail ? "\n         " + detail : ""));
};

// The poster's card grid, found by the template expression that builds it.
const gridRe = /display:"grid",gridTemplateColumns:`repeat\(\$\{cols\},([^`]*)\)`/;
const grid = src.match(gridRe);
check("poster card grid is still built from `cols`", !!grid,
  "no `repeat(${cols},...)` grid template found in Index.html");

if (grid) {
  const track = grid[1];
  check("track is minmax(0,1fr), not a bare 1fr",
    /^minmax\(0,\s*1fr$/.test(track.replace(/\s+/g, " ").trim()) || /minmax\(0,\s*1fr/.test(track),
    "found track sizing `" + track + "`. A bare 1fr lets one cell's min-content " +
    "seize the whole column — see the header of this file.");
  check("track cannot be a bare 1fr", !/^\s*1fr\s*$/.test(track),
    "the grid is back to `repeat(${cols},1fr)`");
}

// The landscape cell keeps the aspect-ratio that makes it a box at all.
check("landscape poster cell still declares aspect-ratio 7/5",
  /\?\s*\{position:"relative",\s*aspectRatio:"7\/5"\}\s*:\s*\{position:"relative"\}/.test(src),
  "the landscape branch of the poster cell no longer sets aspectRatio 7/5 — its " +
  "image is absolutely positioned, so the cell now has no height at all.");

// The landscape image geometry the aspect-ratio is sized against. 71.4286% is
// 5/7: laid out portrait at that width, a quarter turn lands it exactly on the
// wrapper's edges. It is not a round number by accident.
check("landscape poster image is still laid out at 5/7 of the cell",
  /width:"71\.4286%"/.test(src),
  "the rotated poster image's width left 71.4286% (5/7) — the rotation no longer " +
  "lands on the cell edges.");

console.log(failures === 0
  ? "\ndeck poster grid: all checks passed"
  : "\ndeck poster grid: " + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
