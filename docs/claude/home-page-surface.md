# Home page surface

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

- **No "Lorcana Market" h1 or "Click a card for details" subtitle** — both removed 2026-05-26. The search bar sits directly under the top nav. The logo IS the home click target (the title was redundant).
- **Tournament Results panel: `.ht-place` is `white-space: nowrap`** and `.home-tourney-deck` grid is `auto minmax(0,1fr) auto` (was `28px 1fr auto`). The 28px column wasn't wide enough for `"Top 4"` / `"Top 8"` — the place text wrapped to two lines, doubling row height on the narrow signed-in mobile home grid. Auto-width + nowrap keeps each row on a single line; player column's `minmax(0,1fr)` still shrinks with ellipsis when needed.

### Recent set EV — one card per set (2026-09-30)

Zaven, off his phone: *"Reimagine this section, its ugly."* It was a five-column table
that stacked into orphaned numbers under misaligned headers, with four amber Amazon pills
down the right edge and two native checkboxes (`<$1→$0`). `HomeEvStrip` now draws one
card per set: name and verdict (`vs box −47%`) on top, then EV and the two buy buttons,
with a meter along the card's bottom edge (EV against the box; green past a tick when a
set is +EV). The title takes the Toolbox's Cinzel gold, and the toggles are chips
(**No bulk** / **No chase**, same semantics as before) set in Cinzel capitals to match
it. Each set's official wordmark sits left of its name (Zaven, same day).

- **⚠ The box price lives INSIDE TCGplayer's own button** (`$190.00 TCGplayer ↗`), with
  the number-less Amazon pill beside it — see the Amazon section for why that satisfies
  the "Amazon must never read as a caption on a price" rule.
- **⚠ Every layout switch is a CONTAINER query on the panel (`hev`), never a media
  query**, for the reason the Toolbox grid uses auto-fit: which rail the panel lands in is
  decided by the home layout. Measured by forcing the panel from 220px to 900px, nothing
  overflows or ellipses: under ~312px of content (the 240px rail, phones under ~345px) a
  card goes to three lines — name, EV + verdict, buttons — and from 620px it goes two
  across. ⚠ Both numbers were measured, not picked: at 320px the one-line foot's Amazon
  pill overflowed by 2px, and two across below 620 overflows every card.
- A container query cannot style the container itself — only descendants — so the
  panel's own padding does not change with width.
- It is ~50% taller than the table on a phone (320px against ~202px for four sets). That
  was the price of buttons that look like buttons; the meter costs no height.
- **⚠ The set logo sits in a FIXED slot** (`.home-ev-logo-slot`, 56x28, 44x24 in the
  narrow layout), not sized by height: the wordmarks run from 1.25:1 (Whispers in the
  Well) to 2.67:1 (Winterspell), so a shared height starts every name at a different x.
  A set with no logo yet (the weeks after a release, before the next brand-bundle drop)
  keeps an EMPTY slot while any other row has one, so the names still line up.

### Configurable layout (2026-08-04)

Every home section except the movers stack is a **user-arrangeable panel**: show/hide, move between columns, reorder within a column. Edited from the settings popover ("Home page layout"), persisted to `localStorage["packsink:homeLayout"]` as an ordered `[{key, col, on}]`.

