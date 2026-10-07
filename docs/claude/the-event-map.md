# The event map — two surfaces, one component (2026-09-22)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`EventMapView` (beside `scMergePins` in Index.html) draws many events on one OSM map.
Same tiles-as-plain-`<img>` deal as `CalendarMiniMap` — no library, no script, no cookie —
over `osmFitLayout`. Guarded by `node scripts/test_event_map.mjs` (258 checks).

**It needed no migration, no RPC change, no new query and no `_headers` change.**
`get_nearby_lorcana_events` already aggregates lat/lng per series, calendar rows carry
city-level coordinates from `143_calendar_geo.sql`, and `tile.openstreetmap.org` was
already in BOTH CSP directives for the calendar's mini-map. Worth remembering before
anyone scopes a "map feature" as large.

- **The finder's map and the calendar's map are DIFFERENT MAPS**, which is why `height`
  and `fit` are props rather than constants. The finder answers *"which way do I drive"* —
  a 50-mile radius, zoom 11-13. The calendar answers *"where is the season"* — the circuit
  is ~17 Challenges across four continents, so `CAL_MAP_FIT` opens it to `minZoom: 2`.
  One shared range serves neither: capped at 13 the world map cannot fit Tokyo and Chicago
  on one screen at all, and floored at 2 the finder opens on a view of Europe.
- **In the home TILE the Map button pops the box out** (`setMapOn(true)` + `setExpanded(true)`,
  and the chip carries a ⤴). The rail is 240-360px against a 330px-tall map, which is a
  smudge you cannot read a date off — and the expanded card is the same component with the
  same filters, so "pop it up" costs two flags and no new UI. Expanded, or in the App
  overlay, it switches in place.
  - **⚠ `mapHere` (`mapOn && !inTile`) is a different question from `mapOn`**, and both are
    load-bearing. `.sc-results--map` hides `.sc-list` by CSS, so a tile that stored a map
    preference would hide its list and draw nothing in its place — a dead surface with the
    Map button lit over it.
- **⚠ `CAL_MAP_H` was already taken** by the calendar's own mini-map height (150). The
  view's is `CAL_MAP_VIEW_H`. A duplicate `const` at module scope is a SyntaxError that
  takes the whole app to a blank page, and it is not caught by any test — only by loading it.

### ⚠ Only what can be SEEN is rendered, and the box MEASURES itself (2026-09-22)

Two bugs found by sweeping the finished feature rather than from a report. Both
were invisible by construction, and both had been there since the map shipped.

**A clipped pin was still a BUTTON.** `.sc-map-box` is `overflow:hidden`, so a pin
outside the frame was hidden from your eyes and from nobody else. Measured on the
calendar map at a metro focus on a 375px phone: **65 pins drawn, 46 entirely
outside the frame**, the worst **65,685px** away, every one keyboard-focusable and
carrying a full `aria-label` — so Tab walked 46 controls nobody could see and a
screen reader read all 65. Present on desktop too (29 of 65). Clipping hides a
thing from your eyes, never from the tab order.

- `allGroups` is the merge; **`groups` — what the render loop walks — is the
  filtered set**, and it is what every downstream number reads.
- **⚠ INTERSECTION, not centre-in-frame.** A pin whose centre sits just outside
  still shows half its dot at the edge; dropping it deletes something visible. It
  tests against the group's real `scPinR`, the same width the label placer
  reserves, so "drawn" and "reserved" cannot disagree.
- **⚠ `labelSides` is indexed BY POSITION** (`labelSides[gi]`), so it must be
  computed from the same filtered array the render walks. Placing over the
  unfiltered set while rendering a filtered one hands every pin its neighbour's
  date chip — silently, and only on maps that have anything off-frame.
- An off-frame dot no longer reserves label space, which is correct: nothing is
  drawn there, so a chip over it covers nothing.
- **The on-screen list is now literally the events under the pins that are
  drawn** (`groups.flatMap(g => g.items)`), so "the list names exactly what the
  map shows" is true by construction rather than by two nearly-identical tests
  agreeing.

