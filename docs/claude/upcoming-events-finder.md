# Upcoming-events finder — a SECTION of the calendar tile (2026-09-13)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

It was its own home panel until 2026-09-12, a full-screen overlay for a day, and
is now **a section inside the calendar tile** (`<UpcomingSCsBox embed/>` at the
foot of `CalendarPanel`). The panel step was right that the two are not peers —
**the finder is how you FIND shops, the calendar is where they live once you
have** — but making it overlay-only put the ZIP box and the pinned list of your
regular shops one click out of sight, and those are the two halves of one
question. Zaven's ask, verbatim: *"add back the upcoming events near me section
w/tiles, zipcode, results, w/a drop down there too. Just so it's super easy to
see that pinned list and the calendar if you want."* Its own ▾ folds it away
(`packsink:scCollapsed`) and its ⤢ still takes it full screen.

- **`setChamps` stays out of `HOME_PANELS`.** This is a section of another
  panel, not a panel: it has no title link, no pop-out, no column of its own,
  and it travels with the calendar wherever the layout editor puts it.
- **It was NOT made a tab** of the calendar: the finder already has its own
  All/Set&nbsp;Champs/Prereleases tabs (an outer layer stacks two tab rows), and
  after following a shop you want to SEE it land on the calendar rather than
  flip back to check — which is exactly what stacking them delivers.
- **⚠ It shares the tile's `subs`, and that is the point.** `UpcomingSCsBox`
  takes a `subs` prop and `useCalendarSubs(user, skip)` sits out when it gets
  one. Two independent copies of the same table would disagree until a reload,
  so following a shop from a result tile would leave the calendar six inches
  above it unchanged — verified the other way round: a Follow now drops that
  store's events into the list in the same tick.
- **⚠ NOT rendered while the App overlay is up** (`finderOpen`, plumbed App →
  HomeView → CalendarPanel). Both instances persist the same localStorage keys
  on change, and `packsink:scPinned` is the one that bites: pin a series in the
  overlay and the embed still holds the pre-pin array, so its next write drops
  that pin, silently. Unmounting means it re-reads on the way back — verified as
  exactly one `.sc-box` in the DOM while the overlay is open.
- **⚠ A result tile STACKS at rail width** (`.sc-box--embed .sc-tile-main-btn`).
  The standalone `auto minmax(0,1fr) auto` grid gives the date and the distance
  their full nowrap widths and hands the store name what is left — measured
  **10–22px against names 76–204px wide**, so the one thing a result tile exists
  to say was gone. Date and distance share the top line, the store stack takes
  the whole width beneath. The mode chips also tighten to 6px/4px padding: at the
  standalone padding the three labels measure ~198px against ~220px of usable
  rail, which is inside the margin of error for a longer future label.

- **App owns it** — `eventFinderOpen` + `openEventFinder(mode)`, rendered as
  `<UpcomingSCsBox overlay onClose/>`. `overlay` starts it expanded and hands the
  close UP: hiding in place would leave a mounted backdrop swallowing the next
  click.
- **⚠ A `?sczip` deep link now opens the OVERLAY.** It used to work by
  force-showing the panel even for someone who had hidden it (`panelCol`'s
  `if(!m.setChamps && SC_DEEP_LINKED)`); with no panel to force, the overlay is
  the only thing that can honour the link. `SC_DEEP_LINKED` seeds
  `eventFinderOpen`.
- **⚠ The mode travels in localStorage, never a `?scmode=` link** from inside the
  app: `SC_DEEP_SEED` is captured once at MODULE LOAD, so nothing client-side
  would ever see the param. The box reads localStorage in its `useState`
  initialiser and is mounted fresh on every open.
- **Retiring the panel needed no migration** — `normalizeHomeLayout` drops keys it
  does not recognise, so a stored layout holding `setChamps` repairs itself on the
  next load. Verified live.
