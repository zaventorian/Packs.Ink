# Pending / roadmap

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**Pre-launch batch 2026-07-14 (commit `b94eb68`, SW v272 — NOT pushed yet):** SEO/social head meta (title/description/OG/Twitter/JSON-LD; `og-image.png` baked by `scripts/make_og_image.py`; per-view `document.title`+canonical via `VIEW_TITLES`); `robots.txt`+`sitemap.xml`; onboarding tours reworked + LIVE (see tours bullet below); branded cold-boot error screen (`bootFailed` in App); CSP now enforced-lite + full policy as `Content-Security-Policy-Report-Only` reporting to Sentry (enforce after prod runs clean — rename the header); `PRERELEASE_SETS` date-gated (auto-flips 7/17); `create_trade` per-IP rate limit (mig 102, applied); `graded_sale_pkey` search_path pinned (mig 101, applied); mig 103 (drop `_scan_revert_backup`) written but NOT applied. Cloudflare move + CSP enforce remain the post-launch follow-ups.
**Second sweep same day (commits `b813f59`/`5739119`/`5514d8f`/`1b8f8ef`, SW v273):** graded ToS prompt is now SURFACE-TRIGGERED (graded surfaces call `signalGradedSurface()`; App listens on `packsink:graded-surface`; "Maybe later" persists 7 days in `packsink:gradedTosDismissedAt` — the modal no longer greets every visitor on load); branded cold-boot loading card (`bootLoading`) replaces the empty-shell first load; Cards/browse + history-picker "no match" false dead-ends fixed; signed-in-empty Collection CTA; Screener no-results message; `Tip` is tap-toggleable (mobile tooltips work now — EV strip + Master/Play Set gained ⓘ tips); browse-tile quick-add "+" (CardBrowser `onQuickAdd` → CardsView `quickAddOne`); Discover falls back to the previous set's window when the fresh window has <12 decks (set-release-day empty-feed cliff); CardBrowser grid WINDOWED at 150 tiles/slab (IntersectionObserver sentinel); Sentry loader deferred via `window.sentryOnLoad`; fonts preconnect; scanner scripts deferred + dropped from SW precache; card tiles keyboard-accessible + global `:focus-visible` ring.

**Recent systems shipped 2026-06-13/14 (SW v158→v181, pushed `ccf6e5d..9bdac1f`):**
- **Code-review pass (A–E):** setUser id-gate (kills the pref-toggle refetch storm), Screener baseline cols, Following re-enrich, smoothing test+CI, graded-ETL partial upsert, `Supabase.update/delete` retry, `_headers` CSP, TCGplayer/Non-Foil copy, a11y labels. Migration `supabase/67_revoke_rls_auto_enable.sql` — **applied / confirmed live** (2026-06-27 audit).
- **Full audit fixes (2026-06-27):** migrations **90** (collection cost-privacy — removed the cross-user `OR <profile public>` branch from the 3 collection-table SELECT policies, so `amount_paid`/`custom_value`/`notes` no longer leak to any signed-in user via direct PostgREST reads; public/viewer reads already go through the cost-stripping `get_shared_collection_*` RPCs, so zero client change), **91** (wrapped `auth.uid()`/`is_*_admin()` in `(select …)` across 49 RLS policies — `auth_rls_initplan` perf), **92** (covering indexes for 9 unindexed FKs). Core JS libs (react/react-dom/htm/supabase + html2canvas) **vendored under `/vendor/`** (kills the unpkg-outage blank-page boot crash). Added stale-response `cancelled` guards to `EloStoreReport`/`EloEventRoster`; `safeHttpUrl()` on every `graded_sales` eBay URL sink; `.order()` on the `deck_cards` >1000-row pager; Python ETL `select()` now always sends `order=`; graded matview-refresh failure now exits non-zero; staleness math + `get_json` robustness. CSP staged commented in `_headers` (test on a deploy preview, then enable). **Held for your call:** unused-index drops (wait for stat maturity per the index-audit policy). ~~remove built-but-unwired `ArchetypeBreakdown` + `GraduateSubmissionModal`~~ — already gone from Index.html (verified 2026-08-20; zero references). ~~terms.pdf~~ — resolved 2026-07-14: it was the signed TCGplayer affiliate AGREEMENT (not a site ToS); removed from the repo, copy at Desktop/TCGplayer-Affiliate-Agreement.pdf. ~~drop `_scan_revert_backup_20260627`~~ — **DONE**; migration 103 is applied, the table is gone (probed 2026-08-10).
- **`searchNorm()`** — card search folds diacritics + drops apostrophes ("te ka"→Te Kā, "andys room"→Andy's Room). Applied in `nameMatches` + `matchesCardFilter` haystack/contains + both quick-search rankers. Home/avatar suggestion cap 8→20.
- **Image export helper `deliverImage()`** — desktop=sync clipboard, touch=`navigator.share({files})`→`ImageSaverOverlay` long-press fallback (fixes the iOS mover-camera). Card-detail image falls back to a plain `<img>` if the canvas crossOrigin art fails.
- **`UpcomingSCsBox`** — title click → full-screen MODAL box over a dimmed backdrop (click-away/Esc → home); deep-link `?sczip/scc/scdist/scdate`; per-event time; pin-to-top; copy-link.
- **Onboarding tours — LIVE (welcome reworked again 2026-08-21).** `TOURS_ENABLED = true` (hard const, no localStorage gate). The welcome is now ONE screen, not a carousel: `WELCOME_FEATURES` renders four clickable jump-in rows (NAV_ICONS glyphs; `onGo` closes + navigates) plus the primary **"🧭 Show me around"** CTA that starts the guided **site walk**. Fires ONCE at the end of a new account's onboarding chain (name prompt → avatar picker → welcome; `welcomeAfterOnboarding` ref) — never on anonymous first paint. Per-section `COACH_TOURS` (home/cards/screener/history/market/collection/decks) auto-fire once per section, max ONE per browser session (`sessionStorage packsink:autoTourFired`), home exempt, `requiresUser` (collection) waits for sign-in. `Coachmark` drops steps whose selector doesn't resolve at open (aborts without marking seen via `onAbort` if none resolve); it also takes `onDone`/`progress`/`doneLabel`/`skipLabel` for walk mode. Floating 🧭 launcher renders until that section's tour is seen; hidden ≤700px. Help page `.faq-tours` strip: welcome + **Full site walkthrough** + every section. Selectors verified against live DOM 2026-08-21 — keep them in sync when renaming toolbar classes.
- **Guided site walk (2026-08-21).** `SITE_TOUR_ORDER` chains the section coachmarks across views: home → cards → screener → history → decks → market → collection, each stop's last Next reading "Next: <section> →". App state `siteTour {stops, i}`; stops are frozen at start (requiresUser sections dropped for signed-out walkers). Each stop's coachmark mounts on a **growing retry ladder** (900/1700/2800/4200ms, `siteTourAttempt`) because the Screener's shell doesn't render until its movers fetch lands (~1.6s cold) — a single quick retry made the walk skip it. Esc / dim-click / "End tour" ends the walk; the user navigating away mid-walk also ends it AND burns the session's auto-fire flag (so the section they escaped to doesn't immediately pop another coachmark). Sections the walk shows are marked `sectionTourSeen`. **Demo collection**: while the walk runs and a signed-in user's real collection is EMPTY, `buildDemoCollection(raw)` (deterministic ~40 cards from the two newest *priced* mainline sets — prestaged pre-order sets skipped) is swapped in at the CollectionView render site with no-op mutators + a `demoMode` banner, so the Collection stop doesn't tour an empty page; it vanishes when the walk ends and can never write to the DB.
- **Elo event roster / field scouting (LIVE):** migration 68 + `get_event_roster` RPC + `scripts/elo/scrape_rosters.py` + `refresh-elo-rosters` edge fn (verify_jwt=false) + `EloEventRoster` UI. RPH `/events/{id}/registrations/` is CORS-blocked → server-side scrape only.
- Also: `scripts/synthetic_monitor.py` (+ workflow, every 2h), tournament `ArchetypeBreakdown`, deck shop-missing name-aggregation, F4 keyboard shortcuts (`/`, `?`).

