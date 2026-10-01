# Retailer-exclusive sealed product (2026-09-20)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`SEALED_EXCLUSIVES` — a box you can only buy at one chain, which therefore has no TCGplayer
listing, no pid, no price and no `sealed_prices_latest` row. Same answer as `SEALED_PUZZLES`: a
static client const shaped like a sealed_prices row, merged into the Sealed collection at the two
sites that spread the puzzles. Ownership persists in `sealed_collection_items` — no FK on the
product id, so a synthetic id is fine. The first entry was the **Best Buddies Bundle** (Costco,
Sep 2026) — portfolio, 6 Wilds Unknown packs, 18/PD1 + 19/PD1, and `LORCANA_PINS` n:45 — and it
**became a real TCGplayer row four days later** (below), so **the list is EMPTY today**. The
const, `isUnpricedSealed` and the `is_exclusive` render branches stay, as infra for the next one.

- **⚠ `set_id` is NULL, which files it under "Other / Promo"** with the portfolios and everything
  else TCGplayer gives no set (Zaven, 2026-09-20). It shipped with a synthetic `__exclusives__`
  id and a **Retailer Exclusives** section of its own first, which was one product in an empty
  room. Don't give it a real set either: a bundle with Wilds Unknown packs, Attack of the Vine!
  promos and Toy Story portfolio art would be claiming membership of whichever one you picked.

- **Band is `930000000 + n`** — clear of the puzzles' 912.0M and BELOW the 950–970M window
  `isCollectiblePid` owns. That is deliberate: pins and counters are excluded from the Sealed
  tab's unit and SKU counts, and these must NOT be, because a bundle is a box you own.
- **⚠ `n` is a stable hand-assigned id.** Never renumber one — it is what somebody's owned mark
  is filed under. Same rule as the pins.
- **⚠ This is the one static catalog whose rows can become REAL TCGplayer products — and the
  first one did, in four days.** TCGplayer listed the Best Buddies Bundle on 2026-09-24 as
  **719823** (in its Wilds Unknown group; $69.90 Low / $72.77 Market on arrival), the daily
  sealed loader took it that evening, and the site showed **two tiles for one box** — the static
  one on a phone photo, the real one with TCGplayer's studio shot and a price — until Zaven noticed
  the better photo on 2026-09-27. When that happens **delete the entry here**: the real row is
  the one with a price. First check `sealed_collection_items` (and `watchlist_items`) for the
  synthetic pid and move any owned mark onto the real pid rather than dropping it — nobody had
  marked n:1, so nothing moved. **Retire the `n`**: reused, an old owned mark would attach itself
  to a different box. `test_amazon_links.mjs` keeps the retired list and fails if one returns.
- **⚠ NOTHING flags that moment.** This file used to say `reconcile_catalog.py --watch` reports
  the listing as `missing_sealed` — it cannot: `load_sealed_products.py` runs inside the daily ETL
  and absorbs a new SKU the day it appears, so by the watch's next run the product is in
  `sealed_products` and nothing is missing. Whenever this list holds an entry, look for its name
  in `sealed_products` from time to time.
- **The real row files under TCGplayer's own group — Wilds Unknown — not "Other / Promo".** The
  null-`set_id` rule below is about US not picking a set for a box that spans three; TCGplayer
  has picked one (its name is "Disney Lorcana: Wilds Unknown Best Buddies Bundle"), and that is
  left standing. Moving it back would take new loader code: `SEALED_SET_OVERRIDES` only FILLS a
  set the group map left empty and cannot clear one.
- **`isUnpricedSealed(p)`** is the one predicate for "static row, no TCGplayer SKU, no price" —
  puzzles, pins/counters and exclusives. Every surface that would otherwise build a TCGplayer buy
  link, fetch price history or multiply a price by a quantity asks it. **A missed call site is
  silent**: a dead affiliate link on a tile, or a modal that fetches history for a pid that has
  none and draws an empty chart. It is NOT the right question everywhere — the Amazon LINK is
  still gated on `is_collectible` alone, because a puzzle and a bundle are both purchasable there
  and only a pin is not.
- **An exclusive's tile and modal take Amazon as the PRIMARY link**, the shape the puzzles
  already use: there is no TCGplayer page to be the first button, and `amazonForSealed` falls
  through to a `Disney Lorcana <name>` search ("Find on Amazon"), which is honest about not
  promising the product page. That same search fallback is why it does not reach the home Amazon
  shelf: `amazonShelfPool` keeps only `exact` listings plus newest-set searches, and an exclusive
  is neither. Curate an ASIN for one and it WOULD join the shelf, which is the right outcome —
  by then there is a real listing to link to.
- Guarded by the `SEALED_EXCLUSIVES` / `isUnpricedSealed` section of
  `node scripts/test_amazon_links.mjs`. **⚠ It runs over a FIXTURE entry spliced into the real
  `.map`**, followed by every live entry: with the list empty, each `.every` would otherwise pass
  on nothing at all.
