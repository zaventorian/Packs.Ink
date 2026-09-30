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
// THE HOLE (2026-09-18, third report): giving each Location its own 2-column
// span got the size right and left ~45px of dead air on either side of the
// card, so two neighbouring Locations sat ~100px apart. Forcing the whole run
// onto ONE full-width row (`gridColumn:"1 / -1"`) fixed that -- but a forced
// full span can only be placed in an entirely EMPTY row, so a run that landed
// after a half-full row (3 items in a 7-wide row, say) got its own new,
// mostly-empty row below rather than continuing the one it had room to share.
//
// THE SHARED ROW (same day, fourth report -- "keep the locations on the same
// line as the other cards assuming there is room?"): the run is now placed
// with `gridColumn:`span ${spanCols}`` and NO explicit start. Plain CSS Grid
// auto-placement tries the CURRENT row first and only wraps to a new one when
// the span doesn't fit -- exactly "share when there's room, else wrap" -- and
// it already knows about every cell a Coconut leader's 2x2 span reserved, so
// nothing has to re-derive that. `spanCols = max(2, ceil(n * 1.4))` is provably
// enough room for n cards at 1.4W plus their internal 10px gaps, whatever n is
// (spanCols always exceeds n itself for n>=1, and spanCols >= 1.4n).
//
// Each card is sized off `spanCols`, not the grid's own `cols` --
// `calc((100% - (spanCols-1)*10px) / spanCols * 1.4)`. A cell spanning N
// tracks of a `repeat(cols, minmax(0,1fr))` grid has width exactly
// N*W + (N-1)*10 (a spanning item's box includes the gutters between the
// tracks it spans), so the formula algebraically cancels back to W --
// the SAME 1.4W every portrait card's neighbour gets -- regardless of N.
//
// Measured in Chromium against this exact geometry: a 1-item run (spanCols=2)
// shares the current row and lands exactly 10.0px from the previous card,
// zero dead air; a 2-item run (spanCols=3) shares the row AND its own two
// Locations sit 10.0px apart -- the exact hole the full-width fix closed; a
// run landing after a row CSS Grid can't fit it into correctly wraps to a new
// one; and the pre-rotation image width comes back bit-identical to a
// portrait card's own width at both spanCols=2 and spanCols=3.
//
// THE BADGE AND THE DECK EDITOR (2026-09-30). The run's flex line stretched
// each card's box to the row's height, so a Location's quantity badge, pinned
// to the box's top, floated above the card and left of its cost ("line up
// above the ink cost, it's weirdly to the left"): the line is flex-start now
// and the badge sits above the card, right-aligned over the cost hexagon, in
// room reserved for it. The deck editor's image grid and stacked pile drew a
// Location one column wide ("too small ... not full card size?"); they share
// the poster's run helpers through DeckTileGrid, checked below.
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

// The run rule lives in module-level helpers shared with the deck editor's
// image grid and stacked pile (2026-09-30). They are lifted out of Index.html
// and RUN here, so the arithmetic is checked, not just its spelling.
const helperSrc = (() => {
  const a = src.indexOf("const isLandscapeCard = (row) =>");
  const b = src.indexOf("const POSTER_LSCAPE_BADGE_ROOM = ");
  if (a < 0 || b < 0 || b < a) return null;
  return src.slice(a, src.indexOf("\n", b) + 1);
})();
check("the shared landscape-run helpers are still in Index.html", !!helperSrc,
  "isLandscapeCard .. POSTER_LSCAPE_BADGE_ROOM no longer read as one block");