- ~~**`supabase/125_deck_versions.sql`**~~ — **APPLIED 2026-08-24 by Zaven.**
- ~~`supabase/126_deck_versions_grants.sql`~~ — **APPLIED 2026-08-24 by Zaven; verified** (an authenticated read of `deck_versions` returns 200, was a flat 403). Original note: 125 created `deck_versions` with RLS policies but **no table GRANT**, so an owner reading their own history gets a flat 403 (`42501`) before RLS is ever consulted; Postgres's own hint names the fix. Same rule CLAUDE.md already states for matviews: a new relation grants nothing implicitly. Until it lands the History modal shows its "isn't switched on yet" branch — `deckVersionsUnavailable` can't tell "no such table" from "no permission", and shouldn't try. It also deletes one empty probe row left behind while diagnosing.

**Migration ledger.** Claude applies migrations itself, drops included (Zaven, 2026-09-30: *"im fine with claude having access to do everything"*) — see "Running SQL" under Ops for the two routes. A file is STAGED only when something outside the database has to happen first.
- ~~`supabase/193_elo_view_fixes.sql`~~ — **APPLIED 2026-10-07** through the connector; verified. Three wrong numbers on the
  public Elo board, all in the views: `elo_leaderboard_v` took a player's last rating in (date, round) order
  instead of elo.py's (date, event_id, round, table, match) order, so 16 players who played two events on one date
  read wrong (AlecM 1668 -> 1627); its GW% ignored games played under a merged account (SunnyDay 72.4% -> 65.0%);
  and `elo_event_summary_v`'s Avg Elo used each player's LOWEST rating in the event, not their starting one
  (CT's Hobbies 9/27: 1582 -> 1597). Proof the order is right: under it all 56,586 ratings chain (each
  rating_before = the previous rating_after; the old order broke 3,005 times), and the board now sums to exactly
  2160 x 1500, as a zero-sum pool must (it summed to 3,240,160). Grants and security_invoker survived the replace.
- ~~`supabase/192_collection_scoped_share_tokens.sql`~~ — **APPLIED 2026-10-06** through the connector. Backward
  compatible: the five collection readers accept the base token as before, plus a scoped token (HMAC of the
  scope under the base) for their own section; new owner RPC `get_my_collection_share_tokens()`. Live client
  unaffected; the share popover that hands out scoped links ships with the same commit. Run against PGlite
  (28 checks). Verified live over all 123 profiles: the base token gives exactly the old visibility (0
  mismatches), a Cards-scoped token opens Cards only and a Sealed+Graded one only those (0 mismatches), the
  SQL token matches Node's HMAC byte for byte, the token check runs once per call on the profile row (not per
  collection row), and anon cannot call the owner RPC.
- ~~`supabase/191_admin_checks_caller_only.sql`~~ — **APPLIED 2026-10-06** through the connector.
  `is_tournament_admin(uuid)` / `is_elo_admin(uuid)` return false for any id but the caller's when asked from
  anon / authenticated (they are the only role checks that take a user id). Every caller already passes its
  own id. Run against PGlite (22 checks, incl. RLS policies, a definer admin RPC and `can_scout`). Verified live
  by a rolled-back probe: another account asking about the admin gets false, the admin about themself true,
  `can_scout()` still true for them, server-side still true.
