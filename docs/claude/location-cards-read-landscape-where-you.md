# Location cards read landscape where you're READING one (2026-08-24)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

A Location is printed landscape, but every art source frames it portrait with the card turned
on its side. `isLandscapeCard(row)` (`card_type` contains `Location`) decides; two mechanisms
turn it back:

- **`landscapeArt(img)`** wraps an `<img>` in `.lscape-wrap`. `rotate()` doesn't reflow, so the
  WRAPPER is what reserves space: it's the 7:5 box, and the image inside is laid out portrait at
  **71.4286%** (5/7) of the wrapper's width — after the quarter turn that lands exactly on the
  wrapper's edges. Verified in-browser: a 208px wrapper measures 208x149 and the rotated image
  measures 208x149. Don't "simplify" the percentage; it's the whole trick.
- **`drawCardTileCanvas({landscape})`** does the same on canvas: `artH` flips to `artW*5/7`, then
  translate to the art box's centre, `rotate(PI/2)`, and cover-fit into an `artH x artW`
  (portrait) box. The card-poster canvas can't use CSS, and it must stay identical to the DOM
  path or the copied PNG disagrees with what's on screen.

Applied to: the card-detail modal (canvas tile AND the plain-`<img>` fallback), the deck
editor's image-grid and stacked-pile views, and the deck poster's card cells.

### ⚠ A DECK POSTER's Locations SHARE A ROW WHEN THERE'S ROOM — a rotated card doesn't shrink (2026-09-18)

**A portrait cell is W wide and 1.4W tall, so a card's long edge is 1.4W. Turn that same card
sideways and the long edge is STILL 1.4W, which does not fit in one W-wide column.** Every
version that squeezed it into one column therefore drew the Location at **1/1.4 = 71% the linear
size of every card beside it** — reported twice in one day, both times as *"it small"*. Zaven's
framing: *"I know the spacing will be weird but I want to ensure card is as if you turned the real
card horizontal."*

Giving each Location its own `gridColumn:"span 2"` fixed the size and left a **hole**: 1.4W inside
a 2W+gap span leaves ~45px of dead air on each side, so two neighbouring Locations sat **~100px
apart** — reported the same day as *"a giant gap between the two locations"*. Forcing the whole
**RUN** onto one full-width row (`gridColumn:"1 / -1"`) fixed that — but a forced full span can
only be placed into an entirely EMPTY row, so a run landing after a row with room left in it (3
items in a 7-wide row, say) got a brand-new, mostly-empty row of its own rather than continuing
the one it had space to share. Reported the same day, fourth ask: *"can we keep the locations on
the same line as the other cards assuming there is room?"*

**The fix is `gridColumn:`span ${spanCols}`` with NO explicit start** — ordinary CSS Grid
auto-placement. Given a span but no start, the browser tries the CURRENT row first and only wraps
to a new one when the span doesn't fit there — exactly "share when there's room, otherwise take a
new one" — and it already knows about every cell a Coconut leader's `gridRow:"span 2"` reserved,
so nothing here has to re-derive that.

- **`posterGroups` (a useMemo beside `cards`) groups landscape cards by ADJACENCY**, not by
  "is a Location". Locations sort last so in practice a deck's are one contiguous run — but a
  landscape card that somehow isn't last still renders correctly, it just gets its own span.
  Grouping on the card type instead would put the two in the same row.
- **`spanCols = Math.min(cols, Math.max(2, Math.ceil(n * 1.4)))`**, per run of `n` landscape
  cards. This is PROVABLY enough room: `n` cards at 1.4W plus `(n-1)` internal 10px gaps always
  fit inside `spanCols` columns plus `(spanCols-1)` grid gaps, because `spanCols >= 1.4n` and, for
  every `n >= 1`, `spanCols` strictly exceeds `n` itself (so the gap-count term never falls short
  either). Capped at `cols` so an oversized run (more Locations than fit one row) still gets a
  single cell, and its own internal `flexWrap` (below) spills the excess onto a second line INSIDE
  that cell rather than fighting the grid for a second row.
