# Deck view / edit modes

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Click own deck → defaults to **view** (no card browser, no rename); toolbar has **✎ Edit** toggle. Brand-new decks open straight into edit.

- `DecksView` uses `openDeckInMode(id, "view"|"edit")`. Click → "view"; createDeck → "edit"; duplicate → "view".
- Owner controls (Share/Duplicate/Delete/Export) gate on `isOwnDeck`. Import + rename + Saved + CardBrowser gate on `!readOnly`.
- Three list layouts (View ▾): compact list, image grid, stacked pile.
- **CardBrowser ink pre-fill**: `DeckEditor` passes the deck's current `inkColorsInDeck` (1-2 colors) as the `defaultInks` prop. `CardBrowser`'s initial filter state seeds `filter.inks` from that prop *once on mount*. Re-opening the editor re-mounts CardBrowser → re-applies the deck's inks. Edits to chips during the session win after that. Gated to length 1-2 so a malformed/in-flux deck with 3+ inks doesn't auto-apply a weird filter.

### Deck focus — the second desktop edit layout (2026-09-01)

Edit mode had exactly one shape: CardBrowser on 2/3 of the screen, the deck as a
460px sidebar. Great for *finding* cards, wrong once you know what the deck is and
are tuning counts — the thing you're working on was the small column. **`workLayout`**
(`packsink:deckeditor:layout`, `browse` | `focus`) flips it.

- **The switcher heads the DECK PANEL, not the action row.** As a twelfth `.deck-act`
  chip it read as one more export button and nobody would find it; at the top of the
  deck column it is the first thing in the panel you are trying to make bigger.
  Rendered above `listBlock` rather than inside it, because `.deck-view-toolbar` only
  exists when `sectioned.length > 0` — inside, a brand-new empty deck could never
  switch layouts.

- **Focus mode reuses read-only view's shape** — `deck-view-list` + a 340px stats
  rail — because that shape is already proven at 60 cards. The difference is that
  the rows keep their counters, and cards come from a docked bar instead of a grid.
  `.deck-section-list` is `auto-fill minmax(320px,1fr)`, so at ~900px the deck
  flows into two columns for free.
- **The ± grows from 16x18 to 24x24 in this layout.** Nudging counts is the entire
  job here; at sidebar size it's an afterthought you have to aim at.
- **Desktop only, enforced in JS not CSS.** `narrowEditor = useMaxWidth(1100)`
  forces `browse` below 1100px — the grid is single-column there and ≤700px already
  has the Deck/Cards tabs, and unmounting the CardBrowser would leave that "Cards"
  tab showing nothing. The *stored preference survives* the fallback, so widening
  the window brings focus mode back.

**`DeckQuickAdd`** (just above `DeckEditor`) is the adder. It is a BAR, deliberately
— a second grid would just be the browse layout again.

- Search routes through `parseSearchQuery` + `matchesCardFilter` against
  `groupCards(deckRaw)` — the single-canonical-matcher rule, and the same
  mainline-sets-only universe the CardBrowser gets. Behaviour matches the browser
  it replaces exactly, strict-keyword quirks included.