- ~~`supabase/190_anon_write_fair_limits.sql`~~ — **APPLIED 2026-10-06** through the connector. Server-only:
  `_rate_bucket` (account when signed in, address otherwise, IPv6 per /64; an IPv4 bucket hashes exactly as
  before) and a `signed_in` column on `trade_create_events` / `feedback_submit_events`, so `create_trade` and
  `_feedback_rate_limit` keep two backstop pools with a fair share past half the cap. Same messages, same
  signatures. Checked first: a forged `CF-Connecting-IP` is refused by Cloudflare (403, error 1000) and a
  forged `X-Forwarded-For` only prepends, so `_client_ip()` was already unspoofable. Run against PGlite (26
  checks). Verified live by a rolled-back probe (the trade and both event rows land in the right buckets;
  nothing left behind) and an anon REST call.
- **`supabase/189_attendance_anon_columns.sql`** — **STAGED 2026-10-06, apply after the client from the same
  commit is LIVE** (deployed + edge purged; give open tabs a day). It revokes the table-wide SELECT on
  `rph_event_attendance` from anon / authenticated and grants back only `event_id, person_key, played,
  registration_status`. Applied before that client ships, the live Store Status tab 42501s (it still selects
  `best_identifier, rph_user_id` and filters on the standings). Rollback is one line in its header.
- ~~`supabase/188_attendance_person_key.sql`~~ — **APPLIED 2026-10-06** through the connector. Additive:
  `private` schema + `private.server_secrets` (random 32 bytes, no API role can read it), and on
  `rph_event_attendance` a trigger-filled `person_key` (HMAC of the old client key) and a stored generated
  `played`. Verified live: 28,975 rows keyed, 2,635 distinct people under both keys and 2,635 distinct pairs
  (a bijection), `played` equals the old filter on every row, and the Store Status pivot over the old and new
  reads agree on all 107 stores. Run against PGlite first (43 checks, 188 and 189 both twice).
- ~~`supabase/187_starter_deck_foil_rekey.sql`~~ — **APPLIED 2026-10-07 00:3x UTC, right after the v532 deploy;
  verified: 47 rows / 9 users / 55 cards now Holofoil, none left on Cold Foil.** Written as STAGED: apply right after the deploy that
  ships the Starter Deck Foil client change (EXTRAS_MAP `printing:"Holofoil"`). Moves the 12 Starter Deck Foil
  collection entries from Cold Foil to Holofoil (47 rows, 9 users on the day; a Holofoil row made in between
  keeps the larger count). Before the deploy the live client still keys these as Cold Foil, so applying it
  early shows those owners' tiles as unowned until the deploy lands.
- ~~`supabase/186_latest_raw_prices_before.sql`~~ — **APPLIED 2026-10-06** through the connector. Additive:
  `latest_raw_prices_before(pids, printings, before)`, one index probe per key, used by
  `fetchCollectionPriceSeeds` to seed the value charts with each owned item's price going into the range.
  ~0.2-0.4s per 250 keys; capped at 500 per call. Client tolerates its absence.
- ~~`supabase/185_security_hardening.sql`~~ — **APPLIED 2026-10-06** through the connector, from a database
  security review: the tier-list view counter returns before writing a mark for a slug that isn't an openable
  list; `scout_event_meta` is service-role only (its callers are definer functions and the edge function's
  service client); `scan-samples` objects capped at 1 MB (real max 506 KB over 3,546); TRUNCATE / REFERENCES /
  TRIGGER / MAINTAIN revoked from anon + authenticated on all 81 public relations and in postgres's default
  privileges. Verified live: 0 relations left with TRUNCATE, normal grants intact, public reads 200.
- ~~`supabase/184_tier_list_hardening.sql`~~ — **APPLIED 2026-10-06** through the connector. From a review of
  the Tier List maker: the 500-list cap no longer fails edits (only new lists), `forked_from` names a
  parent only while it is public, an owner cannot like their own list, views count once per list per
  viewer (user, or hashed IP via `_client_ip()`) per day in `custom_tier_list_view_marks`, and
  `tier_lists` loses anon writes and TRUNCATE. Run against PGlite with RLS first (26 checks). It changed
  no live rows (2 lists, no copies, likes or views yet). Verified live by an anon REST probe on a
  nonexistent slug (two calls, one mark; probe row deleted after).
- ~~`supabase/178_challenge_c3_set.sql`~~ — **APPLIED 2026-09-30** via `scripts/sql.py`. The C3 set row; its two
  cards are inserted by `patch_pid_overrides.py` on the next daily metadata run from `main`.
- ~~`supabase/177_admin_exec_sql.sql`~~ — **APPLIED 2026-09-30** through the connector. The service-role-only
  `admin_exec_sql()` behind `scripts/sql.py`; see "Running SQL".