- **`HOME_PANELS`** declares the panels + their default column; **`HOME_COLUMNS`** the four targets: `announce` (full-width strip under the search box) · `left` · `main` · `right` (labels: Top strip / Left rail / Below movers / Right rail). **`tools` ("Analytics toolbox", added 2026-08-20, default = top of `right`)** is `HomeToolboxPanel` — `<a href>` chips into the Analytics tools via App's `openAnalyticsTool(subKey)`, with hand-coded `_navSvg`-style line icons (`HOME_TOOL_ICONS`, accent-colored — NO emoji, per user) and a collapsible header (`packsink:home:toolboxCollapsed`, same chevron pattern as the tournaments panel). Because `normalizeHomeLayout` APPENDS new keys at the bottom of existing layouts, it shipped with a one-shot hoist stamp (`packsink:homeLayoutToolbox`, same pattern as the news-rail fix) that moves it to the top of the right rail once; a later user re-position sticks.
- **Movers banners are reorderable in edit mode (2026-08-21)**: each rendered banner gets a `.home-edit-card--banner` bar with ▲▼ only. Order persists at `packsink:homeBannerOrder` (`HOME_BANNER_KEYS` = valuable/chase/rareLeg/promo/graded, normalized by `normalizeBannerOrder`); **null = the built-in hot-aware order** (newest-set banner floats top during release week, bottom after) — the first ▲▼ materializes the order the user is looking at and retires the heuristic. The rareLeg entry moves the whole `rl-news-row` (news feed rides along); banners with no node (signed-out graded, no newest set) render no bar. The movers stack now returns a **Fragment, not a wrapper div**, so banners are direct children of `.home-grid-main` and the edit-mode freeze dims each one while its bar stays live. Banner order shares the edit lifecycle: snapshot on entry, Cancel restores, Reset nulls it.
- **The “Edit layout” launcher lives at the FOOT of the home page** (`.home-edit-foot`), not
  above the movers. As a permanent row up top it cost every visit ~60px of the first screen for a
  control most people press once; the gap between the search box and the movers toolbar is 14px
  now. The **editing** bar is a separate render at the top, and only while editing — it has to be
  sticky so Done and Cancel stay reachable while you rearrange.
