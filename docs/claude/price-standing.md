# Price standing — "is this actually a good price?" (2026-09-10)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

The competitive read, in one line: a restock feed can tell you a box is in stock at $130;
it cannot tell you whether $130 is good. We have daily prices back to 2024-02-08, so we
can — and that judgement is the only reason to click a buy link here rather than on
whichever alert account posted it first. `priceStanding(rows)` (next to
`computeSeriesDeltas`) is that judgement; it renders as a chip at the buy moment on the
card-detail stat rows and in the Sealed detail modal.

Four decisions, each the opposite of the obvious implementation:

- **⚠ It reads `market_price`, NEVER `low_price`.** Low is a published aggregate, not a
  sale: 41% of Lows sit >10% below the cheapest NM sale that actually happened, and
  `smooth_low_prices.py` exists because one bad listing pins it for days. A phantom low
  would render **"Cheapest in 12 months" at the exact moment somebody is deciding to
  buy** — the worst place on the site to be wrong. The guard test pins this with a series
  whose market is flat and whose low cratered on one day, and checks both that the default
  stays silent and that `{field:"low_price"}` *would* have fired (so the test proves the
  default is doing work, not that the function is blind).
- **⚠ It is a PERCENTILE, not a minimum.** A min is decided by one observation — the
  noisiest statistic available. A percentile over the window barely moves when a single
  point is bad.
- **⚠ The window's LABEL must be one the data can support.** A 365-day filter over a card
  with 100 days of history keeps all 100 rows and passes every other floor, so the first
  cut announced *"Cheapest in 12 months"* off one quarter of data. That is a false claim,
  and it lands hardest on exactly the cards people price most — a set released three
  months ago has no year to be cheapest in. `PRICE_STANDING_MIN_SPAN_RATIO` (0.8) makes a
  short history fall back to a shorter, true label instead of overreaching.
- **⚠ Ties count as "at or below", and that needs the spread floor.** A card that sat at
  $5 for half the year and is $5 today is not at a special low, so ties keep it out of the
  bottom decile. The cost is that a perfectly flat series computes to pct 1.0 and would
  announce **"near its 12-month high"** — the opposite of true. `PRICE_STANDING_MIN_SPREAD`
  (1.15) is what catches it: a price with no range has no edge to be near. A sub-window's
  spread is always ≤ the full window's, so failing once fails every shorter window too.

**It says nothing in the middle of the range, and that is the point.** A badge that
renders on every card is furniture; one that appears only at an edge is information.
`null` is the common return — bottom decile → "Cheapest in N", bottom quartile → "Near its
N low", top decile → "Near its N high", everything else → nothing.

- **`priceStanding` is called as a PLAIN FUNCTION in `SealedDetailModal`, not a `useMemo`.**
  The static-product (puzzle / collectible) branch early-returns above it, so a hook there
  would sit after a conditional return and break hook order — the same trap the
  `useMaxWidth(1100)` note describes. It is two passes over at most ~600 rows.
- The chip is a bordered tint, never a filled badge: it sits beside a buy CTA and must not
  compete with it. Dark themes get their own colours — the light green fails on velvet.

Guarded by `node scripts/test_price_standing.mjs` (18 cases). Both bugs above were caught
by writing the test first, and both are the silent kind: a confident false claim next to an
affiliate link.