- **Each card box is `width:` `calc((100% - ${(spanCols-1)*10}px) / ${spanCols} * 1.4)` at
  `aspectRatio:"7/5"` — sized off the run's OWN `spanCols`, never the grid's full `cols`.** A cell
  spanning N tracks of a `repeat(cols, minmax(0,1fr))` grid has width exactly `N*W + (N-1)*10`
  (grid gutters between the spanned tracks are part of a spanning item's own box), so this formula
  algebraically cancels back to `W` regardless of `N` — the identical 1.4W every portrait card's
  neighbour gets, whether the run is sharing a row or sitting on one of its own. Sizing off `cols`
  instead (the pre-2026-09-18 formula) renders the WRONG size the instant a run's span is narrower
  than the full grid — that's the one line that had to change alongside the span itself. Inside
  each box the image rides `.lscape-wrap`'s standing math (**71.4286%** = 5/7), so the quarter turn
  lands on the box's edges: nothing cropped, nothing overflowing.
- **⚠ The box is IN FLOW, never absolutely positioned.** That is what gives the row a height at
  all — an absolutely positioned box gives its row none, which is the collapse the old
  `aspectRatio` on the CELL existed to prevent.
- **⚠ A Location's quantity badge sits ABOVE the card, right-aligned over its cost hexagon**
  (2026-09-30, Zaven: *"line up above the ink cost, it's weirdly to the left"*). The quarter turn
  puts the cost in the top-right corner, so the badge can't sit where a portrait card's does. Each
  card lives in a wrapper with `paddingTop: POSTER_LSCAPE_BADGE_ROOM` (6 + the 25px badge + 4),
  so the badge is level with the portrait badges beside it and a row of nothing but Locations
  still has room for it. **⚠ The run's flex line is `alignItems:"flex-start"` and must stay so:**
  stretched (the default), each card's 7/5 box grew to the row's height and the badge pinned to
  its top floated above the card and left of the cost — the reported bug.
- **The deck editor's image grid and stacked pile use the same runs** (`DeckTileGrid`, 2026-09-30:
  *"locations look too small here, not full card size?"*). Their grids are auto-fill, so the
  component MEASURES its column count, from the same `min` / `gap` it builds the template from
  (styles.css no longer carries those two numbers). Never read the count back off the grid: a span
  too wide for it makes CSS Grid add implicit columns, which the read would then report. There the
  badge drops just BELOW the cost hexagon (a tile has no room above it), and the owned count and
  version chevron move to the top-left, which is art. `groupLandscapeRuns`, `landscapeRunSpan` and
  `landscapeRunCardWidth` (beside `landscapeArt`) are the one copy of the rule.
- Measured in Chromium against the shipped math: a 1-item run (`spanCols=2`) shares the current
  row and lands **10.0px** from the previous card — zero dead air; a 2-item run (`spanCols=3`)
  shares the row AND its own two Locations sit **10.0px** apart, the exact hole the full-width fix
  closed; a run that genuinely can't fit (only 1 free column against a `spanCols` of 2) correctly
  wraps to a new row; and the pre-rotation image width comes back bit-identical to a portrait
  card's own width at both `spanCols=2` and `spanCols=3` — the algebra holds in practice, not just
  on paper.
- **⚠ A cover-fit CROP to a portrait footprint is the other thing that was tried and rejected**
  (2026-09-18, between the two "it small" reports): cell at `aspectRatio:"5/7"` + `overflow:"hidden"`
  with the image overscaled to `width:"140%"`. It made the cell the right size and cut the card's
  ends off, which fails *"card not cut off"*. Don't reintroduce it; the guard test asserts the
  140% sizing is absent.

**⚠ The poster grid must stay `repeat(N, minmax(0,1fr))`, never a bare `1fr`.** A bare `1fr` is
`minmax(auto,1fr)`, so no track can be narrower than its widest cell's min-content — and the
landscape cell used to declare `aspect-ratio:7/5` on ITSELF, which at a row height set by the
portrait cards around it (188px at 7 columns on the 1000px poster) demanded **263px of width**.
That demand froze the Location's whole COLUMN at ~2x and starved its neighbours; in the
reproduction three columns went to literally **0px**, and every card sharing a hijacked column
rendered oversized *including the rows above the Location* — two giant cards stacked in one column
with the rest of the poster shrunken and spilling off the bottom edge. Reported from the wild
2026-09-08. The cell carries no aspect-ratio today, but `minmax(0,` is the general defence against
any cell whose min-content outgrows its column; don't drop it because today's shape doesn't
trigger it. Locations sort LAST, so the poisoning cell is usually below the fold of a cropped
Discord preview — there is nothing at the blowout to look at — and whether it bites depends on
which column the Locations land in, which is why it read as "not sure if it's just me".

Guarded by `node scripts/test_deck_poster_grid.mjs`.

**Browse GRID tiles stay portrait deliberately.** A 7:5 tile in a 5:7 grid either breaks the row
or shrinks every other card to accommodate the odd one out, and on a browse wall you're picking
a card out, not reading it. Click through and it's landscape.