- **On-page layout edit mode (2026-08-21)** replaced the cramped settings-popover editor (which is now just an "✎ Edit home layout" launcher → `startHomeEdit()`). The "✎ Edit layout" chip under the home search enters editing: every panel gets a dashed `.home-edit-card` control bar — ▲▼ reorder, a column `<select>`, Hide/Show — rendered as a SIBLING above the panel, **never a wrapper** (the `.home-left-col > .home-feed` child-selector rule still stands). Hidden panels keep a dimmed bar at the bottom of their column so they're restorable in place. Live panels get `pointer-events:none` + dimming via `.home-editing` so a stray tap can't navigate. The sticky control row (Reset / Cancel / ✓ Done) pins at `top:96px` on phones (below the two-row nav, same trick as `.cards-bulk-bar`). Edits apply live; entering snapshots the layout so **Cancel restores it** (`homeLayoutDraftBase` ref in App); navigating away mid-edit keeps changes and exits. **`normalizeHomeLayout(val)`** is the only way state enters — it drops unknown keys, appends missing ones at their default column, resets bad column names, and never throws. Both App (on load) and HomeView (on render) run it, so a hand-edited or half-migrated value can't render a broken page.
- **Migration**: the old visibility-only `packsink:homePanels` map is read once on first load and folded into the new shape. Both keys are `localStorage`-only — deliberately NOT in the `user_metadata` prefs-sync effect, since a phone and a desktop wanting different arrangements is normal, not drift to reconcile.
- **⚠️ Changing a panel's default `col` does NOT reach existing users.** The layout is persisted on EVERY page load, and `normalizeHomeLayout` keeps any stored column that is still a valid column name — so a browser that visited once holds that column forever. This bit the news feed: it defaulted to `announce` from `927ca7b` until `f1e5819` flipped it to `left`, and every browser from that window kept rendering it as a lone 420px `.home-announce` card under the search box with the whole grid shoved below (reported 2026-08-14 from a long-lived signed-in profile; a fresh profile on the same machine looked correct). Fixed by a **one-shot stamped migration** in App's `homeLayout` init (`packsink:homeLayoutNewsRail`) — stamped, not coerced, because `announce` is still an offered column and a permanent coercion would make picking "Top" for news snap back on reload. Do the same for any future default-column change: one-shot keyed on a fresh stamp, never a standing rewrite in `normalizeHomeLayout`. Done again 2026-09-15 for the rail swap (`packsink:homeLayoutRailSwap`) — and that one adds the other half of the lesson: **re-seat by POSITION as well as column**, or a panel that was APPENDED already carrying the new column name never moves within it. Guarded by `node scripts/test_home_layout.mjs`, which extracts the real code out of Index.html so it can't drift.
- **News feed** (`news` panel, reworked 2026-08-12) bundles the pre-release News tile, any live `EVENT_TILES` convention tile, **any Coconut card revealed in the last `COCONUT_REVEAL_NEWS_DAYS` (14)**, and the standing Format Coconut tile — in that order (dated things first, the standing Coconut notice last, per user request). ONE tile list renders into TWO CSS-gated mounts of the same `.home-news-feed` aside: the `--rail` copy is a normal column panel (default = top of the LEFT rail; the column picker governs only this copy), and the `--rl` copy rides the Rare–Legendary movers banner as the right-hand cell of the `.rl-news-row` grid (`minmax(0,1fr) minmax(150px,32%)`) — the same geometry the old mobile tournament column used. `@media (max-width:1100px)` flips which copy displays: ≤1100px the rail columns sink below the movers, so the rl copy is the visible one (per user: desktop = left column, mobile = beside the movers; the old full-width announce tiles ate half a phone screen). Natural heights only (`align-items:start`, list scrolls inside `max-height` — `min(70vh,560px)` rail / `min(66vh,520px)` rl) — do NOT height-lock the pair; that's what killed both `ChaseRowWithTourney` predecessors. **The cap is viewport-relative on purpose** (was a flat 340px on the rl mount): a pixel cap clipped the list hundreds of px short of the room the row actually had on a tall phone. The aside is the `NewsFeed` component (just above `HomeView`) rather than inline JSX because the clip needs an affordance — phones hide their scrollbars, so a half-cut tile reads as a broken box. `edge` state (`""|top|bot|both`, from a scroll + `ResizeObserver` sync) drives a `news-edge-*` class that masks the clipped end and shows a ⌄ chip. The fade is `mask-image`, NOT a gradient overlay: four themes hold a gradient in `--bg`, which can't be a colour stop — and it was safe because these tiles were text-only (see the CSS-pitfalls note on masks softening child `<img>`s). **The Coconut reveal tile is now the one exception, on a measurement**: at chip size the softening is ≤0.302/255 and exactly 0 at DPR 2–3. Re-measure before putting anything BIGGER than a ~52px thumb in this feed; see "A Coconut reveal is news for a fortnight". In the movers loading/error/no-direction branches the rl copy renders full-width above the status message so announcements never vanish behind a data hiccup on phones. The `announce` strip (full-width, under the search box) still exists as a column target; nothing defaults there anymore.
- **Empty side columns are omitted from the tree**, and `.home-grid` gets `hg-no-left` / `hg-no-right` which narrow `grid-template-columns` to match — otherwise hiding everything on the left left a 240px hole. Columns are **auto-placed in DOM order**; don't reintroduce `grid-column:1` on `.home-left-col` or the omission breaks.
- `moveHomePanel` swaps with the nearest neighbour that is **both in the same column AND visible**. Plain index±1 would swap past a panel in another column (or a hidden one) and read as a dead button.
- Panels are keyed on the component (`key="following"` etc.), not wrapped in a div — several CSS rules are `.home-left-col > .home-feed` child selectors that a wrapper would break.

### Your Graded Movers is a movers ROW, not a panel

It renders in the banner stack (`bannerNodes.gowned`), with `MoversBanner`'s chrome — same title
style, same inline window control, same drag-to-pan marquee as Chase / Rare–Legendary / Promo. It
used to be a boxed sidebar `home-feed` with a collapse chevron, which made the one row about YOUR
cards the only one that didn't look like a movers row.

- **`MoversBanner` takes an optional `renderTile`** so a banner can keep the row treatment while
  drawing a tile `MoverTile` can't: a graded slab has one price and one delta set, where MoverTile
  is built around LOW vs MKT. The camera export is hidden when `renderTile` is set —
  `copyMoverBannerImage` paints MoverTile-shaped cards.
- **⚠️ The marquee renders `cards` TWICE** — that duplication is what makes the loop seamless.
  Both passes have to honour `renderTile`. Missing the second one put a full raw `MoverTile`
  beside every graded tile, and since a flex track stretches its children to the tallest, that
  left ~70px of dead space under every slab. Symptom to recognise: the track holds 2x the item
  count and half of them are the wrong component.
