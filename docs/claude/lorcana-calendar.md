# Lorcana Calendar (`/calendar` + home panel) — 2026-09-12

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**It is the "Lorcana Calendar" everywhere a user reads it** — the h1, the home panel,
the layout editor, the `.ics` name and the exported picture. It shipped as that,
was renamed "Almanac" on 2026-09-14, and was renamed BACK the same day (Zaven: *"I
dont like almanac, lets call it Lorcana Calendar again, but keep the font nice"*).
The Cinzel setting is what the flavour was actually buying — Cinzel renders lowercase
as small capitals, so "Lorcana Calendar" reads as a carved masthead either way, and
the plain name says what the page is to somebody who has never seen it.

- **The word "Lorcana" is part of the name, not decoration**, and it is load-bearing
  in the `.ics` `X-WR-CALNAME`, the filename, the `PRODID` and the exported picture's
  title: a file that lands in somebody's calendar next to "Work" and "Family" has to
  say which game it is about.
- **"calendar" is also the generic noun**, and that is fine. "Add to my calendar",
  "Back on your calendar", "Google Calendar ↗" all read correctly, and the personal
  drawer is literally called **My calendar** for that reason.
- **The `/calendar` URL never moved** through either rename. It is in `VIEW_PATHS` and
  `sitemap.xml`, and links exist in the wild. `VIEW_TITLES.calendar` keeps its
  keyword-shaped SEO title ("Lorcana Release & Event Calendar").


"What's coming for the GAME", the sibling of the geo box above: set releases,
product drops not tied to a set, Disney Lorcana Challenge weekends, Challenge
Championship Qualifiers, plus every event at the stores you follow. List view and
month grid, timeline, five filter chips, `.ics` + Google Calendar export.
Guarded by `node scripts/test_calendar.mjs` (507 checks).

- **⚠ The page OPENS ON THE MONTH GRID** (2026-09-21, Zaven), as the home panel
  has since 2026-09-20. Same flip, same trap: `mode` is persisted on every mount,
  so a plain default change reaches NOBODY who has ever opened `/calendar` — the
  home LAYOUT defaults' lesson. `calReadViewPref` is the one-shot stamp
  (`packsink:cal:viewMonth`), and it is **STAMPED rather than coerced** so a later
  deliberate pick of List sticks. **⚠ A `?cv=` link is checked BEFORE the stamp is
  spent**, or sending somebody a list link would permanently cost them the new
  default. Pinned in `test_calendar.mjs` beside the panel's copy — every way this
  fails is silent.
- **Two sources that NEVER mix.** `calendar_events` (migration 139) is curated by
  hand; `lorcana_events` is the live RPH feed and contributes **only** what you
  followed. There are ~17k upcoming events — a month grid carrying every Tuesday
  league night on earth answers no question anybody has.
- **⚠ Set releases are DERIVED from `SET_RELEASE_DATES`, not seeded into the
  table**, and a table row OVERRIDES one on `(set_name, subtitle)`. That gets
  history free and correct (it is the same map the Set EV chart's markers are
  drawn from, so the two can never disagree) while a slipped date stays a one-row
  edit instead of a commit + cache bump + metered deploy. Seeding would fork one
  fact into two stores. **The subtitle spelling IS the merge key** — use
  `SET_RELEASE_LABELS`' exact words (`Prerelease` / `LGS release` / `Retail
  release`) or the row adds a duplicate entry instead of correcting the first.
  A derived row can be corrected but not deleted; that is the documented contract.
- **⚠ Only `kind='set'` rows participate in that merge.** Keying every kind by
  title would silently swallow two genuinely different events sharing a name —
  two stores both running a "Lorcana 2K CCQ" is the ordinary case, and losing one
  reads as the scan having missed it.

### Sets that are announced but not dated (2026-09-14)

Zaven: *"we only have hyperia city, but we should have the future sets too, if even
just estimates on release date now, as they should line up with dlcs a lot."* He is
right about why: the competitive calendar is read AGAINST the rotation — a Challenge
in March is a Cosmic Quest event or it is not — so a season chart that stops at the
one set with a published date answers half the question it exists for.

- **⚠ `UPCOMING_SET_NAMES` is a SEPARATE const from `SET_RELEASE_DATES`, and must
  stay separate.** That map is read by `inferEventSet` (which stamps a set name onto
  every tournament and every graded-sales window), `setDataPartial`, the Set EV
  chart's markers and the Screener's set ordering — every one of which would then be
  quietly attributing REAL rows to a guessed date. Nothing but the calendar reads
  the estimates. This does not weaken the standing "published dates only" rule on
  `SET_RELEASE_DATES`; it is what lets that rule stand.
- **⚠ Every estimated row is LABELLED an estimate wherever it renders**, and that is
  the entire licence for it to exist — a wrong date on a calendar is worse than no
  date, so what makes a guess admissible is saying out loud that it is one.
  `calEstimated(ev)` is the one predicate. `calEventFullLabel` appends
  `" (estimated)"`, which is what carries the word into the **.ics SUMMARY and the
  Google Calendar handoff** — a guess landing in somebody's real calendar arrives
  labelled. A row draws a `.cal-est` chip, the timeline prefixes the DATE with
  "est." (never the title — the title is what an ellipsis eats first) and draws the
  dot HOLLOW, in the DOM and in the canvas export alike.
- **The dates are DERIVED, not typed** (`calendarSetEstimates`), so they re-derive
  the moment a real date is published and a name that already HAS one is skipped
  rather than shadowed. The rule is measured: LGS-to-LGS gaps over the last five
  sets are 98 / 84 / 70 / 91 days, and **every Lorcana set without exception has
  landed on a Friday with wide retail exactly seven days behind**. So it is a
  quarter past the last known LGS date, snapped forward to Friday — an estimate on
  a Tuesday is wrong in a way a reader can see, which would discredit the ones that
  are right. Each anchors on the PREVIOUS estimate, or the whole remaining season
  clusters on one weekend.
- **No prerelease phase.** Guessing the weekend somebody might book travel for is a
  different order of claim from guessing when a box reaches a shelf.
- **`calSetOrdinal` / `calSetOrdinalLabel` give "Set 14"**, derived from position in
  the two consts, so it can never disagree with the order they are already in. It
  answers the one thing a set's NAME does not — whether the Challenge you are
  looking at falls before or after it. `calSetOrdinalLabel` returns **null** when the
  name IS the ordinal: a set whose name has not been announced is carried as
  "Set 17", and "Set 17 · Set 17" was the first cut.
- **⚠ Every date is a plain `"YYYY-MM-DD"` string, never parsed into a local
  `Date`.** `new Date("2026-03-07")` is midnight UTC, i.e. March 6 everywhere west
  of Greenwich — a set release read a day early, invisible on a US dev machine.
  Arithmetic goes through `calAddDays` (UTC frame: no DST, so +1 day can never
  land on the same date twice). A store event uses `calTzYmd` to sit on the day it
  is in **at the store** — 9pm Friday in LA is Friday for the people going.
- **⚠ CCQs cannot be auto-detected, and this was MEASURED** (2026-09-12). The
  `phase_template_group` trick behind Set Championship detection does not work:
  the template two CCQs shared (`7ffe1457…`) turns out to be a generic Swiss
  template covering Set Championships and "Sunday Evening Weekly Play" alike, 10
  of 992 upcoming events sampled. RPH's `event_type` reads LOCALS for ~99%. So
  `scripts/scan_ccq_candidates.py` (daily, in `discover_scs.yml`,
  `continue-on-error`) **proposes rows at `confirmed=false`** and a person rules
  on them in the editor — the `catalog_watch.json` ack shape. **Never let a script
  flip `confirmed`**: a wrong date beside a tournament somebody would travel for
  is the most expensive mistake this calendar can make. Titles that hedge
  ("possible CCQ") are kept but flagged in the note.
- **The personal layer is localStorage first, Supabase when signed in**
  (migration 140, `screener_views` pattern) — signed-out has to keep working, and
  the table is what carries six followed stores from a laptop to a phone. Three
  kinds: `event` (one date), `series` (a recurring slot), `store` (**every event
  at that shop, now and in future** — the ask that made this a table, since it has
  to keep paying out). A followed store is re-queried by `store_id`; a series
  without one resolves only through the event ids captured at pin time, so it goes
  stale rather than vanishing.
- **⚠ The ✚ popover is `position:fixed`, anchored by measurement.** It opens
  inside the Upcoming-events box, whose `.sc-tile` is `overflow:hidden` and whose
  `.sc-list` is `overflow:auto`: an absolute menu is clipped to nothing by the tile
  before it reaches the scroller. Measured — the menu's top landed 3px below the
  tile's clip box, so the button lit up and no menu appeared. `useCalPopAnchor`
  uses `useLayoutEffect` (coordinates before paint, or it flashes at the fallback
  position) and a **capturing** scroll listener, or scrolling the inner list
  leaves the menu hanging over the page. Same lesson as `.gc-caps-tip`.
- **⚠ `.ics` `DTEND` is EXCLUSIVE**: a one-day release on the 13th ends on the
  14th. Emit the same date for both and Google renders it while Apple Calendar
  silently drops the event. Folding is at 75 **octets**, not characters, and a
  fold splitting a multi-byte character makes the whole file unreadable in Outlook
  rather than merely ugly. Both pinned by the test, along with escaping order
  (backslash first, or every comma double-escapes).
- **⚠ An empty calendar is NORMAL, not a bug** — sets ship roughly quarterly, so
  between a retail release and the next announcement there is genuinely nothing
  ahead, for weeks. Both surfaces refuse to go blank: the page has a **Show past**
  toggle, and the home panel falls back to the last two things that happened
  ("Attack of the Vine! · retail release · 7 wk ago"). A box that blanks for a
  month reads as broken and earns a Hide.
- **⚠ A month cell draws `CAL_CELL_MAX` (3) events, and ONE FEWER when it also has to
  draw a "+N"** (2026-09-15). In the rail a cell is ~44px wide, which holds three dots OR two
  dots and an overflow marker, never both — and a CSS grid row takes the height of its
  tallest cell, so one busy day inflated its whole week. Sep 19 carries four events and was
  doing exactly that. The dots also lay out ACROSS in compact mode, not down, for the same
  reason. Every week measures 34px now.
- **A month cell labels a set release by its PHASE, not its name** (`calChipLabel`).
  A set puts two or three dates in one month all carrying the same title, so
  "Attack of the Vine!" twice a week apart is two identical chips distinguishing
  nothing; "LGS release" / "Retail release" is what you opened a month view to
  read. Everything else keeps its title.
- **The countdown takes the EVENT, not a date**, because "now" has to mean *in
  progress*: day 2 of a three-day championship started yesterday. A start-date-only
  version labelled every 2023 set release **"NOW"** — it shipped into a screenshot.
- URL params `ck` / `cv` / `cm` (chips / list-vs-month / which month), registered in
  BOTH `dirtyParams` and `VIEW_OWNED.calendar` per the standing rule, written with
  `replaceState` (a filter is not a page).
### Where the curated data comes from

- **The 2026-27 season ("Season of Villainy") is seeded by migration 141** — 14
  CCQs and 17 DLCs — from the **Lorcana Fandom wiki's Competitive Season page**,
  which is the only public list of a whole season. Ravensburger announces DLCs
  piecemeal, and **most of these CCQs never appear on RPH at all** (checked:
  White Rabbit, CCS Raleigh, Senigallia, Osaka, RareHunter all return nothing
  from `lorcana_events`), so the wiki is genuinely additive rather than a
  convenience. Three entries that DO overlap were cross-checked and matched to
  the day (D23 Aug 15, Woodzshack Aug 22, Brainwash Cards Sep 19).
- **⚠ `lorcana.fandom.com` 403s both curl and WebFetch, but `api.php` answers
  200.** Read it as `api.php?action=parse&page=<Page>&prop=wikitext&format=json`.
  Same shape of workaround as the lorcanaplayer.com/Jetpack-mirror trick.
- **⚠ The wiki's DLC table has its Players and "Sets Legal" columns transposed**
  (DLC Bangkok's player count reads "Fabled-Hyperia City"). Only NAME and DATE
  are safe to take from it.
- **Everything wiki-sourced carries `source='wiki-2026-27'` and a note saying so**,
  because fan-maintained is a starting point, not an authority. That is the handle
  for replacing a date once the official one exists.
- **`scripts/link_calendar_events.py` is the "add the links as we get them" half.**
  It matches curated rows against `lorcana_events` and attaches the real RPH
  `event_id` + registration `url`. **It only ever ADDS** — a row with a `url` or
  `event_id` is skipped, so a hand-typed link can never be overwritten — and it
  **refuses ambiguity**: a wrong link sends somebody to register for a different
  shop's tournament, so two candidates with equal evidence are both dropped.
  Matching is DATE first (±1 day) and distinctive words second, which is why the
  word test can afford to be loose. `--self-test` (12 pinned pairs, runs before
  any live work) guards the two failure shapes: run-together store names
  (`Woodzshacktcg`, `MalmoGameWeek`) and same-circuit cities that share every
  other word (Brisbane vs Tokyo CCQ must NOT link).
- **fanfinity links are NOT automatable** — no feed, and the slugs aren't
  derivable from an event name. Those are typed into the editor.
- **Set rotation for the season, from the wiki's "Sets Legal" column**: Attack of
  the Vine! → **Hyperia City** → **Into the Inkdark** → **Cosmic Quest**.
  Hyperia City's **prerelease weekend is Fri 2026-10-16 – Sun 2026-10-18**, derived
  from our own feed (1,628 listings: 349 / 588 / 368, tailing to 55 on the Monday)
  and seeded by 141. **Its LGS and retail dates are published nowhere** — type them
  in when they are, never infer them.

### Region, the map, and what a set release is called

- **Region filter** (`?cr=`, `packsink:cal:region`) groups countries rather than
  listing them: the competitive calendar is 17 Challenges across four continents
  and a 30-entry country picker is a worse version of the same question.
  **⚠ An ungeocoded row falls into "Elsewhere", never out of the list** — dropping
  unknowns would make a row we simply have not placed yet invisible everywhere.
  Counts are computed BEFORE the region filter, or every option reads (0) once
  you have narrowed by one.
- **⚠ A set event is named by BOTH halves — "Hyperia City Prerelease".**
  `calEventTitle` is the one accessor and it feeds list, grid, modal, `.ics` and
  the Google handoff. Two opposite failures both shipped: the title alone gives a
  month two identical "Attack of the Vine!" chips a week apart, and the phase
  alone gives a cell reading "Prerelease", which says something is happening
  without saying what. `title`/`subtitle` stay separate in the DATA because they
  are the merge key against `SET_RELEASE_DATES`; this is display only, and
  `calEventSubtitle` returns null for set rows so the phase is not printed twice.
- **⚠ A STORE event is named by its STORE, and its own name is the second line**
  (2026-09-12, Zaven) — the opposite way round from how RPH stores it.
  "Core Constructed" is what Dice Dojo calls its Thursday night and what a dozen
  other shops call theirs, so on a calendar you built by FOLLOWING STORES the
  event name identifies nothing: *"I can't tell it's Dice Dojo without clicking
  on it."* The store is the half that answers which row is yours, so it takes the
  full-width line and the event name takes the muted one under it — list row,
  home panel, modal and `.ics` SUMMARY alike. It now matches the shape the event
  finder's `.sc-tile` has always used.
  - **It is a DISPLAY swap and has to stay one.** `ev.subtitle` is still the
    store name in the data, because that is what the scout hand-off reads out of
    a calendar entry.
  - **`calStoreEventName` trims the store back off the event name.** RPH names
    carry it about as often as not ("Liga Donnerstag Ravensburger Store Wien",
    "DemonicalTCG Lorcana Free Play"), and the store printed twice down two
    stacked lines reads as a bug. Prefix or suffix, case-insensitive, separator
    goes with it; a name that is only the store leaves no second line at all.
  - **A month chip carries the PAIR on its one line, store first** — so the store
    is the half that survives the ellipsis in a 131px cell, and a day holding two
    events at one shop is still two distinguishable chips where there is room.
    **Store kind only**: a curated row's subtitle is its category ("Challenge
    Championship Qualifier"), which only repeats what the kind icon beside it
    already says. The cell cannot take two lines — three two-line chips need
    ~105px against its 86px — so the tooltip carries the full pair instead.
  - **`calEventFullLabel` is the one-line form**, and everything that has to name
    an event in one line uses it: the `.ics` SUMMARY, the Google handoff, the
    month tooltip, the `.ics` filename, and the saved/hidden lists under "My
    stores + saved events". Four separate joins was four chances to drift.
- **The mini map is OpenStreetMap tiles as plain `<img>`** — no library, no
  script, no cookie, nobody profiling a reader for looking at where a tournament
  is. `osmTileLayout` is Web-Mercator and returns the covering tiles plus the pin;
  **x WRAPS at the antimeridian** (a box straddling it must fetch from the other
  edge of the world) and y is clamped. It cost a line in `privacy.html`, the
  attribution OSM's tile policy requires — that credit is not decoration, don't
  remove it — and **`tile.openstreetmap.org` in BOTH `img-src` AND `connect-src`,
  in both copies of the CSP in `_headers`**. It shipped with the img-src half
  only, which reads as working: a first load has no service worker, so the map
  renders, and `_headers` does not apply on the dev server either. On every
  RELOAD the SW re-fetches the tile through `fetch()` — that is **`connect-src`,
  not `img-src`** — the block makes `fetch` reject, sw.js's image branch
  `.catch(() => cached)` hands `respondWith` an `undefined` for a tile it has
  never cached, and the map goes blank. The rule is general (every cross-origin
  img/font/style host needs the connect-src half, because the SW re-fetches all
  of them); guarded by `node scripts/test_csp_headers.mjs`.
  Curated rows carry **city-level** coordinates (a DLC is announced months before
  a venue exists); store events carry the venue's own, from `lorcana_events`.
- **A set event lists what comes out that day**, matched on sealed-product NAME
  and not `set_id`: an unreleased set has no row in `sets` yet — Hyperia City had
  none while its six products were already listed — so the id join would find
  nothing exactly when this is most interesting. Cases are filtered out; they are
  a distributor SKU, not a thing a player walks out with.
- **A prerelease offers "Find a prerelease near you"**, which opens the finder
  overlay already in that mode — see the Upcoming-events finder section for why
  that is an overlay and not a second box beside the calendar. There is also a
  plain **"Near me"** control in the page header and a fourth tool button on the
  home panel.

### What each kind LOOKS like — one icon per kind of THING, not per chip

The five `CALENDAR_KINDS` are FILTER categories, and two of them cover several
genuinely different events. Drawing one glyph per category is what put a Set
Championship and a Tuesday league night behind the same little shopfront, and all
three of a set's dates behind the same booster pack (Zaven, 2026-09-12). So the
icon is resolved from the EVENT — `calendarEventIcon(ev, artIndex)` returns
`{icon, hue, img}` and `CalendarKindDot` draws it, glyph underneath and image over
the top, so a 404 or a blocked host degrades to the drawn icon rather than a gap.

| event | icon |
|---|---|
| set · Prerelease / LGS / Retail | `sparkle` / `box` / `cart`, accent gold |
| product | `gift` + the product's own photo |
| DLC | the official **Challenge badge** (a shield) |
| CCQ | the official **Lorcana hex sigil** (a hexagon) |
| store · sc / prerelease / other | `trophy` / `sparkle` / `store`, all in the store green |

- **⚠ A set date resolves NO automatic photo any more.** All three phases matched
  the same booster pack, which sat ON TOP of the glyph and made them identical
  again however different the glyphs were — and a pack photo in a 13px box is a
  brown smear. `CAL_ART_PREF` / `calendarArtIndex` still exist and still serve
  PRODUCT rows, where there is one product per row and the photo IS the thing.
- **The set's own LOGO moved to the detail modal**, which has 56px of height to
  read a wordmark in. See "Official Lorcana brand art".
- **This supersedes the old note here** reasoning that Challenge and championship
  marks could never appear because they are Disney's and Ravensburger's. Those
  marks are in Ravensburger's own published brand bundle. The disclaimer is about
  affiliation; using a brand's published assets to label that brand's own events
  is not a claim of affiliation.
- **⚠ The DLC/CCQ pair is a SHIELD against a HEXAGON, and that is the point.** The
  obvious pairing — the filled Challenge badge against the bundle's outline
  version of the same badge — was baked and thrown away twice: two shields
  differing only by a gold frame is unreadable at 13px, which is the exact
  complaint this work exists to fix, AND the outline version is white on
  transparency, invisible on all four light themes. The contact sheet caught the
  second one.
- **A curated `image_url` still wins over everything** (migration 145). It is the
  only way to correct a wrong automatic match, and a wrong picture is worse than
  no picture.
  - **⚠ Its host must be in the CSP `img-src` in BOTH copies of the policy in
    `_headers`**, or the image is blocked with no visible error — the glyph shows
    and everything looks deliberate. `tcgplayer-cdn.tcgplayer.com` is already
    allowed, which is why the automatic product matches work.
- **`CAL_COL_LADDER` = `[CAL_FULL_COLS, CAL_GEO_COLS, CAL_BASE_COLS]`.** The
  fetch walks down it on 42703 so a schema missing `image_url` cannot also cost
  the geo columns — the failure mode a single "with columns / without columns"
  retry has.
- **`_calPhaseRank` breaks the same-day tie.** Every recent set opens its
  prerelease weekend on the same Friday shops may first sell it, so two rows share
  a day AND a title, and the title tiebreak was a coin flip decided by whether a
  phase came from the const or from `calendar_events`.
- Sizes are set per surface in CSS, not per call site: 13px in a list row and a
  month chip, 18px in the home panel, 22px in the detail modal.

Guarded by `node scripts/test_calendar.mjs`: that no two different things share a
glyph AND a hue, that the store kinds stay one family, that a set date resolves no
photo, and that a curated override still wins.

### Set 14, and products that are not a set

- **`SET_RELEASE_DATES` gained Hyperia City** (`lgs 2026-10-16`, `retail
  2026-10-23`, sourced from lorcanaplayer.com 2026-09-12 — never inferred; the gap
  has moved before, Archazia's Island ran two weeks where every set since has run
  one). This is what makes the retail release appear at all: it was missing
  because the const stopped at Attack of the Vine!, not because of a bug.
  **Deliberately NOT added to `MAINLINE_SETS`** — that drives EV, both sims,
  Playset Cost and the home "newest set", all of which would render an empty set.
  Prestaging is its own decision with its own scheduled review.
- **`PRODUCT_RELEASE_DATES`** derives `kind:'product'` rows the way
  `SET_RELEASE_DATES` derives set rows: quests, gift boxes and starter sets, which
  no feed we read announces. A const rather than seeded table rows, so a date lands
  without a migration. Use the PUBLISHER's US street date — a EU webshop's
  "release" is its own ship date and runs a day or two off.
- **⚠ The product merge is ASYMMETRIC, and both halves have a failure mode.** A
  curated row SUPERSEDES a derived one of the same name (or fixing a date in the
  table leaves the const's copy sitting beside it), while two CURATED rows sharing
  a name both survive (or two years of the same annual "Gift Set" collapse into
  one). The derived list is a fallback for what the table has not been told yet,
  not a peer of it.
- `supabase/146_hyperia_city_dates.sql` only rewrites 141's note on the
  prerelease row, which now says the LGS and retail dates are unpublished. The
  dates themselves stay in `SET_RELEASE_DATES` — putting them in the table too
  would fork one fact into two stores.

### Hiding one event

"Show me European CCQs, except that one." A hide is a fourth
`calendar_subscriptions` kind (migration 144) keyed on the entry's own `id`,
which is stable for all three shapes the calendar renders — a curated uuid,
`ev:<rph id>`, and `set:<Set>:<phase>`.

**⚠ This feature has a known way to go wrong and it is already written down in
this file.** The graded view's per-card Hide was KILLED in 2026-05 because a
hidden thing became invisible with no way back. Three defences, none optional:

1. **A structural bypass** — `calendarApplyHidden` takes the SAVED set and an
   explicitly saved event is never hidden. "Add this to my calendar" is a clearer
   statement of intent than a hide you may not remember making.
2. **Hidden events are LISTED** in "My stores + saved events", dimmed, with an
   un-hide ×, and they count toward the badge. A hide you cannot see is the
   original bug.
3. **It lives behind the ✚ popover** with an undo toast — not a × on a row, which
   is how the graded one collected accidental clicks.

- **⚠ SAVED and HIDDEN are mutually exclusive, and `add()` enforces BOTH
  directions.** Saving retires a hide (defence 1). Hiding retires a save for a
  subtler reason found while testing: without it, hiding something you had saved
  left both rows, the bypass kept it on screen, and **the Hide button silently
  did nothing**. Both halves live in `add()` so every future caller inherits them.
  The bypass is then defence in depth — it only decides if both rows somehow
  coexist (stale storage, a half-synced device), and it decides for showing it.
- Until migration 144 runs, hiding works **per device**: the CHECK constraint
  rejects `kind='hide'` and the remote write fails silently, while localStorage
  keeps it. Same degradation as every other pre-migration state here.
- **⚠ 144 drops the old CHECK by LOOKUP, not by name.** A column CHECK gets an
  auto-generated name; guessing it wrong would leave the old constraint in place,
  rejecting every hide while the migration reported success.

### Per-store event kinds

**A followed shop's weeklies outnumber the events you follow shops FOR by about
ten to one** — Griffonest Games lists 13 locals against 1 Set Championship and 1
prerelease — so a blanket follow buried the SC under six copies of "Weekly Core
Constructed". A follow now carries a subset: **Set Champs / Prereleases /
Locals**, toggled per store in "My stores + saved events".

- Stored in the subscription's `meta.kinds`, matched against `lorcana_events.kind`
  (`sc` / `prerelease` / `other`).
- **⚠ ABSENT means EVERYTHING, and that is what makes it backwards-compatible** —
  every follow made before this shipped has no `meta.kinds` and must keep
  delivering the whole feed. An empty array is treated as unset too. Only a
  deliberate toggle ever writes the array.
- **⚠ An excluded kind FALLS THROUGH to the pinned checks** rather than returning
  false: a series you pinned at that shop, or a single date you saved, is a
  deliberate choice and outranks the blanket filter.
- **An unrecognised kind rides with the catch-all.** RPH only sets those three
  today, but a fourth must not vanish silently — the same thing the feed itself
  does with `kind='other'`.
- `calStoreKindsOf` returns them in CANONICAL order, not stored order, or the
  chips would reorder themselves as you toggle. `other` is last because it is the
  catch-all and the noisy one — the toggle most people want to find.
- **The last active chip can't be switched off** — same invariant as the movers
  chip groups and the calendar's own kind chips. A follow that delivers nothing is
  a confusing way to spell "unfollow", and × is right there.
- **⚠ `updateMeta` computes the merge from `subs`, not inside the setState
  updater.** An updater must be pure and React may call it twice; deriving the
  value there and writing it through would fire the remote call on a value that
  is not necessarily the one that won. It MERGES, so a store's `city`/`state`
  survive a kind toggle.

### The home panel's list pager

- **‹ › step through time in list mode** (Zaven, 2026-09-12) — the panel shows a
  window of the schedule, not just the next few, so "what's after that" needs no
  trip to the page. `calendarPanelWindow` is the pure core, guarded.
- **⚠ Page 0 is anchored on the first UNFINISHED event, not on index 0.** The pool
  is sorted oldest-first and carries years of past set releases, so anchoring on
  the head would open the panel on 2023 the moment past events are in scope. An
  event running right now anchors page 0 — the same in-progress rule the countdown
  uses. Paging backwards walks into the past, which is the list-shaped version of
  the page's "Show past".
- **⚠ Clamp the PAGE, not the start.** Clamping `start` to `length - n` keeps the
  last page full by REPEATING a row you have just scrolled past, so › reads as
  "one row on" rather than "one page on". A short last page is what pagination is
  supposed to look like. The test pins "consecutive pages do not overlap".
- The pager is a **footer, not a heading** — list rows carry their own dates, so it
  only has to say where in time you are; the month view's bar is above because you
  need to know the month before you can read the grid. It is hidden entirely when
  everything already fits: dead arrows are worse than no arrows.
- Changing a filter **resets to page 0** rather than clamping you into wherever the
  shorter list now ends.

### The map's tiles are NOT lazy

**⚠ `loading="lazy"` on the mini-map was a bug, not an optimisation.** The `<img>`s
only exist while the modal is open and are in view the moment they are created, so
lazy buys nothing — and Chrome defers every lazy image while
`document.visibilityState === "hidden"`, which leaves the map permanently blank
with four pending requests and no error anywhere. Caught because the preview pane
was backgrounded; forcing one tile eager loaded it instantly. Same lesson as the
deck quick-add thumbnails, and the same trap the offline-testing note describes.

### Keeping it current

- **`scripts/watch_calendar_sources.py`** is the calendar's catalog-watch: a daily
  sweep (in `catalog-watch.yml`, `if: always()`) that is red ONLY when an event
  has been announced that the calendar does not have. Three sources, because none
  sees everything — **Ravensburger's own Challenge page** (the authority on which
  events are sanctioned, added 2026-09-14), the community season page (the only
  place a whole season is listed at once) and RPH itself for qualifier-shaped
  store titles. Rulings live in `scripts/calendar_watch.json`; an ack may carry
  `until` so it expires and re-alerts. **It never writes to the calendar** —
  publishing stays a person's decision, the same rule as `confirmed`.

### ⚠ disneylorcana.com's qualifier list is SPLIT ACROSS LOCALES (2026-09-14)

`/<locale>/play/lorcana-challenge` heads its list **"North America Challenge
Championship Qualifiers"** on en-US and carries a SECOND list, **"EU & UK
Challenge Championship Qualifiers"**, only on en-GB / de-DE / fr-FR. Neither page
hints the other exists, so reading one locale loses half the season silently —
which is how **CCQ Sevilla** was absent from the calendar entirely. Always read
both. (it-IT is STALE — it still lists June 2026 — so it is not a third locale to
add, it is a trap.) The watcher fetches both and merges.

- **⚠ Dedupe on the REGISTRATION URL, not the name.** The same qualifier is named
  differently on each locale, differently again by the community wiki, and
  differently again by RPH's store listing — "White Rabbit CCQ" / "CCQ Essen
  2026" / "Disney Lorcana: CCQ Essen 2026" are one event whose names share no
  words. The URL is the only key that survives translation. The name fallback is
  **date-guarded** (`already_have`), because a loose name test alone would
  suppress next season's "CCQ Sevilla" while this season's is still in the table.
- **⚠ A scan-derived `location` is the STORE's registered address, not the
  VENUE.** `Charlie's Collectible Show` was on the calendar at **Stone Mountain,
  GA** — its RPH home store — for an event at 3801 Sumner Blvd, **Raleigh NC**. A
  travelling show is wrong by construction, and nothing errors: the row looks
  complete. Check a promoted candidate's city against the organiser's own page.
- **⚠ A wiki stub and a scan candidate for one event both exist, and the PUBLIC
  SEES THE WRONG ONE.** 141 seeded the season by name; `scan_ccq_candidates.py`
  separately proposed the same events off RPH at `confirmed=false`. Unreconciled,
  three qualifiers existed twice — the confirmed stub with no venue and no
  registration link rendering publicly, the unconfirmed row carrying both
  invisible. Migration 150 merged them; when draining the candidate queue, look
  for a same-date stub to delete rather than confirming alongside it.
- **Geocode anything you add** (`country`/`latitude`/`longitude`). 143's pass only
  saw rows that existed then, and an ungeocoded row falls into the region
  filter's **"Elsewhere"** bucket — visible, but not to someone filtering to their
  own region. A set or product release correctly has no country: it is worldwide.
- **⚠ `lorcana.fandom.com` 403s a page fetch but `api.php` answers 200.** Read it
  as `api.php?action=parse&page=<Page>&prop=wikitext&format=json`.
- **⚠ Do NOT send a custom User-Agent to Supabase.** `Mozilla/5.0 (packs.ink
  calendar watch)` returns **401 Unauthorized with a perfectly valid service
  key** — the edge in front of PostgREST rejects the agent string before the key
  is checked. Isolated by sending one request four ways: bare 200, +Accept 200,
  +that UA 401. The watcher therefore gives the wiki its UA and Supabase none.
- **User-facing copy never names where a listing was compiled from.** Readers want
  to know whether a date is firm, not who typed it up; `notes` is displayed in the
  modal, so it says "Announced for the 2026-27 season. Confirm … with the
  organiser" instead.


### Timeline mode - the season on one axis (2026-09-14)

List and Month both answer "what is on this date". Neither answers the question a
competitive season actually raises - **how far apart the Challenges are, and which
regions have a run of them against a four-month drought** - because in a list every
row is one row tall whether the next thing is tomorrow or in June. A third mode
(`?cv=timeline`) draws distance as time. `calendarTimeline()` is the pure core,
`CalendarTimelineView` the render; guarded by `node scripts/test_calendar.mjs`.

- **The default is ONE PACKED TRACK, not one row per region** - see "Region rows
  are a PICK, not the layout" below, which is where that decision and its
  failure modes live. (This originally read "lanes are `CALENDAR_REGIONS`", and
  that swimlane default is exactly what the section replaced.)
- **Positions are FRACTIONS of the window (0..1), never pixels**, the same rule the
  pin board's placements follow - the layout has to hold at the 1120px floor and at
  2400px, and the component only ever multiplies by 100 and writes a `%`.
- **⚠ `CAL_TL_MIN_PX` is inline-styled onto the chart from JS, not set in
  styles.css.** The label de-collision is measured against it, so a second copy of
  the number in the stylesheet is how the packing and the thing being packed
  quietly stop agreeing. Same for `CAL_TL_LABEL_PX` and `.cal-tl-label`'s width.
- **⚠ A right-anchored label is drawn BACKWARDS from its marker**, so `_calTlStack`
  has to reserve *that* span. Reserving forwards for both leaves a label-wide hole
  to the left of every right-anchored label that an earlier title is then free to
  be drawn into - two names on top of each other, at the one end of the chart with
  no room to notice. Anchoring at all is the `.scanner-qa-rowinfo` lesson on a
  horizontal axis: a label past the right edge is simply gone.
- **⚠ The label stack starts ABOVE the rail** (`CAL_TL_RAIL_H`). Offsetting row 0
  from zero puts the titles on top of the dots, the span bars and the gap chips
  they describe, and it looks deliberate.
- **⚠ There are NO gap chips any more** (removed 2026-09-23, Zaven: "remove the xd
  between events"). The timeline used to print "82d" on the rail between markers;
  the axis spacing already says it. `calendarTimeline` no longer computes `gaps`,
  and `test_calendar.mjs` fails if `cal-tl-gap` or `lane.gaps` reappears.
- **⚠ Sets and products are not in a PLACE**, so they get a release rail of their
  own under the lanes - which is also what lets the lanes read as "where you would
  travel to". Their `country` is null, so a lane assignment that only asks
  `calRegionOf` files every release under **Elsewhere**, which is both wrong and
  the one lane nobody would think to look in.
- **A set release is projected UP through every lane** (`seasons`), so a Challenge
  can be read as "that one is in the Hyperia City season". Without it the release
  rail is a second list that happens to sit underneath rather than the context for
  the first. **One line per SET, never per phase** - a set puts two or three dates
  in the window a week apart, and three lines that close together is a smear; the
  prerelease is skipped so the line lands on the LGS date, when the set is
  generally on sale.
- **Store events get one lane per SHOP, and only the SC and the prerelease in it
  are labelled** - see "Your local shops are LANES" below, which is where that
  rule and its failure modes live. (This originally read "unlabelled ticks in a
  lane of their own", and that lane-level answer is the thing that section
  replaced.)
- **Sharing is the LINK, not a picture**, and that is principled rather than a
  shortcut: `?cv=timeline` + `?cm=` + `?ck=` + `?cr=` already reproduce exactly what
  the sender saw, and a live link picks up a corrected date where a rendered PNG
  freezes the sender's copy - the same reasoning `?g=` carries for being identity
  only. **⚠ `cm` had to start being written for timeline as well as month**, or a
  shared link silently snaps back to today.
- **`.cal-view--wide` (1260px) applies in timeline mode only.** 1224px of chart
  (104 gutter + 1120 track) fits the 1300px body's content box, so a desktop sees
  the whole season at once and anything narrower scrolls sideways - which is the
  natural gesture here, with the lane names `position:sticky` and opaque
  (`--bg-modal`, per the Screener's sticky-NAME rule; `--bg-card` is translucent in
  the dark themes and would let the months show through).

### Region rows are a PICK, not the layout (2026-09-14)

Zaven, on the first cut: *"the region rows, I dont want to just copy the layout
from that tweet we saw."* Correct, and the reason is structural rather than a
matter of taste. **Five fixed swimlanes is the shape a global announcement
graphic uses, because it is addressing five continents at once and knows nothing
about any of its readers.** This site knows where you are: the region CHIPS in
the filter row already ask that question, with live counts, so lanes asking it
again is the same control drawn twice - and two of the five (Latin America,
Elsewhere) are near-empty all season, spending a third of the chart's height
saying nothing.

- **Packing is the default**: events sort by date and stack into as many rows as
  they need, so **the row COUNT is the density** and an empty vertical band across
  the whole track is the drought. That reads the gaps BETTER than five lanes you
  have to scan in parallel, and narrowing to one region re-packs for that region.
- **⚠ But a DLC and a CCQ are NOT one track** (2026-09-14, Zaven: *"break up DLC
  and CCQ sections, not all in challenges"*). `CAL_TL_CIRCUIT_KINDS` makes packed
  mode one lane PER KIND, keyed on the event's own `kind`, labelled from
  `CAL_TL_KIND_LANES` (**Challenges** / **Qualifiers** — the full word, because a
  lane name is structural where a chip is an abbreviation you say out loud). A
  championship weekend you travel to and the qualifier that earns the invite are
  different decisions, and the number that matters — *how long until the next
  Challenge* — is hidden by a CCQ three weeks earlier when the two share a lane.
  It also made the chart SHORTER: one mixed lane stacked to the depth of the
  worst cluster in either, where two lanes each stack to their own.
- **An unrecognised kind gets a lane of its own** rather than being folded into
  the Challenges, and `CAL_TL_GROUP_OF` still files it in the circuit block by
  elimination — so a kind added later lands in the right place with nobody
  remembering to list it.
- **⚠ The circuit is the one lane that is NEVER row-capped.** `CAL_TL_STORE_ROWS`
  caps the personal lanes because an SC cluster would stack twenty rows deep on
  one weekend; the circuit is the content, and capping it would demote the back
  half of a busy month to unlabelled dots - exactly the information the chart
  exists to carry. Pinned in both modes by the test.
- **Region rows stay REACHABLE** as `?cg=region` (a Packed / By region control in
  the timeline bar, `packsink:cal:group`). Comparing two regions' runs against
  each other is a real question; it is just not the one most readers arrive with,
  and an empty region lane is not rendered at all, so even that mode is not the
  graphic's fixed five.
- **⚠ Only a real region lane offers itself as a filter.** "Challenges" is every
  region at once, so clicking it could only mean "all", which is where you
  already are.
- **⚠ `CALENDAR_REGIONS` is the CIRCUIT's regions, not a continent map**
  (2026-09-14, Zaven: *"those 7 are the actual regions of events, each feed into
  their own championship"*). North America · Europe · Asia · Japan · China ·
  Oceania · Brazil · Latin America · Elsewhere. Each runs its own Challenge season
  and feeds its own Continental Championship, so "which region" is a competitive
  fact about where a winner goes next — not geography. Folded in, Japan's,
  China's, Oceania's and Brazil's runs were each invisible as a group to exactly
  the readers most likely to want them.
  - **⚠ A finer taxonomy loses nothing, and that is what makes it safe — so there
    is NO combine/split toggle.** The chips are a multi-select, so Asia + Japan +
    China + Oceania reproduces the old "Asia-Pacific" exactly, while a coarse
    bucket could never be taken apart. A second control answering the question the
    chips already answer is the thing this page just had removed from it.
  - **⚠ Keys are NARROWED, never renamed.** `apac` still parses (Asia without
    Japan, China or Oceania) and so does `latam` (without Brazil). A renamed key
    parses to nothing, and `calRegionSet` hands back "everywhere" on an empty
    parse — so a shared link would silently WIDEN to the whole world rather than
    fail. Narrowing is the lesser lie, and this shipped the same week.
  - **An empty region gets no lane and a dimmed `(0)` chip.** That is what makes
    nine regions safe on a chart: Brazil and China have no events this season, and
    a lane of empty track each is the very complaint the packed default answers.
    "Latin America 0" is kept deliberately — it says the season has nothing there,
    where dropping it would file a Buenos Aires event under "Elsewhere", which is
    the bucket for a row we have not PLACED.
- **⚠ A RELEASE IS IN NO PLACE, so `calRegionless` makes it match every region.**
  A set comes out worldwide; narrowing to Europe and losing the Hyperia City dates
  is the page disagreeing with itself, because reading the Challenges AGAINST the
  rotation is most of what the region axis is for. It also keeps "Elsewhere"
  meaning "not placed yet" instead of filling with eleven rows that were never
  anywhere (it read 11 before this, 0 after). **They are excluded from the region
  COUNTS for the same reason**: adding them to all nine makes every chip nine
  bigger and none of them comparable, which is the only thing a count is for. The
  timeline never needed either half — a release goes on its own rail whatever the
  grouping.
- **The grouping NEVER reaches the personal lanes or the release rail** - a shop
  is a subject rather than a category, and a release is in no place at all. The
  test pins that for both modes.
- **Three blocks, ruled apart: the circuit -> yours -> Releases** (`lane.group`,
  `lane.first`). They separate by SPACE (`margin-top`), not by a heavier border:
  a 2px grey line across the chart read as a scar. The month bands run
  continuously through the gap because the grid is one absolute overlay.
- **⚠ A set's PRERELEASE never reaches the timeline** (`calTimelineSkip`,
  2026-09-14 — Zaven, on Hyperia City: *"we dont need 3 dots, just lgs and
  retail"*). Every recent set opens its prerelease weekend on the SAME Friday its
  LGS release lands, so the rail drew three labels for one set with two of them on
  the identical date — a stack of near-duplicates exactly where the chart is trying
  to say "the set arrives here". It still renders in List, Month, the detail modal
  and the .ics, where sharing a day with another row costs nothing. A STORE
  prerelease is a different thing and is untouched.
- **A season boundary carries a DIAMOND in the axis row** (`.cal-tl-season > i`,
  and the same shape in the canvas painter). The line itself stays faint — it is
  context behind the events, not an event — but a 1px hairline whose only
  affordance was a `title` was a marker nobody could find. **⚠ The fade lives on a
  `::before`, never on the span**: `opacity` on the parent multiplies down, so the
  diamond could never be brighter than the hairline it marks. Its tooltip names
  the set AND its ordinal ("Set 14 · Hyperia City").

### The chart's typography (2026-09-14)

Same day, same ask: *"work on the formatting and font."* Everything in the chart
was within a pixel of everything else - 10px grey caps for the row names, 10px
grey caps for the months, 11px for the titles - so nothing said which was
structure and which was content.

- **⚠ A STRUCTURAL row name is set in Cinzel**, the site's own display face, used
  nowhere else in this chart. That is what separates "Challenges" and "Releases"
  (categories the chart invented) from a shop's name, which is a proper noun
  somebody chose and stays in the body face and the store green. The counts
  beside them stay body-face and tabular - a Cinzel numeral beside a Cinzel word
  reads as part of the title rather than as a tally.
- **Three tiers now, and they are meant to be unequal**: the title is CONTENT and
  leads (11.5px/700), the date is DATA and recedes (9.5px/500, tabular), the axis
  and row names are STRUCTURE and are quieter than both (600).
  **⚠ Those numbers were retuned on 2026-09-14 and the first set was a lie** — they
  were picked while the font request loaded no weight above 600, so 800 and 600
  rendered as the same face and the "three tiers" were two. See "Fonts — ask for a
  RANGE". With real weights loaded the old numbers over-fired, so each dropped one
  step. Anything that touches these should check what is actually LOADED first.
- **The year turn is the one real event on the axis** and was the twelfth
  identical grey word in the row; `.cal-tl-mon--year` gives it the text colour.
- **A three-day Challenge draws as a BAR and a one-day CCQ as a dot**, so the
  shape says how long it runs before the label does. The bar is deliberately
  flatter than the dot is round - a fat lozenge just reads as a bigger dot.
- **⚠ On the RELEASE rail the QUALIFIER moves to the SECOND line**
  (`calTlLabelParts`), and that is the difference between reading the rail and not.
  `calEventTitle` joins set and phase into "Hyperia City LGS release" - 24
  characters into a 140px label, so a set with three dates rendered as "Hyperia
  City LGS rel", "Hyperia City Retail r" and "Hyperia City Beast G": three
  near-identical clipped strings whose clipped-off half was the only thing telling
  them apart. **PRODUCTS get the same rule** (2026-09-14): a product's qualifier is
  its own `subtitle`, or whatever follows a colon in its name ("Illumineer's Quest:
  The Great Hunny Rescue"). A name with **neither keeps its ellipsis** - inventing a
  break point would cut a word where the name does not have one, which is the thing
  this rule exists to stop.
- **⚠ The DATE is its own field (`{title, qual, range}`), never concatenated into
  the qualifier** - that is what lets both renderers PIN it and shrink the qualifier
  instead. As one ellipsing string it was the date that got eaten ("The Great Hunny
  Rescue · O…"), and the date is the one thing a timeline label cannot do without.
  The DOM makes the sub-line a flex row with `.cal-tl-label-q` shrinking and
  `.cal-tl-label-r` fixed; the canvas measures the tail first and clips only the
  qualifier into what is left.
- **⚠ `text-overflow:ellipsis` does NOT reach an anonymous flex item.**
  `.cal-tl-label-t` is a flex row (glyph + text), so the title hard-cut mid-word with
  **no ellipsis at all** - which reads as a broken label rather than a truncated one,
  and is why the release rail looked wrong even where truncating was the right answer.
  The text lives in its own `.cal-tl-label-n` span now, and that span carries the
  ellipsis. Any future flex label needs the same wrapper.
- **⚠ `CAL_TL_LABEL_PX` (140) and `.cal-tl-label`'s width are ONE number in two
  files** - the packing is measured against it. It grew from 126 with this pass,
  which also moved a test fixture: a date chosen to anchor LEFT at 126px anchors
  right at 140px, and the pair then tests nothing.
- **The canvas export is set in the SAME TWO FACES as the screen** - Nunito Sans for
  the body, Cinzel for the title and the structural row names - and loads every
  (weight, size) it paints up front, best-effort. A canvas falls back to the generic
  family silently when a face is not loaded AT THE WEIGHT ASKED FOR, so the picture
  would otherwise be visibly a different document from the screen it was copied off.
  Its body stack was the OS UI font until 2026-09-14, which was exactly that bug in
  its other half.
- **⚠ A lane name's colour is the CIRCUIT's, not the rail's.** The canvas keyed it on
  `lane.below`, which is inverted: the picture lit RELEASES up in gold and greyed out
  the one lane the chart is about. It reads `lane.group === "circuit"` now, matching
  `.cal-tl-lane--circuit` on screen. Nothing tests the canvas, so compare the two by
  eye whenever either side's colours move.
- **The bar states a WINDOW, so it uses `calMonthLabelShort`** - "Sep 2026 - Aug
  2027". The full form wrapped to three lines at 390px and out-weighed the chart
  under it at every width. The EXPORT header keeps the long form: that is a
  document, and a picture with the year abbreviated is one nobody can date.
  **⚠ Even short, it takes its OWN LINE below 700px.** It is the one thing in the
  bar that cannot shrink further, and squeezed between the steppers and three
  controls flex crushed it to 37px and wrapped it into a 100px three-line stack.
  `.cal-tl-bar` wraps and the label is `order:-1; flex:1 0 100%` there.
- The gutter went 104px -> 120px (96px on mobile) to hold a Cinzel "CHALLENGES";
  the chart is 1240px against `.cal-view--wide`'s 1260px, so it still fits.
  **⚠ At 96px that word has exactly 65px and wants 65** — measured at 390px it
  ellipsed to "CHALLENG…" one pixel short, and the mobile `gap:4px` is what gives
  it back. Don't restore the 6px gap without re-measuring.

### The filter row, and what it can now say (2026-09-14)

The toolbar was one line holding the kind chips, a region `<select>` and the mode
toggle. Row one now chooses the CHART; **row two (`.cal-filters2`) chooses what is
on it** — search, regions, and the timeline's window length. Splitting them is what
stopped a single row wrapping into a pile once the third and fourth control landed.

- **⚠ `?cr=` holds a SET now, as a csv** — "how did Europe and North America
  compare" is a question the timeline's lanes invite and a one-of-N picker cannot
  ask. `calRegionSet` parses it; **a bare `na` and a bare `all` still parse exactly
  as before**, so every stored pref and every link in the wild keeps working. The
  `<select>` is gone: one control that can express the set, rather than a picker
  that can only ever say one thing. `calNormRegionPref` sorts to canonical order,
  or two identical filters produce two different URLs.
- **`?cq=` is one search box across all three modes.** It reads what a person
  searches BY — the name, the place, the note — and never the kind or the date,
  which the chips and the window already answer. **Folded through `searchNorm`**,
  because this season alone holds Düsseldorf, Malmö and Senigallia and nobody types
  those with the diacritics. `useDeferredValue`d, same as the Cards browser.
- **`?cspan=` is 6 / 12 / 24 months**, timeline only. 12 is one competitive season
  and stays the default, so the param is omitted at 12 and the URL stays clean.
- **`?cg=` is `packed` (default) or `region`**, timeline only - see above.
- Counts on both chip rows are computed AFTER the search but BEFORE their own
  dimension, so no chip ever claims rows the page is not showing and no option
  reads (0) purely because you already narrowed by it.

### One chip system, one casing rule (2026-09-14)

Zaven: *"all the text, i dont like the [casing] of it and the stuff like 'My stores +
saved events' — the lack of consistancy in cases. make it more visually astetic."*

- **The page asks three multi-select questions and drew each at its own size.** Kind
  chips were 12px/600/16px-radius, region chips 11px/700/999px, the near chip a
  third — three controls doing one job reading as three unrelated widgets.
  `.cal-chip-filter`, `.cal-region-chip` and `.cal-near-chip` now share one metric
  (5px 10px, 11.5px, 700, 999px), and so do the three segmented groups
  (`.cal-modes`, `.cal-spans`, `.cal-tl-group`). What still DIFFERS is the ON
  state, and that difference is information: a kind chip lights its own hue because
  the hue is the legend for the icon beside it; a region fills solid because
  "where" has no colour of its own.
- **The rule, written down so it stops drifting: a CONTROL is sentence case** (it
  is a phrase addressed to you — "Show past", "By region", "North America"), **and
  a STRUCTURAL label is uppercase with tracking** (it names a part of the chart,
  not a thing you press — a lane, a column head, a day-of-week). Initialisms keep
  their capitals on both sides (DLCs, CCQs, SCs, .ics).
  - **⚠ SUPERSEDED FOR THIS PAGE 2026-09-21** (Zaven: *"make it all caps and match
    the font — same with all text on this page actually, where it makes sense"*).
    The sentence-case half only ever held in the SOURCE: the kind chips, the
    Filters button and the region toggle were already set in **Cinzel**, whose
    lowercase glyphs are drawn as small capitals, so they RENDERED as caps while
    the mode buttons, the near chip, the header actions, Today, the day-of-week
    row and the drawer's chips sat beside them in Nunito sentence case. One row,
    three different-looking widgets. Every control and structural label on
    `/calendar` now shares that face (one rule, declared under `.cal-near-chip` in
    styles.css), which is why **"SCs near me" reads SCS NEAR ME with no
    `text-transform`** — the stutter the lane-label note below worries about is a
    `text-transform:uppercase` problem, and small caps do not have it.
  - **⚠ CONTENT never joins in**, and that half of the old rule stands: event
    titles, a followed shop's name, the lede, the search box and the prose links
    inside sentences all stay in the body face. A shop's name is a proper noun set
    as it is written — the same rule the timeline's lane names follow.
  - **⚠ A NUMBER never joins in either.** A Cinzel numeral beside a Cinzel word
    reads as part of the word rather than as a tally, so every count takes the body
    face back — and that rule has to be declared AFTER the one it is taking it
    from. `.cal-spans` ("6 mo / 12 mo / 24 mo") is two thirds numeral and is left
    out of the Cinzel set entirely.
  - Cinzel's small caps sit wider than Nunito at the same size, so the tightest
    controls give ~1px back. Measured after: no horizontal overflow at 360 / 375 /
    desktop, and "Follow a store" wraps to its own line at 375 rather than pushing
    the row off the edge.
- **"My stores + saved events" is now "My calendar"**, and it moved from a line of
  its own into the END of the filter row. It named two of the four things in the
  drawer (a pinned series and a hidden event are in there too), it was the longest
  label on the page, and a "+" in a control label is punctuation doing a word's
  job. It is also the phrase the ✚ menu already uses, so the two halves of one idea
  share one word. Stranded on its own row it was the only control on the page with
  nothing beside it; its BODY still opens below the whole row, and the wrapper is
  only rendered when open (an empty one kept its 14px margin).
- **⚠ The lane label is "Near me", not "SCs near me"** — a lane name renders
  uppercase, and "SCS NEAR ME" is an initialism the rule turns into a stutter. The
  chip that switches the lane on still says "SCs near me", and the exported
  picture's caption names the radius.
- **"Follow a store" sits beside the "SCs near me" chip** (2026-09-21, Zaven). The
  two are the same question answered opposite ways round — a radius applied once
  against a shop added for good — so as a PAIR they explain each other. It opens
  the same finder `onFindEvents()` the drawer's "Find & follow more stores" opens,
  and the drawer keeps its copy: that is where you go to MANAGE the list, not to
  add to it. **This does not reopen the name-alike problem the header note above
  describes** — that was two controls both called some variant of "near me"; these
  two say different things.
- **The home panel's title is two lines in a 240px rail, on purpose.** "LORCANA
  CALENDAR" does not fit one line beside four tool buttons, and both alternatives
  are worse: wrapping the TOOLS costs more height than the second line, and
  shortening the title here would have the home page and the page it links to
  calling one thing two names. `line-height:1.1` is what keeps the masthead from
  towering over its siblings' one-line titles.

### Hover tells you the whole event (2026-09-14)

Zaven: *"on home screen calendar, if you hover over event, give the info — same if on
month view."* A month-grid chip is ~130px wide and a home-rail row ~200px, so both
truncate the one thing they exist to say, and the answer was a `title=` — one
unstyled line, after a ~1s delay, that cannot show a countdown, a venue, or the note
saying a date is a guess. `useCalHoverCard` / `CalendarHoverCard` replace it with
what the detail modal opens with, minus the map and the buttons.

- **⚠ MOUSE ONLY.** It fires on `pointerenter` and only for `pointerType === "mouse"`:
  on a touch screen the tap already opens the modal, and a card summoned by a finger
  would flash over the row you just tapped. `@media (hover:none)` hides it as belt
  and braces. Keyboard FOCUS opens it too, instantly — a focus is deliberate where a
  pointer crossing a row is not.
- **⚠ `pointer-events:none` on the card.** It is positioned over a grid of click
  targets, and a tooltip that can swallow the click on the thing it describes is
  worse than no tooltip.
- **⚠ The native `title=` had to GO from the month chip**, or both fire and one of
  them is the single grey line this replaced. `aria-label` carries the name for a
  screen reader, which is what the attribute was really doing.
- Positioned SIDEWAYS first (a rail row and a month cell are both narrow, so the room
  is left or right; a card directly below covers the next week), measured in
  `useLayoutEffect` so it never flashes at its fallback spot.
- **⚠ Only a scroll that can actually MOVE the trigger closes it — "any scroll" was
  the bug** (fixed 2026-09-15, reported as *"it'll pop up and disappear instantly"*).
  The listener is CAPTURING, so it hears every scroll anywhere in the page, and the
  home page's movers marquees **scroll themselves for as long as the tab is open**:
  `.movers-wrap` and `.graded-movers-strip-wrap` each fire a scroll event about every
  60ms, forever. So the card was closed one frame after it opened, every time, on the
  home panel — which is the surface this feature exists for. Measured in the live
  page: `pointerenter` 10290ms, card in 10431ms, card **gone 10504ms**.
  - The handler now ignores a scroll whose target does not `contain` the anchored
    element, which is why `hov` carries `el` at all. A document scroll still closes
    (the document contains everything), an ancestor scroll still closes, and a trigger
    that has been unmounted closes. All four verified against the live page.
  - **⚠ It cannot be verified by watching `scrollY`.** A page that is not being
    painted (pane hidden, window behind) still updates the scroll position but stops
    DISPATCHING scroll events, so the fix reads as broken and the bug reads as fixed.
    Dispatch a synthetic `scroll` at a chosen target instead — that is what
    `test_calendar.mjs` pins, and how the four cases above were separated.
- One hook per LIST, not per row, so only one card can ever be open.
- **⚠ In `CalendarMonthView` the hook sits ABOVE the early return** (hook order), and
  in `CalendarPanelList` the card is a SIBLING of the `<ul>` — a `<ul>` may only
  contain `<li>`.

### Same-day repeats collapse to "CCQ ×3" (2026-09-15)

Zaven: *"if multiple of the same event on the same day, can we do like CCQ x3 instead
of 3 logos? and on hover show all."* Sep 19 carried three CCQs and drew three
identical medals down three rows — three logos saying the same word, in the one place
on the site with no room for them. `calCellItems` collapses them to one chip; the
hover card lists every member; clicking expands the group in place.

- **⚠ The grouping key is the ICON, not the KIND, and that is the whole care in it.**
  A set's prerelease and its LGS release **share a Friday on every recent set** and
  draw a sparkle against a box with two different phase words. Keying on kind would
  render them "Release ×2" and delete the phase — which is the entire reason a set
  chip is labelled by phase rather than by name. Different icon, so they stay two
  chips. Verified live on Oct 2026: *Hyperia City Prerelease* and *Hyperia City LGS
  release* remain separate. The key carries kind + glyph + image, so a store SC
  (trophy glyph) never merges with a DLC (the Challenge shield image) either.
- **⚠ Clicking a group EXPANDS it rather than opening an event.** A chip standing for
  three events cannot honestly mean "open the first one". The open set is keyed
  `<date>|<kind>|<icon>|<img>` and cleared when the month changes, or a September key
  would still count as open in October.
- **⚠ `×` is the literal character, never `&times;`.** htm does not decode HTML
  entities in a template, so the first cut rendered `CCQ&times;3` on screen. Caught in
  the browser, not by a test — the DOM said `textContent: "CCQ&times;3"`.
- **⚠ The count has to survive the compact chip's label hide.** The rail cell hides
  `> span:not(.cal-ico)`, which would take the count with it — and the count is the
  entire point of the collapse in a 44px cell. The override is four classes so it wins
  outright rather than on source order.
- The hover card's grouped form takes the CELL's day, not the first event's range: a
  three-day Challenge sitting beside two one-day qualifiers would otherwise head the
  list with the wrong dates.

### A dense cell's count belongs to its MARK, not the day (2026-09-23)

Zaven, on the home rail: three CCQs and one SC drew a **"4" on the CCQ mark** —
the day's TOTAL, pinned to one kind of thing. Each group mark now wears its own
`×N` as a corner pill (`.cal-chip--group > span.cal-chip-x`, four classes so it
beats the dense label-hide), and the cell's `.cal-cell-more` counts only events
that did NOT fit, drawn TOP-LEFT so the two numbers never share a corner.
Measured at 375px: Sep 26 reads CCQ ×2 and SC ×2, two 22px marks, pills clear.

Same review pass added **`?ce=<id>`** — a link to ONE event (Copy link in the
detail modal; registered in `dirtyParams` + `VIEW_OWNED.calendar`). An `ev:<rph
id>` the reader does not follow is fetched directly, since it will never be in
their `all`. The six calendar prefs now write through `usePrefWrite`, so a shared
link no longer repoints the reader's home tile. `useCalDialog` is the one
keyboard contract for the three calendar dialogs (focus in/out, Tab trap, Esc
only for the innermost). ⚠ A store event is SAVED as `"123"` and HIDDEN as
`"ev:123"`; `calSavedRefOf` is the one place that reconciles them.

### The cell's day number stops owning a row (2026-09-15)

Zaven: *"make the logos a tinny bit bigger, and the numbers a lil smaller. use the
space better. currently the row with the date number is unused space. I can't tell
that's a challenge shield on the calendar."*

- The number is **absolute in the top-right corner** (9.5px, was 11px in flow), so the
  events start at the cell's top and the grid gains a chip row. Measured: the first
  chip now sits 4px from the cell top. Only the FIRST chip reserves the number's width
  (`padding-right:20px`), so a long title cannot run under it and the rest keep their
  5px.
- The kind icon goes **13px → 17px**, with the `<svg>` sized to 15px in CSS — `uiIcon()`
  writes width/height ATTRIBUTES at 13, so growing the box alone only adds padding. The
  DLC/CCQ marks are `<img>`s that fill the box, so this is what makes the Challenge
  shield tell itself apart from the qualifier's hexagon.
- **`CAL_CELL_MAX_FULL` (4)** spends the reclaimed row; compact keeps `CAL_CELL_MAX`
  (3), which was measured to the pixel for the week-height fix and is left alone. A
  4-chip cell GROWS (86px → 102px, last chip fully inside) rather than clipping —
  verified, because `.cal-cell` is `overflow:hidden`.
- **⚠ All of this is scoped `.cal-month:not(.cal-month--compact)`.** The rail cell is
  34px tall with icon-only chips; an absolute number and a 20px reservation there would
  undo the tuning the week-height fix depends on.

### Your local shops are LANES, and SCs near you are one more (2026-09-14)

Zaven, correcting an earlier reading of "add local events": *"I dont mean own
event / Just tieing in your local stores on rph / Be that sc s or otherwise /
Mayve you wanna make just a timeline of sc s local to you."* So a personal event
form is NOT what this is; the followed-store layer already had the data and was
drawing it as an anonymous strip of ticks. Two halves:

- **ONE LANE PER SHOP** (`CAL_TL_STORE_PREFIX` + the store id), named by the SHOP
  — read off its own first entry's `subtitle`, the same rule the list rows follow.
  A followed store is a place you drive to, so the whole reason to put it on a
  season chart is to see WHICH shop runs what and when; "My stores" over a row of
  unnamed ticks says only "somebody near me plays on Saturdays", which you knew.
- **`?cn=1` — "SCs near me"**, a lane of Set Championships inside the event
  finder's OWN saved ZIP and radius, at shops you have not followed.

- **⚠ WHETHER AN ITEM GETS A LABEL IS A PER-ITEM QUESTION** (`calTimelineLabels`),
  and that is the whole trick to putting a shop on a season chart. `ticks` used to
  be a per-LANE boolean, which forces a choice between two wrong answers: label
  every store event and the one Set Championship is buried under fifty league
  nights; label none and the Set Championship is gone. The SC and the prerelease
  are named, `rph_kind === "other"` stays a tick. The marker is still there and
  still clickable — only the title is dropped, and a league night's exact date is
  one click away in List, where an event with a time belongs.
- **⚠ Past `CAL_TL_STORE_ROWS` (3) a label DEMOTES to a tick rather than growing
  the lane.** SCs cluster: a whole season's worth lands inside one four-week
  window, so an uncapped near-me lane is a twenty-row stack over one weekend and a
  flat empty band either side of it — unreadable in both directions at once.
  Region lanes are uncapped; a season is ~17 Challenges across five of them, so
  they never come close, and capping one would silently drop a Challenge's name.
- **⚠ A shop you FOLLOW wins over the same shop inside your radius**
  (`calendarMergeStore`, keyed on the RPH event id, the only stable key either
  side carries). Without it one SC draws in two lanes, which reads as a
  duplicate-rows bug rather than as a merge that went wrong. The chip therefore
  counts what the merge ADDED, never what the query returned — "4" beside a lane
  holding 3 is the one thing a chart must never look like.
- **⚠ The near query is bounded to SET CHAMPIONSHIPS on purpose.** It is the ONE
  place the live RPH feed reaches the calendar without a follow, and the standing
  rule is that ~17k upcoming events must never wash into a month grid. An SC
  inside your own radius is a dozen a season, and "where is the season being
  played near me" is a question the followed-store layer cannot answer, because
  you have to already know a shop exists to follow it.
- **It reuses the finder's saved `packsink:scZip` / `scRadius` / `scCountry`
  rather than asking again.** A second postal-code box on a second screen is two
  answers to one question that can then disagree. With no ZIP set, the chip says
  so and opens the finder instead of toggling.
- **A failed geo lookup SAYS so** (`.cal-warn--near`). Silently showing the
  calendar without the shops you asked for is the same shape of lie as a filter
  you cannot see — you would read the season as empty near you.
- **⚠ Past `CAL_TL_MAX_STORE_LANES` (6) the tail rolls into one `Other shops`
  lane.** Six named lanes is already ~300px of chart; somebody following twenty
  shops wants the busiest named, not a wall. Lanes sort busiest-first, so the shop
  you actually go to leads.
- **⚠ A SHOP NAME IS NOT UPPERCASED, and that is width, not taste.** The gutter is
  128px in the DOM and clips at 94px on the canvas: "GRIFFONEST GAMES" at 0.06em
  tracking fits neither and ellipses mid-word into "GRIFFONE… GAMES", which reads
  as a broken label rather than a shop. A region name is a category and keeps its
  caps; a proper noun is set as it is written and gains the ~15% back. The rule
  lives in BOTH renderers, or the picture disagrees with the screen it came from.
  Same reason the near lane is called **"SCs near me"** — named for the chip that
  switched it on, because "Set Champs near me" fits neither gutter.
- **⚠ The DATE belongs in a marker's `aria-label`, not only its `title`.** A shop's
  fourteen league nights carry one name between them, so without it a screen
  reader reads the whole lane as the same control repeated.
- **The near source is NOT a subscription** — nothing is written to
  `calendar_subscriptions`, so there is no migration behind any of this. Following
  a shop is still how you say "this one is mine".

### Export image — drawn, not screenshotted

`buildCalendarTimelineBlob(tl, opts)` paints the chart on a `<canvas>` and hands it
to `deliverImage` (desktop = sync clipboard, touch = share sheet), the same path
every card export takes. **Not html2canvas**, for the documented reason: it paints
whatever `styles.css` the browser happens to hold and the service worker can hold a
stale one, so a CSS fix stays invisible in the export until the SW updates.

- **⚠ It consumes the SAME `calendarTimeline()` object the DOM does**, so the two
  agree on every position by construction rather than by two sets of maths being
  kept in step. That is `drawCardTileCanvas`'s standing contract and the only thing
  that makes "the copied image is what was on screen" true.
- **⚠ The DOM positions a label by its BOTTOM EDGE; canvas positions text by its
  BASELINE.** Porting the DOM's offset straight across drops every label by its own
  descender plus its second line — which printed the date through the dots it
  labels, on every lane, and looked deliberate.
- The picture carries the window's own months in its header and the active filters
  as a subtitle (`filterCaption`), so a shared chart can never be read as the whole
  season.

### Prettier: the month bands are the load-bearing one

Alternating month bands (`.cal-tl-band`, every other column) are the single biggest
readability win on a year-wide axis — gridlines alone leave one undifferentiated
grey field with nothing to track a row across. The today line gained a pip so it
reads as a marker rather than another gridline, and a lane tints on hover.


### ⚠ The season seed is short one Challenge, and five dates are disputed (2026-09-14)

Checked against a published 2026-27 season schedule. Everything in 141 matched to
the day except:

- **DLC Nanjing, 21-22 Nov 2026 is MISSING** - the season's only mainland-China
  Challenge, which is why a community page maintained by English-speaking players
  does not carry it. Staged as `supabase/152_calendar_dlc_nanjing.sql` at
  `confirmed = false`, so it sits in the admin editor to rule on and no visitor is
  shown a date nobody has checked.
- **Five Challenges disagree, and ours are kept.** Bangkok, Singapore, Hong Kong
  and Taipei read Sat-Sun there against Fri-Sun here; Lyon reads Wed 5 - Fri 7 May
  2027 against Fri 7 - Sun 9 May. **Every one of the twelve both sources agree on
  runs Friday to Sunday**, so a Wednesday start is a shape no Challenge in either
  source has and Lyon looks like an error there rather than here. The four Asian
  ones are genuinely ambiguous - a two-day regional weekend is plausible - so they
  stay as seeded. A wrong date on a calendar is worse than no date, and that cuts
  against changing five on an unverifiable source as much as it cuts for it.
- **Set 15/16/17 dates stay out.** That schedule marks Into the Inkdark, Cosmic
  Quest and Set 17 "est." - estimates off the release cadence. `SET_RELEASE_DATES`
  takes published dates only, for the reason already written there: the cadence has
  moved before.
- **⚠ The wiki cannot be re-checked from an agent sandbox** - `lorcana.fandom.com`
  is egress-blocked to both curl and the fetch tool, so `api.php` answers only from
  CI. `scripts/watch_calendar_sources.py` is what sees it daily; its `acks` were
  still empty when this was found, i.e. nothing had been ruled on yet.

### On the home page

- **Default position is the TOP of the RIGHT rail** (Zaven, 2026-09-15; it was
  the top of the LEFT rail from 2026-09-12). **⚠ The rails are not the same
  width — left is 240px, right is 360px (`.home-grid`) — so "which rail" is
  really "does this panel need the extra 120px", and the calendar is the panel
  that does: its rows carry a date, a countdown, a subtitle AND a title.** The
  Toolbox and Set EV went the other way, to the foot of the left rail, for the
  mirror reason. Two mechanisms, because one is not enough: its place in the
  `HOME_PANELS` array covers a browser with no stored layout
  (`defaultHomeLayout` keeps that order), and `HOME_LAYOUT_RAIL_SWAP_KEY` is the
  one-shot stamp for every browser that has one.
  - **⚠ Re-seating is by POSITION as well as column.** A browser that never saw
    `HOME_LAYOUT_CALENDAR_KEY` had the panel APPENDED carrying today's default
    (`right`) — the right COLUMN but the bottom of it — so a column-only move
    leaves it under the collection chart forever. Splice before the first panel
    of the target column, never at index 0: the layout is one flat array across
    all columns, so index 0 may belong to another rail.
  - **⚠ Each move is guarded on the panel still being where the OLD default put
    it**, so a calendar someone dragged to `main` is left alone. `HOME_LAYOUT_CALENDAR_KEY`
    stays in the code — it is a no-op now, but removing a spent stamp re-fires
    nothing and costs nothing to keep.
- **Moving into 240px broke two things, and both were fixed rather than
  accepted** — the reason this is not just a two-line const change:
  - **The Toolbox goes ONE column in a rail** (`.home-left-col .home-toolbox-grid`).
    Two columns there give a chip 108px and its label 64, and the labels want up
    to 83 — so "Expected Value", "Trade Compare" and "Set Breakdown" all
    ellipsed, and a clipped name on a NAVIGATION chip is the one thing it cannot
    afford. Costs ~100px of height at the foot of the longest column.
  - **Set EV's set name takes a line of its own**, with the three numbers under
    the headers and the head row's "Set" cell hidden. The four-column row gave
    the name 58px against the 106 "Whispers in the Well" wants. Same
    tables-become-stacks trade the EV and Sealed rows already make on a phone.
  - Both are **scoped to `.home-left-col`, not to a breakpoint** — the rail is a
    fixed width, so moved anywhere wider they go back to their full shape.
- **⚠ On mobile a wide panel spans BOTH columns of the rail** (`grid-column:1/-1`).
  At ≤1100px `.home-left-col` is a 2-up grid, which suits Following and
  Tournament Results — a name and a number — but a half cell is **176px**, even
  narrower than the 240px rail. Measured at 375px the calendar got a 169px box
  and clipped 6 of 6 meta lines and 5 of 6 titles; Set EV clipped every price
  there once it moved in, so **it now spans too**. The Toolbox does not: one
  column of chips reads fine at 162px. The calendar's rule stays live for anyone
  who moves it back to the left.
- **⚠ A row prints only what CHANGED from the row above it** (`calPanelRows`,
  2026-09-15). Sep 19 carries three CCQs and the panel spent **six lines saying
  three things**: every row repeated the date, the countdown and the category,
  while the titles — the only part that differs — were the half being ellipsed.
  The date and countdown lead a day, a repeated subtitle is dropped entirely,
  and that day is four lines. **A day with ONE event is byte-identical to
  before**; the common case must not pay for the fix.
  - The comparison is against the PREVIOUS ROW, which is only sound because
    `rows` is date-sorted (`calendarPanelWindow` slices an already-sorted pool).
  - **⚠ A continuation row's `aria-label` carries the day**, because the visible
    date is now on a different row and `aria-label` overrides the content — a
    screen reader would otherwise hear three untethered titles.
  - The hairline moved to the TOP of each day's first row: it separates DAYS,
    not events. Three CCQs on the 19th are three things happening that day.
- **The panel row is TWO STACKED LINES, not three columns.** In the 240px rail a
  `[date | title | subtitle]` row left the title ~80px, so "GNG Attack of the
  Vine! Set Championship" rendered as "GNG …". Date, countdown and subtitle share
  one muted line; the title gets the full width. The meta line is **sentence case
  with no letter-spacing** — uppercasing it cost ~15% of the width and clipped the
  store name on every row, to make secondary text look like a tag.
- **Its title goes to `/calendar` at EVERY width** (`HOME_ALWAYS_SECTION`), unlike
  every other panel, which pops out below 1100px. Popping this one out would
  re-show the identical six-row list over a dimmed page; the month grid and the
  filters are what "bigger" means here. It is therefore excluded from
  `HOME_POPOUT_KEYS` too.
- **⚠ `HOME_POPOUT_KEYS` must stay on ONE line** — `scripts/test_share_links.mjs`
  extracts it with a single-line grab, and splitting it truncated the const into a
  syntax error that only surfaced in that test.