**⚠ THE HEIGHT IS MEASURED, exactly as the width is — CSS gets the last word.**
The calendar passes `CAL_MAP_VIEW_H` (480) while
`.cal-map-view .sc-map-box{height:340px !important}` renders it **340** on a
phone, so every number derived from the prop was computed for a box **41% taller
than the one being drawn in**: the fit framed pins into 480px of vertical space
and the bottom ~140px was then clipped, `scPlacePinLabels` placed chips against a
floor that did not exist, and pins landed genuinely outside the box (measured: one
at `top:471px` inside a 340px box). ~29% of the map was laid out where it could
never be seen.

- **⚠ The style still writes the PROP, never the measurement.** The box's height
  comes from `H`, so feeding a measurement back in is a loop; reading it only for
  the maths converges in one pass whether or not CSS overrides it.
- The width was already measured for exactly this reason, and its own comment
  says so — "the box is a different width embedded in the calendar tile, expanded
  over the page, and on a phone, so it is measured rather than assumed". The
  height is no different, and a breakpoint duplicated in JS and CSS is the
  one-number-in-two-files trap this file warns about elsewhere.

**⚠ A merged pin DISCLOSES, it does not RECITE.** A pin standing for 25 events
carried all 25 in its `aria-label` — **1,755 characters** as one button's
accessible name, which a screen reader reads start to finish with nothing to skim,
on the pin most worth landing on. The names were never at risk: the callout it
opens is already a list of real buttons, one per event, which is the reachable way
to expose them. It now says what it is and what activating it does, and carries
`aria-expanded` (absent on a single pin, which discloses nothing). Measured:
**1755 → 85 characters**.

A tile that fails to load now hides itself (`onError={hideBrokenImg}`) instead of
drawing a broken-image glyph over the map.

Measured after, at 375x667 and 1280x900: pins **65 → 19** and **65 → 36**, **0 out
of frame at either width**, 0 chips outside the box, 0 chip-over-pin overlaps, 0
horizontal overflow — and the finder's fitted map still shows all 7 of 7 results,
so nothing that should be drawn was dropped. The on-screen count falls with the
pins; that is the list becoming honest, not losing anything.

**Deliberately NOT changed by that sweep**: the finder's map takes neither `focus`
nor `onPan`, so it cannot be dragged or zoomed while the calendar's can. That is
left as-is rather than "fixed" — the finder's map is a fitted overview of a radius
you already chose, its merged pins are answered by the callout and the list
beneath it, and it offers no grab cursor or zoom control to suggest otherwise.
Giving it pan without zoom would be half a control on a map whose whole job is to
frame one search.

### The date on the pin, and why placement is a FIT

A bare dot says "an event is here", which the list beside it already said. The date is what
turns the map into a plan. But **a label is ~5x the footprint of its dot**, so two shops
whose DOTS clear each other comfortably have labels that overlap completely — `scMergePins`
(11px) cannot catch that, because they are genuinely different places.

`scPlacePinLabels(pins, w, h)` decides per pin: a chip to the right, to the left, or none.

- **⚠ A label that will not fit is DROPPED, never stacked or shrunk.** The dot survives and
  the callout still names every event under it, so a dropped label costs a glance — where a
  chip drawn half off the edge is simply gone with nothing on screen to say it existed
  (the `.scanner-qa-rowinfo` rule, and the timeline's).
- **⚠ Right THEN left, the left one drawn BACKWARDS from its dot.** Without the flip, no pin
  in the right-hand third of the map could ever be labelled — a whole edge going quiet.
- **⚠ EVERY dot is reserved before anything is placed**, labelled or not: a chip may never
  cover another event's pin, which would hide something clickable.
- **⚠ A MERGED pin is WIDER than a plain one** — it carries a count. Reserving 22px for it
  let a chip clip its edge by 2.5px, measured live: invisible in a screenshot, and still
  over a click target. `scPinR(count)` derives the real width from the pin's own CSS
  (`min-width:22px`, 5px padding and a 2px border each side, plus the digits).
- **⚠ Every reserved box is inflated by `SC_LBL_BLEED` (1px).** The chip is centred by
  `top:50%` + `translateY(-50%)` inside a bordered parent, so where it lands can differ from
  the arithmetic by a rounding — measured at exactly 1px, which was enough to put one chip's
  corner over a neighbouring pin. A pixel of slack costs a marginal label and buys the
  guarantee the function exists for.
- **Ties go to whoever the LIST ranks first** — the finder sorts pinned-then-soonest, the
  calendar by date — so the surviving label is the one the reader was going to look at first.
- `scLabelW` over-estimates slightly (52 against a measured 49.7), which is the SAFE
  direction: it reserves more than it uses.
- **⚠ A pin's date is SHORT** (`scPinDay` → "Sep 27", never `fmtSCDate`'s "Sat, Sep 27").
  Every character it does not need is a pin that keeps its label instead of falling back to
  a dot. Verified live: 40 pins → 17 chips, 0 chip-chip, 0 chip-dot and 0 out-of-frame.

