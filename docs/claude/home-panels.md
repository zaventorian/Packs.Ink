# Home panels: the title is a link, and the width decides where to (2026-09-06)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

You could not link anyone to one box on the home page — "the tournament box" was "scroll down".
Every configurable panel therefore has a title that is an **`<a href>` +
`navHandler`**, so ctrl/⌘-click and middle-click open the destination in a new tab and right-click
offers **Copy link address** without opening anything. That last point is the whole reason **no
box carries a link icon** — Zaven's constraint. Don't add one.

**Where the link goes depends on the width, and `panelTitleNav` (HomeView) is the one place that
decides.**

- **Above 1100px the title goes to the panel's SECTION** — Tournament Results to
  `/decks?s=tournaments`, Toolbox to `/analytics?a=overview`, Recent set EV to `/analytics?a=ev`.
  Up there the rails are real columns and every box is already fully visible, so popping one out
  over a dimmed page only re-showed you what you were looking at, and reaching the section took
  two clicks instead of one.
- **At or below 1100px the title still POPS THE PANEL OUT** at `/?panel=<key>`, over the dimmed
  page, where the Copy-link button lives. Down there the rails stack under the movers or ride a
  banner in a 32% column, and a box that cramped genuinely earns a whole screen.
- **News pops out at every width** — it is the one panel with no section of its own
  (`panelDest.news` is null), so there is nothing else for its title to do.
- An existing `/?panel=<key>` link **still opens the modal at any width**; only the title's own
  behaviour is width-dependent. The pop-out is simply not reachable from a wide home page's title
  any more, which is fine — right-click there copies the section link, which is the more useful
  one to send.

- **`homePanelTitle({cls, label, panelKey, panelNav})`** (next to `HOME_PANELS`) builds it and
  knows nothing about the decision: it calls `panelNav(key, label)` and renders whatever
  `{href, go, title}` comes back. Each panel renders `${homePanelTitle(...) || <its old title>}`,
  so a mount with no `panelNav` (the `--rl` copy of NewsFeed, any future non-home mount) still
  renders exactly as before.
- **`panelDest` is the one map of where a panel points**, and it feeds BOTH consumers — the
  title's link when wide, and the pop-out modal's footer button (`panelCta`, derived from it) at
  every width. One entry per panel means the two can't drift into naming different destinations.
- **The panel is MOVED into the modal, not copied.** `columnNodes` skips `openPanel`; a second
  mount would re-run its fetches and fork the collapsible ones' open/closed state.
- **⚠ `useMaxWidth(1100)` is a HOOK** and sits with the other HomeView hooks, above `panelNode`.
  HomeView has no early return before it today; adding one above it would break hook order.
- **`.home-title-link`'s reset sits ABOVE the per-title colour rules** in styles.css on purpose:
  it is an `<a>` now, so it needs `text-decoration:none` + `color:inherit`, but
  `.home-feed-title--chase` must keep its gold. Declared late, `color:inherit` wins and the gold
  titles go grey.
- **`panel` is registered in BOTH `dirtyParams` and `VIEW_OWNED.home`** — the standing rule for
  every deep-link param. Unregistered, the link appears to work and then silently resets.
- **pushState, not replace** (unlike the sub-tab params below): a modal is a place you can leave,
  so Back closes it. `closePanel` only calls `history.back()` when the entry is one it pushed —
  on a cold `/?panel=` load, back would leave the site, so it cleans the URL instead.
- **The calendar is deliberately excluded**, and `HOME_POPOUT_KEYS` (not `HOME_PANEL_LABELS`) is
  what `shareUrlLabel` checks. (`setChamps` used to be the exclusion here for the same reason,
  until it stopped being a panel at all.) Its title goes to /calendar and already
  carries richer deep links (`?sczip` / `scc` / `scdist` / `scdate` / `scmode`) that a bare
  `?panel=` would flatten. Labelling it would promise a link that opens nothing.
- Guarded by `node scripts/test_share_links.mjs`, which now walks every panel key.