- **The `nothingFollowed` invitation is GONE**, and its own rationale is why. It
  existed because retiring the panel removed a visible ZIP box from the home page
  and "a button one click inside a tile is a weaker prompt than an input sitting
  there asking to be filled" — the input is back, directly below where the button
  was, so the line had nothing left to pay back. `.cal-panel-find` went with it.
- **The store-icon tool in `cal-panel-tools` stays.** It is the way to the
  full-screen finder when the embed is folded away, and `CalendarDetailModal`'s
  "Find a prerelease near you" still needs `onFindEvents` regardless.

### One box, no country picker — postal code OR town (2026-09-14)

The box used to make you pick a country from a 21-entry `<select>` before you could type,
because zippopotam's URL is `/{country}/{code}`. It is one field now. `scResolveOrigin` is
the single resolver behind BOTH search boxes (this one and the Elo Upcoming SCs distance
box), guarded by `node scripts/test_event_search.mjs`.

**⚠ The picker was never what stood in people's way — the geocoder was, and it failed
silently.** zippopotam wants a TRUNCATED key for several countries, so a Canadian typing
their own postal code got "Postal code not found" with the picker set correctly, for as
long as this box has shipped:

| typed | zippopotam wants | share of events |
|---|---|---|
| `M5V 3L9` | `M5V` — the 3-char FSA | CA 5.9%, the #2 market |
| `SW1A 1AA` | `SW1A` — outward code only | GB 5.1%, #3 |
| `1012 AB` | `1012` | NL 1.1% |
| `D02 AF30` | **nothing works, in any form** | IE 0.2% |
| `01001-000` | **mostly 404s** (`70000-000` hits, São Paulo and Rio do not) | BR 2.5% |

So a universal box WITHOUT `scNormalizePostal` would have been a regression: no country
label left to hint at the format, and twenty wasted requests before the same failure.
Measured the day it landed — 57% of the 35,576 upcoming events are US, **43% are not**, so
"just default to US" was never good enough either.

**The ladder**, in order; the common case stops at step 4 after ONE request:

1. **Infer the country offline** — `packsink:scCountry` (the country that actually worked
   for this person last time) → the browser's timezone → `navigator.language` → US (the
   57% prior). ⚠ The timezone index is built at RUNTIME from `Intl.Locale("und-XX")
   .getTimeZones()` over the country list; a hand-kept copy of 114 zone names is a thing
   that silently rots.
2. **Sniff the format** (`SC_POSTAL_FORMATS`) to narrow candidates. ⚠ Sniffing alone can
   never disambiguate — a 5-digit code is real in 8 of these countries and a 4-digit one in
   7 (`2000` is Sydney, Haarlem, Antwerpen, Neuchâtel, Hausleiten AND Frederiksberg).
   Inference is what picks; the visible answer is what corrects it.
3. **Normalize per candidate** — the truncations above. This is the load-bearing half.
4. **Probe zippopotam in order**, stopping at the first hit. Below the inferred country the
   order is `SC_GEO_COUNTRIES`' market order, **not** however the format table lists them.
5. **Fall back to our OWN place index** — `lorcana_events?city=ilike.<q>%`, 90–240ms, no
   migration and no new third party (the table is anon-readable and already carries city +
   coordinates). This is what makes Ireland, Brazil and the **20 countries that were never
   in the picker at all** work — Thailand, Taiwan, Norway, Czechia, Hong Kong and the rest,
   1,734 upcoming events between them.

- **⚠ Nothing is silent: the results head names the town it chose** (`near ${origin.city}`)
  and the search row offers the corrections. That is what makes dropping the picker safe, so
  do not "tidy" it away. **Two shapes, two controls, and they are mutually exclusive by
  construction** — `scResolveOrigin` fills `altCountries` OR `altPlaces`, never both, because
  a postal code and a place name go down different paths.

### The country control is built from what RESOLVES, not what could (2026-09-15)

A `<select>` LEFT of the postal input, listing every country the typed code really resolves
in, each labelled with the town it would land in — `US · Chicago` / `FR · Muirancourt` /
`MX · Aviacion` / `FI · Isokoski`. Zaven's ask: *"a drop down on the left for country, pop up
only if it's in question, and only populate the other possible options for said zip code."*