### ⚠ The map defaults to ALL events, and yours is the FILTER (2026-09-22)

Zaven: *"I want map to default to all events, then you can filter down to just
yours"* — and *"if i click every event near me, it opens a new smaller window."*
One mistake, two symptoms. The map held the circuit plus the shops you follow, so
zooming to your own town answered a narrower question than the one asked, and the
route to the real answer was a link opening the finder's map in a second, smaller
window over the one already on screen.

- **A focused map fetches every event around that point** — `useMapNearbyEvents`,
  the same `get_nearby_lorcana_events` the finder uses, with **`p_kind: null`** so
  league nights count. Measured near Chicago: **26 pins before, 65 after**, 34 of
  them in frame.
- **⚠ ALL is the default and the left-hand option.** The shops you follow are the
  NARROWING; as the starting point they show an empty map to exactly the person
  who has followed nothing yet, which is everyone once.
- **⚠ The map draws `listed` PLUS the feed, never the feed alone.** The circuit
  and your own shops ARE the calendar. `calendarMergeStore` keys on `event_id`,
  so a shop you follow is never drawn twice.
- **⚠ It only ever runs FOCUSED.** ~17k upcoming events; a whole-world map of
  them is not a map, and that RPC is the most expensive read on the screen. No
  focus, no fetch, plus a module-scope cache per (point, radius).
- **⚠ The radius is the finder's own `packsink:scRadius`**, not a second setting —
  the two-postal-code-boxes trap again.
- **⚠ `mapNear` / `mapRows` sit BELOW `listed`**, which they read: a `useMemo`
  runs at its own declaration point, so above it that is a TDZ ReferenceError
  into the error boundary (the `screenerPayload` trap).

### Dragging it, and the kind chips (2026-09-22)

- **A pointer drag pans it.** ⚠ The tiles move under the finger on ONE transform
  layer holding the tiles AND the pins, and the layout is recomputed only on
  release — refetching a tile set per `pointermove` is a request storm and a
  juddering map, and moving the shared parent is what keeps a pin on its street.
- **⚠ `scPanCenter` works in WORLD PIXELS, not degrees** (a pixel is worth more
  latitude near the poles) and **inverts the sign** (dragging the tiles right
  shows what was west). **Longitude WRAPS, latitude CLAMPS**: a drag west past
  the antimeridian must come out at +179, not -181, which `osmFitLayout` rejects
  as out of range — so the map would go blank rather than error.
- **⚠ 5px before a drag starts**, the movers banner's threshold, so a click on a
  pin is still a click.
- **⚠ `touch-action:none`, which is what a map is.** The cost is accepted: on a
  phone you scroll the page from above or below the map, not across it — which
  is why the map is shorter at ≤640px.
- **A drag lands you in FOCUS mode** even from the fitted view: once you have
  moved the map by hand, "fit everything" is not what you asked for, and
  snapping back on the next render would undo the drag in front of you.
- **Set Champs / Prereleases / Locals chips.** ⚠ A DIFFERENT axis from the chips
  above, which are the calendar's own kinds — a store event is one row under "My
  stores" whether it is a Set Championship or a Thursday league night. Only rows
  carrying an `rph_kind` are filtered, so a DLC, a CCQ or a set release never
  vanishes because Locals is off. Last active chip can't be switched off.

### `/calendar?cv=map`, the fourth mode