- **It keeps a `HOME_PANELS` entry purely for its on/off flag** (the Graded collection's "show on
  home" toggle flips it) and is marked `fixed` so the layout editor offers Show/Hide only — its
  position comes from the banner ▲▼ instead. `HOME_FIXED_KEYS` panels render their editor bar in
  the home header, on every width.

### Pairing a panel with a movers banner

News / Following / Tournament results (`HOME_PAIRABLE_KEYS`) can sit **beside any movers banner,
on either side**, chosen in the layout editor. This generalises what the News feed already did
with the Rare–Legendary banner, which was hardcoded in one component.

- Stored as `pair` (a `HOME_BANNER_KEYS` value or null) + `pairSide` on the panel's layout entry.
  **`normalizeHomePair` validates both and never throws** — an unknown banner, a bogus side, or a
  pairing on a non-pairable panel all collapse to "not paired", same contract as the rest of
  `normalizeHomeLayout`: it repairs a stored layout, it never rejects one.
- **A paired panel leaves its column** — both the render list and the editor-bar list — or it
  renders twice. Its editor bar travels with it, above the pair row.
- **Only the three narrow list boxes are offered.** Set EV or the collection chart in a 32% column
  is unreadable.
- **`setHomePanelPair` releases whoever held the banner**: two boxes in one 32% column leaves
  neither readable, so claiming a banner un-pairs the previous occupant.
- A panel paired to a banner that isn't rendering (signed out of graded, no hot set) **falls
  through to the bottom of the stack** rather than vanishing with no way to get it back.
- **The News feed's legacy Rare–Legendary ride stays the default** (it is what every existing
  browser renders on a phone) but an explicit pairing overrides it — `newsExplicitlyPaired`.
  Without that, picking "beside Chase Movers" puts the feed on the page twice.
- **`.home-pair-side > .home-feed` needs `display:block !important`.** The News rail copy is
  `display:none !important` below 1100px; a panel the user deliberately paired has to beat that,
  or it renders into the DOM invisibly.
- **The pair row does NOT stack on phones.** Beside-the-banner IS the mobile case — it exists
  because the rails sink below the fold there — and this is the geometry the News row has run at
  on phones for months. Measured at 412px: banner 226px, panel 150px, same top.

### The at-the-table shortcuts are `fixed` panels

`HOME_PANELS` entries may carry **`fixed: true`** — they are not columns of the grid, they are
shortcuts pinned into the home header. Two of them: `dice` and `lore` (a die and a lore pip),
**phones only** — rolling for turn order and keeping score both happen at a table with the phone
already in your hand, and on a desktop the Analytics tab is right there.

- **Both are ON by default as of 2026-08-27** (Zaven). They cost the page no height (see the
  absolute positioning below), so opt-in bought nothing and hid the two controls people most want
  mid-game. Existing browsers had them stored off — `normalizeHomeLayout` deliberately honours
  `off` when it APPENDS a key, so flipping the default alone reaches nobody who has ever loaded
  the site. A **one-shot stamp** (`packsink:homeLayoutTableShortcuts`) switches them on once.
  Stamped, not coerced, per the standing rule: a later deliberate Hide has to stick.
- **The rail is 90px wide now, and the toolbar's first line has to be told.** The rail is
  absolutely positioned, so the time-window chips don't know it is there — with two bubbles it sat
  on top of the 1Y chip at 320px, making a filter unclickable. `.home-toolbar:has(.home-shortcuts)
  .seg-grp{max-width:calc(100% - 94px);flex-wrap:wrap}` reserves the width on the first-line item
  only, so the chips wrap inside their own pill at ≤360px and stay on one row from 375px up. The
  94 is measured: the pill's natural width is 251.3px and reserving 96 clipped it by 0.3px and
  wrapped a 375px phone that had the room. `:has()` scopes it so hiding both shortcuts gives the
  width straight back.

- `HOME_FIXED_KEYS` keeps them out of `columnNodes` on both the render and the edit path, and out
  of `HOME_POPOUT_KEYS` (there is no panel to pop out).