let H = null;
if (helperSrc) {
  H = new Function("html", helperSrc +
    "; return {groupLandscapeRuns, landscapeRunSpan, landscapeRunCardWidth, POSTER_LSCAPE_BADGE_ROOM};")(() => null);
}
if (H) {
  // Grouped by ADJACENCY, so a Location that somehow isn't last still renders
  // correctly — it just takes a cell of its own.
  const loc = (id) => ({ card_id: id, meta: { card_type: "Location" } });
  const chr = (id) => ({ card_id: id, meta: { card_type: "Character" } });
  const runs = H.groupLandscapeRuns([chr("a"), loc("b"), loc("c"), chr("d"), loc("e")]);
  const shape = JSON.stringify(runs.map(r => [r.landscape, r.items.map(i => i.card_id).join("")]));
  check("grouping is by adjacency, not by card type",
    shape === JSON.stringify([[false, "a"], [true, "bc"], [false, "d"], [true, "e"]]),
    "got " + shape + ". Grouping on 'is a Location' alone would put a Location " +
    "that isn't last into the same row as one that is.");

  // spanCols = max(2, ceil(1.4n)), capped at the grid's own column count.
  const spans = [1, 2, 3, 4, 5].map(n => H.landscapeRunSpan(n, 99));
  check("a run spans max(2, ceil(1.4n)) columns",
    JSON.stringify(spans) === JSON.stringify([2, 3, 5, 6, 7]), "got " + JSON.stringify(spans));
  check("a run never spans more columns than the grid has",
    H.landscapeRunSpan(4, 3) === 3 && H.landscapeRunSpan(1, 1) === 1,
    "a span wider than the grid makes CSS Grid add implicit columns, which " +
    "breaks the whole grid");

  // PROVABLY enough room: n cards at 1.4W plus (n-1) gaps fit in the span.
  let roomy = true;
  for (let n = 1; n <= 12; n++) for (const gap of [8, 10, 22]) for (const W of [80, 110, 127, 180]) {
    const S = H.landscapeRunSpan(n, 99);
    if (n * 1.4 * W + (n - 1) * gap > S * W + (S - 1) * gap + 1e-9) roomy = false;
  }
  check("an uncapped span always holds its n cards at 1.4W plus their gaps", roomy);

  // The card is 1.4W of ITS OWN cell, whatever the span: evaluate the calc()
  // for a cell S*W + (S-1)*gap wide and it must come back to exactly 1.4W.
  // Sizing off the grid's full `cols` renders the wrong size the moment a
  // run's span is narrower than the grid.
  let exact = true, form = "";
  for (const [S, gap] of [[2, 10], [3, 10], [2, 8], [5, 22]]) {
    form = H.landscapeRunCardWidth(S, gap);
    const m = form.match(/^min\(100%, calc\(\(100% - (\d+)px\) \/ (\d+) \* 1\.4\)\)$/);
    const W = 127, cell = S * W + (S - 1) * gap;
    if (!m || Math.abs((cell - Number(m[1])) / Number(m[2]) * 1.4 - 1.4 * W) > 1e-9) exact = false;
  }
  check("a landscape card is 1.4 columns of its own cell, capped at the cell", exact,
    "got `" + form + "`. Without min(100%, ...) a one-column grid draws the " +
    "card 40% wider than the grid.");

  // The poster's badge room: 6px down (level with the portrait badges beside
  // it) + the 25px badge (14px/800 type, 3px padding) + a gap, above the card.
  check("the poster reserves room ABOVE a Location for its badge",
    H.POSTER_LSCAPE_BADGE_ROOM >= 6 + 25 + 2,
    "POSTER_LSCAPE_BADGE_ROOM is " + H.POSTER_LSCAPE_BADGE_ROOM);
}

check("the poster still groups landscape cards into runs",
  /const posterGroups = useMemo\(\(\) => groupLandscapeRuns\(cards\), \[cards\]\);/.test(src),
  "the `posterGroups` useMemo no longer calls groupLandscapeRuns — without it " +
  "every Location is its own cell again and neighbouring Locations go back to " +
  "sitting ~100px apart.");
check("the poster sizes each run from the shared helpers",
  /const spanCols = landscapeRunSpan\(g\.items\.length, cols\);/.test(src) &&
    /width:landscapeRunCardWidth\(spanCols, 10\),paddingTop:POSTER_LSCAPE_BADGE_ROOM/.test(src),
  "the poster's landscape run no longer takes its span from landscapeRunSpan and " +
  "its card width from landscapeRunCardWidth, or lost the badge's room");

// The run is placed with a SPAN and no explicit start, so plain grid
// auto-placement shares the current row when it fits and wraps when it
// doesn't — the fix for "keep the locations on the same line ... if there is
// room". A hardcoded "1 / -1" forces a brand-new, always-empty row every time.
// alignItems flex-start (2026-09-30): stretched to the row's height, the 7/5
// box grew past its aspect and the badge pinned to its top floated above the
// card, left of the cost ("weirdly to the left").
check("a landscape run is auto-placed by span, top-aligned, not stretched",
  /gridColumn:`span \$\{spanCols\}`,display:"flex",flexWrap:"wrap",alignItems:"flex-start",gap:10/.test(src),
  "the landscape run is no longer an unanchored `span ${spanCols}` flex line " +
  "with alignItems flex-start — it's back to `gridColumn:\"1 / -1\"` (which can " +
  "never share a row), an explicit start crept in, or the cards stretch to the " +
  "row's height again.");
