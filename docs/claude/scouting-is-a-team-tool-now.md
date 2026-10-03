# Scouting is a TEAM tool now (migration 143, 2026-09-12)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

"Who is in this room, what are they playing, and what did they play last time?" Two open
text fields — **deck** and **notes** — per PLAYER per EVENT, shared across the scouting team,
readable from three surfaces and durable across events so next month's roster arrives
pre-annotated: *9/12 · Gemini Games · Cosmic Destroyers · tapped out turn 4 every game*.
Guarded by `node scripts/test_scout.mjs`.

### Access is an EMAIL allowlist, and it is NOT the store-report gate

- **`can_scout()`** = tournament admin **OR** an address in **`scout_members`**. Every
  scouting surface and every scouting RPC runs on this one.
- **`can_view_store_report()` is deliberately untouched.** It is the wider allowlist
  (admins + `elo_report_viewers`, keyed on `user_id`) and still gates the store report and
  the plain roster. Notes are the team's own intel; re-gating a scout surface on the store
  report silently shows them to a wider room, which is why `test_scout.mjs` pins every
  render site to `canScout`.
- **Email, not `user_id`, because a `user_id` can only be added AFTER someone has signed in**
  and you have gone and looked it up. An email is addable before a teammate has ever opened
  the site. `scout_members.user_id` remains as the escape hatch for a provider that omits
  `email` from the JWT. Emails are lowercased by a trigger so the lookup is an equality test.
- **`ScoutContext`** (App, beside `GradedAdminContext`) carries the answer; three unrelated
  surfaces ask and it never changes mid-session. **It decides what to OFFER, never what to
  allow** — every RPC re-checks `can_scout()` itself, and `scout_notes` / `scout_members` are
  RLS-on with NO policies, so PostgREST cannot reach them directly at all.
- Admins manage the list in-app: **Who can scout** at the top of the Scout tab
  (`ScoutMembers`, `scout_members_list` / `_add` / `_remove`, all `is_tournament_admin`).
- Localhost preview: `packsink:scoutPreview=1` renders the UI; every write still needs a
  real allowlisted session.

### One note per (event, player) — shared, attributed, and it OUTLIVES the event

- **Not one row per author.** A decklist is a fact about the table, not an opinion, so a
  teammate amending yours is the wanted behaviour; `updated_by_name` + `updated_at` keep it
  attributable rather than anonymous. The editor shows the existing text, so an amendment is
  deliberate rather than a blind overwrite.
- **⚠ The event label (`event_name` / `event_date` / `event_tz` / `store_name`) is
  DENORMALISED onto the note.** `lorcana_events` is an UPCOMING feed that prunes what has
  already happened (migration 121), and the archive does not reach back before it landed.
  The entire point of a note is that you read it next month, so the log has to survive its
  event row disappearing. `get_scout_player` reads `scout_notes` and nothing else. Never
  "normalise" these away. `event_tz` is stored because a 7pm Friday in Elgin is Friday for
  whoever was in the room — the log says the day they were actually there.
- **Emptying both fields DELETES the row** rather than storing two blanks: an empty note
  would still count toward the prior-notes badge, and that count is the one thing it must
  not lie about.
- **⚠ The panel lists the roster UNIONED with this event's notes (migration 144), not the
  roster alone.** 143 listed only `elo_event_roster_members`, and the roster scrape is
  DELETE-then-INSERT — so the moment a player dropped their registration, every note the
  team had written about them **stopped rendering on the event it described**, while the row
  sat untouched in the table and still showed in that player's own history. No error, no
  empty state, nothing to notice; the data was fine and the panel quietly disagreed. The
  union also gives you **Add player**, for someone RPH never recorded (`scout_player_key`
  already produces a `name:` key when there is no RPH id — it only lacked somewhere to
  appear). An off-roster row is **marked, never hidden**: `off_roster` drives the badge and
  its own stat. **`Signed up` still counts the ROSTER only** — folding our own hand-added
  rows into it would restate RPH's number as something it isn't.
- **`player_key` is `rph:<user id>`, falling back to `name:<lowercased display name>`.** The
  RPH account id is the real key; the name fallback exists because a guest plays without an
  account and a fuzzy key beats no key. **Computed SERVER-side in both directions** —
  `get_scout_event` returns it, `save_scout_note` recomputes it from `(rph_user_id, name)` —
  so the client has no mirror that could drift. The test pins that the client never builds one.

### Scope: tracked stores, ANY event kind — plus anything a scout adds by hand