- **It is `position:absolute` in the movers toolbar's empty top-right corner**, level with the
  time-window chips. A row of its own pushed the whole movers stack down for a button most people
  never switch on; the point of a shortcut is that it costs nothing. Measured: toolbar height and
  document height are byte-identical with it on and off. `margin-left:auto` would NOT do — the
  toolbar wraps, so the die would land at the end of whatever line it wrapped onto (next to
  Pause) instead of level with 1Y.
- The layout editor gives a fixed entry **only Show/Hide** — no arrows, no column select. Its
  control bar renders in the header row and **must render on desktop too**, or it would be
  impossible to switch on from a laptop.

### Artist Alley poster: columns follow the CARD COUNT

`artCols` / `artMax` are derived from `cardsForArtist.length` and used by the screen grid, the
`@media print` pin and the narrow-screen rule, so the three can't drift. A fixed 6-across grid
made a 4-card artist's poster four postage stamps in a sea of green — the cards ARE the poster,
so with fewer of them each one gets bigger rather than the page getting emptier. `artMax` caps
the growth: two 600px cards read as a mistake, not as emphasis.

### Movers-banner chip filters (`MoverChipGroup`)

Three banners carry a multi-select chip group in their `controls` slot. All use the shared `MoverChipGroup` + `toggleChipKey` + `readChipPref` trio — **don't hand-roll another one.**

- **Chase Movers** — `CHASE_RAR_ORDER` (Epic / Enchanted / Iconic), persisted at `packsink:home:chaseRars`.
- **Sealed Movers** — `SEALED_MOVER_KIND_ORDER` (`boxes` / `troves` / `specials`), persisted at `packsink:home:sealedKinds`. See "Sealed Movers" below.
- **Rare–Legendary Movers** — `RL_PRINTING_ORDER` (`normal` / `foil`, labelled Normal / Cold Foil), persisted at `packsink:home:rlPrintings`. Was a one-of-N `Both | Normal | Cold Foil` seg-grp keyed `packsink:home:rlPrinting` until 2026-08-02; the old key is still read once as a migration (`"all"` falls through to the default). `MOVER_FOIL_PRINTINGS` buckets Holofoil under foil, so there's no third state.

Invariants:

