# Elo weekly refresh — set rotation is the failure mode (2026-09-08)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`.github/workflows/elo_weekly_refresh.yml` (Mon 11:00 UTC) runs `scripts/refresh_elo.py`:
download the canonical SQLite from Supabase Storage → ingest → renames → aliases →
recompute → export to Supabase → upload the DB back. Two steps feed it events, and
**only the second one still matters**:

1. `ingest.py --xlsx season_files/wilds_unknown.xlsx --season "Wilds Unknown Summer 2026"`
   — the hand-curated season sheet. It is a permanent no-op now (`skip=50` every week);
   it is the historical Wilds Unknown seed, not a live intake.
2. `discover_store_scs.py --ingest` — the real intake. Store-driven: it derives the RPH
   `store_id`s we already count from non-ignored events in the DB, pulls the CURRENT set's
   SCs off RPH, and ingests the ones at those stores. `fetch_current_set()` reads the
   newest released *numbered* set from Supabase `sets`, so it auto-advances at rotation.

**⚠ The board froze at the Attack of the Vine! rotation and NOTHING went red.** Step 2
found all 68 AotV SCs at tracked stores — including the 14 played 09-05/09-06 — and then
refused to ingest one of them, because `season_label_for()` found no existing
`"Attack of the Vine! …"` label in the DB and the code skipped the whole set with
*"seed its first event via the spreadsheet first"*. Step 1 skipped its 50 already-ingested
events, step 2 is deliberately `run_soft`, so the workflow was green while ingesting zero.
The guard was over-cautious: **scope comes from the tracked `store_id` set and
`EXCLUDED_STORE_IDS`, never from the label** — it was refusing to ingest a set for want of
a display string. It now SEEDS instead: `season_label_from_date()` names the season
`"<set> <northern-hemisphere season> <year>"` off the first SC it is about to ingest
(reproduces `Fabled Fall 2025`, `Wilds Unknown Summer 2026`, `Whispers in the Well Spring 2026`
exactly), overridable with `--season-label`.

- **Only the SET half of a season label is load-bearing.** `eloSeasonSetLabel()` longest-prefix
  matches it against `MAINLINE_SETS` to head the Stores columns, and the Stores tab assigns
  seasons by DATE (`eloSeasonForDate`), not by this string. The tag is display text on the
  season chip and in the events table. `SEASON_REVIEWS` is the one place it must match
  exactly — and that is curated per published recap, so add the entry when you publish one.
- **`--season-label` cannot rename a season that already has events** — it only names a set
  being seeded. Renaming an existing one is a DB edit, not a flag.
- **`name_nets()` generates the three spellings per set** (`X Set Championship`,
  `X - Set Championship`, `Set Championship X`) instead of the old hand-kept map that
  covered only Wilds Unknown and Winterspell — RPH's name-relevance filter drops ~4% on a
  single phrasing, and a dropped SC is a store falling off the board. Byte-identical nets
  for those two sets; a rotation needs no edit.
- **`CURRENT_SET_FALLBACK` in `discover_wu_scs.py` is stale by nature** (it is only reached
  when the Supabase `sets` read fails) but a stale value files this set's SCs under the
  previous set. Bump it at rotation.
- Guarded by `python scripts/elo/test_season_seed.py` (stubbed pulls + temp SQLite, no
  network): the seeding path, that seeding does not widen scope, the label shape the UI
  prefix-matches, and that an existing set keeps its stored label.
- **The remaining hole is alerting, not ingest.** A weekly refresh that ingests zero events
  for the current set still exits 0. If this bites again, the fix is a floor check in
  `refresh_elo.py` (current set has ≥1 event, or ≥1 new event in the last N days), not more
  discovery.
- **A soft step that fails now leaves a `::warning::` on the run** (2026-10-06), and
  `ingest.py` exits 1 when any event errors. So the season-sheet ingest is `run_soft` (one
  RPH flake there must not cost the week) while the hand-added `--ids` ingest stays `run`:
  a one-off that fails turns the dispatch red instead of ending green with nothing ingested.
  Guarded by `python scripts/elo/test_ingest_guards.py`.

