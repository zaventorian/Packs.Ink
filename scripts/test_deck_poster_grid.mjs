// test_deck_poster_grid.mjs — guards the deck poster's card grid: the
// blown-out-column bug, and the size a Location renders at.
//
//     node scripts/test_deck_poster_grid.mjs
//
// THE COLUMN BUG (reported from the wild 2026-09-08, a Discord screenshot of a
// Ruby/Amber deck with 4 Locations): the grid was `repeat(N, 1fr)`. A bare
// `1fr` is `minmax(auto, 1fr)`, so a track can never be narrower than the
// min-content of its widest cell -- and the landscape cell then declared
// `aspect-ratio: 7/5` on itself, which at a row height set by the portrait
// cards (188px at 7 columns on the 1000px poster) demanded 263px of width.
// That demand became the track's automatic minimum, froze the Location's whole
// COLUMN at ~2x and starved the others -- three of them to literally 0px in the
// reproduction, with every card sharing a hijacked column (the rows ABOVE the
// Location included) rendering oversized. Locations sort last, so the poisoning
// cell is usually below the fold of a cropped preview: there is nothing at the
// blowout to look at, which is why it read as "not sure if it's just me".
// `minmax(0,` is the general defence and stays, whatever shape the cell takes.
//
// THE SIZE (reported twice, 2026-09-18, both times as "it['s] small"): a
// rotated card does not shrink. A portrait cell is W wide and 1.4W tall, so a
// card's long edge is 1.4W -- turn the same card sideways and the long edge is
// still 1.4W, which does not fit in one W-wide column. Every version that
// squeezed it into one column therefore drew the Location at 1/1.4 = 71% the
// linear size of every card beside it. A cover-fit crop to a portrait footprint
// was tried in between and rejected: "still horizontal and card not cut off ...
// as if you turned the real card horizontal".
//
// THE HOLE (same day, third report): giving each Location its own 2-column span
// got the size right and left ~45px of dead air on either side of the card, so
// two neighbouring Locations sat ~100px apart. A RUN of landscape cards now
// shares ONE full-width row and lays out as a flex line at the grid's own 10px
// gap. Each card is still exactly 1.4W, because the row is the full grid width:
// (100% - (cols-1)*10) / cols is W by construction at every column count.
//
// Measured in Chromium against this exact markup, at every column count the
// poster offers (5/6/7/8): the Location's long edge equals a portrait card's
// long edge to within 0.03px (188.0 vs 188.0 at 7 columns), two adjacent
// Locations sit 10px apart, and the quantity badge rides the card's own corner
// 6px in -- not the row's.
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
    /minmax\(0,\s*1fr/.test(track),
    "found track sizing `" + track + "`. A bare 1fr lets one cell's min-content " +
    "seize the whole column — see the header of this file.");
  check("track cannot be a bare 1fr", !/^\s*1fr\s*$/.test(track),
    "the grid is back to `repeat(${cols},1fr)`");
}

// Landscape cards are grouped into runs by ADJACENCY, so the grouping still
// works if a Location ever stops sorting last — it just takes a row of its own.
const groupMemo = src.match(/const posterGroups = useMemo\(\(\) => \{\n([\s\S]*?)\n  \}, \[cards\]\);/);
check("the poster still groups landscape cards into runs", !!groupMemo,
  "the `posterGroups` useMemo is gone — without it every Location is its own " +
  "cell again and neighbouring Locations go back to sitting ~100px apart.");
if (groupMemo) {
  const body = groupMemo[1];
  check("grouping is by adjacency, not by card type",
    /prev\s*&&\s*prev\.landscape/.test(body) && /isLandscapeCard/.test(body),
    "the run grouping no longer joins a landscape card to the landscape card " +
    "BEFORE it. Grouping on 'is a Location' alone would put a Location that " +
    "isn't last into the same row as one that is.");
}

// A run takes a full-width row; the cards inside it are a flex line at the
// grid's own gap, which is what makes two Locations sit 10px apart.
check("a landscape run takes a full-width row",
  /gridColumn:"1 \/ -1",display:"flex",flexWrap:"wrap",gap:10/.test(src),
  "the landscape run no longer spans the whole grid as a wrapping flex row. " +
  "Per-card 2-column spans put ~45px of dead air on each side of every card, " +
  "so two neighbouring Locations sat ~100px apart — the 'giant gap' report.");

// The card's own footprint: 1.4 * the column width the grid itself is using,
// which is exactly a portrait card's long edge. aspect-ratio 7/5 makes the
// short edge W. IN FLOW, so a row of nothing but Locations still has a height.
check("landscape card box is 1.4 grid columns wide at aspect-ratio 7/5",
  /width:`calc\(\(100% - \$\{\(cols-1\)\*10\}px\) \/ \$\{cols\} \* 1\.4\)`,aspectRatio:"7\/5"/.test(src),
  "the landscape card box is no longer sized at 1.4 of the grid's own column " +
  "width — that is what makes the rotated card exactly as big as its portrait " +
  "neighbours, at every column count the poster offers.");

// 71.4286% is 5/7: laid out portrait at that width inside the 7/5 box, a quarter
// turn lands the image exactly on the box's edges — EXACT fit, no cropping.
check("landscape poster image is still laid out at 5/7 of its box",
  /width:"71\.4286%"/.test(src),
  "the rotated poster image's width left 71.4286% (5/7) — the rotation no longer " +
  "lands on the box's edges.");

// The 2026-09-18 cover-crop attempt must not have crept back in.
check("landscape poster image is NOT overscaled/cropped",
  !/width:"140%"/.test(src) && !src.includes('aspectRatio:"5/7", overflow:"hidden"'),
  "found the reverted cover-crop sizing (140% width / a clipped 5/7 cell) — the " +
  "card must render whole, uncropped, same as a physically rotated card.");

console.log(failures === 0
  ? "\ndeck poster grid: all checks passed"
  : "\ndeck poster grid: " + failures + " FAILED");
process.exit(failures === 0 ? 0 : 1);
