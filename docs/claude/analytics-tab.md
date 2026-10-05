# Analytics tab (reorganized 2026-08-20: 8 tabs → 5)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`MARKET_SUBS` = overview / ev / trade / avg ("Set Breakdown") / setval / sim / swiss / lore / dice / ticker (+ elo, hidden unless pinned). The consolidation:

- **Swiss Odds (`swiss`, added 2026-08-20)** embeds the standalone `swiss.html` page as `<iframe src="/swiss?embed=1">` (canonical path is `/swiss` — Workers Assets pretty-URL handling 307s `/swiss.html` and the worker's legacy `/lab/swiss` route to it, DROPPING the query, so never point the iframe at `/lab/swiss`) — the sim stays a separate file on purpose (its Monte Carlo engine is a hot loop ordinary visitors shouldn't download inside Index.html; see the commit that added it). `?embed=1` sets `data-embed` on the page root pre-paint, hiding its own brand/flag/theme chrome, then strips the param via replaceState so the page's Copy-link never leaks `embed=1`. The header's "Open full page ↗" escape hatch was removed 2026-08-21 (user call — redundant once the embed worked; `/swiss` stays reachable by URL and the embed's own Copy-link shares it). swiss.html links `/styles.css` UNVERSIONED (network-first SW keeps it fresh; a `?v=` there would drift from the bump-cache lockstep, which doesn't know about this file).
  - **Below 960px the Swiss tab is an AUTO-HEIGHT frame** (`SwissEmbed`, 2026-09-26): there the simulator stacks into one column and stops being a sticky-sidebar tool, so a fixed ~600px box made it a window you scrolled inside while the page scrolled past it to the footer. swiss.html carries the same content-measuring height reporter as ticker.html, and its embed CSS sets `body{min-height:0}` (100vh inside a frame sized FROM the content is a growth loop). Wide, it keeps the fixed frame. The embed also hides its own title (`.sw-titles`) — the tab header already names it — and the "Internal preview" pill is gone.
  - **Both embeds follow the site's theme toggle** (`syncFrameTheme`): their pages read the theme once at load, so a toggle left them the other colour until reload, and a system-mode override (never persisted) never reached them. The host copies its own `data-theme`/`data-mode` in on the frame's load and on every change.
  - **Swiss Copy link describes the run ON SCREEN** (`LAST_RUN`), not the live form — typing a record used to rewrite the link from settings nobody had run. The link carries the cut the person PICKED (`cutChoice`), never the field-clamped one: `c=12` from a 12-player Top 16 is a value the menu lacks, and reopened as "No cut" (older links now snap to the smallest offered cut at or above it).

- **Stream Ticker (`ticker`, added 2026-09-15)** embeds `ticker.html` the same way —
  `<iframe class="market-embed-frame" src="/ticker?embed=1">` — and for the same reason: the
  configurator is a page you set up once and then paste into OBS, not a calculator worth
  carrying inside Index.html. `?embed=1` is swiss's mechanism copied: the pre-paint boot sets
  `data-embed` on the root, which hides `.tk-top` (brand, title, and the one `<a>` on the page,
  a link to packs.ink that would otherwise navigate the iframe out of the tool), then strips
  the param via replaceState. The overlay URL the tool copies is built from
  `location.origin + location.pathname`, so it is the `?bar=1` OBS form either way and an
  embed flag can never leak into it.
  - **⚠ Both embeds need a `_headers` carve-out or the tab renders the browser's gray
    broken-page icon.** The site-wide `X-Frame-Options: DENY` + `frame-ancestors 'none'`
    refuse framing even from packs.ink itself. `/swiss` and `/ticker` each detach-and-replace
    both, to SAMEORIGIN / `'self'`; the CSP is otherwise the `/*` policy VERBATIM, so an origin
    added to one must be added to all three. `node scripts/test_csp_headers.mjs` pins that.
    Invisible in local dev, which does not apply `_headers` — verify with `npx wrangler@4 dev`.
  - **⚠ `/ticker` must keep having NO worker route.** Workers Assets' pretty-URL handling serves
    it with the query intact; a route that fetches `/ticker.html` gets 307'd to `/ticker` and
    the redirect DROPS the query — which is both the OBS config and `embed=1`.
  - **It is a tab, NOT a home-Toolbox chip.** `HOME_TOOLS` deliberately omits it, same rule that
    omits Simulator: the toolbox is the calculators an ordinary visitor opens cold, and an OBS
    overlay is for the handful of people who stream.
  - `.market-embed-frame` (was `.market-swiss-frame`) is the one CSS rule both embeds use, so
    the two frames can't drift.