- Every read and write resolves the event through **`scout_event_meta`** (the upcoming feed →
  the archive → `set_championships` → the opt-in ledger → a note's own label, first hit wins)
  and refuses anything out of scope. Without that check, pasting an event id starts logging
  notes on a shop in another state.
- **Scope is TWO things since migration 148**: the automatic half is `elo_tracked_stores` and
  nothing widens it, and the opt-in half is one row in `scout_events` per event a scout added.
  See "Scouting an event outside the bubble" below.
- **But not SCs only.** `elo_event_roster` **loses its FK to `set_championships`** here, so a
  league night at a shop you scout — full of the same people, and already on the calendar —
  can carry a roster. `scrape_rosters.py --event` looks in `lorcana_events` first for the
  same reason.
- **`get_roster_scout` (89) is re-created with a LEFT JOIN.** It INNER JOINed the roster, so
  an event whose roster had never been pulled did not appear in the Scout tab at all — and
  the panel's Refresh button is the only way to pull one. You could not reach the control
  that would have made the event visible. Its gate widens to `can_view_store_report() OR
  can_scout()`; the body is otherwise 89's, unchanged.

### The slate keeps an event for 24 HOURS past its start (migration 147)

143 scoped `get_roster_scout` to `start_datetime >= now()`, so an event left the Scout tab at
the exact moment it became the one you were standing in. Reported from the floor 2026-09-12:
three 3:00 PM Set Championships were on the tab at 2:59 and gone at 3:00. **A sheet is filled
in DURING the event and finished on the drive home**, so the start line is the worst possible
cutoff. The window is `now() - interval '24 hours'`, which is a day's play plus the evening you
write it up, and is the same grace whatever time the event started.

- **⚠ The bulk roster sweep is deliberately NOT widened to match** — the edge function's
  "Refresh all rosters" and `scrape_rosters.py`'s scheduled run still scope to
  `start_datetime >= today`. Those replace a roster **delete-then-insert**, so pointing the
  automatic pull at events that have already been played risks overwriting the roster of the
  very sheet somebody is filling in, with whatever RPH's registration list says afterwards.
  What makes that safe is that the **per-event** refresh — the ↻ inside a sheet, and
  `scrape_rosters.py --event` — resolves through `scout_event_meta` and has never had a date
  filter, so re-pulling the event you are sitting in already works. Put one there and the
  in-room workflow dies with no error.
- **⚠ The slate is no longer all-future, so a started row has to SAY so.** Unmarked, a
  Sunday-morning tab headed "Saturday, Sep 12" reads as stale data rather than as the event
  you were just at — the same "is this thing even updating?" confusion a silent window costs
  everywhere else here. `scoutStartedAgo` renders `Started` for the first hour and
  `Started Nh ago` after that, in the accent colour: it sits inside the `.muted` meta line, so
  `.elo-scout-began` has to take its colour back or the one thing separating a live row from a
  listing is the grey of the address beside it. Its gap is a `margin-left`, because htm
  collapses the newline between `${timeLbl(ev)}` and the span away and the dot would otherwise
  butt straight against the time.
- **Order stays chronological**, so a started event sorts FIRST. That is right for the person
  it exists for — you are in the shop — and the chip is what stops it reading as clutter.
- `SCOUT_LIVE_HOURS` (client) and the migration's `interval '24 hours'` are two spellings of
  one fact; `scripts/test_scout.mjs` pins that they agree, and that 147 changes **only** that
  predicate — re-typing a 120-line function to move one line is how a gate, a join or an
  aggregate quietly goes missing.
- **Upcoming SCs, the calendar and the "Near me" finder are untouched.** A list called
  *Upcoming* holding a finished event is a different claim, and nobody asked for it.

### Scouting an event outside the bubble (migration 148, 2026-09-12)

Zaven: *"some team members might be outside the bubble a little … if a scouting user pins an
SC or clicks on one, give them the option to add roster for that and scout and have those
players in the database (even if non elo matches)."* So scope splits in two and the ceiling
comes off:

- **The AUTOMATIC half is untouched.** `elo_tracked_stores` still decides what reaches the
  Scout tab on its own — *"don't auto add any more to our main scouting tab"* — and
  `scripts/test_scout.mjs` pins the slate's tracked half as byte-identical to 147's.
- **The OPT-IN half is `scout_events`**, one row per event a scout pressed Add on, carrying who
  added it. The event then behaves like any other: roster pull, sheet, notes, player history.
- **An added event DOES appear on the Scout tab, marked `Added`.** That reads the constraint as
  forbidding a wider automatic scope, not as hiding what somebody deliberately added — notes
  written at an out-of-bubble event would otherwise be reachable only through a player's own
  history, which is a strange place to have to go to finish the sheet you filled in an hour ago.
- **Players needed nothing new.** `scout_player_key` already falls back to `name:<lowercased>`,
  `get_scout_event` LEFT JOINs the leaderboard so an unrated player renders NR, and 144's "Add
  player" covers a walk-in. The tracked gate was the only thing in the way.

- **⚠ The gate WIDENS IN PLACE: `scout_event_meta.tracked` now means "in scope for scouting",
  and `store_tracked` / `opted_in` carry the narrow facts.** Every consumer — get_scout_event in
  BOTH 143 and 144, `save_scout_note`, and the `refresh-elo-rosters` edge function — already read
  that one flag and already meant the wider thing. The tidy alternative (a new `scoutable` column
  plus a re-gate of every caller) would mean 144 and 148 both re-create `get_scout_event`, so
  pasting **144 after 148** would silently revert the gate and an added event would stop opening
  with a message blaming the store. Widening the flag the callers already read makes the paste
  order stop mattering. **Verified** against a real Postgres in the worst order (143 → 148 → 144
  → 147): the gate stays open and notes still write; the only losses are the `Added` chip and the
  tab listing.
- **⚠ `scout_event_meta` must be DROPped before it is re-created** (a `RETURNS TABLE` signature
  cannot be changed by `CREATE OR REPLACE`) and **re-granted to `authenticated` AND
  `service_role`** — the drop takes the grants with it, and service_role's is what the edge
  function needs. The matview-grant trap, in function form, for the second time in this feature.
- **⚠ REMOVING an event must stay reversible, and that is why `scout_notes` is a resolution
  source.** The upcoming feed prunes what has happened, so an aged-out event resolves only off a
  stored label. With the ledger as the last source, taking such an event back off the board left
  `scout_event_add` unable to name it ever again: the sheet was orphaned permanently and the
  notes survived only in each player's history — exactly the failure the graded view's per-card
  Hide was killed for. Reading a note's own denormalised label after the ledger means anything
  with something to lose can always be re-added. **The fixture harness caught this**; nothing in
  the static tests would have.
- **⚠ The `Added` chip and Remove require `!store_tracked`.** An added event at a tracked store is
  on the tab either way, so the chip would name the wrong reason and Remove would appear to do
  nothing. Same reason the slate's added branch carries a `NOT EXISTS` against the tracked half:
  without it an added SC lists twice and reads as a duplicate-rows bug.
- **⚠ The Scout row's chip is a SIBLING of the store name, not a child.** `.elo-scout-ev-store`
  ellipses, so a chip inside it is simply gone on a long store name with nothing on screen to say
  it existed — the `.scanner-qa-rowinfo` lesson again. `.elo-scout-ev-storeline` is the flex row.
- **Adding pulls the roster immediately** when the event has never had one. Adding and then
  hunting for a second button is two steps for one intention, and the roster is the whole reason
  you added it. Remove is two-tap (the graded slot-remove contract) and its toast says the notes
  are kept.
- **The calendar modal and the near-me finder no longer pre-filter on the tracked-store list** —
  that gate hid the button on exactly the events a scout most wants a sheet for. `get_scout_event`
  is the scope, and its refusal is where the Add button lives. `useTrackedStoreIds` is gone with
  it; the Stores tab's own `elo_tracked_stores` fetch is unrelated and stays.
- **The edge function needs NO change** — it reads `meta.tracked`, which widened. (The redeploy
  outstanding from 143 is still outstanding.)
- **`supabase/diagnostics/scout_any_event_fixture.sql` + `_checks.sql` are a throwaway-Postgres
  behaviour harness** for the whole chain (143 → 144 → 147 → 148): 12 assertions, run order in
  the fixture's header. Not wired into CI (no Postgres there, and a red job everyone ignores is
  worse than a script you run when you touch the file). `scripts/test_scout.mjs` pins the SQL's
  text; this pins what it does. Every scouting failure mode is silent, so both are wanted.