- **⚠ `o.altCountries` is NOT offerable as it stands.** It is the FORMAT's candidate list —
  eight countries share the bare 5-digit shape — and the walk stops at the first hit, so most
  of them were never probed and usually do not hold the code at all. Offering them was
  offering seven guesses under every correct answer. **`scCountryOptions` probes them** and
  keeps only the ones that answer.
- **Measured over 40 real US ZIPs: 72% collide with at least one other country, 28% collide
  with NONE** (Sweden 15, Finland 13, Mexico 11, then France/Spain/Germany twice each). The
  sharpest is **`75001` = Addison, Texas AND Paris 01 Louvre**. So the overlap is real and the
  control cannot simply be deleted — but it is absent for a quarter of codes, and the old chip
  row could not tell those two cases apart.
- **⚠ The guess is only ever wrong when you search somewhere you are NOT.** The country comes
  from your own timezone (the ladder in `scResolveOrigin`), so it is right whenever you are
  searching near yourself, which is what the box is for. The failure it exists for is the
  travel case: an American typing `75001` for Paris and silently getting Addison, Texas.
- **⚠ It runs AFTER the search returns, and is never awaited.** Results are never delayed by
  up to seven extra lookups; the control appears a moment later, and only when the probe
  proves there was a choice. **`countryOpts.length > 1` gates the render**, so a code unique
  to one country shows no control at all.
- **⚠ Cached by CODE, not by which country resolved first, and sorted by market order.**
  Picking a country re-runs the search forced to it; without the cache that re-probes six
  countries to rebuild the identical list, and without the sort the list reshuffles under the
  click that used it — the one thing a picker must not do.
- **⚠ Only cleared when the TYPED CODE changed** (`probedZip` ref). Clearing on every search
  makes the dropdown vanish for the second the event query takes and then come back, which
  reads as the control breaking under the click that just used it.
- **⚠ `.sc-zip-input` needs `flex:1 1 90px;min-width:0`** once a sibling shares its row: a
  flex item's default `min-width` is `auto`, so the select would otherwise push the input past
  the row's edge.
- The pre-search country picker stays gone, and `sc-country-select` is still pinned as absent —
  this control is post-search, conditional, and a different thing.

### "Not Chicago?" is the TOWN axis only

- A typed NAME that matched several real towns (`altPlaces`) — "Dublin" is Ohio, California
  and Ireland. **⚠ The QUESTION stays visible; the ANSWERS collapse behind it** (`altOpen`),
  because a name can match a lot of towns and the first one is usually right.
  - **⚠ `runSearch` re-collapses it**, so a corrected guess asks its question afresh.
    `useAltPlace` deliberately does NOT, because flipping back between two towns of the same
    name is the one case where you want the list to stay up.
  - **⚠ The toggle must unset border, background, radius AND padding.** The global `button`
    rule paints all four, so without the reset the question renders as one more chip beside
    its own answers — which is most of what made the row read as clutter.
  - **⚠ Its caret is a CHILD span, not a `::after` `content:"\25BE"`.** A CSS escape written
    through a shell heredoc came out as a literal 0x15 byte that nothing flags; the panel
    already spells its collapse arrows as literal `▸`/`▾` in the markup.
