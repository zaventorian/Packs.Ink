# [Format Coconut] starter decks + Discover's third tab (2026-08-22)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**`DISCOVER_FORMATS`** is now the single source for Discover's sub-tabs — `core` / `infinity` / `coconut`, keyed on exactly what `checkDeckLegality()` stamps as `format`. Before it existed the tab list was a hardcoded pair, so a published Coconut deck classified as neither and **was invisible in Discover** from migration 110 until this shipped. The empty-state copy and the one-shot auto-fallback both read the list, so a fourth format needs no other edits.

**26 house starter decks — one per leader**, published by `scripts/seed_coconut_starter_decks.py` from the plain-text lists in `scripts/coconut_starter_decks/`. Edit a `.txt`, re-run with `--commit`, done.

Each new Beta wave opens a gap — The Vine - Towering Stalk shipped 2026-09-15 with no list and got one (**Second Growth**) on 2026-09-16; Pete - Bad Guy and the six dual-ink wave-2 leaders got theirs on 2026-09-28 (20-26 in the folder). Nothing breaks meanwhile: the seeder's `LEADERS` mirror carries every leader and only consults a slug a `.txt` actually names, and it PRINTS the leaders it found no file for, so the gap reports itself. Writing one is a design job, not a chore — it has to pass every rule `checkDeckLegality` enforces, and the names are thematic (Sherwood Volley, Everything the Ink Touches), never "<leader> starter".

**⚠ They are the OLDEST public decks on the site, and that is what made them disappear.** Discover fetches the 200 most recently updated public decks (`DISCOVER_LIMIT`), and a `limit` TRUNCATES rather than paginating — so the feed looks complete while everything past row 200 is simply never fetched. A deck seeded once and never edited sinks as the site grows. On 2026-09-16 there were 288 public decks past the cutoff, the cut landed at row 200 on the Tinker Bell deck, and **17 of the 18 starters were invisible: the whole Coconut tab was one deck.** Nothing errored, and re-seeding "fixes" it for a few weeks by bumping `updated_at`, which is why it can come back looking new. `refreshDiscover` now fetches them SEPARATELY by `STARTER_DECK_TAG` and merges them in, so they are exempt from recency by construction.

- **⚠ The starter fetch must NOT feed the `<12` fallback count.** That fallback exists to catch an empty fresh window on a set-release day; starters are always present, so folding them in before the test would mask it and strand the feed on house decks alone.
- The ~88 ordinary public decks past the cap are still unreachable in Discover — a separate call, since raising the limit also raises what `hydrateDecksByIds` pulls (~57 `deck_cards` rows each).

- **Ownerless** (`user_id = null`), like tournament decks — so they stay out of everyone's Your Decks, and (same rule) are stored **plaintext**: the deck-obfuscation codec only covers user-authored decks.
- **Deck ids are a UUIDv5 of the leader slug**, so a re-run REPLACES a deck instead of publishing a second copy. `deck_cards` is deleted before re-insert, otherwise a card cut from the list would linger. Never change the `NS` namespace — that orphans every one of them and republishes them as duplicates.
- **`tags = ['packs-ink-starter', 'coconut:<slug>']`.** `isStarterDeck(d)` keys the "by Packs.Ink" byline (tile + the shared-deck banner) and the amber `.deck-card-starter` leader strip off that first tag; without it they read "by anonymous", which makes a curated launch feed look abandoned. The strip names the LEADER, never the word "starter" — the deck names are thematic (Sherwood Volley, Everything the Ink Touches, Four Pawpsicles), so the leader is the part a reader still needs.
- The seeder re-checks **every rule `checkDeckLegality()` enforces** (60 cards, ≤3 inks incl. the leader's, singleton except the associated 4-of and the leader's own exceptions) before writing. A starter deck that renders with a ⚠ badge is worse than no starter deck.
  - **⚠ A dual-ink leader's `LEADERS` entry is a TUPLE of both inks**, and one ink matching EITHER satisfies the leader-ink rule, same as `checkDeckLegality`. A bare string there would reject every legal list that happens to skip the first ink.
  - **Meta, not theme alone.** The lists lean on cards the tournament decklists actually run (Grandmother Willow, Demona, Isis, Ursula - Deceiver, Strength of a Raging Fire, the Luisa pair), then build the leader's engine around them. Mine them the same way before writing a new one: ownerless non-starter `decks` rows are the tournament uploads.