- **The deck's own inks pre-select its ink chips**, the same `defaultInks` rule the
  CardBrowser follows: 1-2 inks, seeded once on mount, and a chip the user turns off
  stays off. Until 2026-09-11 the bar passed a blank filter, so "belle" in a
  green/blue deck listed every Belle in every ink (Zaven's report). The six shields
  sit in the bar (`.deck-quickadd-inks`), and when the ink filter empties the
  results the message names the inks and offers **search every ink** — a filter you
  can't see from the results is a search that silently lies.
- **Results open UPWARD.** The bar is the last thing on screen; a downward list has
  nowhere to go.
- **The whole ROW adds a copy**, art included — the `+` is the affordance, not the
  only target. `−`/`+` therefore `stopPropagation`, or `−` would remove one and the
  row would immediately put it back. At the copy limit the row goes `.full`: dimmed,
  default cursor, click inert.
- **Enter adds and does NOT clear the query or close the list** — a playset is four
  presses, not four searches. `⇧Enter` removes, `↑↓` pick, `Esc` clears then blurs.
- **⚠ The thumbnail must NOT be `loading="lazy"`.** Chrome defers lazy images in
  plenty of situations (a backgrounded tab is only the documented one) and a
  deferred thumb renders the row as a blank slot where the card should be — which
  is exactly what shipped first. At most 30 rows, all within one scroll: eager is
  correct here. Hovering a row shows the full card through DeckEditor's existing
  `hoverPreview` (z-index 1000, so it clears the dock's 38); that replaced opening
  the detail modal, which could not keep the click once the row became the add
  target.
- **The placeholder must keep starting with "Search"** — App's global `/` shortcut
  focuses the first visible input matching `/^search/i`, and with the CardBrowser
  unmounted this is the only one. That's a free keyboard entry point, not a coincidence.
- **`quickAddMaxFor` mirrors the clip inside `onDeckQtyChangeStable`** (the 4-of cap
  is per Product Name, across variant card_ids) so `+` greys out at the cap instead
  of clicking to no effect.
- **Bottom-anchored chrome has to clear the dock.** `.offline-pill` and
  `.packsink-flash-toast` get a `body:has(.deck-quickadd)` lift, and the sticky stats
  rail is capped at `100vh - 96px`, same lesson the mobile Deck/Cards bar already
  taught. The card-detail overlay is z-index 100 against the dock's 38, so modals
  still cover it.

### Deck editor mobile bottom bar

At ≤700px the editor renders a `.deck-editor-mobile-tabs` toggle bar that's `position: fixed; bottom: 0; left: 0; right: 0; z-index: 40`. **Was previously sticky top:60px** which got clipped by the variable-height (~80-90px) two-row top-nav, leaving the toggle perpetually half-hidden. Bottom-fixed dodges that entirely and puts the toggle in the thumb zone.

- The bar uses `bottom: -1px` (1px overshoot off-screen) to dodge subpixel rendering gaps where the page background was bleeding through a hairline on some Android renderings.
- `padding-bottom: calc(9px + env(safe-area-inset-bottom))` — buttons stay above the iPhone home indicator.
- `body:has(.deck-editor-mobile-tabs){padding-bottom: calc(70px + env(safe-area-inset-bottom))}` reserves vertical space at the page level so the bar doesn't overlay the last deck rows / footer. `:has()` scope means other pages don't get phantom bottom padding.
- **Tab labels**: edit mode = `Deck` / `Cards`. Read-only = `Deck` / `Deck Info` (the latter shows stats/charts panel since there's no card browser).
- **CSS rule**: `.deck-editor-grid.readonly.mobile-tab-cards .deck-editor-panel{display:block}` + `.deck-view-list{display:none}` overrides the base `.mobile-tab-cards .deck-editor-panel{display:none}` so the Deck Info tab actually shows the panel in read-only mode.
- **Toolbar gating**: on the Cards mobile tab, the toolbar action row collapses to the `.deck-toolbar-keep` set (Done / Undo / Export Image / Import / Export Decklist / Delete — widened from the original Done+Delete in `269e28b`). Share / Notes / Mulligan / Print Proxies / Duplicate hide via the `.hide-on-cards-tab > *:not(.deck-toolbar-keep)` CSS rule at ≤700px. **Share and Notes sit in `.deck-toolbar-pop` wrapper divs — a class, never an inline `display` style**, because an inline display outranks the rule's `display:none` (they escaped the collapse for months that way). Keeps the toolbar from competing with the card browser for vertical real estate.

### HIGHLIGHT MISSING (flipped logic 2026-05-26)

The pill toggle on `DeckEditor`'s list view (`packsink:deckview:highlight` localStorage).

**Current behavior** (flipped):
- Cards you're **missing** copies of get **faded** (opacity 0.45, `.missing-fade` class on `.deck-row` / `.deck-grid-tile` / `.deck-stack-tile`).
- Cards you **own** (have all needed copies) render **normally**.
- X/Y badge on tiles: **green** (`.deck-tile-owned-frac.complete`) when fully owned, **red** (`.deck-tile-owned-frac.incomplete`) when missing.

**Old behavior** (pre-flip): faded owned cards, highlighted missing with a red border (`.missing-pop` class). Removed because the user wanted owned cards to visually pop, not the missing ones. The `.missing-pop` CSS rules were deleted; `.owned-dim` was renamed to `.missing-fade` (the class name now matches what it does post-flip — fades MISSING cards, not owned).

### Deck row mobile compaction

At ≤700px:
- Cost shield column: 32px → 26px
- Cost shield icon height: 28px → 24px
- Inline ink shield: kept (provides a second visual confirmation of ink color alongside the row tint)
- Grid gap: 8px → 6px
- Row horizontal padding: 8px → 6px
- Price chip: smaller font + tighter padding
- Counter buttons: 18px → 20px (slightly bigger for tap-target ergonomics)