Beside List / Month / Timeline, rendering **`listed`** — the same array the list renders, so
"Show past" and every filter above mean the same thing there as here, and a map can never
quietly hold a different set of events from the view you switched away from. `cv` was
already validated against `CAL_VIEW_MODES` and registered in `dirtyParams` + `VIEW_OWNED`,
so `?cv=map` needed no routing change at all.

- **⚠ "Not on the map" is TWO facts and they must not be added up.** A set or product
  release is WORLDWIDE — in no place by definition, the same reason the timeline gives
  releases a rail of their own — while a store event with no coordinates is a GAP in the
  data. Counted together, the calendar permanently reported *"11 events have no location on
  file"*, which reads as broken software rather than as the truth. `worldwideOf` splits
  them; the live footer reads **"11 releases are worldwide · 1 event has no location on
  file"**. Filtered to releases alone the map says so instead of looking empty.
- **⚠ Map does not write `cm`.** It ignores `month` entirely, so a link off it would carry
  an anchor that does nothing there and silently moves the Month view on arrival.
- The glyph is a FOLDED MAP, not a pin: this names a view, and a pin says "location".

### Getting TO the map, and getting DOWN to a town (2026-09-22)

Two reports from Zaven, both true, and both about the same gap: the map existed
and there was no ordinary way to reach or aim it.

- **"I don't see the button for it on the home page."** The finder's List/Map
  toggle lives inside `.sc-results-head`, which cannot render until a search has
  RESULTS — so a visitor who has never typed a postal code sees no map entry
  point on the home page at all. **`cal-panel-tools` gains a map glyph** beside
  List and Month: always visible, an `<a href="/calendar?cv=map">` + `navHandler`
  per the SPA-nav convention.
  - **⚠ The mode travels through the STORED preference, not the URL.**
    CalendarView reads `?cv=` out of `location.search` in a **mount-time**
    `useMemo`, and App writes the pathname only after the view changes — so a
    param set at click time is not on the URL yet when it is read. The click
    writes `CAL_VIEW_LS` and navigates, the same handoff shape as
    `?a=sealed` → Screener. The `href` still carries `?cv=map` so a
    modifier-click opens the right thing.
  - It reuses `panelNav("calendar", …)`, which resolves at every width because
    `calendar` is in `HOME_ALWAYS_SECTION`.
- **"On calendar, I don't see a way to pop in a zip code and zoom in."** The
  calendar map opens on a whole season across four continents, which is its job,
  and had no way down. `.cal-map-bar` is a place box + a **zoom stepper**.
  - **⚠ It shares `packsink:scZip` / `scCountry` with the event finder** rather
    than keeping a second one, and resolves through **`scResolveOrigin`** — so it
    takes a postal code or a town in every country that box does. "Where are you"
    is one question; two boxes that can disagree is how someone ends up on the
    wrong Dublin on one surface and the right one on the other.
  - **A STEPPER, not a slider or a pinch.** The map is static `<img>` tiles with
    no pan, so the honest control is the one that re-renders it at a new zoom.
    `CAL_MAP_FOCUS_Z` 9 (a metro), bounded 3-13. 44x36 at ≤640px — it is the one
    control here you press repeatedly.
  - The lookup is **sequenced** (`mapSeq`) like the finder's own search: two
    lookups can overlap and a stale FAILURE landing last would wipe a good
    answer, which is the bug that box already had once.

**`osmFitLayout` grows an optional `focus` {lat, lng, zoom}.** It overrides the
centre and the zoom and **shares every line below it deliberately** — the
wrap-to-nearest-copy and the pin subtraction are the two places a pin can drift
off its tile, and a second copy of either is exactly how that happens.

- **⚠ The fit's `minZoom`/`maxZoom` do NOT apply to a focus.** Someone who pressed
  + chose that zoom; only the 0..19 that tiles exist for bounds it.
- **⚠ It reads coordinates through `coord`, never a bare `Number()` — Null Island
  again.** A focus half-built from a lookup that returned nothing (`{lat: null}`)
  is a perfectly finite 0N 0E, so "zoom to my town" would have centred the
  Atlantic. Four half-built focuses now fall back to the fit; the guard test
  caught this, not a screenshot.
