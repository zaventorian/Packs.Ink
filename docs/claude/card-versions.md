# Card VERSIONS: what counts as one, and what it's called (2026-08-24)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Two silent bugs shipped here, both on Peter Pan - Pirate's Bane (Enchanted, Into the Inklands).
Guarded by `node scripts/test_card_versions.mjs`.

### `printingBadge` is the ONLY thing that decides a tile says "Foil" (2026-09-13)

Zaven, on seeing an Enchanted and a promo both wearing FOIL in the Graded Market strip:
*"age old problem that keeps coming back."* It kept coming back because **five surfaces each
asked `printing !== "Normal"` on their own**, and each was therefore wrong in the same way: an
Enchanted is cold foil BY DEFINITION, has exactly one printing, and has nothing to be told apart
from — so "ENCHANTED · FOIL" states a difference that does not exist. Nothing errors, and it
goes out in the shareable PNG exports too.

**`printingBadge(printing, cardId)` is the one answer now**, reading `_printBadge`, an index
stamped from the catalog in App's render beside `setSetReleaseDates` (same reason — an effect
lands a frame late and paints the wrong label first; nothing renders before `raw` is non-empty,
see `bootLoading`). Converted: `MoverTile`, `paintMoverTile` (banner + single-tile PNG),
the Graded Market tile, `paintGradedTile` (its PNG) and the graded bulk-add row. (Your Top Movers was a sixth, until it was
removed from the home collection panel 2026-09-23.)

- **⚠ The rule is NOT "is this a chase rarity", and the live catalog holds counterexamples in
  BOTH directions.** Challenge Promo (C1) is rarity *Promo* and its 8 cards genuinely split, into
  Top Prize foil and Prize Wall non-foil — two different markets (Cinderella - Stouthearted PSA
  10: **$1,707 vs $280**). So the question is **whether a second printing exists**, which only
  the catalog can answer — hence an index rather than a rarity list. (This used to cite PD1's Beast
  as a Promo that splits Normal / Cold Foil. It doesn't; see the promo-sets note below.)
- **⚠ The Challenge words are looked up by BUCKET, never by the raw printing.**
  `PRINTING_VARIANT_LABEL` is keyed `"Foil"`/`"Non-Foil"`, and C1 stores its foil as `"Holofoil"`,
  which `variantBadge` deliberately suppresses as a finish word — so passing the raw value returns
  null and silently drops Top Prize / Prize Wall, the one split on the site where the label is
  worth $1,400. The guard test caught exactly this in the first cut of the fix.
- **A graded sale's `printing` is whatever an eBay title said**, so a finish word is folded through
  `gradedFoilBucket` before the lookup. Three sales saying "foil" once grew Peter Pan - Pirate's
  Bane a third version tab; the same words reach the Graded Market strip, and Gramma Tala wearing
  FOIL is that bug in its second home.
- **⚠ The graded tile's badge sits OVER the art, not in the meta row** (`.nav-tab-beta` trick — it
  costs no layout width there). In the row it was `flex:0 0 auto` beside an ellipsing
  `.gmover-grade`, so "TOP PRIZE" (51.8px in a 106px row) crushed "PSA 10" from 36.4px to 6.3px
  and clipped it at 375px. The grade is the whole point of a graded tile; a badge must never eat it.
- **⚠ And because it sits over the art it needs `.gmover-tile{isolation:isolate}`** (2026-09-15,
  Zaven: *"prize wall logo on cards in movers will bleed over anything on screen over it"*).
  `.gmover-foil` is `position:absolute; z-index:1`, and a `position:relative` parent with
  `z-index:auto` **creates no stacking context** — so the badge was painting in the ROOT one and
  outranked every overlay that does not set an explicit z-index. Measured in the live page: a
  full-screen fixed overlay at `z-index:auto` or `0` lost the hit test to "PRIZE WALL"; only at
  `z-index ≥ 1` did it win. Isolating the tile scopes the z-index to the tile, which is all it was
  ever for.
  - **The same bug sat on `.home-shortcuts`** (absolute, `z-index:2`, in `.home-toolbar`) and was
    fixed the same way. Both were found by walking every element with a numeric z-index and
    asking whether ANY ancestor creates a stacking context — worth re-running after adding a
    positioned badge, because nothing about the symptom points at the CSS.
- **Measured over the whole live catalog (5,896 rows) the day it shipped**: 2,662 rows KEEP their
  Foil badge (every genuine mainline split, untouched), **512 stop claiming one** (225 Enchanted,
  90 Epic, 10 Iconic, 162 single-print promos, 25 Extras), and 7 C1 cards go from "Foil" to
  **"Top Prize"** with their siblings gaining "Prize Wall". Nothing legitimate was lost.
- **Still says a finish on a single-printing card, deliberately left alone:** the scanner review
  row's `.scanner-qa-pronly` chip (`prOnly` in ScannerOverlay), which shows "Holo" on an
  Enchanted. That surface answers a different question — *which SKU am I about to save* — so it
  is Zaven's call, not a silent cleanup.

Guarded by `node scripts/test_printing_badge.mjs` (41 cases), whose last section fails when a
render site grows its own copy of the predicate again. That is the part that makes it stop.

- **"Top Prize" / "Prize Wall" are CHALLENGE PROMO words.** `PRINTING_VARIANT_LABEL` maps
  Foil/Non-Foil to them, and applying it globally put a **"Top Prize" version tab on an Into the
  Inklands card**. `gradedVariantLabel(printing, setName)` is the one place that knows the
  vocabulary is C1-only — the card modal's `splitLabel` / `splitBadge` both route through it now.
  Never call `PRINTING_VARIANT_LABEL` or bare `variantBadge` without a set in hand.
- **A finish word is not a version.** `SPLIT_PRINTING_CARD_IDS` cards (Genie *Two Swords*, Peter
  Pan *Text Error*) have exactly two versions: the base and the named one. Everything else that
  can land in `printing` is a FINISH — and on an Enchanted, cold foil by definition, "Foil"
  distinguishes nothing. **Three eBay sales whose titles said "foil" grew that card a third
  version tab.** `isFinishOnlyPrinting(p)` folds them into the base; `isNamedSplit` gates it so
  C1 (where Foil/Non-Foil ARE the two versions, and two different markets) is untouched.
- The same fold applies when resolving the version a card was OPENED to — a click carrying a
  finish resolves to the base, not to whichever tab sorted first.
