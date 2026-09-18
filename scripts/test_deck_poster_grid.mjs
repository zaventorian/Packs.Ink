// test_deck_poster_grid.mjs — guards the deck poster's card grid against the
// blown-out-column bug, and against a Location cell being a visible runt.
//
//     node scripts/test_deck_poster_grid.mjs
//
// Bug #1 (reported from the wild 2026-09-08, a Discord screenshot of a
// Ruby/Amber deck with 4 Locations): the grid was `repeat(N, 1fr)`. A bare
// `1fr` is `minmax(auto, 1fr)`, so a track can never be narrower than the
// min-content of its widest cell -- and a landscape cell used to declare
// `aspect-ratio: 7/5` on the cell itself (its image is absolutely positioned,
// so the cell needs the aspect-ratio to have a height at all). Measured in
// Chromium at 7 columns on a 1000px poster: the row was 188px tall (the
// portrait cards set it), so a 7/5 cell demanded 188 * 7/5 = 263px of width.
// That demand became the track's automatic minimum, froze the Location's
// whole COLUMN at ~2x, and starved the other columns -- in the reproduction,
// three of them to literally 0px. The track must stay `minmax(0, 1fr)`, or a
// cell whose min-content is wider than the column can hijack it again.
//
// Bug #2 (reported 2026-09-18): with the cell shaped 7/5 (shorter than a
// portrait cell), a Location rendered visibly SMALLER than every card around
// it -- same width, much less height. The cell now keeps the SAME 5/7
// footprint as every other card, and the rotated image is overscaled to
// 140% width (COVER, not exact-fit) so it fills that taller box and is
// center-cropped left/right by the cell's own `overflow:hidden`, rather than
// shrinking the whole cell to fit the image untouched.
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

// The landscape cell matches the portrait cell's footprint (5/7), same as
// every other card, and clips the overscaled image to it.
check("landscape poster cell matches the portrait 5/7 footprint",
  /\?\s*\{position:"relative",\s*aspectRatio:"5\/7",\s*overflow:"hidden",\s*borderRadius:8\}\s*:\s*\{position:"relative"\}/.test(src),
  "the landscape branch of the poster cell no longer sets aspectRatio 5/7 + " +
  "overflow:hidden — it will render shorter than its portrait neighbours again.");
check("landscape poster cell does NOT go back to the shorter 7/5 box",
  !/\?\s*\{position:"relative",\s*aspectRatio:"7\/5"\}\s*:\s*\{position:"relative"\}/.test(src),
  "found the old 7/5 landscape cell shape — that is the shorter box that made " +
  "a Location look smaller than the cards around it.");

// The landscape image is overscaled to COVER the taller 5/7 box (140% width,
// still sized by the 5/7 aspect-ratio) rather than exact-fitting a 7/5 one.
check("landscape poster image is overscaled to 140% to cover the cell",
  /width:"140%",height:"auto",\s*aspectRatio:"5\/7"/.test(src),
  "the rotated poster image is no longer sized at 140% width / aspect-ratio 5/7 " +
  "— it will exact-fit a 7/5 box again instead of covering the 5/7 cell.");

console.log(failures === 0
  ? "\ndeck poster grid: all checks passed"
  : "\ndeck poster grid: " + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