- **⚠ Zooming somewhere EMPTY is the common outcome, not an edge case.** The
  calendar holds the circuit plus the shops you follow — follow none and a zoom
  to your own town is correctly, completely empty, and an empty map with no
  explanation reads as broken software. `EventMapView` counts what landed inside
  the frame and renders `focusEmpty` over the tiles with the two ways out: turn
  on "SCs near me", or open the finder, **which is the map that does hold every
  local event**. Pins outside the frame are clipped by `overflow:hidden`, which
  is right, but silent.

### The pins wear the calendar's marks, and the map lists what is on screen (2026-09-22)

Zaven: *"instead of yellow dots, can we use the logos that corrispond with the
calendar?"* and *"below map, a list view of all events on screen."*

- **A pin carries the same `{icon, hue, img}` the calendar draws beside that event
  everywhere else** — the Challenge shield, the qualifier hexagon, a trophy for a
  Set Championship, a shopfront for a league night. `KindIcon` is split out of
  `CalendarKindDot` so both surfaces draw from ONE stack: a Challenge shield on the
  calendar and an anonymous yellow dot on the map for the same event is the two
  surfaces disagreeing about what the thing IS. The finder's marks go through
  `calendarEventIcon` with a synthetic store row (`scSeriesIcon`) rather than a
  second icon table — a finder result and the calendar row for one shop night are
  the same event seen from two pages.
- **⚠ A MERGED pin only wears a mark when every event under it AGREES.** Taking the
  first one's would state, in a picture, that the pin is a Challenge when half of it
  is a league night. Measured near Chicago with every kind on: 65 pins, 38 marked,
  27 mixed and correctly left as plain counts.
- **⚠ An icon pin INVERTS** — a light disc carrying the kind's colour, not the
  colour as the disc. The DLC and CCQ marks are IMAGES with their own palette and go
  to mud on a saturated ground, and a white glyph on a pale hue is unreadable at
  that size. On the dark themes `--bg-modal` makes it a dark disc with a coloured
  glyph, which is what separates it at a glance from the gold count-only pin.

**⚠ AN ICON PIN IS WIDER, AND `scPinR` HAS TO BE TOLD — this shipped wrong once.**
`SC_PIN_ICON` asked for 14px while `.cal-ico` (the shared glyph stack it borrows)
declares its own **18px** box and is declared LATER in styles.css at equal
specificity — so the cascade gave it 18 and the reservation was 4px short on every
marked pin. **It passed a live sweep anyway**: `SC_LBL_BLEED`'s 1px of slack
happened to cover most of the shortfall, and that pixel exists to absorb the
`translateY` rounding, not a systematic error. The same class of bug is already
recorded here at 2.5px, where it *did* put a chip corner over a click target.

- Both halves had to move: `SC_PIN_ICON` is **18**, and
  **`.sc-map-pin .sc-map-pin-ico` carries TWO classes** so it out-specifies
  `.cal-ico` and the number is enforced rather than merely stated.
- The chrome term now over-reserves by ~2px, which is the SAFE direction — the same
  call `scLabelW` already makes.
- **The guard parses the rule out of styles.css** and asserts its width, height and
  flex-basis all equal `SC_PIN_ICON`, plus that the selector still carries two
  classes while `.cal-ico` sizes itself. Verified it fails on drift (reverting the
  CSS to 14 gives 3 failures) rather than passing vacuously.

**The list under the map** is the same events in date order, scoped to what is ON
SCREEN — panning and zooming narrow it, which is what makes it a reading of the map
rather than a second copy of the list beside it.

- **⚠ Derived from the SAME in-frame test the pins use** (`inFramePins`, with
  `inFrame` as its length). Two ways of answering "is this one showing" is how a
  list ends up naming an event the map is not drawing. Sorted by the pin's `i` — the
  caller's own order, date-sorted on both surfaces — never by pin position, which
  orders a list of dates by latitude.
- **⚠ Capped at `SC_MAP_LIST_CAP` (40) with a "Show N more", and the cap is
  MEASURED**: the calendar map at a metro with every kind on is **65 pins but 232
  events** — a merged pin is several league nights — and 232 rows is about ten
  screens of page hanging under a 480px map. The header always states the true
  count, so the cap hides nothing it does not name, and the button names the
  REMAINDER ("Show 192 more" beside 40 rows), because "Show all 232" next to 40
  visible rows reads as though 232 more are hidden.