- **The zippopotam note is GONE from both boxes** (2026-09-15, Zaven: *"I dont like the lots
  of text"*). It was three lines of type above a one-line input — the worst ink-to-answer
  ratio in the panel, on the surface with the least room for it. **The disclosure did not
  move: `privacy.html` names `api.zippopotam.us` for this box and is the binding one**;
  `SC_ZIP_TITLE` puts the sentence on the input's own tooltip, where it costs no height.
  Don't re-add a paragraph; if the wording has to change, change it in `privacy.html`.
- **⚠ `useAltPlace` must NOT go through `runSearch`** — that would re-resolve the typed name
  and land straight back on the place the user just rejected. It reuses the coordinates
  `scLookupPlaces` already returned and calls `fetchNear` directly. An earlier cut watched
  the origin in an effect instead, which made every ordinary search hit the RPC twice.
- **⚠ An empty candidate list is NOT the same as `null`.** `[]` means postal-shaped with
  nobody who can look it up (an Eircode); `null` means not a postal code at all. The
  failure message branches on `cands !== null` — with `.length` it told someone who had
  just typed a postal code to try a postal code.
- **⚠ Trim place names at the SOURCE (`scPlaceLabel`).** zippopotam names a Canadian FSA by
  listing every neighbourhood in it — "Downtown Toronto (CN Tower / King and Spadina /
  Railway Lands / Harbourfront West / Bathurst Quay / South Niagara / YTZ)" is one real
  answer — which wrapped the heading onto three lines the first time a Canadian code worked.
- **⚠ `scRankPlaces` breaks a name tie on the browser's country.** "Dublin" matches Ohio,
  California and Ireland equally well, and without it the winner is whatever order the rows
  arrived in: an Irish visitor landed on Dublin, California. An exact name still outranks it.
- **⚠ `ilike` does not fold diacritics.** The table says "Zürich" and people type "Zurich",
  so a miss retries on the first letter and folds with `searchNorm` client-side — bounded,
  and only on a miss.
- **`?scc=` still works both ways**: read as a forced country so a shared link reproduces
  exactly, and written from what the search RESOLVED to. `packsink:scCountry` is now "what
  worked", not "what you picked" — and is only written after a lookup confirms it, or an
  empty initial value would erase the stored preference of everyone who had picked one.
- The **Elo Upcoming SCs** box was hardcoded to `geocodeZip(z, "US")` behind a
  digit-stripping 5-char input, so a tracked store outside the US could never be given a
  distance origin. It shares the resolver now and got this for free.

#### ⚠ Loosening `scZipReady` turned a mount effect into search-as-you-type — fixed 2026-09-14

Both boxes carry an effect meaning *"auto-run once on mount when a search is already
saved"*, and both listed `zip` in their deps. That was only ever safe because `scZipReady`
was `/^\d{5}$/` for US — **true at a complete ZIP and nowhere before it**. Widening it to
`length >= 2` so it could take town names and non-US formats silently changed what those
effects DO: for anyone with no saved search, the first time the gate turns true is the
**second character they type**. Typing `60625` ran a real search on `60`.

- **The visible symptom was a stale error over correct results** —
  `Nothing matching "60". Try a postal code, or check the spelling.` sitting above *94 near
  Chicago, IL* — because nothing ordered the two requests. Reproduced both ways: with the
  partial landing last it also called `setResults(null)` and **deleted the 94 good rows**.
- **The deps are EMPTY now**, and `didSearch` (the "has anything been searched yet" flag the
  mode-switch effect reads) is set by `runSearch` itself. ⚠ Leaving it in the effect instead
  looks equivalent and is not: a first-time visitor's *manual* search would then never arm
  it, and the Set Champs / Prereleases chips would clear the results and re-query nothing.
- **Empty deps alone are not enough.** Two searches can still overlap — Search pressed twice,
  a radius chip tapped mid-search, a "did you mean" button — so `searchSeq` / `geoSeq` gate
  every commit, **the `catch` most of all**: a stale FAILURE overwriting a good result is the
  reported bug. Both awaits now land before anything is committed, so the header can never
  name a new city over the previous search's rows either.
- **Changing only the DISTANCE no longer re-resolves the typed text** (`searchAtRadius`). It
  cost a geocode round trip on every chip tap and — worse — threw away a place picked off the
  "Not Dublin?" row, silently putting you back in the wrong Dublin.
- Sections 12 + 13 of `test_event_search.mjs` pin all of it, and both halves were checked
  against the real bug rather than assumed: re-adding `zip` to the deps, or dropping the
  guard from one `catch`, each fails the run.
