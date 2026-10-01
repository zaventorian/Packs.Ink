# Top-level nav

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**Two-row icon nav** (restructured 2026-05-25). Row 1 = "my stuff", Row 2 = "market intel". Home tab removed — the logo IS the home click target.

- **Row 1**: Collection · Cards · Decks · Scan
- **Row 2**: Screener · Price Graphing · Analytics · Help

Icons live in `NAV_ICONS` (Index.html) — hand-coded inline SVG (Tabler/Lucide-style line glyphs), `stroke="currentColor"` so they inherit theme color. To add/swap an icon: edit the `path` for that key in NAV_ICONS, no asset file needed.

- **Scan** (added 2026-08-04, gated on `canScan`) is an `<a href="/scan">` + `navHandler` like every other tab since 2026-09-27, when `/scan` became a route (it opens the scanner and rewrites the address to `/`). It was the one `<button>` in the nav because the scanner had no URL for a modifier-click to open. Everything in the nav must stay an `<a>` (see "SPA navigation"). It went in **row 1, not row 2**: both rows are 217px wide at the mobile sizing, so a 4th chip on row 2's longer labels (PRICE GRAPHING / ANALYTICS) is what pushed ANALYTICS off the edge on ≤420px phones before. It carries a `.nav-tab-beta` "BETA" flag, absolutely positioned over the icon so it costs no layout width — `.tabs` is a horizontal scroller on mobile, and because `overflow-x:auto` forces the cross axis to clip too, a badge hanging outside the chip would be cut off rather than drawn.
- **The top-bar 📷 bubble is GONE** (2026-08-10, user request). It predated the Scan tab and was kept as a second entry point; once the tab shipped it was a redundant control competing for the crowded right cluster. `.tabs-grid` carries `padding-right:8px` on mobile so the last chip in a row isn't flush against the scroller's right edge (which read as clipping). That gutter belongs on the scrolled CHILD, not on `.tabs` — padding on a scroll *container* is dropped at the end of the scroll range in several engines.

- **Screener** = sortable financial-database table (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface. Has a prominent **Raw Prices / Graded mode toggle** (segmented buttons) above the preset chips — flips the table between TCGCSV raw + graded data.
- **Price Graphing** = per-card history + multi-card Compare (handoff from Screener batch action).
- **Analytics** = umbrella for calculator-y tools. The 2026-08-20 consolidation took it from 8 tabs to 5; it has grown since, and `MARKET_SUBS` is the list, not this line: Overview · Expected Value · Trade Compare · Set Breakdown · Playset Cost · Simulator · Swiss Odds · Lore Tracker · Dice Tray · Stream Ticker (+ hidden pinnable Elo). Sub-tab is reflected in the URL (`?a=<sub>`) — see "Trade Comparison tool" and "Analytics tab" below.

### Mobile top-nav structure (do NOT regress)

- Scroll lives on `.tabs` (middle), NOT on the whole top-nav. Logo + right cluster stay anchored as flex peers.
- Right cluster on mobile is `flex-direction:column` with two rows:
  - **Row 1**: profile/sign-in pill (collapses to avatar-only on ≤640px) **+ install bubble** (📲, conditional on `!isStandalone && (isIOS || isAndroid)`)
  - **Row 2**: help bubble (?) + theme toggle bubble (🌙/☀)
- The install bubble lives in row 1 next to the profile because it **disappears** once the user installs the PWA (`isStandalone` flips true). Having it pair with the profile avatar means row 1 naturally collapses to just-the-avatar post-install, no layout shift. Putting install in row 2 (its old location) pushed row 2 to 3 bubbles wide (~116px) and tipped `ANALYTICS` off the right edge of the scrolling tabs container on phones ≤420px.
- **Help is a bubble in the right cluster's bubble row** (as of 2026-05-26), NOT a peer chip in tabs row 2. The previous "Help chip inside the tabs row" layout collided with the sign-in pill / profile chip on phones — the chip sat at the right edge of the scrolling tabs row and overlapped the anchored right cluster. Moving Help to `.top-nav-right-row--bubbles` puts it in the same flex container as install + theme, where it can't bump into the sign-in pill above it. Implemented as `<button class="theme-toggle theme-toggle--help">` (inherits bubble shape; `.active` paints accent when view=faq).
- **Gear badge on the avatar** (`.profile-gear-badge`, added 2026-08-04): a 13px gear pinned to the top-right of the profile button's avatar, so the button reads as "account **and** settings" rather than just "me" — theme, home layout, offline images and sign-out all live behind it and people weren't finding them. Purely decorative; `.profile-btn > *{pointer-events:none}` already makes the button the sole click target. Lights accent on hover and while `aria-expanded="true"`.
- Every container in the right cluster has `background: var(--bg)` explicitly so the sticky header paints opaquely over scrolled content.
- **The profile button is EXACTLY 36x36 on mobile**, like every bubble beside and below it. It
  used to size to its content — 42px wide, a 20px avatar swimming in 11px of padding — which made
  right-cluster row 1 wider than row 2, so the link bubble sat 6px left of the help bubble under
  it and the rows read as misaligned (reported 2026-08-24). Fixed width is what makes the columns
  line up; the avatar fills 28px and the gear badge tucks inside the button instead of hanging
  5px past its right edge.
- **Mobile tap-target floor: 36px** on every top-nav control (`.signin-btn`, `.profile-btn`, `.theme-toggle`, `.theme-toggle--help`). Apple HIG recommends 44pt; 36px is the compromise that keeps the two-row nav from growing too tall. Was 26–28px before 2026-05-25 and the profile pill was nearly impossible to hit on iPhone — don't shrink back below 36px.

### iOS safe-area-inset (do NOT regress)

Index.html has `<meta viewport-fit=cover>` + `apple-mobile-web-app-status-bar-style=black-translucent`, which tells iOS to extend content edge-to-edge under the Dynamic Island / home indicator. Every page-level element that sits near a screen edge MUST honor `env(safe-area-inset-*)` or it lands under the unsafe zone on notched iPhones (14 Pro+, 15/16/17 Pro/Pro Max).

- **`body` padding** uses `max(designed, env(safe-area-inset-*))` on all four sides — desktop and non-cutout devices see 0 from env() so the designed 24px / 14px floor applies; notched devices pad outward to clear unsafe zones.
- **`.card-detail-close`**: `top: max(10px, env(safe-area-inset-top))` so the X stays tappable on iPhone (Photo 3 regression).
- **`.settings-popover` mobile pin**: `top: calc(56px + env(safe-area-inset-top))` so the menu doesn't open under the Island when tapping the avatar.
- **`.gc-add-fab` (graded mobile FAB)**: `bottom: calc(18px + env(safe-area-inset-bottom))` so the Add button isn't clipped by the home indicator.

Any new sticky / position-fixed / position-absolute element near a viewport edge should add `env(safe-area-inset-*)` to its offsets.