- **⚠ Expanding is NOT reset when the events or the frame change.** Somebody who
  asked for the whole list and then nudged the map has not changed their mind.
- **⚠ No inner scroll.** The finder's map lives inside a scrolling overlay, and a
  scroll box inside a scrolling parent is the peephole the print-proxy dialog had to
  have taken out of it.
- **⚠ `mapIconOf` is declared BELOW the `art` index it closes over.** A `useCallback`
  evaluates its dependency array at its own declaration point, so higher up it is a
  TDZ ReferenceError into the error boundary — the `screenerPayload` trap. Pinned by
  source position in the test.

**What "Whole season" does, since the name only says half of it**: it clears the
focus, so the map re-FITS to everything it holds (not a zoom step — it frames the
pins, which for the circuit is the world) **and drops the local events entirely**,
because `useMapNearbyEvents` is gated on having a focus. Measured: 65 pins / 232
events at a Chicago focus becomes **24 pins / 28 events**, the circuit plus the
shops you follow. That is the right meaning of the word, but it is a bigger action
than "zoom out".

### A map you can SEND — `?scview` and `?cmap` (2026-09-22)

Zaven: *"can we make maps shareable via link? like if i want to share a map at a
zipcode for set champs so someone else can see."* Both maps could be OPENED by
link and neither could be SENT. The finder's Copy link already carried the ZIP,
the distance, the kinds and the date — everything except which VIEW, so a map
link landed the recipient on a list. The calendar's `?cv=map` carried the mode
and nothing else, and that map opens on the whole season: the one thing the
sender was showing was the one thing the URL could not say.