**Robin Hood's bonus card.** `COCONUT_CARDS` entries may carry `bonus: "<Product Name>"` — a card the leader plays from OUTSIDE the deck ("from your collection"). It is **display-only**: it costs no deck slot and does NOT consume the singleton allowance, so a normal Robin's Bow may still sit among the 60. `coconutBonusMeta(coconut, cardById)` finds its catalog row (scan by Product Name — the bonus is named in card text, not by id); the deck showcase and the poster both tuck it behind the leader.

- **The tilt is `rotate(8deg)` about `top left`, and the card sits LOW (`bottom:7%`), not high.** Anchoring a clockwise tilt anywhere on the right swings the top-right corner ~30px past the stack, out through the showcase's border and (in the poster) into the neighbouring card tile; anchored top-left the swing goes down-left instead. Sitting low is what puts the bonus card's rules text below the leader's bottom edge where some of it is actually readable — the point of showing the card at all. The leader gives up width for it (76% in the showcase, 78% in the poster).
- **Every `<img>` rendering `coconutArtUrl()` passes `crossOrigin="anonymous"`, including the ones that never touch a canvas.** The bucket sends `ACAO:*`, so the CORS request always succeeds — but Chrome caches a no-cors response separately, and a later canvas-bound request for the same URL reuses it and fails with `naturalWidth 0`. That is exactly how the deck poster's leader came out blank whenever the (non-CORS) showcase loaded first.

### A Coconut reveal is news for a fortnight (2026-09-15)

Beta cards land weekly, so each one announces itself and then stops, above the standing
"New Format" tile. `coconutFreshCards(nowMs)` is the pure core, guarded in
`test_coconut_legality.mjs`.

- **⚠ It keys on an explicit `revealed:"YYYY-MM-DD"` on the entry, NOT on `cn`.** `cn` is
  ours (see the Beta 2 note above), so its order is an artifact of how we numbered a wave,
  not of when anything was shown. **The 18 Beta 1 cards carry no `revealed` and so can
  never fire this** — they all arrived together off one PDF and there is no day to date
  them to.
- **⚠ ONLY THE NEWEST REVEAL DAY SHOWS (2026-10-08, Zaven: *"update the coconut news beat to just have merida now"*).** `coconutFreshCards` still bounds news to the window, but then keeps only the cards sharing the newest `revealed` date, so a new reveal REPLACES the previous one instead of stacking (Pete, Black Cauldron and Merida had been riding the rail together). Same-day cards still show together (the six wave-2 duals). The old stacking is one deleted filter line away. Merida is cn 28, art at `card-art/coconut/028.jpg`, deck "Wisp Season".
- **⚠ A reveal date in the FUTURE is ignored rather than trusted.** A typo'd year would
  otherwise announce a card nobody has seen, on every home page, until someone noticed.
- **⚠ The tile is gated on the row being in `raw`**, the same reason the standing tile's
  count is derived from `raw` and not from `COCONUT_CARDS.length`: a client replaying an
  older catalog cache has no row for a card added since, and a tile announcing a card its
  own Cards tab cannot show is worse than no tile.