### Set Championships are recognised by RPH's template, not only the title (2026-09-10)

`is_sc()` needed the words "set championship" in the title, and stores don't always type
them: "Lorcana Set Champs", "Attack of the Vine Store Championship", "Set Chamionship". RPH's
official SC event template stamps **`phase_template_group` `f6a76808-…`** on every event made
from it, whatever the title says, so `is_sc()` now accepts the title OR that group
(`SC_PHASE_TEMPLATE_GROUPS` in `discover_wu_scs.py`), and side-event words veto both.

- **Measured exhaustively, not sampled**: every event at all 103 tracked stores since
  2025-08-01 (4,723). The group sat on 444 of 448 titled SCs and on 26 events that weren't
  titled — **all 470 are real SCs**. The title test missed all 26: of the 6 played since
  Winterspell, **5 never reached the board**, and 5 more (2026-09-12 to 09-20) were on track to
  miss it.
- **Widening the title test instead would not have worked.** "champ" also matches "Lorcana
  League Play last week before Championships" and "League Season Finale - Single Elimination
  Championship"; both carry a different template.
- **Recognising them was half of it; FINDING them needed a second pull.** The name nets in
  `discover_store_scs.py` are RPH's relevance search, which never returns a title that names no
  set. `pull_store_scs()` reads each tracked store's own feed across the set's season
  (`set_window()`: this booster set's release up to the next one's, from Supabase `sets`), and
  `sc_set_for()` places a setless title by DATE — the rule the Stores tab already uses for every
  event, and `discover_events.py` for an upcoming SC. Measured at ~25s a season for 103 stores;
  it finds exactly the untitled SCs above (6 / 1 / 4 for AotV / Wilds Unknown / Winterspell).
- **Knock-on effects, all intended**: `discover_events.py` now files these as `kind='sc'` and
  mirrors them into `set_championships`, so they reach the Upcoming SCs tab, the roster scrape
  and `sync_elo_tracked_stores`' 75-mile rule; `scrape_store_history.py` classifies history the
  same way.
- **The per-set config template UUID changes every rotation; this group has not moved since
  Reign of Jafar.** If it ever does, `discover_events.py` prints a `::warning::` once fewer than
  80% of ≥30 titled SCs carry it. An annotation, not a failure, because the title test keeps
  working; `is_sc_by_name()` is the old test, kept for exactly that check.
- **Older seasons are NOT backfilled by the weekly refresh**, which only asks about the current
  set. With the canonical DB pulled locally,
  `python scripts/elo/discover_store_scs.py --sets "Winterspell" "Wilds Unknown"` lists what they
  missed (4 SCs at tracked stores as of 2026-09-10). Ingesting them re-rates history, so that is
  a decision, not a chore.
- Guarded by `python scripts/elo/test_sc_template.py` (the rule, the window, the store-feed
  pull) and `test_season_seed.py` (a store-feed-only SC is ingested; an excluded store's feed is
  never asked).

### Adding ONE event by hand (2026-09-08)

"Count this event, but not this store" — a guest/out-of-area shop, or an SC discovery
didn't classify. Two halves, and doing only the first is the trap:

1. **Add the id to `ONE_OFF_EVENT_IDS`** in `scripts/elo/elo_scope.py`, then
2. **Actions → ELO weekly refresh → Run workflow**, `event_ids: <id>` (space-separated
   for several; `event_season` blank inherits the current set's label).

**⚠ The ingest MUST happen inside a refresh run.** The canonical SQLite is downloaded
from Supabase Storage at the top of `refresh_elo.py` and uploaded at the bottom, so an
ingest run anywhere else is silently overwritten by the next refresh. That is why this is
a dispatch input on the existing workflow rather than a script you run on its own.

- **`ONE_OFF_EVENT_IDS` is the "don't count the store" half, and it is not optional.**
  Scope is derived from ingested events, so a plain ingest enrols that store. The list keys
  on the EVENT id, which also means adding one needs no lookup of the store's id.
- **⚠ Scope is derived TWICE, and the list has to reach both** — which is why it lives in
  its own `elo_scope.py` rather than in either consumer:
  - `discover_store_scs.tracked_store_ids()` reads the **local SQLite** and decides whose
    SCs future discovery ingests.
  - `sync_elo_tracked_stores` reads the **Supabase `elo_events` mirror** and decides whose
    SCs reach the site's Upcoming SCs tab — and through `elo_tracked_stores`, the store-history
    backfill behind the Stores tab's events/tickets/fans. Its rule 1 matches on store NAME, and
    rule 4 tracks an in-region history store even with no upcoming SC, so filling the store name
    (below) is exactly what would have enrolled the shop a day later, via the daily
    `discover_scs.yml`, with nothing in the Elo refresh to show for it.
- **It is NOT `EXCLUDED_STORE_IDS`** (its neighbour in `elo_scope.py`, see below). That one
  drops a store's events entirely; here the event fully counts — matches, ratings, the
  player's rating — and only the STORE is out of scope. Different question, different list.
- **The one-off is ingested AFTER discovery, BEFORE the rename/alias passes**: after, so
  the current set's season label already exists to inherit; before, so a player appearing
  for the first time is merged like any other.
- **`ingest.py --ids` fills the store name from the events API** (it already fetched that
  payload for the date). Without it a hand-added event stored `store=NULL` and rendered
  nameless in every list. The xlsx and discovery paths pass a store explicitly, so this
  only fills the gap the manual paths left.
- `event_ids` is validated as digits-and-spaces in the workflow and reaches the shell
  through `env:`, never interpolated into the command line.
- Guarded by `python scripts/elo/test_season_seed.py` — on BOTH sides: a one-off must not
  track its store locally, must not reach the Upcoming-SCs allowlist name set or the
  store_id-resolution samples, an ordinary event must still do all three, and the one-off
  must stay in the DB.

### Taking a store OUT of scope (2026-09-12)

`EXCLUDED_STORE_IDS` is the other half of `elo_scope.py`: this shop is not Chicagoland,
past and future, whatever the rules infer. It started with the two central-Indiana stores
(Good Games - Indianapolis, Storming Good Games — both ~165 mi out) and since 2026-09-13
holds 15: all of Michigan, plus anything over a 3 h 30 m DRIVE (the Fox Valley / Green Bay
corridor and Springfield). The per-store drive times are in `elo_scope.py`.

**⚠ Both of these were true at once, and a store excluded months earlier was still on the
Scout tab** (reported 2026-09-12, and either one alone is enough to reproduce it):

1. **The list reached one consumer.** It lived inside `discover_store_scs.py`, which gates
   the Elo **ingest**. `sync_elo_tracked_stores` writes `elo_tracked_stores` — the table
   that gates the Upcoming SCs tab, the **Scout tab**, whether a scouting sheet opens at
   all, the roster scrape and the Stores tab's history — and had never heard of it. Exactly
   the split `elo_scope.py` was created to prevent for `ONE_OFF_EVENT_IDS`, which is why
   both rulings live there now and both scripts import them.
2. **The sync could only ADD.** Its write is an upsert with no delete anywhere, so a store
   that qualified once stayed tracked forever and no rule change could ever take a row back
   out. `prune_excluded()` is that delete.

- **⚠ Only the explicit list is deleted — drift is REPORTED.** Pass 2 resolves store_ids
  over the live RPH API, so a 404 or a timeout makes a perfectly good store look unmatched
  for one run; deleting on that evidence would drop a real shop off four surfaces, silently,
  on a green run. A tracked store no rule matched is printed with the line that names
  `EXCLUDED_STORE_IDS` as the way to remove it, and left alone.
- **The exclusion beats every rule, not just the one that tracked the store.** Pass 1's gate
  is an OR (history / geo / curated), so the skip sits above all three, and pass 2 re-checks
  after RPH resolves the id — the history-with-no-upcoming-SC shape is how Indianapolis got
  there originally.
- **`--dry-run` must be dry on BOTH writes.** A flag that still deletes is a lie in the one
  direction that loses data.
- `service_role` already has DELETE on the table (migration 69) — no migration needed.
- A store is out of scope the moment it is in the list, but the row only leaves on the next
  `sync_elo_tracked_stores` run — the daily `discover_scs.yml`, or run it by hand.
- **Scouting notes already written are NOT lost.** Losing the row makes `scout_event_meta`
  report `tracked: false`, so the sheet stops opening — but `scout_notes` carries its own
  denormalised event label and `get_scout_player` reads that table and nothing else, so the
  player's history still shows what the team logged there. Same property that lets a note
  outlive its event being pruned from the upcoming feed.
- Guarded by `python scripts/elo/test_excluded_stores.py`: that one object is shared by both
  importers (identity, not equality — a local copy holding the same ids today is how they
  drifted and it compares equal), that neither pass tracks an excluded store, that an
  existing row is deleted, and that an unmatched one is not.

### …but a store cut from Elo STAYS on Store Status (2026-09-29)

Zaven, after WorldClassCards (5392 / 5393) asked why they had vanished: *"add back wcc and
any other previous elo store we cut, so they can track progress."* Cutting a store from the
rating is a statement about where the scene plays, not about the shop, and the Store Status
tab is how a shop follows its own RPH tier progress. **The cut took them off that tab only
because the tab, the history top-up and the roster scrape all read `elo_tracked_stores`** —
the same table `prune_excluded()` deletes them from.

- **`elo_scope.STATUS_ONLY_STORE_IDS`** is the list, and it is `frozenset(EXCLUDED_STORE_IDS)`:
  derived, so a future exclusion keeps its Store Status row by default. To take a store off
  that tab too, subtract it there with a reason. Checked 2026-09-29: the 15 exclusions are the
  only stores ever cut. Battle City, Grognard and Zeek's each have an `is_ignored` event, but
  that was a data-quality call on one event, and all three are still tracked.
- **⚠ It is deliberately NOT written into `elo_tracked_stores`.** That table also gates Upcoming
  SCs, the Scout tab, scouting sheets and the SC roster scrape, and a cut store belongs on none
  of them. Instead the Store Status consumers union it in: `scrape_store_history.store_status_ids()`
  (the daily 30-day and hourly 2-day top-ups), `scrape_event_attendance.target_events()`,
  `report_store_tiers`, and the client.
- **⚠ The client carries a COPY, `ELO_STATUS_ONLY_STORE_IDS`**, because the browser cannot read
  a Python file. `test_excluded_stores.py` fails when the two disagree: an id only in the copy
  is a row whose numbers froze the day it was cut; an id only in `elo_scope` is scraped and
  never shown. Adding an exclusion therefore means adding the id to Index.html too.
- **The client unions only once `elo_tracked_stores` answered.** An empty tracked list means "no
  filter" (the pivot's fixture rule), and 15 ids would turn that into a tab of just the cut
  stores.
- **Their rows say "Not in Elo"** and have no store-report link: that report is built from the
  Elo events these stores no longer have (their `elo_events` rows are `is_ignored`).
- **Several were cut before their full history was ever pulled** — Chimera, Draw 7, Fanfare,
  Gnome Games and Titan Games had history back to August 2026 only, and every roster since
  the cut was unscraped. Actions → Discover Lorcana events → `backfill_stores: status` +
  `skip_discover: true` runs `scrape_store_history.py --status-only` (full history for just
  those 15); the next hourly store-stats refresh then scrapes every roster they are missing.
- Guarded by section 5 of `python scripts/elo/test_excluded_stores.py`.

### Results integrity — the refresh checks what it holds, not just what it adds (2026-09-28)

Asked to confirm the Elo results were current, a pass over **all 444 rph events** against
RPH found the refresh green and the data wrong in four ways, none of which any run reported:

| Found | Cause |
|---|---|
| **HoneyBee 9/13 (919790)**: two semifinals stored as 0-0 draws; RPH has 2-1 wins | ingest stored a match from a round still being played (no result yet), and the `(round, table)` dedupe guard then kept the real result out forever. The draw rule read 0-0 as an agreed draw, so four ratings never moved. |
| **Critical Games 6/28 (707597)**: our final had xiong c winning; RPH, SunnyDay | the TO re-scored the final after we pulled it. RPH's own standings already said SunnyDay 1st at 6-0. |
| **Game 'n Grub 9/20 (843303)**: zero matches, two rounds played | the TO never closed it, so it sat in RPH's **`inProgress`** bucket, which discovery's past + upcoming search never returns. |
| **Every Attack of the Vine! SC**: no official standings | `backfill_official_standings.py` was manual-only, last run in July — event pages ranked by raw points: byes dropped, no OMW%, a points tie decided "champion" alphabetically. Plus **162 older rows** keyed on merged-away players, invisible because the view joins on the canonical id. |

What the refresh now does (all guarded by `python scripts/elo/test_results_integrity.py`):

- **`ingest.match_is_complete`** — a non-bye match whose own RPH `status` isn't COMPLETE is
  never stored; it fills in on the next pull. **`ingest.sync_match_result`** — on a re-pull, a
  stored result that differs from RPH's COMPLETE one takes RPH's winner + games. Only the
  result moves, never the players, never a `source != 'api'` row, and only when the RPH names
  still resolve to the stored pair (a name resolving to someone else = a re-paired table; left
  alone). Byes are guarded by COUNT, because a renamed bye-holder resolves to a new player_id
  and each re-pull used to add a second bye for the same seat (675962).
- **Discovery pulls `inProgress` too** (`PULL_STATUSES`), and **`requeue_unfinished` re-pulls
  every unfinished event already in the DB by id** — played ones at any age, unplayed ones for
  60 days so a cancelled SC ages out — passing the event's own stored store/location/date/
  season. ⚠ Never re-pull with those left None: ingest fills the store from RPH's CURRENT
  name, which drifts (store 3813 is "Gemini Games, LLC" here and "Pegasus Games" on RPH), and
  the store report keys on the name.
- **`verify_results.py --days 30 --repair`** (soft, after the rename/alias passes, before the
  draw flags + `elo.py`). Same `sync_match_result` rule; never inserts or deletes; clears a
  repaired event's standings so they re-fetch. **⚠ It skips any event a person has touched —
  `events.notes`, a locked official standing, or any `source != 'api'` / negative-round_id
  row — and that is the ONLY thing protecting a hand correction.** A hand edit to a match must
  leave one of those marks or the next Monday puts RPH's version back. (631941, the MOHZAK
  fabricated-results event, is protected by its notes; e276338's bogus final by its lock.)
  ⚠ **Never force a wholesale re-pull of a FINISHED event** to "fix" it — the dedupe guard
  cannot know that a row was deleted on purpose, so 631941's fabricated matches would come
  straight back.
- **`backfill_official_standings.py`** (soft, after `elo.py`): only EVENT_FINISHED events with
  matches, fetched once (`--force` re-fetches, locked always skipped). Names resolve ONLY
  against players who played that event — no global lookup, because a renamed account's new
  name can already be a separate row from another event ("[IF] BrentsToys" is our Brents31) —
  then **`pair_by_record`**: a leftover row that played pairs with the one unplaced participant
  holding the identical W-L-D, when that record is unique on both sides. On 2026-09-28 it placed
  15 renamed accounts, all verified by name ("March 8th" = UglyCapybara39, "Piggly Wiggly" =
  Nimble_Nurgle, boomsplosion = Matthew). `recanonicalize_standings` re-keys rows onto a
  merged player's canonical id every run.
- **Checking it by hand**: `python scripts/elo/verify_results.py --all` against a downloaded copy
  (`elo_db_storage.py download --to <scratch>` then `--db <scratch>`) is read-only without
  `--repair` and takes ~5 min. Expected residue: the hand corrections above (160509 / 171547
  hand-entered finals, 276338, 631941) plus whatever is still being played.