- **Set Breakdown (`avg`) = Card Averages + Heatmap merged.** One rarity×set table with a metric toggle (`packsink:market:avgMetric`): `$ per card` averages, or `% of box EV` with the old heatmap's cell shading. **The share lens uses per-set `getPull(set)` — the deleted `HeatmapView` used the flat v1 `PULL` for every set, which was simply wrong for Wilds Unknown onward** (6 Legendaries not 4, 2.5 Epics not 1.5, 0.333 Enchanted not 0.25). Default selection = 4 newest sets (all-sets was a 1,655px-wide table); the `All` chip restores everything; exactly 2 selected still reveals the Diff column (pp units in share mode). The per-rarity "Pull rate" column is gone — rates differ per set now, so each cell's `title` tooltip carries its set's exact rate.
- **Simulator (`sim`) = Pack + Box + Monte Carlo merged.** Mode lives in `packsink:market:simkind` (`pack | box | bulk`); "Odds" (bulk) is the old `MonteCarloView`, mounted as a mode. The `sim-kind-bar` `<select>` is gone — a `.market-sim-kind` segmented control sits in the shared header.
- **Sealed tab DELETED — the Screener's Sealed mode superseded it.** `SealedView` is gone from Index.html and its `.sealed-view/.sealed-row*/.sealed-set-*` CSS from styles.css. The display-type classifier helpers (`SEALED_DISPLAY_TYPE_ORDER`, `deriveSealedDisplayType`, `isHiddenSealedListing`, `SEALED_PUZZLES`, `cleanSealedName`) **stay** — Screener sealed mode + SealedCollectionView consume them.
- **Legacy `?a=` keys must keep resolving** (old links exist in the wild): `MARKET_SUB_ALIASES = {heatmap→avg, montecarlo→sim, sealed→ev}`. App's `marketSub` initializer additionally one-shots the mode preset (`heatmap` writes `avgMetric=share`, `montecarlo` writes `simkind=bulk` to localStorage before the view mounts), and **`?a=sealed` redirects to the Screener**: a mount effect writes `packsink:screener:showSealed=1` / `showGraded=0` and `setView("screener")`. The popstate handler resolves aliases too.
- **Sub-tabs are `<a href="/analytics?a=…">`** via `navHandler` (SPA-nav convention — modifier-click opens a tool in a new tab). On ≤640px the bar is a single scrolling row (was a 3-row 127px wrap); the trailing gutter is a `::after` flex child per the scroll-container-padding gotcha. The 36px tap floor moved from `.market-subtabs > button` to `> .market-subtab`.
- **Shared chrome**: `MarketHeader` (the EV header pattern as a component — emits `.ev-header.mkt-header`) + `MarketExplainer` (collapsible "ⓘ How this works", collapsed by default, persisted per tool at `packsink:market:explain:<id>`). Every tool now has the header; the always-on `.market-explainer` walls are gone. `MARKET_SUB_TITLES` gives each sub-tab its own `document.title`.
- **EV rows carry a `⚄ Sim` chip** (`.ev-row-simbtn`) → `simulateSet(setName)` jumps to Simulator/Box with the set preselected. The set selection is SHARED across the three sim modes: MarketView owns `simSet`, each mode consumes it as `presetSet` in its `useState` initializer (modes remount on switch) and reports picks back via `onSetChange` — so Pack ↔ Box ↔ Odds keeps the set. BoxSim's `onOpenOdds` flips to bulk mode. The EV row's `onKeyDown` guards `e.target===e.currentTarget` so Enter on a focusable child doesn't also fire the row's open-history.
- **⚠ The Low / NM Market toggle ALWAYS opens on Low, and is NOT persisted** (2026-09-21,
  Zaven: *"why did price default to nm market? we should always default to low"*).
  MarketView owns one `priceMode` shared by EV, Playset Cost and Set Breakdown — a plain
  `useState("low")` now, matching the Screener. It used to persist to
  `packsink:market:priceMode`, **and the Collection » Sealed tab read and wrote that SAME
  key**, so flipping the toggle there to value a sealed collection silently retargeted three
  Analytics tools, on every later visit, with nothing on screen saying why. Sealed has its own
  `packsink:sealedColl:priceMode` now (beside its `:display` / `:trackCosts` siblings) and
  still persists — it is a collection-value preference, where every tool under Analytics
  states a COST and which number that cost is built from has to be readable off the screen on
  arrival. The old key is orphaned, which is what stops a stale `market` resurfacing; it needs
  no migration.
