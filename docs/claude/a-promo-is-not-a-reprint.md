# A PROMO IS NOT A REPRINT (2026-09-01, Zaven)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

A **reprint is a second BOOSTER printing, and only that.** A promo is a *variant*
of the booster card: you may always play it in place of the original, but it is not
a new release of the card. Two consequences, and they are the whole rule:

- It can never make a card "a reprint", nor make one "the original".
- **It does not put a rotated card back in Core.** An old card getting a promo today
  (Curator's Collection, say) stays out of the format — the promo rotates with the
  card it promotes.

`_setMainlineById` (set_id → is-a-booster-set, filled by `setSetReleaseDates`
beside rank/family) carries the flag onto every entry `printingsFromRows` emits.
Two predicates, and picking the wrong one is the bug:

- **`spansTwoReleases`** — does this card exist in more than one place *at all*.
  Only `reprintVerdict` uses it, purely to decide whether to say anything.
- **`spansTwoMainlineReleases`** — is there an actual reprint. This is what
  `deckReprintNotes` qualifies on and what picks `reprintVerdict`'s branch.

Measured the day it landed: of 2,489 names, **315 span two families but only 177
span two booster sets** — so 138 cards were being called reprints on the card page
and in every deck's footnote. `Ariel - Spectacular Singer` (The First Chapter +
Curator's Collection: Heroines) is the shape of all of them, and reads **"Has
promos"** now, not "Original print · Reprinted in…".

- **Verdict kinds: `reprint` / `original` / `alt` / `promo`.** The first three are
  computed over BOOSTER printings only, so a promo set can never be named as where
  a card was first printed or reprinted. `promo` is said from whichever side you
  are standing on — "Promo printing · Promo of the *X* card" on the promo, "Has
  promos · Also printed as a promo in *X*" on the booster card.
- **Promos still LIST**, on the card page and inside a qualifying deck row. That is
  where you find the $140 Curator's Ariel against the $1 First Chapter one; the
  point is that the *count* and the *verdict* are about booster printings.
- **`checkDeckLegality`'s Core test reads booster printings only** —
  `MAINLINE_SETS.includes(s) && coreLegal.has(s)`. `SET_PARENT` is deliberately NOT
  consulted there any more: a set's own promos are promos of that set's cards,
  which are already in the pool, and consulting it is exactly how a future
  "Set 14 Promos" reprint of an old card would have wrongly re-legalised it.
  **Verified a no-op across all 2,489 names on the day** — it closes the hole
  rather than changing today's answers.

Guarded by `node scripts/test_reprints.mjs` (33 cases).