- ~~`supabase/176_into_the_inkdark_set.sql`~~ — **APPLIED 2026-09-30** through the connector. A set row
  for Into the Inkdark (set 15, `set_into_the_inkdark`, code NULL like Hyperia City's was) so
  TCGplayer group 24890 binds and its sealed products stop loading with no set.
- ~~`supabase/175_discord_report_latest.sql`~~ — **APPLIED 2026-09-30** through the connector. The
  latest daily and weekly Discord report, kept for `/reports send`, plus the public
  `discord-reports` storage bucket for its pictures. Additive only. Safe in either order:
  before it lands the report job prints that `/reports send` stays off and posts to
  subscribers as before, and the command answers "isn't switched on yet".
- ~~`supabase/174_calendar_chattanooga_london_youth.sql`~~ — **APPLIED 2026-09-25 by Zaven; verified
  via REST** (both rows read back: Chattanooga CCQ confirmed Nov 7-8, DLC London carries the Youth
  Division notes; re-checked 2026-09-28). From two Ravensburger OP graphics. ⚠ It was applied under
  the name **169** and renumbered twice before merge (169 → 172 → 174), because main's
  `169_tcgplayer_names.sql`, then `172_price_movers_freshness.sql` and `173_discord_reports.sql`,
  took those numbers first. Same SQL, and re-running it is safe.
- ~~`supabase/173_discord_reports.sql`~~ — **APPLIED 2026-09-28 by Zaven; verified** (an anon read answers `42501 permission denied`, i.e. the table exists and stays private).
  Written as 172 and renumbered before any push: `172_price_movers_freshness.sql` (branch
  `claude/suspicious-wilbur-7a848a`) took 172 and was APPLIED the same day.
  `discord_report_subscriptions` (server, channel, cadence, last_posted_on, last_error); RLS on with
  no policies, service_role only. The bot and `discord_reports.py` both treat a missing table as
  "not switched on yet" and stay green. Pure ASCII, short header, per the 142 lesson.
- ~~`supabase/172_price_movers_freshness.sql`~~ — **APPLIED 2026-09-27 by Zaven; verified
  exhaustively on live data** (see "A move has to be OBSERVED inside its window"). Drops
  and recreates `price_movers` with `low_date` / `market_date` and the in-window guard,
  and re-asserts `refresh_price_movers()` with its function-level 5-minute timeout and
  migration 10's anon lockdown. One read around then hit 57014 and the retry succeeded —
  consistent with the rebuild holding the matview's lock, which blocks readers for the
  ~40s a drop-and-recreate takes (not verified; the evening refresh fits too).
- ~~`supabase/171_playmat_sections.sql`~~ — **APPLIED 2026-09-27** through the Supabase connector.
  Widens `playmats_section_chk` to allow `disney` and `ravensburger` (Zaven's own headers for the
  shop exclusives); nothing else. The catalog was reloaded under it the same day.
- ~~`supabase/170_playmats.sql`~~ — **APPLIED 2026-09-27** through the Supabase connector (additive:
  a new table, its read policy and grants, and the `playmat_prices_latest` view). Loaded the same
  day: 63 mats (`load_playmats.py`), 21,570 prices from the local archive cache plus the
  2026-09-26 publish (`backfill_playmat_prices.py`). Safe ahead of the client — nothing read it
  until the Playmats tab shipped.
- ~~`supabase/168_curators_cc2.sql`~~ — **APPLIED 2026-09-30** through the connector. Creates
  `set_curators_cc2` — "Curator's Collection: Beauty and the Beast" (code **CC2**), the second
  Curator's Collection drop (see 107 for CC1, Heroines). Announced at D23 2026, six premium foil
  reprints at ~$99.99 from a handful of Disney locations starting 2026-10-01; not on TCGplayer at
  authoring time, so `tcgplayer_group_id` is null like CC1's. **After the migration lands, run
  `python scripts/patch_pid_overrides.py`** — the six `REPRINT_PROMOS` entries added the same day
  (Be Our Guest 1/CC2, Mrs. Potts - Enchanted Teapot 2/CC2, Belle - Hidden Archer 3/CC2, Lumiere -
  Fiery Friend 4/CC2, Gaston - Intellectual Powerhouse 5/CC2, Beast - Tragic Hero 6/CC2 — bases
  confirmed against Lorcast: Fabled #31/#121, Ursula's Return #52, Rise of the Floodborn
  #72/#147/#173) are what actually inserts the six card rows; the migration only creates the set
  they hang off. Each carries a repo-local art crop (`Logos/cards/*-cc2-N.jpg`, pulled from the
  D23 reveal video, same "read off the announcement photo" call as PD1 #18/#19) since there's no
  TCGplayer pid yet — fill in the pid and drop the art path once it's listed, same card_id so no
  collection marks move. Added to `SET_ORDER` (after PD1), `UNIFIED_TILE_SETS` and
  `PROMO_RARITY_SETS` (single-printing, promo rarity, same as CC1), plus a `POP_SET_ALIASES`
  entry (`"cc2-"`) for PSA pop parity. The sealed $99.99 box needs no code — same as CC1, the
  generic `"curator's collection" → Collector's Edition` bucket in `load_sealed_products.py`
  picks it up automatically once TCGplayer lists it, per that function's own comment.
- ~~`supabase/163_raw_sales.sql`~~ — **APPLIED 2026-09-20 by Zaven**, and the backfill is
  **loaded**: 78 raw sales across 18 cards, back to 2023-10. `raw_sales` + `raw_sales_rollup` +
  `refresh_raw_sales_rollup()`. **⚠ Its `statement_timeout` is a function-level `SET` clause,
  not a `set local`** — migration 131 had to fix exactly that on the market-index refresh, which
  died at the role default every time because the GUC is armed before the body runs.
- ~~`supabase/159_deck_short_links.sql`~~ — **APPLIED 2026-09-30** through the connector. Short deck links:
  `packs.ink/?d=<12 chars>` instead of the ~100-char `?deck=&token=` link. `deck_short_links` +
  `deck_short_code(deck, token)` (mint, one per deck+token) + `resolve_deck_short_code(code)`. A
  code dies with its token, so the existing rotate-on-less-visible trigger revokes it. Safe to ship
  the client first: the poster falls back to the full link (minus `https://`), and an unresolvable
  `?d=` lands on `/decks`.
- ~~`supabase/152_calendar_dlc_nanjing.sql`~~ - **APPLIED 2026-09-30** through the connector.
  One row: DLC Nanjing, 21-22 Nov 2026, at `confirmed = false` so it is admin-only
  until ruled on in the /calendar editor. Pure ASCII, short header, per the 142
  lesson. **⚠ It was WRITTEN as 150 and renumbered before merge**: a concurrent
  session landed `150_calendar_official_challenge_page.sql` on main while this
  branch was open. Both are real, unrelated, and both want running - the number
  was the only thing broken. A reference to "150" written before 2026-09-14 may
  mean the Nanjing row; every one in this file now says 152.
- **There is no 151.** A `151_calendar_custom_events.sql` was staged on 2026-09-14
  for a personal add-your-own-event feature, and both were DELETED the same day:
  Zaven's *"I dont mean own event"* corrected the reading the feature was built
  from. Nothing of it shipped, so nothing to unwind — and the local-shops work
  that replaced it needs no migration at all.
- ⚠ **Numbers 143 and 144 each have TWO files** — the scouting pair below and the calendar's
  `143_calendar_geo.sql` / `144_calendar_hide.sql`, written by a concurrent session the same day
  (as 139 already had two). **Always say the FULL FILENAME**, never "run 144".
- ⚠ **150 nearly became the third, and the near-miss is the lesson.** Two sessions each wrote a
  `150_*` on 2026-09-14 - `150_calendar_official_challenge_page.sql` (merged to main) and the
  Nanjing row (this branch) - and nothing anywhere errors when that happens: both files apply
  fine, and it is the ledger and any "run 150" instruction that break. Caught before merge and
  the branch's became **152**, so only one `150_*` exists. **Take the next number from
  `ls supabase/*.sql | tail` at the moment you COMMIT, not when you start** - a branch open for
  a few hours is long enough for the number you picked to be taken.
- ⚠ **Granting someone the scouting feature is a PASTE, never a migration — this repo is
  PUBLIC.** `scout_members` is an EMAIL allowlist, so a seed file is fourteen real people's
  addresses in a git history that is permanent and world-readable. A session wrote exactly that
  as `149_scout_members_seed.sql` (PR #52, closed unmerged 2026-09-13) and it had already been
  pushed to a public branch before anyone looked — **`refs/pull/52/head` keeps it fetchable even
  now**, because GitHub retains pull refs after the PR closes and the branch is deleted. So
  there is no number 149: the grant lives at `Desktop/scout_members_seed.sql`, outside the repo,
  and the ledger carries the gotchas instead of the data. Add people from the admin panel's
  **Who can scout** box; reach for the file only for a bulk paste.
  - **⚠ It is a SEED, not a reconciler.** Re-running RE-ADDS anyone an admin has since removed,
    because a removed row is deleted and so conflicts with nothing. `on conflict do nothing`, so
    a re-run cannot clobber a note edited since. Both verified against a throwaway Postgres 16
    running 143's own table text.
  - **⚠ A wrong address fails SILENTLY** — `can_scout()` returns false and the Scout tab simply
    is not rendered, so if a teammate reports it missing, the address is the first thing to
    check. Sign-in is Google OAuth only, so a non-gmail entry (comcast.net, yahoo.com) matches
    only if that address is itself a Google account; and **Gmail ignores dots in the local part
    but the JWT does not** — someone who signed up as `codybraun1@` is not matched by
    `cody.braun1@`. Confirmed against the real function. Either way the fix is one row.
- ~~`supabase/148_scout_any_event.sql`~~ — **APPLIED 2026-09-12 by Zaven.** Lets a scout add ANY
  event to scouting by hand: `scout_events` (the opt-in ledger), a widened
  `scout_event_meta`, `scout_event_add` / `scout_event_remove`, and the slate + sheet
  carrying the `Added` mark. The automatic tracked-store scope is untouched. See
  "Scouting an event outside the bubble". **It is a SUPERSET of 144 and 147 for the
  scouting functions**, so `144 → 147 → 148` in ascending order is right and pasting
  **148 alone** is also right. ⚠ **If any of these is ever re-run, never run an EARLIER
  scouting file AFTER it** — that costs the hand-added events on the tab (147) or the
  "added by" line (144), never the gate, which is verified. That is the repo's standing
  re-running-an-old-migration hazard, and it applies after the fact as much as before.
- ~~`supabase/147_scout_window_24h.sql`~~ — **APPLIED 2026-09-12 by Zaven.** The Scout tab's
  slate keeps an event for **24 hours past its start** instead of dropping it the
  minute the doors open: `get_roster_scout`'s window goes from
  `start_datetime >= now()` to `>= now() - interval '24 hours'`. Reported from the
  floor — three 3:00 PM SCs were on the tab at 2:59 and gone at 3:00, which is the
  exact moment a scouting sheet starts being useful. **Only that predicate
  changes**; the body is 143's verbatim, and the test asserts it. Independent of
  144_scout_off_roster.sql (which never touches this function). **148 contains this
  change, so never re-run 147 AFTER 148** — it would drop the hand-added events from
  the slate.
- ~~`supabase/144_scout_off_roster.sql`~~ — **APPLIED 2026-09-12 by Zaven.** Fixed a SILENT
  data-hiding bug in 143 found on review: the panel listed only the roster, and
  the roster scrape is delete-then-insert, so a note about a player who dropped
  their registration stopped rendering on its own event while staying in the
  table and in that player's history. `get_scout_event` is re-created to union
  the roster with this event's notes (`off_roster` marks which), which also
  enables **Add player** for someone RPH never recorded. Plus
  `scout_member_delete(uuid)` so the admin panel's Remove works on a row added by
  user_id. **148 contains this file's `get_scout_event` and `scout_member_delete`, so
  never re-run 144 AFTER 148** — it would drop the "added by" line from the sheet header.
- ~~`supabase/143_scout_team.sql`~~ — **APPLIED 2026-09-12 by Zaven; verified via
  anon REST probes**: all ten functions answer `42501 permission denied` rather
  than `PGRST202`, and `scout_notes` / `scout_members` are unreachable directly.
  The team scouting feature: `scout_members` (the email allowlist), `scout_notes`,
  `can_scout()`, `scout_event_meta`, `get_scout_event`, `save_scout_note`,
  `get_scout_player`, the three admin member RPCs, a re-created `get_roster_scout`
  (LEFT JOIN + the scout gate), and the `elo_event_roster` FK drop. See "Scouting
  is a TEAM tool now". **Still outstanding: redeploy `refresh-elo-rosters`** —
  the per-event roster refresh falls back to refreshing every tracked SC, and for
  a scout who is not also a store-report viewer it just 403s (reported from the
  floor 2026-09-12; the toast now says which, see "Pulling a roster on demand").
- ~~`supabase/139_calendar_events.sql`~~ — **APPLIED 2026-09-12 by Zaven** (this entry
  said STAGED until 2026-09-12 while 142's own note already recorded an anon read of
  `calendar_events` returning 34 rows — the ledger contradicted itself for a day). The
  curated calendar (sets / products / DLCs / CCQs) + the two championship rows already
  committed in `EVENT_TILES`.
- ~~`supabase/144_calendar_hide.sql`~~ — **APPLIED 2026-09-12 by Zaven.** Widens
  `calendar_subscriptions.kind` to allow `'hide'`, so a hide follows you between
  devices instead of staying on one.
  **⚠ Its NUMBER collides** with a concurrent session's
  `144_scout_off_roster.sql` (and `143_calendar_geo.sql` with `143_scout_team.sql`).
  Numbering is first-come across sessions and nothing enforces it, so say the
  FULL FILENAME when asking for one of these to be run.
- ~~`supabase/146_hyperia_city_dates.sql`~~ — **APPLIED 2026-09-12 by Zaven.** One UPDATE, correcting 141's
  note on the Hyperia City prerelease row, which says its LGS and retail dates are unpublished —
  they now are, and the calendar shows them two lines below it. Seeds no dates (they live in
  `SET_RELEASE_DATES`); a no-op where 141 never landed.
- ~~`supabase/145_calendar_image.sql`~~ — **APPLIED 2026-09-12 by Zaven.** One nullable
  `calendar_events.image_url`, the per-event art override. `CAL_COL_LADDER` still drops
  the column on 42703, so a database without it falls back to the automatic match or the
  glyph. Its header carries the two rules that
  are easy to get wrong later — don't store a Disney/Ravensburger mark in it, and
  the host must be in the CSP `img-src` in BOTH copies in `_headers`.
- **`supabase/142_calendar_geo_and_read_fix.sql`** — **HALF-APPLIED.** Its policy
  fix IS live (2026-09-12, verified: an anon read of `calendar_events` returns 34
  rows where it used to raise 42501). Its `alter table` half never ran — selecting
  `country` still gives 42703 — and two attempts at the whole file failed with no
  error reaching me. **Don't re-run 142; run 143.**
  The bug it fixed is worth keeping written down: 139's SELECT policy read `to
  anon, authenticated using (confirmed or is_graded_admin())`, but migration 134
  revoked EXECUTE on that function from anon — so an anonymous read did not get
  `false`, it RAISED 42501 and the whole curated calendar was invisible to
  everyone not signed in. Every other policy in the repo that calls that function
  is scoped `to authenticated`; that one wasn't.
- ~~`supabase/143_calendar_geo.sql`~~ — **APPLIED 2026-09-12; verified** (geo
  populated, 0 rows still naming the source, the only row without a country is
  the Hyperia City prerelease, which is correct — a set releases worldwide).
  It was 142's unapplied half re-issued **in pure ASCII with a short header**;
  142 itself failed twice with no error text, and that was the difference, so
  **prefer plain ASCII and a short preamble for anything meant to be pasted.**
- ~~`supabase/139` / `140` / `141`~~ — **APPLIED 2026-09-12 by Zaven.**
  141 seeded the Season of Villainy (14 CCQs + 17 DLCs, plus Hyperia City's
  prerelease weekend from our own feed). Its ids are
  `uuid5(6b3e1d2a-…, '<kind>:<title>')` so a re-run updates in place, and its
  conflict clause deliberately does not touch `url`, `event_id` or `confirmed` —
  a re-seed must never undo what a person or the linker added on top. 142's
  provenance rewrite depends on 141 having run, so keep the order.
- ~~`supabase/140_calendar_subscriptions.sql`~~ — APPLIED 2026-09-12. The
  per-user layer (followed stores, pinned series, saved events) + a
  `(store_id, start_datetime)` index on `lorcana_events`, which is the query the
  feature is built on and the one 113 does not have. Also safe to ship first:
  without it the client stays on localStorage, which is exactly the signed-out
  path, so nothing breaks — follows just don't travel between devices yet.
- ~~`supabase/127_watchlists.sql`~~ — **APPLIED 2026-08-25 by Zaven.** Watchlists + items.
- ~~`supabase/128_market_index.sql`~~ — **APPLIED 2026-08-25 by Zaven**, then superseded by 130 the same day. Do NOT re-run it: its flat `MIN_COMPONENTS = 20` is the bug 130 exists to fix, and re-running would silently empty every narrow scope again.
- ~~`supabase/129_price_alerts.sql`~~ — **APPLIED 2026-08-25 by Zaven.** Alert rules + firing ledger.
- ~~`supabase/130_market_index_scopes.sql`~~ — **DDL APPLIED** (confirmed 2026-09-01: `universe` is present in the live PostgREST schema for both matviews, and 128 had no such column). But it is a **two-step** migration and **step 2 was never run**, so both matviews sat empty from the day it landed until 131 — every read a 500 (`55000 … has not been populated`), and the Screener's vs-Mkt column plus Price Graphing's benchmark picker / By Index mode silently showed nothing. Nothing alerted: the client returns `null` on the failure path, so there was no crash to notice.
- ~~`supabase/139_collectible_boards.sql`~~ — **APPLIED 2026-09-12 by Zaven.** Where pins and lore counters
  sit on the Pins & Counters boards: `collectible_boards` (owner-only RLS, grants in the same
  file) + `get_shared_collectible_boards` for viewers. Safe to ship the client first — until it
  lands, boards save on the device and the tab says so. See "Pins & Counters".
- ~~`supabase/137_amazon_stock_checks.sql`~~ — **FULLY APPLIED 2026-09-26; verified.** Until then it was
  only half on the live database: `select=msrp` answered `42703 … msrp does not exist`, so the in-place
  extension below had never reached it, whatever this entry said. Zaven re-pasted the (idempotent) file
  and the same read with the public key now returns rows with `msrp` and `price_over`. The lesson: an
  in-place extension of an applied migration needs its own paste and its own probe. Original entry: the manual Amazon stock
  **and price** check: anon-readable, graded-admin writes. **Extended in place 2026-09-12**
  with `msrp` + `price_over` (the 20%-above-MSRP ceiling) rather than followed by a new
  migration — the whole file is idempotent (`create table if not exists`, `add column if not
  exists`, `drop policy if exists`), so running it once is the install and running it again is
  the upgrade, whichever state the database is in. Until it lands, `/gear`'s admin checklist
  says "apply migration 137" and nothing is ever hidden. Safe to ship the client first.
- ~~`supabase/138_feedback_threads.sql`~~ — **APPLIED 2026-09-11 by Zaven; verified via REST
  probes** with the publishable key: the unread count and the thread list return 200, both the
  4-argument and the old 3-argument `submit_feedback` call shapes resolve (each raises `empty
  feedback` before any write), a follow-up on a nonexistent thread raises `feedback not found`,
  and anon is refused both admin functions with `42501`. Feedback replies and follow-ups:
  `feedback_messages`, the unread columns on `feedback`, and nine functions (see "Feedback
  replies").
- ~~`supabase/136_elo_player_rounds_intentional_draw.sql`~~ — **APPLIED 2026-09-12 by Zaven.** Appends
  `is_intentional_draw` to `elo_player_rounds_v` so the profile prints `ID` instead of `DRAW`.
  `create or replace view` (not drop+create — the view may have dependents, and replace allows a
  column appended at the END); the body is migration 62's verbatim plus one trailing column per
  UNION half, `false` on the bye half. Safe to ship the client first — the fetch retries without
  the column on 42703.
- ~~`supabase/135_elo_intentional_draws.sql`~~ — **APPLIED 2026-09-08 by Zaven; verified** (`information_schema.columns` shows `is_intentional_draw` boolean default false on `elo_matches`). Adds the column the site needs to SAY a draw was agreed. **Live since the 2026-09-08 refresh** — `refresh_elo.py` flags before `elo.py` on every run, and the first `position-only` pass flagged **1167 of 2548** draws (784 ID-strong, 383 ID-likely).
- ~~`supabase/132_scan_samples_public_beta.sql`, `133_anon_write_backstop.sql`, `134_public_release_hardening.sql`~~ — **APPLIED 2026-09-05 by Zaven**, the diagnostics file first and then the three in order (the agent had no DB access that day, so the diagnostics output was not reviewed; the migrations were staged by the 2026-09-04 public-release audit). 132 = scan-photo upload gate + per-user storage cap (see the scanner section). 133 = the anonymous-write rate limits (`create_trade`, `submit_feedback`) keyed on the FIRST hop of `X-Forwarded-For`, which the caller controls — 133 prefers `cf-connecting-ip` (falls back to today's behaviour if absent) and adds a global hourly backstop; its header says how to confirm which header carries the real client IP. 134 = grant/RLS hygiene (revoke EXECUTE from PUBLIC on ~16 functions, drop `notes` from the shared-collection RPCs, narrow the anon `profiles` column grant, `avatar_url` CHECK, `report_graded_sale` caps, search_path pin, backup-table drop). `supabase/diagnostics/public_release_live_checks.sql` is the read-only companion: paste it FIRST — it answers what the repo cannot (live `scan_samples` policies, the two live-only Elo RPC bodies, PUBLIC-executable functions, which header carries the client IP).
- ~~`supabase/131_market_index_timeout_pin.sql`~~ — **APPLIED 2026-09-12 by Zaven, with step 2** (`select public.refresh_market_index();`) reported run in the same sitting. Not probed from the agent sandbox, which has no egress to Supabase — **the visible confirmation is the Screener's vs Mkt column and Price Graphing's benchmark picker carrying data**; if either is still blank, step 2 did not take and it is safe to re-issue on its own. **It is what makes step 2 possible at all**, so it had to land BEFORE the populate. 130 pinned the refresh's `statement_timeout` with an in-body `set local`, which cannot work: `statement_timeout` is armed when the outer `select refresh_market_index()` begins, and changing the GUC part-way through does not re-arm the running timer — so the refresh died at the role default (measured: 8s → 57014, reproducibly, every attempt). Every refresh function that WORKS pins it as a **function-level `SET` clause** instead (migration 25, restored by 109). Proof it is the placement and nothing else: `refresh_price_movers` carries the identical `begin … exception … end` sub-block, pins at the function level, and completed a **38-second** refresh over the same PostgREST path with the same key. **Read the migration-109 lesson as "pin it as a function-level SET clause", not merely "pin it".** 131 also swaps the exception-driven CONCURRENTLY probe for an explicit `relispopulated` check, since on a WITH-NO-DATA matview the first CONCURRENTLY attempt is guaranteed to raise and the happy path was an error path. **Two steps**: paste 131, then run `select public.refresh_market_index();` separately (first run is non-concurrent and slow). After that the ETL selfheal job keeps it current — the "Refresh market index" step is `continue-on-error` on purpose, per the rule that this one refresh must stay optional.
- ~~`supabase/112_drop_legacy_graded_feed.sql`~~ — **APPLIED 2026-08-22 by Zaven; verified via REST probe** (`graded_prices_daily` / `graded_prices_latest` both 404; `graded_sales_rollup` + `card_prices_latest` healthy). The 70,990-row archive remains at `Desktop/graded_prices_daily_archive_20260729.jsonl` (18.9 MB).
- ~~`supabase/123_drop_prerelease_events.sql`~~ — **APPLIED 2026-08-22 by Zaven; verified via REST probe** (404). Its precondition (retiring `discover_prereleases.py`'s `main()` upsert; the script is analysis-only now, `discover_events.py` owns the daily write) shipped the same day in `536c639`.
- **`supabase/119_feedback_service_role_read.sql`** — APPLIED 2026-08-10. `service_role` can now read + update `feedback`, so the queue is reachable from a script instead of only the in-app admin inbox.
- ~~`supabase/120_price_movers_full_catalog.sql`~~ — **APPLIED + client pushed; verified live 2026-08-20** (anon REST probe: `price_movers` count = 5,871, inside the expected ~5,500–5,900). The Screener's client-side follow-through is also complete: `sbFetchAll` paginates the now-5.8k-row fetch, the default `$5` min-price floor renders as a visible "Low ≥ $5 ✕" chip in the `price-db-hiddenfilters` strip (plus the zero-results empty state names it), and the count reads "X of N" when any filter narrows the view.

**Active roadmap — where to keep going (2026-06-14):**
1. ~~Apply migration 67 (rls_auto_enable revoke)~~ — DONE / confirmed live (2026-06-27 audit).
2. ~~Enable tours~~ — DONE 2026-07-14 (full rework + enabled; see the tours bullet above).
3. **Build F9 movers digest + F10 set-completion meter** (specs in the feature-brainstorm memory). F6 portfolio P/L, F7 price alerts, F8 CSV round-trip, F12 deck sparkline also parked.
4. **SC localized set names + stale-row pruning** (discover_scs follow-ups). Optionally narrow Elo tracked stores to IL-only (roster currently covers IL/IN/WI/MI).

**iPhone bugs to verify after the 2026-05-26 deploy lands** (may already be resolved by the tap-target / safe-area / sticky-overlap fixes — retest before doing more work):

- **Recent Set EV panel off-center on home (Photo 2)** — deferred pending safe-area retest. Likely resolves incidentally.
- **Profile pill click "spawns a duplicate username" on iPhone (Photo 4)** — was probably a half-tap registering twice on a 28×28 hit area; now 36×36. If it persists, dig into the profile-pill click handler / settings-popover mount logic.
- **Tournament Results panel rendering twice on mobile** — attributed to stale service-worker cache serving an older Index.html. Force-quit PWA twice (let v68 take over). If it persists, real component-mount bug.

**Top of the list:**

- ~~Domain transfer Netlify → Cloudflare~~ — **DONE 2026-08-04**, packs.ink is served by the Cloudflare Worker. See "Deploying" above. Remaining Phase 4: add a Cloudflare **www → apex redirect rule BEFORE decommissioning Netlify** (Netlify's load balancer is what serves www's 301 today, so killing it first breaks www). Never enable free Bot Fight Mode — it has no skip rules and breaks native card art.
- **Card scanner** — SHIPPED as a public beta 2026-08-04 (see "Card scanner" above). ✓-row precision measured 2026-08-23: **v16 = 98.2% (167/170), 95% lower bound 95.7%** — clears the bar, and `SCANNER_QA_ONLY` is now permanently true by product decision (review-before-save), so that measurement gates nothing. Remaining: on-device detection tuning; foil/glare reads; the 3 known misses are all name/art collisions between distinct cards.

**Nice to have:**

- Sim a pack inline button on each row in Playset Cost / Set Values.
- Deck-list cost-curve sparklines on the Decks tab list (currently only in editor).
- More Extras & Oddities curation — re-run audit scripts periodically.
- Floor-coverage indicator on Screener (1 lonely listing vs 10 sellers at the floor). Needs TCGCSV `/products`.
- Stale-data warning per row on Screener — flag rows whose `low_today` is > 3 days old.
- Deck-notes-popover may collide with iOS keyboard when its `<textarea>` is focused (mobile-audit finding #8 from 2026-05-26). Hasn't been observed in the wild; flagged for if it surfaces.
- Sweep dynamic-string overflow on long deck names / tournament names / usernames in narrow flex contexts — make sure they all get `flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis`.

**Quality / operational:**

- Re-run [supabase/diagnostics/index_usage_audit.sql](supabase/diagnostics/index_usage_audit.sql) once stats age past ~13 days, drop unused.
- EV % change pills can underreport for newest set (`evFromBucket` reads `rarity_avg_daily` with no Low↔Market fallback).
- ~~Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6 in `etl.yml`~~ — DONE 2026-06-13 (C8).
- **The cron-job.org GitHub PAT (`packsink-etl-dispatch`) has NO expiration date** — verified on the GitHub fine-grained-tokens page 2026-08-22, with Zaven looking at it. Every earlier note claiming "issued 2026-05-24, 90-day expiry, dies ~2026-08-22" was WRONG (it described intent, not the token as created) and triggered a false fire-drill at the 8/22 pre-launch audit. Nothing expires; the ETL keeps running on it indefinitely. Token lives in each of the 5 cron-job.org jobs' `Authorization: Bearer <token>` header. **Zaven's call 2026-08-22: keep it non-expiring — no rotation planned.** Don't re-raise this as a to-do. If the token is ever revoked/broken, the ETL silently falls back to the GitHub `schedule:` safety net (hours late, not never) and cron-job.org emails failure alerts; health check = `gh run list --workflow=etl.yml` showing `workflow_dispatch` runs at 20:30 / 22:00 / 22:30 UTC.
- ~~5 `.bak` PNG icon files at repo root~~ — confirmed already gone from disk (2026-06-27 audit); nothing to delete.