- **The home Toolbox is NOT a mirror of this tab bar, and it holds exactly SIX chips** (three
  even rows of the two-column grid). As of 2026-10-05 (Zaven): Expected Value · Trade Compare ·
  Set Breakdown · Playset Cost · Swiss Odds · Tier List (Tier List took Simulator's chip; Simulator
  stays an Analytics tab and the EV rows' Sim button still opens it). **Dice Tray and Lore Tracker came out**
  — on phones they already have their own bubbles in the movers toolbar's corner (the fixed
  `dice` / `lore` HOME_PANELS entries), which is where someone mid-game reaches for them. The
  Stream Ticker stays out (an OBS overlay is not a cold-open tool). Dropping a chip from
  `HOME_TOOLS` must never drop the tool — every one of them is still an Analytics tab.
- **The Lore Tracker's glyph IS `LORE_PIP_PATH`** — `HOME_TOOL_ICONS.lore` references the same
  const the tracker's own `LoreDiamond` draws, so the two can never drift. A tall diamond whose
  four sides bow INWARD by 13%: the waist is the whole difference between "lore" and "a diamond",
  and past ~30% it stops being a pip and becomes a sparkle. Verified by rasterising the path, not
  by eye at 17px. The pip is the WHOLE glyph — it sat over a rising-tick baseline until
  2026-08-27, which cost it a third of the box for detail invisible at chip size.
- **`HOME_TOOLS` order is the render order of a two-column grid**, so the first pair is the top
  row. Chips carry a label and no
  subtitle (dropped 2026-08-27): the second line doubled every chip's height, and what each tool
  answers is what Analytics » Overview is for.
- **The Dice Tray hands off to it with a corner bubble**, not the row that used to sit under the
  tray ("Rolled? Keep score in the Lore Tracker"). A row reads as a next STEP, and it isn't — you
  roll for turn order once and keep score all game. `.dice-lore-btn` is absolute at the stage's
  top-right (`.dice-stage` carries the `position:relative` and a 48px top pad so a full row of
  type chips can never wrap under it), and stays an `<a href="/analytics?a=lore">` + `navHandler`
  so modifier-click still opens a tab — the Lore Tracker has a real route, unlike the Scan tab.
- **The Dice Tray reads a TOTAL and never names a winner** (Zaven, 2026-09-26). It used to say
  "Player 2 goes first with 4", light up that die, and offer "Reroll the tie" with a roll-off mode
  behind it. All of that is gone: players read their own dice, and tapping one rerolls just that
  one. The per-seat "Player N" labels stay, because they only say whose die is whose. Don't bring
  back a verdict line or a highlight.
- **The tab bar also renders a right-aligned "Sealed ↗" pointer chip** (`.market-subtab-ext`) — a muscle-memory bridge to the Screener's Sealed mode. It and the `?a=sealed` redirect share App's `openScreenerSealed` callback (writes the two screener localStorage flags, then `setView("screener")` — must run before the Screener mounts, since its mode flags are read in `useState` initializers).
- **Coachmark fixes that shipped with this work** (tour infra, not Analytics-specific): an open auto-tour now DISMISSES on top-nav view change instead of following the user into a view where its selectors match nothing (context-free floating card; dismissal does NOT stamp `sectionTourSeen` — abort semantics). And the tip re-measures on a slow keepalive for its whole life instead of stopping 1.1s after mount, so async data reflowing the page can't strand the spotlight.
- Dead code cleaned with it: the unused v1 `CompareView` (absorbed into Card Averages long ago), `.trade-intro`, `.card-avg-chip-reset`, `.sim-kind-*` CSS.
