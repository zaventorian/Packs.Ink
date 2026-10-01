# Card search finds SEALED PRODUCT too, in its own section (2026-09-21)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

"What is a booster box going for" had no answer in any search box — sealed was
reachable only from the Sealed collection tab, the Sealed movers row and the
Screener in sealed mode, three places you have to already be in. Typing
"illumineer's trove" returned nothing. Both card-search surfaces now carry a
**Sealed products** section: the home quick-search dropdown (under "Variants &
other versions") and the Cards grid. `searchSealedProducts` is the one matcher
behind both. Guarded by `node scripts/test_sealed_search.mjs`.

**A row opens `SealedDetailModal`, which already WAS the sealed card-tile** —
photo, set · type, Low + NM Market, the `priceStanding` chip, the 6-window Δ%
grid and the full price-history chart. Nothing about it was rebuilt; it only
lacked a way in.

- **⚠ PRICED ROWS ONLY, and that single rule is what makes sealed safe next to
  card search.** Pins, lore counters and puzzles are **named after cards** — 27
  of the 70 pins/counters are literal `Character - Version` names ("Mickey Mouse
  - Brave Little Tailor", "Belle - Mechanic Extraordinaire") and most of the
  rest are bare character names, which is why `deriveSealedDisplayType` already
  short-circuits on them. Admitting them drops ~70 card-named rows into card
  searches, **every one of them also `isUnpricedSealed`** — a dead end on the
  surface whose entire job is showing a price. That is the same call
  `HomeQuickSearch` already makes when it skips Coconut leaders, and it is what
  the user meant by "I don't want to make card search worse". Verified live:
  elsa / mickey mouse / ariel / winnie the pooh / moana / belle each return
  their cards and **zero** sealed rows, while `stitch` correctly surfaces the
  Stitch Collector's Gift Set beside 27 cards. Five predicates enforce it
  (`printing !== "Normal"`, `product_type === "Promo Single"`,
  `isUnpricedSealed`, `isHiddenSealedListing`, and both prices null); the test
  pins all five at source, because dropping any one is silent.
- **⚠ Its own section BELOW the cards, computed independently of them.** The
  card lists are untouched, so no query can cost a card its slot however it is
  written — that is the whole reason this needs no opt-in token, and it is a
  source-level property the test asserts (the home `suggestions` memo must stay
  a function of `[q, raw]` alone, and the sealed divider must sort after the
  cards').
- **⚠ The Cards-tab grid is sized for BOXES** (square cell, `object-fit:contain`),
  which is the point of a section rather than interleaved tiles: a booster box
  in a 5:7 card grid either breaks its row or shrinks every card around it —
  the same trap documented above for Location cards. A sealed tile in the card
  grid was considered and rejected for exactly that.
- **⚠ Deliberately NOT `matchesCardFilter`**, and this is a real exception
  rather than a bypass: sealed has no ink, rarity, cost, classification or body
  text, so every dimension that matcher exists to enforce is absent. The Price
  Graphing sealed picker is already on the "intentionally do NOT use it" list
  for the same reason. The haystack is the cleaned name + display type + **set
  name**, tokens AND-ed, so `azurite booster box` and `vine trove` both land
  even where TCGplayer's own name omits one half.
- **⚠ On the Cards tab it is gated on TYPED TEXT plus any `contains` CHIPS, and
  on no other chip.** Every other chip is a card dimension sealed does not have,
  so an "amber commons" filter would otherwise list every booster box on the
  site as if it had matched something. A `contains` chip is different — it IS
  typed text, just committed — and it has to count, because **the home search
  bar hands a query over by committing it as a chip and blanking the input**.
  Reading `filter.search` alone meant a handoff of "trove" landed on zero cards
  AND zero sealed: a total dead end, reached by the exact flow the feature
  exists for. Never offered in the deck editor (`deckMode`) — sealed is not
  deck contents.
- A zero-card search that DID match sealed says so ("No cards match your search
  — but it matches sealed product, below") instead of dead-ending. The section
  renders after the empty state, so "below" is true.
- **`ProductPhoto`'s wrapper is `position:absolute`, so the slot carries its own
  size** — the standing rule from the sealed movers / collection tiles. The
  white studio sweep is cut client-side as it is everywhere else.

### ⚠ The home search bar must PARSE like the Cards box — fixed 2026-09-21

Typing `elsa promo` into the Cards smart-search parses to name `elsa` + rarity
`Promo` and returns 13 cards. Handing the **same words** over from the home
search bar — Enter, or the Search button — committed them whole as
`contains: "elsa promo"`, a literal phrase no card's haystack holds, so it
matched **nothing**. The most natural way to use the home box was the one that
broke, and it broke silently: an empty grid, no error. Reported by Zaven, who
had noticed the two surfaces disagreeing.

- **The handoff effect now runs `smartSplitSuggestion(q)`** — the same splitter
  the Cards box's own Enter key uses — and applies it the same way
  `applySuggestion`'s `"split"` branch does: dimension chips, plus the residual
  name as a `contains` chip. `elsa promo` → `rarity: promo` + `contains: elsa`,
  13 cards, identical to typing it. Verified for `mickey amber` (17) and
  `rapunzel enchanted` (2) too.
- **⚠ A query with NO dimension in it must still commit as ONE phrase chip.**
  That is the older "feels bad" fix and it is still load-bearing: free text is
  token-ANY in CardsView, so `go go` as free text returns 278 cards. The split
  is tried FIRST and the whole-phrase commit is the fallback — get that order
  backwards and every name search blows up.
- A query containing explicit `x:` syntax (the Artist Alley `artist: <name>`
  link) still goes through as parsed search TEXT, untouched.

### ⚠ A `contains` phrase of REPEATED words collapsed to one token (2026-09-21)

`matchesCardFilter`'s `contains` branch falls back, when the contiguous phrase
misses, to "require every token" — and that test is a bare **substring**
(`hay.includes(t)`), not a word match. So a phrase whose words are all the same
asked only *"does the haystack contain `go`"*, which matched **Gopher, Gothel,
Gonna, Good and Gosalyn**: **278 cards for a two-word phrase**. `go go` is the
literal example the phrase-chip commit path was written to fix, so the code
carried a comment claiming a fix that was never there — found while verifying
the handoff above, not reported.

- **The tokens are DEDUPED** (`[...new Set(...)]`), so a phrase whose words are
  all identical has one distinct token, fails the `length > 1` test, and is
  contiguous-only — which is what it always meant. **278 → 3**, all Go Go Tomago.
- **⚠ Any phrase with two genuinely different words is untouched**, and the
  fallback's real purpose survives: it exists to span the `" - "` in a full card
  name, so `mother gothel evil ever` must keep matching. Both directions pinned.
- The bare-substring test is still loose for OTHER short tokens; only the
  degenerate all-same-word case is fixed here. Widening it to word boundaries
  would change every `contains` search on the site and is a separate call.