- **The last active chip can't be turned off.** An empty selection renders an empty banner whose only way back is the chip you just used to empty it. `toggleChipKey` returns `selected` unchanged in that case, and the chip's tooltip explains why.
- **Filter AFTER sorting, before `.slice(0,20)`** — so the top 20 comes from the selected tiers, not from whatever survived a slice of the full pool.
- **The banner subtitle and the title-click Screener jump both read the selection.** Chase passes `filterRarities`; rare–leg passes `showFoil` / `showNonFoil`. Both are in the buckets `useMemo` deps.
- **These keys are preferences, not caches.** They live under `packsink:home:` but do NOT match any `AUX_EVICTABLE_PREFIXES` entry (`packsink:home:tourneys:` is the tournament *cache* — note the trailing colon, and that `packsink:home:tourneyCollapsed` deliberately doesn't match it). Don't add a bare `packsink:home:` prefix to that list or every home preference resets on the next `AUX_CACHE_VERSION` bump.
- Persistence is **per browser (localStorage), not per account** — these aren't in the `user_metadata` prefs-sync effect, so picks don't follow a signed-in user across devices.

### Sealed Movers (2026-09-11)

A movers row for sealed product, from Zaven's feedback: *"Toggles for product types. Maybe boxes,
Troves, specials. Ignore packs, puzzles, etc."* `sealedMoverCandidates` → `sealedMoverRows` →
`SealedMoverTile`, all just below `MoverTile`. Guarded by `node scripts/test_sealed_movers.mjs`.

- **Three chips, not the Screener's type list.** `SEALED_MOVER_KIND_OF_TYPE` maps
  `deriveSealedDisplayType` onto Boxes (Booster Boxes), Troves (Illumineer's Troves) and Specials
  (Gift Sets, Collector's Edition, Bundles, Quests). Packs, starter decks, prerelease packs,
  cases/displays, promo singles, `[Set of N]`, stale rows, puzzles, pins and counters never reach
  the banner, and a display type the map doesn't name stays out until someone decides where it
  belongs.
- **Same qualifying rules as the card banners** (`qualifies` / `cmpAbs` in HomeView): Δ% on Low,
  prior Low in the window ≥ $5, a flat 0% is not a move, the direction toggles filter, and the top
  20 is taken AFTER the chips narrow. The prior Low is derived from the Δ%
  (`low_today / (1 + pct/100)`), because `computeSealedDeltas` doesn't carry the prior price.
- **History is fetched per HORIZON, not per window.** One `fetchCollectionPriceHistory` over every
  candidate, reaching `SEALED_MOVER_WINDOW_DAYS[window] + 14` days back: 1D costs two weeks of rows
  and only 1Y pays for a year (measured ~2.8s cold in the preview). A deeper fetch serves every
  shallower window, and the module-level `_sealedMoverHist` survives HomeView unmounting on every
  tab switch (1h ceiling). A chip toggle re-filters, never refetches.
- **It asks for `market_price`** (`{market:true}`). The default select leaves it out because the
  collection rollup values on Low — and without it every MKT delta and `market_today` is null. The
  Screener's Sealed mode had exactly that bug (a dash in every NM Market cell) and passes it now too.
- **`SealedMoverTile` is MoverTile's markup with three changes**: the photo is `object-fit:contain`
  (`.mover-tile--sealed`; a box cover-cropped into 5:7 loses its name), type + set sit where rarity
  goes, and the links are the product's own (`tcgUrl(pid)` + `amazonForSealed`). It renders through
  `MoversBanner`'s `renderTile`, so the row has no camera export — that paints MoverTile-shaped cards.
- **`MoversBanner` takes `emptyText`**, so the row says "Loading sealed prices…" while its history
  is on the way instead of claiming nothing moved.
- A tile opens `SealedDetailModal` on the home page (HomeView now receives `updateSealedQty` /
  `updateSealedMeta`); the title opens the Screener's Sealed mode with the chips carried onto
  `filterSealedTypes`.
- **Banner key `sealed`, seated after `promo`.** A stored order (anyone who has pressed ▲▼) would
  get it appended at the bottom, so App's `homeBannerOrder` init inserts it after Promo once, behind
  the `packsink:homeBannerOrderSealed` stamp — stamped, not coerced, so a later ▲▼ sticks.
- **Every card banner's Screener jump now says `showSealed:false`.** `applyView` only touches the
  Sealed flag when a payload names it, so a Screener last left in Sealed mode opened Chase /
  Rare–Legendary / Promo / Most-Valuable filters on top of the sealed table.

### Mobile: the movers stack is ONE row plus a chip strip (2026-09-20)

Above 1100px the three home columns sit SIDE BY SIDE, so picking a column is a spatial
choice. Below it they concatenate, and "which rail" quietly becomes "how far down the
scroll" — which is why the desktop layout reads well and the phone did not. Measured
signed out at 375x812 before this shipped: the page was **4622px (5.7 screens)**, the
movers stack **2354px of it (51%)**, the calendar began at screen **3.3** and the rails
at **4.1**. `MoversPicker` (just above `MoversBanner`) replaces the stack with one banner
and a chip per row: **3274px, 4.0 screens, calendar at 1.6**.

- **NOT while editing.** The ▲▼ reorder bars are interleaved INTO the stack, so a
  collapsed stack would offer arrows for one row and hide the rest. Edit mode renders
  every banner at every width.
- **⚠ The Rare–Legendary key carries the news feed** (`bannerNodes.rareLeg` wraps both in
  `.rl-news-row`) and on a phone that rl copy is the ONLY one rendered — the rail copy is
  `display:none` ≤1100px. So the collapsed branch shows the BARE banner and lifts the news
  feed out; otherwise tapping any other chip deletes the news feed from the page with no
  way back. Same for a panel paired to a banner: lifted, whichever chip is live, or half
  the page appears and disappears as you tap along the strip.
- **`MOVERS_PICK_ALL` ("all") is a pick like any other** and shares the one localStorage
  key with the banner keys, so it must never collide with one. It renders the SAME stack
  the desktop path builds — news back inside its pair row — rather than a second
  implementation that could drift.
- **⚠ `MOVERS_PICK_ORDER` is the STRIP's order, deliberately not the STACK's.** The stack
  follows the ▲▼ and the hot-set heuristic, where the newest set sits last outside release
  week; as a menu that buries the row people most want (Zaven, 2026-09-20). An unlisted key
  falls to the end, so a new banner needs no edit here.
- **`HOME_BANNER_RARITIES`** draws the rarity marks instead of a word on the three
  rarity-group rows, through the same `RarityTag` accessor the in-banner Epic/Enchanted/
  Iconic buttons use (`MoverChipGroup`'s `iconOf`). ⚠ An icon chip needs a LIGHTER off
  state than a word chip: `filter` inherits, so a second grayscale on the `<img>` stacked
  on the chip's own and took the Rare/Super Rare/Legendary gems to invisible.
- **⚠ The newest set's chip is its LOGO, and `SetLogo` must be passed `eager`.** A lazy
  image sized `height:Npx; width:auto` lays out 0px wide before it loads, and in a
  horizontal scroller that degenerate box never triggers the fetch — the chip rendered as
  an empty pill with the file serving 200. `lorcanaSetArt()` also returns `{src, mono}`,
  NOT a url; passing it to an `<img src>` yields "[object Object]" and the silent fallback
  to the word hides it. A set with no logo yet (the normal state for a new set's first
  weeks) correctly falls back to the word.
- **`newestSetIsNew` is a SECOND window, not a widening of `newestSetIsHot`.** That one
  ends the Friday after LGS and floats the banner to the top of the STACK; this one runs a
  fortnight and decides only which chip the picker opens on. Folding them together would
  quietly move the banner order. An explicit pick still wins: a heuristic may choose for
  you, never over you.

### The news box collapses, and un-collapses itself (2026-09-20)

591px → 45px, desktop and mobile. **⚠ The stored value is not a boolean — it is the
CONTENT SIGNATURE that was on screen when you minimised it** (`NEWS_COLLAPSE_LS`). If what
would render now differs, the box opens itself: "maximize it again when something new is
posted" (Zaven). That shape is what makes it safe to forget — a box collapsed in March
cannot swallow a set announcement in June, which a plain boolean would.

- Signature = tile **keys** (not count: a new tile replacing an old one is news and the
  count would not move) + each fresh Coconut reveal's slug + the reveal counter's
  **count** — its tile key is the constant `news` all season, so the key alone never
  moves as cards land. It fails silently in exactly one direction: the box just never
  reopens.
- **⚠ Nothing volatile may enter it.** A countdown would reopen it on a timer and make the
  minimise a lie; anything that changes when YOU act would pop it open at the moment you
  finished with it.
- **⚠ Renaming a token reopens every collapsed box once**, because the stored signature no
  longer contains it. Fine when the box is changing anyway (the poll removal below did
  exactly that); don't rename one for tidiness.
- The comparison is at RENDER, not in an effect, so new content paints open with no
  expanded-then-collapsed flash.
- **⚠ `contain:size` has to be released** on the `.rl-news-row` copy, which takes its
  height from the banner beside it: without that, collapsing leaves a full-height empty
  rectangle.
- Guarded by the signature section of `node scripts/test_home_layout.mjs`.

**The home poll is GONE (2026-09-27, Zaven: "remove the poll from news").** It sat at the
top of this box, above the News title, from 2026-09-18 (commits `4e8c8eb` and `af34a13`;
migrations 161 / 162 / 167). The client went with it — `useHomePoll`, `HomePollBox`,
`.home-poll*` — and so did the `lead` slot, which existed only to lift the reveal counter
ABOVE the poll; the counter is the first tile in the list again, under the title.
`test_home_layout.mjs` fails if the poll comes back, because a long-lived branch merging in
can resurrect it without a conflict.

- **The database side was left alone**: `polls`, `poll_votes`, `get_active_poll()` and
  `vote_poll()` are still live, now called by nothing. Dropping them is a human paste —
  and it deletes every vote ever cast — so it waits for an explicit ask.
- Bringing a poll back means restoring those two commits' code, not a rewrite; the next
  poll was always meant to be an INSERT, not a deploy.