### Where it renders

`ScoutEventPanel` is the one component; `inline` renders it in place, otherwise
`ScoutEventModal` wraps it.

**It is a SHEET, not a list of cards** (2026-09-12, Zaven: *"I'd rather just click on
the event name and it's a nice layout and interface there, like an excel sheet"*).
Columns are **Elo · Player · Deck · Notes**; Deck and Notes are the inputs themselves.
Type, Tab, saved — there is no Edit / Save / Cancel anywhere, because logging a room of
24 people one modal at a time is the thing that makes a scouting tool go unused.

- **A cell commits on BLUR and only when it changed.** Without that test, tabbing across
  a full sheet fires a write per cell.
- **⚠ `save_scout_note` writes BOTH fields, so a cell edit has to send its sibling back —
  and each save triggers a reload, which opens a race.** Tab from Deck into Notes fast
  enough and the second save is built from the PRE-save row: it sends the old deck back
  and silently undoes the edit you just made. `inflight` (a ref, keyed by player) holds
  what was last SENT and beats the loaded row until its reload lands, then is dropped so
  a teammate's concurrent edit degrades to the documented last-write-wins. Verified
  against a deliberately slow 600ms server — without it the second write carries `deck:""`.
- **⚠ There is a GLOBAL `button{border;background;border-radius;padding}` rule.** Anything
  in the sheet meant to read as text (the name, the Elo) must unset all four or it renders
  as a chip and the sheet stops looking like a sheet. This broke exactly once, when the old
  card-row styles were swapped out and took the resets with them.
- **⚠ It SCROLLS sideways on a phone rather than collapsing to stacked cards**, against the
  site's usual mobile-table pattern — collapsing puts you back at one player per screenful,
  which is what the sheet exists to fix. The Player column pins **only under 760px**, where
  it actually scrolls: sticky needs an opaque `--bg-modal` (the usual translucent tokens let
  the scrolling columns show through, same rule as the Screener's NAME column), and on a
  desktop sheet that never scrolls that opaque panel just draws a stray box around every name.
- **The event row IS the way in.** No expand-then-button: clicking a row in the Scout tab
  opens its sheet. The old inline roster preview is gone.

| Surface | How you get there |
|---|---|
| Elo » Scout tab | expand a day's event → **Log decks + notes** |
| Elo » Upcoming SCs | an event's modal → **Scout this event** (replaces the roster CTA for scouts) |
| Calendar | a store event's modal → the **Scout** tab (only for a tracked store) |
| Home » Upcoming near me | an event's modal → **Scout this event** |

- **Clicking a player's NAME opens their whole history**, because that is the question you
  opened a scouting panel to answer. The **Elo rating** is the link to the Elo profile. The
  `⟲N` chip is the "we have seen this person N times before" flag and opens the same history.
- **⚠ Esc belongs to the innermost dialog.** `useEscToClose` and the calendar modal's own
  handler are both document-level, so one keypress would otherwise close the history modal
  AND the panel underneath it. Both now skip when `.scout-history-modal` is in the DOM.
- The calendar decides whether to offer the tab from `useTrackedStoreIds` (one module-cached
  fetch of the public `elo_tracked_stores`). A curated row carrying an `event_id` but no
  `store_id` is offered anyway and the panel answers — refusing on a missing field would hide
  the one event you wanted.

### Pulling a roster on demand

- **Per event, for any scout**: `↻ Refresh roster` inside the sheet → the `refresh-elo-rosters`
  edge function with `{event_id}`. It resolves through `scout_event_meta`, refuses an
  untracked store, and scrapes that one event.
- **Every roster, admin only**: `↻ Refresh all rosters` in the **Scout tab header** — not on
  Upcoming SCs, where it used to be and where nobody looked for it. It walks every tracked
  upcoming SC, one paginated round trip each, which is why members get the per-event button
  instead. One master button, in one place.
- The function now accepts **either** credential (`can_view_store_report` OR `can_scout`),
  each in its own try/catch so a pre-143 database missing `can_scout` does not sink a request
  the other gate opens.
- **⚠ The edge function needs redeploying** (`supabase functions deploy refresh-elo-rosters`).
  A function deployed before this ignores the body and refreshes every tracked upcoming SC
  instead — which reaches the event when it IS an SC and never when it is a league night.
  It **echoes `event_id` back when it understood us**, which is how the client tells, so the
  toast says which happened instead of reporting a site-wide total as this event's count.
  `scripts/elo/scrape_rosters.py` is the cron safety net and mirrors the logic; keep the two
  in sync.
- **⚠ And until it IS redeployed, a scout who is not also a store-report viewer gets a flat
  refusal** — the old copy gates on `can_view_store_report()` alone, so the sheet opens (the
  database says `can_scout()`) and its one button answers 403. Reported from the floor
  2026-09-12 as *"Couldn't refresh the roster: Edge Function returned a non-2xx status code"*.

### ⚠ A failed Edge Function call hides its reason — read `error.context` (2026-09-13)

`supabase-js` throws `FunctionsHttpError` whose `.message` is the FIXED string *"Edge Function
returned a non-2xx status code"*, for every one of the five ways this call fails — not
authorized, unknown event, untracked store, a database error, a platform timeout. The
`Response` rides along **unread** on `.context` (`invoke` does `if(!r.ok) throw new
FunctionsHttpError(r)` before touching the body), so the real `{ok:false, error:"…"}` is
there for the asking and the toast was naming none of it.

**`edgeErrText(e)` (beside `scoutErrText`) is the one accessor** — it reads the body, prefers
the body's own reason over the status, and every roster-refresh failure routes through it.

- **⚠ A 403 here is NOT "you aren't on the team", and must never say so.** This panel only
  renders once `get_scout_event` has returned, i.e. after `can_scout()` already said yes in
  the database — so the only way the function can still refuse is the stale deployment above.
  Answering "scouting is team-only" sends the reader to check the one thing known to be fine.
- A 404 is two different missing things: **our** `unknown event` (RPH has no such event)
  against the **platform's** `NOT_FOUND` (the function was never deployed). The body
  separates them; the status cannot.
- A 5xx/504 names the redeploy too — the pre-143 copy ignores `{event_id}` and scrapes every
  tracked upcoming SC, which is exactly how one event's refresh runs long enough to be killed.

### Scouting an event that ALREADY HAPPENED (2026-09-13)

Reported by a scout: *"Is there a way to go to previous tournaments to update this
scouting report? When I try to open a previous tournament it just shows the tournament
results."* **Nothing server-side ever refused.** `get_scout_event`, `save_scout_note` and
`scout_event_add` gate on `can_scout()` and `tracked` and **never on a date**, and
`scout_event_meta` resolves a played event through `lorcana_events_history` (and
`set_championships`, the ledger, a note's own stored label). The sheet was willing the
whole time; what expired was the way IN — 147 stops the Scout tab's slate 24h after an
event starts, and that slate was the only door.

So the fix is a DOOR, not a gate change: **Elo » Tournament Results → an event →
`Log decks + notes`** (`.elo-scout-link` in `EloEventDetail`'s header, beside Store
report), opening the same `ScoutEventModal` EloView already owns. That is exactly where
the reporter looked.

- **⚠ `get_roster_scout` is the ONLY scouting function allowed a date filter**, and the
  guard test pins that on the other three — one `and` in the wrong function silently
  deletes this, and the symptom is a button that 403s rather than an error anyone reads.
  The test also asserts the slate DOES carry one, so it cannot pass vacuously.
- **Gated on `canScout`, never `canViewStore`** — the standing access-widening trap. And
  the button renders `canScout && onOpenScout && …`, so a dropped prop makes it vanish in
  silence: the test pins both the signature and EloView's pass-through.
- **`.elo-scout-link` reuses `.elo-store-link`'s rule** rather than adding a near-copy. That
  rule exists only to let a `<button>` sit in this row: `.elo-event-link` is declared LATER
  and wins back the pill's background, border and padding, so what actually survives from it
  is `cursor` + `font:inherit` — which an `<a>` gets for free and a `<button>` does not.
- **Already reachable, and worth saying so**: the CALENDAR's Scout tab is
  `canScout && ev.event_id != null` with no date test, so a past store event opens a sheet
  today with **Show past** on. It only covers stores you follow, which is why it did not
  answer the report.
- **Still migration-shaped if it is ever wanted**: a "previous events" toggle on the Scout
  tab itself means widening 147's window in `get_roster_scout`. The button needs no
  migration at all, so it shipped first.

### ⚠ The sheet's Elo column: the rating is DATA, the link is an AFFORDANCE (2026-09-13)

The cell rendered `p.matched && onPlayerClick ? rating : "NR"`, so on the two surfaces that
mount `ScoutEventPanel` with **no** `onPlayerClick` — the calendar's Scout tab and the Near-me
finder's modal — **every rated player read NR**, while the header's Avg Elo / Top Elo,
aggregated server-side over those very rows, printed real numbers (1554 / 1777 against six
NRs, in the report that found it). A scouting sheet claiming nobody in the room is rated is
wrong about the one column it exists for, and nothing errors.

`EloEventRoster` already had the split right and is the shape to copy: the number renders from
`current_rating`, the click keys on `matched && onPlayerClick`. Where there is nowhere to
navigate to, the rating is a plain `<span>` — it inherits `.ss-elo`'s accent + tabular numerals,
so no CSS was needed and the two surfaces differ only by the hover underline.
