# Official Lorcana brand art (2026-09-12)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Ravensburger distributes a **"Complete Bundle"** of brand assets — 890 files, 313 MB: all 13 set
logos, 21 ink badges (singles AND the 15 dual pairs), 9 rarity icons, the promo stamps printed on
promo cards, the card-face glyphs, the Challenge badge, the card back, playmat and social borders,
punch-out tokens, and per-set background textures. **They update it as new sets come out.** Zaven
holds the link; ask him for it.

**`python scripts/bake_brand_assets.py --bundle "<...>/Complete Bundle"`** is the whole pipeline,
bundle → `Logos/lorcana/` (44 files, 728 KB). Guarded by `node scripts/test_brand_art.mjs`.

- **It is an explicit MANIFEST, not a directory sweep** — same rule as `build_dist.mjs`.
  Ravensburger renames files between drops ("Set6_Colour" one set, "AzuriteSea-Color" the next), so
  a sweep would silently ship whatever it found under whatever name it found it under. `--check`
  writes nothing and NAMES anything that moved, which is exactly the report you want the day a new
  bundle lands.
- **`--contact` writes a light/dark sheet. Look at it.** Same lesson as `cut_collectible_bg.py`: a
  logo with an empty alpha channel bakes to a 1px file and a "white" glyph that was actually black
  is invisible on one theme, and neither produces an error. It is what caught the CCQ mark being
  white-on-transparent (see below).
- **Format is a decision, not a convention.** WebP for the big airbrushed art — set logos are
  1.3 MB as PNGs and 350 KB as WebP, and their SVGs are 300 KB–1.8 MB each because Illustrator
  exports every gradient mesh as thousands of paths. PNG for small multi-colour icons. SVG,
  rewritten to `currentColor`, for single-colour glyphs. NOT palette-quantized (that is right for
  `cut_collectible_bg.py`'s photos and bands an airbrushed wordmark visibly).
- **⚠ A single-colour SVG must be rendered as a CSS MASK (`LorcanaGlyph`), never an `<img>`.**
  Inside an `<img>`, `currentColor` does not reach the file — it resolves against the SVG
  document's own initial `color`, which is UA-dependent and flips with the browser's dark
  preference. A mask ignores colour and paints the shape's alpha in `background`, which is what
  makes one file work on all seven themes. (This is NOT the `mask-image` pitfall in the CSS notes —
  that one is about a mask on a CONTAINER, which softens child `<img>`s. This is a leaf span.)
- **⚠ SET LOGOS ARE WORDMARKS**, legible from ~40px of height and an unreadable smudge at 13px. They
  go in headers, modals and section titles; a list row gets a glyph. `SetHeading` renders the logo
  in place of the set NAME and keeps the name in the DOM, visually hidden — a logo is a picture of a
  word, and dropping the text takes the set out of reach of a screen reader and of ctrl-F.
- **⚠ The First Chapter is black line art and always will be** — the bundle has no colour version in
  any variant. It ships as an SVG so `.set-logo--mono` can invert it on the dark themes, and it is
  copied VERBATIM rather than recoloured, for the `currentColor`-in-an-`<img>` reason above.
  Its viewBox is TIGHTENED at bake time using the sibling PNG's alpha bbox: every set logo is
  exported on a square canvas, so a wide wordmark occupies a 927x263 band inside 1000x1000 and
  renders a third the size of the twelve trimmed WebPs beside it. `trim_alpha` handles that for
  rasters; an SVG has no alpha to trim, so the number comes from the PNG of the same artwork
  (verified against the browser's own `getBBox()` to a tenth of a unit).
- **`lorcanaSetArt(name)` returns null for any set with no logo** — every promo set, Extras, and the
  newest set for the few weeks between its release and the next bundle drop. That is the normal
  steady state, so every call site renders without one.
- **Dual-ink PAIRS are the gap the bundle filled.** A dual-ink card used to render two single
  shields side by side (twice the width in the narrowest column on the site) or a flat slate pie
  slice. `inkShieldSrc(inks, ink)` is the one accessor; `inkPairIcon` **sorts the two names before
  building the filename**, because Lorcast publishes `inks` in the card's PRINT order — the live
  catalog holds both `Ruby/Sapphire` (18 rows) and `Sapphire/Ruby` (2 rows), 16 orderings over 15
  files. Getting this wrong 404s about half of all dual-ink cards, which reads as a CDN hiccup.
  The six SINGLE shields stay at `Logos/inks/*.png` — re-baking them would move their box from
  96x96 to 96x110 and reflow every ink shield on the site to no end.
- **A per-CARD ink slot gets the pair badge; a per-DECK ink list does not.** A deck's two inks come
  from different cards and each shield is independently clickable as a filter.
- **`PROMO_STAMPS` is keyed by SET name**, and only for stamps that map to a set in `SET_ORDER`. The
  bundle also carries GenCon, Disney100, League, Cruise, Film, Publishing and Magical Places marks;
  baking them would ship icons nothing can render. A promo set with no stamp (Magical Places Promos,
  Curator's Collection, Promo Set 4, PD1) falls back to the generic Promo rarity icon. **Magical
  Places Promos carries the bundle's own mark** (`promo/magical-places.svg`, from
  `MagicalPlaces_Dark.svg`, baked 2026-09-18). **⚠ `.gitignore`'s promo-kit rule must stay
  anchored (`/promo/`)** — the bare `promo/` it was matched `Logos/lorcana/promo/` too, so a newly
  baked stamp was silently left out of `git add` while the six older ones (tracked earlier) looked fine.
- **The rarity icons already shipped from an earlier copy of this bundle** — 6 of the 8 are
  byte-identical to `Rarity Icons/*-Color.svg`. `uncommon` and `legendary` are the Outlined
  variants, deliberately.
- **Deliberately NOT baked**: the punch-out Tokens (gold-on-transparent with a red die-cut line —
  print assets, not icons), the Dividers (binder inserts), the playmat and social borders, and the
  Background Images (only 8 of 13 sets, several with a Ravensburger logo baked in — incomplete
  coverage makes them unusable as a systematic per-set treatment).
- **The update reminder is a `brand-assets` scheduled review** in `scripts/catalog_watch.json`,
  due 2026-11-07 and every 90 days after. Nothing can watch for a new bundle: there is no feed, no
  version number and no notification, and a missing logo is invisible because the fallback is
  correct behaviour.