- **It shows the WHOLE CARD, and it is the ONLY tile in this feed that carries art**
  (2026-09-15, Zaven: *"have the full card image shown there"*; it was a 52px character crop
  from the reveal tile's first cut the same day). A reveal is about what the card looks like,
  so this one earns the exception — every other tile here stays text-only.
- **Two click targets, and BOTH land on the Coconut-filtered Cards page with the card open**
  (corrected 2026-09-15 — Zaven: *"if you click it, it should open card page on coconut filtered
  page (i mispoke last time)"*). The art used to call `openCardsWithSearch`, which opens the card
  against the UNFILTERED catalog: a click from a tile headed "New Coconut card" dropped you on the
  whole browse with one card open and the format you came for nowhere in sight. Pinned in BOTH
  directions in `test_coconut_legality.mjs` — that the art reaches the filtered page, and that it
  does not go back to the unfiltered one, which is the half that fails silently.
  The card render is also a little smaller (max 124px, was 176px); the documented 96px min-width
  floor is untouched, so three reveals in one window still wrap rather than shrink past legible. The `ink +
  " leader"` sub-line is gone — the picture says it.
  - **⚠ The button is nested inside the tile's `<a>`, so the anchor takes `navCapture`.** A
    nested button's `stopPropagation` does NOT cancel the anchor's own default navigation.
    (`navCapture` only fires when the closest interactive ancestor is a DIFFERENT element, so
    a click on the title still reaches `navHandler` — the simplified version of it quoted in
    the SPA-navigation section omits that check.)
  - **⚠ A pid-less card CAN be opened now — this used to be impossible and the note saying so
    was the blocker.** `groupFromSimCard` looks rows up BY `tcgplayer_product_id` and every
    Coconut row has none, so the handoff silently landed on the tab with no modal. Those cards
    have exactly one printing, so `groupCards([row])` is the whole job; the pid path is
    untouched, because it is the one that finds BOTH printings of an ordinary card.
  - **⚠ `openCardsFilteredBySet(setName, openCardId)` sets `card` AFTER its delete loop**,
    which strips `card` along with every other leaf param.
  - **⚠ The mask hazard, and what is NOT known about it now.** `.home-news-feed`'s edge fade
    is a `mask-image`, which forces offscreen compositing and softens child `<img>`s (the
    CSS-pitfalls note). At 52px it was measured properly: probe thumb mid-list in the
    fully-opaque band (in the ramp you measure the *intended* fade and learn nothing), masked
    vs unmasked, Chromium at DPR 1/2/3 — **mean channel diff ≤0.302/255, exactly 0 at DPR 2
    and 3**. **That measurement was NOT repeatable for the full card**: the agent sandbox has
    no DPR control and no way to read compositor pixels. A masked-vs-unmasked A/B at DPR 1.25
    was visually indistinguishable, which is weaker evidence. The mask is also CONDITIONAL —
    it is only on `.news-edge-*`, i.e. only when the list is actually clipped. **Re-measure
    properly on real hardware if the card ever looks soft**; the mask itself cannot be traded
    for a gradient overlay, because `--bg-surface` is translucent in all seven themes.
  - **⚠ The cards sit UNDER the text, never beside it.** Two inside the 14-day window is two
    consecutive weekly reveals, i.e. the COMMON case, and a left-hand column squeezed the
    title into three wrapped lines at rail width. Capped at `COCONUT_REVEAL_MAX_THUMBS` (3).
  - **⚠ `min-width:96px` is what keeps this honest.** Below about that, a grayscale beta
    render stops reading as a card at all — the reason the 52px crops existed — so three
    reveals in one window WRAP rather than shrinking to share a row. Measured live: 176px in
    the desktop rail, 130px on a 390px phone.
  - **⚠ Art is uploaded to the bucket SEPARATELY from the card's code entry, so "revealed but
    no photo yet" is a real state — and a weekly cadence reopens it every week.** A failed
    render hides its whole BUTTON (hiding the `<img>` alone leaves an empty bordered box that
    is still a click target), and
    `.home-news-cards:not(:has(.home-news-card:not([hidden])))` collapses the row so the tile
    falls back to exactly the text-only tile it used to be.
  - **⚠ `.home-news-card` sets `display:block`, which out-specifies the UA's
    `[hidden]{display:none}`** — so `.home-news-card[hidden]{display:none}` is load-bearing
    twice: without it a failed render paints an empty bordered box AND the `:has()` collapse
    above can never fire.
- **⚠ `coconutArtUrl` carries `COCONUT_ART_REV` too** (fixed 2026-09-15). The rev was on
  `coconutThumbUrl` ONLY — the character crop least likely to change — and missing from the
  full card, which is the only thing that shows the rules text a Beta 1.1 re-render rewrites.
  `packsink-img-v1` survives deploys, so all nine full-art call sites were serving
  pre-rebalance wording to anyone who had loaded the card once.
- **`coconutRowId(slug)` is the one accessor for the synthetic `coconut::<slug>` id**, read
  by the catalog transform that mints the row and by this tile's gate. A drifted prefix
  fails silently — the tile just stops appearing — so the test pins that exactly one place
  in the file builds that string.
