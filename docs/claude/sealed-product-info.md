# Sealed product info — where it was sold, what was in it (2026-09-30)

Zaven: *"some were costco exclusive, some sams club, some target only at black friday ... if you click on them."*
`SEALED_PRODUCT_INFO` (Index.html, just above `SealedDetailModal`) is keyed by TCGplayer product id and renders as
**About this product** in the sealed detail modal (`SealedAbout`), plus a "<retailer> exclusive" tag on the tile's
sub-line when `ex === "exclusive"`. 42 entries: every bundle, collection starter set, gift set, collector's edition,
quest, trove, prerelease box and D23 set, not boosters or plain starter decks.

- **⚠ Every entry was read off a named source (`src`), and a field nobody could verify is ABSENT**, so the panel says
  less rather than something wrong. Retailer claims are published to users: don't add one from memory. Most are
  medium confidence (lorcanaplayer.com, ICv2 and retailer listings; costco.com, samsclub.com and ravensburger.us
  block fetches), and a few say so in `more` (a Portfolio Bundle launch price was never verified).
- **Only `exclusive` and `limited` draw a badge.** "wide" is stored but silent: a "widely available" tag on every
  trove is noise. Troves carry date / price / contents only.
- **A new exclusive = one entry here.** Not-yet-released products (Hyperia City box, Beast gift box, Great Hunny
  Rescue) say so in `more`; re-check them after release.
- Re-researching: the entries came from three parallel research passes with a strict "omit what you can't verify"
  brief. Reuse that brief; never accept a note describing HOW the search went ("from a search summary").

## Collection set grid (2026-09-30)

- **Sealed tiles in one section are the same size** (`grid-auto-rows:1fr` + stretch on `.sealed-coll .gc-set-grid`,
  footer pinned with `margin-top:auto`). It replaced `align-items:start`, so a bundle with a wrapped name was taller
  than its neighbour.
- **A set name takes two lines before clipping** (`.set-progress-card .set-heading:not(.has-logo)` clamp 2).
- **A promo set that splits Non-Foil / Foil (the two Lorcana Challenge sets) is ONE row, Non-Foil left, Foil right**
  (`.set-progress-split`), the room of a promos-only tile. The percent drops below a 300px card (`@container`).
  Booster sets keep stacked rows and chase pills. Promos / Extras / split tiles are `.set-progress-card--flat` (the
  block sits at the bottom so bars line up across a row).
- **"Ravensburger Play Hub Promos" (RPH) was in the DB with 7 cards and NO tile**, because a set absent from
  `SET_ORDER` is never drawn in the Collection grid. It is in `SET_ORDER`, `UNIFIED_TILE_SETS`, `PROMO_RARITY_SETS`,
  `NUMBERED_PROMO_SETS` and `DREAMBORN_CN_SUFFIX_SETS`. **A new promo set needs all of those** (plus
  `node discord/tools/extract_site.mjs`, since `SET_ORDER` is copied into the Discord bot).
