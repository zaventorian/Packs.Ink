# Lore Tracker (Analytics » Lore Tracker)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

A full-bleed scoreboard for a table. Guarded by `node scripts/test_lore_tracker.mjs`, which
extracts the real pure functions out of Index.html.

- **The board covers the page, nav included, and always has** — the full-screen toggle is gone
  (2026-08-27). "Exit full screen" un-covered the page and left you on the Analytics tab still
  looking at a board, which is a step rather than an exit. The way out is **Exit to home** in the
  menu, an `<a href="/">` + `navHandler` driving App's `openHome` (`setView("home")`), passed down
  through MarketView. The `body{overflow:hidden}` effect is unconditional now and its cleanup is
  what restores scrolling on the way out.
- **The base win target lives on the GAME (`game.win`), not just in prefs**, so a stored game
  replays at the target it was played at. Read it through **`loreWinOf(game)`**, never
  `game.win` — a game stored before the setting existed has no such field and must read as 20.
  `LORE_WIN_PRESETS` is Pack Rush 15 / Standard 20 / Coconut 25, plus a Custom number
  (`LORE_WIN_MIN`..`LORE_WIN_MAX`). A settings change moves the goalposts on the board you are
  looking at, same contract as the seat settings.
- **`LORE_WIN_PRESETS` and `LORE_WIN_MODIFIERS` are different things.** The presets are the
  table's base target, a format choice. The modifiers (Donald Duck - Flustered Sorcerer) retarget
  individual SEATS mid-game, and `loreTargets` takes the MAX — so a modifier can only ever raise a
  seat's target, and Donald asking for 25 is correctly a no-op at a Coconut table already on 25.
  Both live behind the goal button in the bar, presets first.
- **The goal button drops its number only when the seats actually disagree.** `modsOn ? "" : win`
  blanked it whenever any modifier was on, even when every seat still shared a target.
- **Preset chips are shortcuts, not the set of legal values.** `loreReadPrefs` CLAMPS the round
  length and the win target rather than membership-testing them — the old test silently reset a
  custom 45-minute round to 50 on every reload, which is the one failure mode a Custom control
  must not have. "Custom" is not a stored mode: it is the state of holding a number that isn't a
  preset, held in a `minsCustom` / `winCustom` flag purely so you can ENTER it from a preset.
- **The board dresses for the format** (2026-08-27) — three flourishes, all decoration, none
  load-bearing (the bar's goal button is what actually states the target). `loreFormatOf(game)`
  maps the BASE target to a name: 15 → Pack Rush (seat names and numbers go italic), 25 → Coconut
  (a drawn coconut glyph beside each seat name, from `UI_ICON_PATHS` — never an emoji, per the
  icons rule), anything else → nothing. It reads `loreWinOf`, NOT a seat's target, or one Donald
  would put the whole table in coconuts. A hand-typed 25 counts as Coconut, deliberately: someone
  typing it is playing it, and storing a preset id would let a custom number contradict it.
- **Player 1 is the BOTTOM seat, the opponent the top one** (2026-09-12, Zaven) — a phone propped
  on a table faces whoever set it down, so the near half of the screen is theirs and the far half
  is the player across the table. `seatOrder` reverses the render for two seats; **`idx` stays the
  true player index** (it keys the score, the rename and every stored event), so never re-derive a
  player from render position. This also settles which side "Face-to-face" turns around: seat 1,
  now the top one. Rendering seat 0 first put YOU at the top and flipped YOUR half — wrong twice.
- **The seat's background art is cropped to the top 68% of the card**, top-anchored: the card's
  frame, its art and its name down to the classification band, stopping where the ability box
  starts. 68% was measured off both Lorcana layouts (a character's classification band and a
  song's both end at 67%). **Top-anchoring alone is not the trick** — on a seat narrower than
  ~1.05:1 a plain `object-fit:cover` scales by width and runs down into the rules text, so
  `.lore-seat-art` is `height:147.1%` (100/68) of the seat and the seat's own `overflow:hidden`
  is what makes the cut. A seat WIDER than that shows less than 68%, which is fine: the top of
  the card is the part that must never be cut, and the old `object-position:center 22%` cut it.
- **A seat that played a modifier wears its card**, a round crop beside that seat's lore total.
  The art is resolved once in LoreTracker from `CatalogContext` by the modifier's own `card` name,
  so a future `LORE_WIN_MODIFIERS` entry gets a badge for free. `object-position` sits high —
  a centred crop of a Lorcana card is mostly costume. Missing art renders nothing; it is a
  flourish, and the modifier row above is what tells you the rule is on.
- **⚠ At 3–4 seats the grid halves each header and the name input is the only thing that can
  give** — and an `<input>` clips rather than ellipsing, so a badge eating 22px there costs
  letters of a real name. The flourishes shrink in `.lore-seats--n3/--n4`. Measured at 390px/4
  seats: 59px of name at full size, 70px shrunk, 81px with none at all, against 89px wanted by
  "Player 1" — the squeeze predates them, but don't deepen it.
- **Best-of-3/5 was removed** (2026-08-27, Zaven): the match score it kept lived in a corner of
  the bar and changed nothing about play, so it cost a settings row to answer a question a table
  holds in its head. `matchLen` / `wins` / `resetMatch` and the `match` + `wins` prefs are gone.
