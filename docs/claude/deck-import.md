# Deck import — text parser

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`parseDeckText(text, raw)` — used by Bulk Upload, import deck text, tournament rows. Accepts:

- `4 Name`
- `4x Name`, `4× Name`, `4 - Name`
- **`4 Name - Subtitle (3-16)`** — Dreamborn export format. `(N-CN)` = (1-based MAINLINE_SETS index, collector number). When present, exact lookup via `candidatesBySetCN[N|CN]` wins over name scoring — useful for disambiguating chase/base printings.

Name scoring (when no exact-pid hint):
- `+100` if Set ∈ MAINLINE_SETS
- `-80` if Rarity ∈ {Enchanted, Iconic, Epic} (demote chases vs base)
- `-60` if isCustomVariant
- `-40` if isCustomCard
- `-20` if any variant_label
Highest wins, tiebreak by iteration order.

### The decklist round trip (2026-09-26)

`deckToText` (the Decklist button, both tile copies) and `parseDeckText` (Import + every
tournament upload) have to agree, and every way they disagree is silent. Guarded by
`node scripts/test_deck_text.mjs`, which replays the real functions.

- **⚠ The export is a PLAIN list — no `# Section` headers, no blank lines** (2026-09-29).
  It used to head each type group with `# Characters` and a gap, and Discord, where most lists
  get pasted, renders a line starting `# ` as a heading: a 16-card list became a screenful of
  big type (reported from a Discord share). Cards stay grouped by type and sorted by cost; the
  headers are gone. A plain `N Name` list is also the one format every other Lorcana importer
  reads. **Comments use `//`, never `#`** — Discord leaves `//` alone. The parser still skips
  `#` lines, so a list copied before this still imports (pinned).
- **A Coconut deck's leader is exported as `// Coconut leader: <Name - Version>`** and read back
  (and applied via `onUpdateMeta`). The leader sits OUTSIDE the 60, so it is not in
  `deck.cards`, and the export used to drop the one card that defines the deck. A comment, so a
  tool that doesn't know Coconut skips it.
- **One line per CARD, not per printing** — a base + its Enchanted exported as two lines with
  the same name, which a tool that doesn't sum duplicate lines reads as half the copies. A card
  missing from the catalog is a `// N × <card_id> (not in the catalog)` comment, never `N crd_…`.
- **Import folds accents** (a third key, `foldCardName`, after the normalized and squashed ones),
  so "Te Ka" finds "Te Kā".
- **A `(set-cn)` wins over the name only when it names a printing OF that card** (its job:
  picking the Enchanted), or when the name alone matches nothing. When the two name different
  cards the NAME wins and the line is reported (`mismatched`) — a list numbered by another site's
  scheme, or one typo, otherwise imported a different card silently.
- **Over the copy limit is trimmed AND reported** (`trimmed`, summed across lines) in the
  import confirm, beside the unmatched lines.
- **Not done, and a decision for Zaven:** exporting a non-default printing WITH a `(set-cn)`
  suffix would make the Enchanted survive our own round trip, but some other tools choke on the
  suffix. Today a mixed base + Enchanted exports as one plain line and re-imports as the base.

### One card, however it's spelled — `cardFamilyKey` (2026-09-26)

Lorcast's Product Name is not stable across printings: 12 cards on the live catalog differ by
case ("HeiHei" / "Heihei", "Down In" / "Down in") or by a curly vs straight apostrophe. Keyed on
the raw string, a deck could hold 4 of each spelling and pass, and a rotated printing whose
reprint is spelled differently read as Infinity instead of Core. **`cardFamilyKey(name)`**
(beside `getDeckLimit`: diacritics folded, curly quotes straightened, whitespace collapsed,
lower-cased) is what every "is this the same card" question groups by: the 4-of cap in
`checkDeckLegality`, DecksView's `setsByProductName` (**its keys ARE family keys now** — look it
up through `cardFamilyKey`, never the raw name), the editor's `deckQtyByName` / +/− caps,
`deckReprintNotes`, `cardPrintingsFor` and `deckToText`. It lives inside the span
`test_coconut_legality.mjs` slices, and `test_reprints.mjs` grabs it by name; both pin a split
spelling in each direction.