- **The finder: `?scview=map|list`**, written by the Copy link button and read
  by the map toggle. One param, because the rest of that view was already
  shareable. The button reads **"Copy map link"** when the map is what is on
  screen — the link carries the view now, so a button still saying "Copy link"
  beside a map leaves the one person who wants to send it guessing.
  - **⚠ This REVERSES a deliberate call in that file** (*"which way you prefer to
    read results is yours, where the results ARE is what a link is for"*). A map
    is not a rendering preference laid over a list — at a glance it answers which
    of these is worth the drive, which is the whole reason to send one.
- **The calendar: `?cmap=<lat>,<lng>,<zoom>[,<label>]`** plus `cmr` (radius),
  `cms` (scope) and `cmk` (SC / prerelease / locals). So the address bar IS the
  shareable map and the existing "Copy link to this page" needs no second
  control beside it.
  - **⚠ The LABEL is LAST and only the first three fields are split off.** Every
    American city name contains a comma, so anything that splits the whole string
    and takes field 3 truncates "Chicago, IL" to "Chicago".
  - **⚠ Coordinates are the identity; the label is cosmetic and is NEVER
    re-resolved on arrival.** A second geocode could answer differently and move
    the recipient's map off the spot the sender chose, which is the entire
    promise of the link. It is length-capped (48) because it is text off a URL
    rendering into the toolbar and the empty-state line.
  - **⚠ Null Island, a THIRD time.** `Number("")` and `Number(null)` are both 0,
    so a half-written `?cmap` is a perfectly finite point in the Atlantic that
    renders as an ordinary, empty map. Every field must be a number somebody
    actually wrote down — a blank field is a MISSING field.
  - **⚠ All four are written in map mode ONLY and deleted otherwise.** A `cmap`
    left on the URL after switching to List is a stale anchor that does nothing
    where you are and silently repoints the map on the way back — the trap `cm`
    is already guarded against one line above.

**⚠ A POINTED map link is COMPLETE — defaults included.** This shipped broken in
the first cut and only showed up on opening the link AS SOMEBODY ELSE: the
sender was on "All events" (the default, so omitted) and the reader's saved
scope was "Just mine", so a set-champs map at a ZIP reproduced as a map of the
shops THAT READER follows — for most people none. An empty map, at the right
place, with no error and nothing on screen to say a filter had been swapped
underneath it. **"Omit the default" is only safe when the reader's fallback IS
the default**, and here the fallback is the reader's own stored preference.
`cmap` is what separates the two kinds of link and is why this does not make
every map URL long: a map somebody AIMED is the thing that gets sent, so it
carries everything; a bare `?cv=map` (the home tile's own Map button) is "open
MY map", where inheriting your own preferences is right, so it stays short.

**⚠ A LINK MAY CHOOSE FOR YOU, NEVER OVER YOU.** `usePrefWrite` (beside
`useEscToClose`) is the shared hook: a value that arrived from a URL skips its
FIRST localStorage write, so having a look at somebody's shared map cannot
silently repoint the reader's own view / scope / kind defaults from one click on
someone else's link. Their own toggle persists exactly as before. Same rule
`?cv=` already follows against the month-view stamp. The seeded radius was
already safe — only the `<select>`'s own onChange writes `packsink:scRadius`,
which the finder shares.

All four calendar params are registered in **BOTH `dirtyParams` and
`VIEW_OWNED`**, the standing rule whose failure is silent: unregistered, the link
works for the SENDER, who is already there, and resets for everyone they send it
to. Pinned in `test_event_map.mjs` along with the codec's round trip, every Null
Island shape, the comma in a place name, the zoom clamp and the label cap.

### How the finder itself works

`UpcomingSCsBox` (Index.html). ZIP/postal + radius + optional date, three modes: **All / Set Champs / Prereleases**. Reworked 2026-07-30 so **All means literally every Lorcana event RPH lists** — locals, league nights, draft nights — not just the two classified subsets.

- **One table, one query.** All three modes read `lorcana_events` through the `get_nearby_lorcana_events(lat, lng, radius_mi, kind, max_series, max_occurrences)` RPC; a mode is just the `kind` filter. Before, "all" merged two tables client-side, so a mis-classified event could appear in one tab and not the other. `p_kind` is `null` for All.
- **Results are SERIES, not events.** 68% of upcoming events are the same weekly repeating (measured 2026-07-30: 4050 of 5953 in a 3-week window), so Los Angeles at 50mi is ~1.8k rows but only ~58 real listings. The RPC groups and the tile reads "Every Thu 6:00 PM · 4 upcoming ▾", expanding to the individual dates. Grouping server-side is deliberate — client-side would ship a half-MB of near-duplicates to a phone.
- **Series key = store + kind + format + local weekday + local start time.** Explicitly NOT the title: stores stamp the date into it ("7/30/26 Lake Forest Lorcana Core Constructed Thursday"), which would split every weekly into one-offs. A genuine one-off is just a series of length 1. Cadence itself is re-derived client-side from the real dates (`scCadence`) so a biweekly isn't mislabelled weekly; irregular spacing falls back to "N dates".
- **Pins and the modal are per-series / per-occurrence.** `packsink:scPinned` now holds `series_key` strings (was event ids — old numeric pins simply stop matching, which is the intended lapse). The modal takes `{series, occ}`: venue/format/geo from the series, date + entry + capacity + the registration link from the one date clicked.
- **No date ceiling.** The RPC returns everything upcoming; series collapsing is what makes that readable. `p_max_series` caps at 400 listings, `p_max_occurrences` caps each series' expanded date list at 24 (`occurrence_count` stays the true total).
- **Deep links**: `?sczip/scc/scdist/scdate/scmode/scview`. `SC_DEEP_LINKED` gates force-rendering the box when the home panel is hidden — `scmode` was missing from that list until 2026-07-30, and `scview` (list vs map) until 2026-09-22. See "A map you can SEND" above for why the view rides the link at all.
- **`safe_local_ts(ts, tz)`** wraps `at time zone` so one malformed RPH timezone can't fail the whole query.

**Discovery: `scripts/elo/discover_events.py`** (daily, `.github/workflows/discover_scs.yml`). ONE scan of the ~17k-row upcoming index → classifies every event → writes both `lorcana_events` (all kinds) and `set_championships` (SC subset, unchanged, because the Elo pipeline binds to that table). Replaced two full scans of the same index.

- Classification is **imported, not reimplemented**: `is_sc()` from `discover_wu_scs.py`, `classify()` from `discover_prereleases.py`. Everything both reject is `kind='other'`. Those two scripts stay on disk — they own the logic and still work for targeted single-set re-pulls.
- **Gate the prerelease classifier on `via`, never on the returned set name.** `classify()` returns `(None, "name")` for "definitely a prerelease, but I can't tell which set" — the NORMAL case outside a launch window, where `fetch_launch_sets()` is empty so there's no default set. Gating on the name demotes clearly-titled prereleases to `other` (6 live events on 2026-07-30: "Second Chance PreRelease (Sealed)", "Hyperia City PreRelease", …). `set_name` is nullable for exactly this. `discover_prereleases.py`'s own `main()` still has the bug — it only ever hid because `prerelease_events` was written during launch windows and never pruned.
- **RPH's own `event_type` cannot do this job** — it reads `LOCALS` for ~99% of events (1972 of the soonest 1991, measured 2026-07-30). Same for `gameplay_format`: an SC and a league night are both Core Constructed.
- `set_name` stays **NULL for `kind='other'`** unless the title names a set. A Thursday league night belongs to no set and must not claim one.
- **Past events are ARCHIVED, not deleted (migration 121).** `archive_past_events()` copies every already-happened row into `lorcana_events_history` before the sweep touches it, and **the sweep is skipped entirely unless that archive succeeded** — including when the table doesn't exist yet, in which case past rows just accumulate in `lorcana_events`. Delete-then-archive would strand them permanently: RPH's feed is `display_statuses=upcoming`, so nothing can re-pull an event that already happened. This is what makes "every event this store has run" answerable at all — **RPH store tiers score Total Events / Unique Fans / Event Tickets over the four most recent set seasons across EVERY event type**, and `elo_events` can't answer it (it's the curated, SC-shaped, hand-compiled Elo ingest, driven by `season_files/*.xlsx`, not by discovery). `registered_user_count` IS the Event Tickets metric — but it's frozen at the last pull that saw the event listed, i.e. roughly the day before, so treat it as a floor, not a final count. **It does not backfill** what earlier sweeps already deleted; recovering that depends on whether RPH will serve past events at all (`scripts/elo/probe_rph_history.py`, read-only, must run somewhere that can reach `api.ravensburgerplay.com`). `HISTORY_COLS` in the script and the column list in migration 121 are a straight copy — add to one without the other and the archive silently drops the column. **The archive is INSERT-ONLY** (`resolution=ignore-duplicates`, 2026-10-06): a past row sits in `lorcana_events` for 30 days and used to be re-merged daily, over the `display_status` the store-history top-up had corrected. Guarded by `python scripts/elo/test_events_archive.py` (stubbed HTTP, no network): ordering, the skip-on-failure modes, paging, and the column contract.
- **Pruning.** Every upsert stamps `last_seen_at`; after the pull, upcoming rows RPH hasn't listed for `PRUNE_GRACE_HOURS` (36h) are deleted, plus rows older than 30 days. Guarded by `MIN_PULL_ABSOLUTE` (4000) **and** `MIN_PULL_RATIO` (70% of the upcoming rows on file) — a partial pull from a network flake must never mass-delete live events. `--no-prune` skips it entirely. **A count that fails is `None`, never 0** (0 switched the ratio guard off), and skips the prune with a `::warning::`. The two subset tables never pruned, which is why stale SCs accumulated.
- **⚠ Even a COMPLETE pull misses live events, so one miss must never delete one** (2026-09-10). The scan pages by offset through ~21k rows that move while it reads; the three orderings and the name net narrow the gap but don't close it. That night's pull came back without 10 of the 508 upcoming events at tracked stores, and the old prune (delete whatever this run didn't see) had deleted Gemini Games' 9/20 Set Championship, so it never reached Upcoming SCs although RPH listed it. Two fixes, both in `discover_events.py`: the 36h grace (two daily misses in a row, with room for cron to run late), and **`add_tracked_store_feeds()`**, which folds each tracked store's own upcoming feed into the scan before anything is classified, upserted or pruned. It reads both store-filter spellings and re-checks `store.id`, through `scrape_store_history.fetch_store_feed`. The feeds are a supplement, never a gate: an unreadable store list or feed leaves the scan's rows as they were, with a `::warning::` once more than half the feeds fail. Guarded by `python scripts/elo/test_events_archive.py`.