check("the old forced full-width span is gone",
  !/gridColumn:"1 \/ -1",display:"flex",flexWrap:"wrap"/.test(src),
  "found the reverted `gridColumn:\"1 / -1\"` full-row force — that's what " +
  "stops a Location sharing a row with room left in it.");

// The card's own box is 7/5 and IN FLOW, so a row of nothing but Locations
// still has a height. Its badge is right-aligned over the cost hexagon.
check("a Location's box is 7/5, with its badge above the cost",
  src.includes('? html`<${React.Fragment}><div style=${{position:"relative",aspectRatio:"7/5"}}>${art}</div>${qty}</>`') &&
    src.includes("top:6,right:landscape ? 0 : 6,"),
  "the landscape box lost its 7/5 aspect, or its badge is no longer right-" +
  "aligned over the cost (Zaven, 2026-09-30: \"line up above the ink cost\").");

// THE DECK EDITOR (2026-09-30, "locations look too small here, not full card
// size?"): its image grid and stacked pile drew a Location one column wide,
// the 71% the poster was fixed for. Both go through DeckTileGrid, which
// measures its auto-fill column count from the same min/gap it builds the
// template from — one source, so the span can never exceed the real grid.
const tileGrid = src.match(/const DeckTileGrid = \(\{className, items, renderItem, min, gap\}\) => \{\r?\n([\s\S]*?)\r?\n\};/);
check("DeckTileGrid is still in Index.html", !!tileGrid);
if (tileGrid) {
  const body = tileGrid[1];
  check("DeckTileGrid measures columns from the min/gap it builds the grid from",
    body.includes("Math.floor((el.clientWidth + gap) / (min + gap))") &&
      body.includes("gridTemplateColumns:`repeat(auto-fill,minmax(${min}px,1fr))`,gap"),
    "the measured column count and the grid template no longer share `min` and " +
    "`gap` — a run's span can then exceed the real column count");
  check("DeckTileGrid sizes runs with the shared helpers",
    body.includes("groupLandscapeRuns(items)") &&
      body.includes("landscapeRunSpan(r.items.length, cols || 2)") &&
      body.includes("landscapeRunCardWidth(span, gap)"));
}
check("the deck editor's grid and stacked views both use DeckTileGrid",
  /<\$\{DeckTileGrid\} className="deck-section-grid" items=\$\{section\.items\}\s+renderItem=\$\{renderItem\} min=\$\{110\} gap=\$\{8\}\/>/.test(src) &&
    /<\$\{DeckTileGrid\} className="deck-section-stack" items=\$\{section\.items\}\s+renderItem=\$\{renderItem\} min=\$\{160\} gap=\$\{22\}\/>/.test(src),
  "a deck-editor tile view is back to mapping renderItem into a plain grid, " +
  "which draws a Location one column wide");

const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
const cssRule = (sel) => {
  const i = css.indexOf("\n" + sel + "{");
  return i < 0 ? null : css.slice(i + sel.length + 2, css.indexOf("}", i));
};
check("styles.css does not also carry the deck grids' columns",
  cssRule(".deck-section-grid") === "display:grid;" && cssRule(".deck-section-stack") === "display:grid;",
  "`.deck-section-grid` / `.deck-section-stack` set their own columns again — " +
  "DeckTileGrid sets them inline, from the same numbers it measures with");
check("a run of Locations is top-aligned, not stretched to the row",
  /align-items:flex-start/.test(cssRule(".deck-lscape-run") || ""),
  "`.deck-lscape-run` lost align-items:flex-start — each tile then stretches to " +
  "a portrait row's height, leaving an empty band under the card");
check("a Location tile's quantity sits below its cost hexagon",
  /\.deck-grid-tile--lscape \.deck-grid-tile-qty,\s*\.deck-stack-tile--lscape \.deck-stack-qty\{top:calc\(18% \+ 4px\);\}/.test(css),
  "the landscape quantity badge left the column under the cost hexagon — at " +
  "the tile's top-right corner it covers the cost");

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
