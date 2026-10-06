# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## How these notes are organised (2026-09-30)

This file is loaded into every session, so it holds RULES: the things that are wrong to break and not obvious from the code. The long write-ups (why a feature is shaped the way it is, what was measured, what was tried and reverted) live one file per feature in **`docs/claude/`**. A section below that says "Full notes:" is a stub: the pointer, its guard tests, and the rules that bite most often. **Open the full file before changing that area** — the stub is a reminder, not the whole contract.

- A new note goes in the feature's file under `docs/claude/`; add a line here only when it is a rule another session could break without knowing.
- The migration ledger and the roadmap are in `docs/claude/pending-roadmap.md`. Take the next migration number from `ls supabase/*.sql` at the moment you commit.
- `node scripts/test_claude_docs.mjs` fails if a stub points at a missing file or this file grows past 200 KB again (it was 793 KB).

## ⚠️ Push policy — NEVER push without explicit user OK

Netlify is on a metered build plan and Zaven is on limited credits. Every `git push origin main` triggers a deploy that costs build minutes. **Default behavior: commit locally, then STOP and ask before pushing.** Batch pushes to the end of a session (or across multiple sessions) so one deploy carries multiple commits.

The classifier reinforces this: even with `Bash(git push:*)` in `.claude/settings.json`, the classifier may still block individual pushes when it judges them unauthorized. Treat the rule above as the source of truth — don't try to push silently just because the rule allows it.

Exception: explicit user instruction in the current turn ("push it", "ship this", "deploy now"). Anything less = commit only and report what's staged for the next push.

### "Push" means SHIP, end to end (standing instruction, 2026-08-20)

Zaven: *"whenever I say push please do everything such that it'll be live."* So the word is not a request for `git push` — it authorizes the whole chain, and stopping halfway leaves prod stale while the work reads as done:

1. Push the branch.
2. Merge its PR to `main` (squash — main carries ~one commit per PR).
3. **Run the deploy** — Actions -> *Deploy to Cloudflare* -> `confirm: deploy`, `purge: true`. A merge ships nothing on its own; see "Deploying" below.
4. **Verify the edge**, don't assume it. The workflow's verify step does this; if you deployed by hand, `curl -s https://packs.ink/__nope-$RANDOM | grep -o 'styles.css?v=[0-9]*'` hits the SPA fallback on an uncacheable path and shows what the Worker is really serving.
5. Report the version actually live.

This does NOT weaken the rule above: without the word, still commit and stop. It only settles what the word means once it is said.

## Stack

- **Frontend**: `Index.html` + `styles.css` + `logo.js`, React via `htm` template literals, no build step. Served by `python scripts/dev_server.py` (port 8766 — AnkiConnect squats 8765; it 404s any path with a dot-segment, because it used to serve the repo-root `.env` — the service key — to anything on loopback, 2026-09-27). CSS extraction is deliberate for caching + editor sanity — do NOT inline CSS back into Index.html.
- **Prod is the Cloudflare Worker** (`packs-ink`), not Netlify — cutover 2026-08-04. Netlify still exists only to serve `www`'s 301 → apex; see `scripts/CLOUDFLARE_MIGRATION.md`. **Netlify no longer builds anything**: `netlify.toml` carries `[build] ignore = "exit 0"` (2026-09-05) because every push and PR was still running a full metered build + Deploy Preview (whose `_headers` check fails on the Cloudflare-only `!` lines). The last Netlify deploy stays live for the www redirect. Delete the file to build on Netlify again.

### ⚠️ Deploying — a git push does NOT ship the site

`wrangler.toml` says to set the build command in the Cloudflare dashboard so pushes deploy. **That was never done.** Every deployment in the Worker's history is "Manually deployed" via Wrangler. Confirmed 2026-08-10, when prod was found frozen at `packsink-v309` for 5 days while `main` had reached v314 — pushing changed nothing.

```
node scripts/build_dist.mjs && npx wrangler@4 deploy
```

- `build_dist.mjs` is an explicit include-list → `dist/` (55 files). It refuses to build if the native/worker markers go missing.
- **The deploy copy has its comments stripped (2026-09-30).** Comments were 28% of `Index.html` and 30% of `styles.css` (1.06 MB + 248 KB), and every visitor downloaded them. `scripts/strip_comments.mjs` removes them from `dist/index.html` and `dist/styles.css` only; the source files, the guards (which read the source) and the Discord bot's `sitecode.mjs` are untouched. Measured at brotli 5 (about what Cloudflare serves): the two files together go from 1.19 MB to 0.68 MB.
  - **⚠ It uses a real tokenizer (acorn, vendored at `scripts/vendor/acorn.mjs` because `deploy.yml` runs no `npm ci`), never a regex.** The file is full of `//` inside URLs, regex literals and htm templates, and `// proxied to /img-proxy/*` reads as a block-comment opener — the `test_no_emoji.mjs` trap.
  - **Line numbers are preserved** (a comment is replaced by the newlines it held), so a Sentry trace from prod still names the right source line.
  - `stripIndexHtml` re-tokenizes its output and throws if the token stream changed; `build_dist.mjs` then ships that file unstripped with a `::warning::`. A bigger download, never a broken one.
  - **Prod is therefore not byte-identical to the dev server's page.** When a bug reproduces only on prod, `node scripts/build_dist.mjs` and serve `dist/`.
  - Guarded by `node scripts/test_strip_comments.mjs`, which replays it over the real files.
- **A deploy is safe with respect to `.env`.** The runbook warns that Wrangler auto-loads it; verified via `wrangler deploy --dry-run` that the only binding is `env.ASSETS` — no vars, no secrets, and `dist/` contains no `.env` or service key. Re-check with `--dry-run` if `wrangler.toml` ever grows a `[vars]` block.
- **Then purge the Cloudflare cache, or the HTML stays stale.** The deploy updated `sw.js` immediately but `/` kept serving the old document (`CF-Cache-Status: HIT`) with the previous `styles.css?v=`. Because the SPA fallback means every route and query-string variant caches its own copy of the HTML, a by-URL purge misses most of them — use **Purge Everything** (Caching → Configuration). Traffic is ~0.1 req/sec, so the origin-load cost is nil. To tell a stale edge from a stale origin, curl a path that cannot be cached: `curl -s https://packs.ink/__nope-$RANDOM | grep -o 'styles.css?v=[0-9]*'` hits the SPA fallback and shows what the Worker is really serving.
- Rollback: grey-cloud `A packs.ink → 75.2.60.5` in the dashboard. Instant, no redeploy.

**You can also deploy without a laptop: `.github/workflows/deploy.yml` (Actions → Deploy to Cloudflare → Run workflow).** It runs the exact two commands above, purges the cache, then verifies the edge. `workflow_dispatch` ONLY — deliberately never `on: push`, because batching deploys is the point, not an oversight. Type `deploy` in the confirm box; `dry_run` builds and validates without publishing.

- Needs three repo secrets: **`CLOUDFLARE_API_TOKEN`** (Workers Scripts:Edit + Account Settings:Read + Cache Purge:Purge), **`CLOUDFLARE_ACCOUNT_ID`**, **`CLOUDFLARE_ZONE_ID`**. The token is scoped so it cannot touch DNS — it can never perform the grey-cloud rollback, which stays a dashboard action.
- **`Zone → Workers Routes → Edit` was GRANTED to the token 2026-08-23** (edited in the dashboard, packs.ink-scoped, same secret — no roll, so the GitHub secret is untouched). Historical context: the missing permission made every real run of this workflow "fail" after a SUCCESSFUL deploy (found 2026-08-20) — wrangler uploads the script first, then reconciles `wrangler.toml`'s `routes` against the zone; that second call 403'd (`Authentication error [code: 10000]`, `/zones/*/workers/routes`) and the bare non-zero exit skipped the purge and the verify. The deploy step's swallow for that one case (upload succeeded AND the error names `workers/routes`) stays as belt-and-braces; with the grant in place the annotation should simply stop appearing — if it ever returns, the token permission regressed.
- **The verify step is the point of the workflow, not decoration.** It curls `packs.ink/__deploy-check-<random>` — a path that cannot be cached, so it hits the SPA fallback and reports what the Worker is really serving — and fails the run if the served `styles.css?v=` doesn't match what was built. That is the difference between "deployed" and "deployed but the edge is still stale", which is exactly the failure that froze prod at v309 for five days.
- It also warns (never blocks) when the `Index.html` / `sw.js CORE_ASSETS` / `CACHE_VERSION` trio fall out of lockstep.
- **⚠ The verify step is blind to a version that never moved, and on 2026-09-08 two shells shipped as `v377`.** PR #31 and PR #32 each branched from a main at v376 and each bumped to 377; #31 deployed, then #32 merged and deployed, and its verify compared the served `styles.css?v=377` against the built `377` and passed — against the *previous* PR's HTML. Nothing was broken for users (Workers Assets is content-addressed, so wrangler re-uploaded the three changed files, and `Index.html` / `styles.css` / `logo.js` are network-first anyway), but the run proved nothing and the number now names two different shells. **When two PRs are in flight, the second one to merge must bump PAST the version, not to it.** The workflow now records what the edge serves BEFORE deploying and warns when new `Index.html` bytes ship under a version that was already live — the one signal that separates a genuine collision from an innocent redeploy is wrangler's own `+ /index.html` line, which only appears when the bytes actually differ. It stays a warning: by the time it can be known the deploy has already happened and is fine, and it is the label that is ambiguous, not the code.
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog**: `cards`, `sets`, `prices_daily`, `sealed_products`, `graded_prices_daily`, `playmats` (+ view `playmat_prices_latest`; see "Playmats").
  - **User**: `profiles` (carries collection-sharing visibility + share_token cols), `collection_items`, `sealed_collection_items`, `graded_collection_items`, `graded_collection_goals`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`, `screener_views`.
  - **Tournament**: `tournaments`, `tournament_decks`, `tournament_admins`, view `tournament_results_v` (security_invoker on).
  - **Events (RPH)**: `lorcana_events` (migration 113) — EVERY upcoming Ravensburger Play Lorcana event (~17k), `kind` ∈ `sc|prerelease|other`. What the site's "Near me" event finder reads. `set_championships` is the SC subset kept in lockstep for the Elo pipeline only. `prerelease_events` was DROPPED 2026-08-22 (migration 123). See "Upcoming-events finder".
  - **Misc**: `trades` (token-keyed shareable Trade Compare payloads; RLS-locked, access only via `create_trade` / `get_trade` RPCs — migration 54). **30-day retention** via `cleanup_old_trades()` (migration 65), called daily by the selfheal job in `matview_self_heal.py`.
  - **Matviews**: `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`, `graded_prices_latest`.
- **ETL** (`.github/workflows/etl.yml`):
  1. `scripts/etl_tcgcsv_daily.py` — TCGCSV → `prices_daily`, then refreshes the 4 raw-price matviews. Idempotent: skips fetch when today's snapshot is already loaded; exits 0 (not error) when TCGCSV hasn't published yet (>95% byte-identical to yesterday's).
  2. Daily Lorcast metadata refresh: 21:00 UTC (bumped weekly→daily so a pre-order set fills in within a day of each spoiler; deliberately NOT fired by `job=='both'`, which pings thrice daily).
  3. **RETIRED 2026-06-30 — there is no graded ETL.** The third-party graded feed was discontinued; the legacy client paths were deleted 2026-07-29 and `graded_prices_daily` / `graded_prices_latest` were **DROPPED 2026-08-22** (migration 112; archive on Desktop). All graded value comes from the in-house `graded_sales` scrape (see "Graded pricing: legacy vs current"). Its scripts (`etl_tcgpricelookup_daily.py`, `graded_overrides.json`, the `probe_/backfill_/cleanup_*graded*` helpers) were deleted 2026-07-29. A `scrape_stale` finding from the catalog watch is about the IN-HOUSE scrape and is worth chasing; see "Catalog watch".
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed catalog**: `scripts/load_sealed_products.py`.
- **MCP**: Supabase, Sentry and Gmail are **claude.ai account connectors** (claude.ai → Customize → Connectors), so they reach desktop, cloud and phone sessions alike — direct DB query/mutation access without paste-back. **There is no project `.mcp.json`**: its `supabase` and `netlify` entries and a local-scope `sentry` were removed 2026-09-27. The CLI copies' sign-ins had lapsed, so every session opened with "need authorizing" (and signed in, they'd double every tool); Netlify never had a token and stopped building the site 2026-09-05. Don't re-add them — git history has the old file. ⚠ `claude mcp list` does not show the connectors even with the app's environment stripped, so their absence there proves nothing; per the docs a terminal session on the claude.ai login lists them under `/mcp`.

## Native app (Capacitor) — groundwork 2026-07-17

Android/iOS shell around the SAME zero-build web app. **Read `native/README.md` before touching it** (architecture decision, phase roadmap, store checklists). Invariants:

- **appId `ink.packs.app`** — permanent once the first Play upload happens.
- Bundle = `native/www/` (gitignored), generated by `native/sync.mjs` (include-list copier; renames Index.html → index.html; excludes sw.js, scanner models, vendor/ort). `npm run app:sync` after ANY web-file edit — the installed app does NOT pick up Netlify deploys.
- **`IS_NATIVE_APP` / `SITE_ORIGIN` / `PROXY_ORIGIN`** consts in Index.html (defined just above `lorcastToProxy`) are the native shims: skip SW registration, absolutize `/img-proxy` + `/tcg-img-proxy` to packs.ink (rides Netlify edge cache; ACAO:* on both proxy routes in `_headers` keeps canvas exports untainted), force copied share links to say packs.ink, stub OAuth sign-in with a toast (Google blocks OAuth in WebViews — phase-2 Custom-Tab + deep-link + PKCE flow), keep + tag native Sentry events despite the localhost filter. All inert on web. `sync.mjs` refuses to build if these markers disappear from Index.html.
- **Never register the service worker in native builds** — registration is guarded AND sw.js is excluded from the bundle.
- `node_modules/` + `native/www/` gitignored; the `android/` project IS committed. Icons/splashes regenerate via `npm run app:assets` from `native/assets/logo.png`.

## Languages (i18n) — localized cards + site language (2026-10-03)

Full write-up: **`docs/i18n.md`** (source survey, matching rules, roadmap). Invariants:

- **`card_localizations` (migration 179, APPLIED)** holds every card printed in ja / de / fr / it:
  name, version, rules text, classifications, and the art URL. Filled daily by
  `scripts/sync_intl_cards.py` (`.github/workflows/intl-cards.yml`) from **Takara Tomy** (ja) and
  **Ravensburger's gallery** (de/fr/it). Lorcast and duels.ink are English-only. Art is a 600px WebP in
  `card-art/intl/<lang>/<source key>.webp`, keyed on the SOURCE id so a retired stand-in never orphans it.
- **Matching refuses rather than guesses** — set + collector number confirmed by name; a number hit with
  a different name is dropped. `match_how='name'` rows borrow a NAME for other printings and **never
  carry art**. `python scripts/test_intl_cards.py` pins both directions.
- **`"Product Name"` stays English.** Language is a display layer: `localizeCatalog` (App) swaps `img_*`
  and adds `loc_name` / `loc_text` / `loc_classes`; render sites use `cardDisplayName(row)`. Never key
  anything on a localized name.
- **UI text:** `_t("English string", vars)` / `_term(kind, value)`; dictionaries `i18n/<lang>.js` are
  BAKED by `python scripts/build_i18n.py` from `i18n/src/*.json` (edit the sources, never the .js; bump
  `I18N_VER` in the head boot script). Loaded pre-paint, only for a non-English language, so English
  visitors pay nothing. **Changing language reloads the page** — by design.
- **⚠ New on-screen text ships translated, in the same commit (2026-10-03).** Wrap it in `_t()`, add
  the key to `i18n/src/ui.json` with ja / de / fr / it, run `python scripts/build_i18n.py`, bump
  `I18N_VER`. Two guards enforce it in CI: `scripts/test_i18n_coverage.mjs` (via
  `scripts/i18n_audit.mjs`) fails on any NEW unwrapped text node, visible attribute (title /
  placeholder / aria-label / alt / our components' label props) or `flashToast("...")` literal
  inside Index.html's html`` templates, against the ratchet `i18n/src/untranslated_baseline.json`;
  and `build_i18n.py --check` fails on a `_t()` key missing from ui.json. The baseline only ever
  SHRINKS (`node scripts/i18n_audit.mjs --update`; `--accept` to grow it is a deliberate act).
  English on purpose (brands, Elo / scouting, admin screens, the FAQ template) is listed with a
  reason in `i18n/src/english_on_purpose.json`. **⚠ The scanner cannot see text in DATA consts**
  (`EVENT_TILES`, `NEWS_ARTICLES`, chip label arrays): translate those at the render site with
  `_t(label)` so the key lands in ui.json, or carry per-language copies in the data.
- **Wrapping a string changes the source text a guard test may anchor on** (`test_calendar`,
  `test_event_search`, `test_sealed_search` were taught both forms). Run the guard suite after a wrap.
- **Nobody is prompted to switch** (Zaven, 2026-10-03). A language is chosen in ⚙ Preferences or the
  footer's language dropdown. A first-visit "switch to Japanese?" banner was built and removed the same
  day — don't reintroduce one without asking.
- **A card never printed in the card language still shows**: English art, plus an UNOFFICIAL
  translation of its rules text (`i18n/cards_mt/<lang>.json` → `scripts/load_mt_card_text.py`,
  `match_how='machine'`, `source='packs-ink-mt'`, name/art NULL, labelled in the card modal). The official
  text always wins; a translation of an older English text (`en_hash`) is deleted, and the daily run's
  artifact lists what needs (re)translating. The sync's pruning never touches these rows.
- **How it works** is translated whole: `i18n/src/faq/<lang>.html` (from `python scripts/faq_source.py`,
  first line `<!-- en:<hash> -->`) baked into the dictionary as `faqHtml`. It is injected as HTML, so the
  guard checks every translation keeps the English page's exact tags. **The Amazon Associates sentence
  stays English verbatim** in every language, FAQ included. The Elo pages are English on purpose.
- Chinese prints are archived LOCALLY only (`scripts/archive_zh_cards.py`, unofficial source) — publishing
  them is Zaven's call.

## Card scanner — PUBLIC BETA 2026-08-04

Full notes: `docs/claude/card-scanner.md` (27 KB). **Read it before changing this area.**
Camera → identify → review → save.
Guards: `scripts/test_scanner_guest.mjs`, `scripts/test_scanner_verify.mjs`, `scripts/test_scanner_extra.mjs`, `scripts/test_scanner_asset_cache.mjs`, `scripts/test_scan_variants.mjs`, `scripts/test_scanner_edit_search.mjs`, `test_scanner_scope.py`, `test_scanner_unreleased.mjs`.
Covers: Gating; Scanning signed out; Which PRINTING: the ORB version check; The index follows the catalog; its assets survive deploys; Version chips in the review row; The review editor's search IS the site's smart search; ⚠ `parseSearchQuery`'s exclusion prefixes match a WHOLE token — fixed 2026-09-12; Consent + the upload opt-out (migration 114); The overlay is a DIALOG, and Back closes it; Retention — a promise with a cron behind it; Storage cost + the abuse cap (migration 115); Where the user-facing copy lives.

- ⚠ `parseSearchQuery`'s exclusion prefixes match a WHOLE token — fixed 2026-09-12
- ⚠ The upload gate is the SNAP's flag (`job.guest`), never `user`.
- ⚠ The account's consent effect sets `consentOk` EITHER way
- ⚠ A `/scan` landing opens the modal BEFORE the deferred `scanner.js` has run
- ⚠ A NOT-confident ORB winner does not replace the read's pick
- ⚠ When the right card is not among the candidates, ORB still finds 20+ inliers on some other card's art

## Deck import from a PICTURE of a deck (2026-09-08)

Full notes: `docs/claude/deck-import-from-a-picture-of.md` (11 KB). **Read it before changing this area.**
Paste or drop a deck poster into Decks » Import decklist and it reads the cards off the image.
Guards: `scripts/test_deck_image.mjs`, `scripts/test_scanner_matcher.mjs`.
Covers: Counts ARE read — and the chip is located from the MEAN; The pitch sweep, and the resolution floor; ⚠ dHash in scanner.js was bit-reversed — fixed 2026-09-08; The matcher has a regression guard — `node scripts/test_scanner_matcher.mjs`.

- ⚠ dHash in scanner.js was bit-reversed — fixed 2026-09-08
- ⚠ Candidate lattices are scored by ESTIMATED CARD YIELD
- ⚠ Glyph templates are BAKED (`QTPL_B64`), never rendered at runtime.
- ⚠ The normalisation box is 20x22, and that width is load-bearing.
- ⚠ Autocorrelation proposes harmonics of the strongest periodicity, which is not always the card pitch.
- ⚠ But the whole VISUAL path is inert on camera photos.

## Lore Tracker (Analytics » Lore Tracker)

Full notes: `docs/claude/lore-tracker.md` (5 KB). **Read it before changing this area.**
A full-bleed scoreboard for a table.
Guards: `scripts/test_lore_tracker.mjs`.

- ⚠ At 3–4 seats the grid halves each header and the name input is the only thing that can give

## Pin + lore-counter photos (2026-08-24)

Full notes: `docs/claude/pin-lore-counter-photos.md` (14 KB). **Read it before changing this area.**
45 pins and 25 lore counters render on their own Collection tab (Pins & Counters — see the next section; until 2026-09-11 they were tiles at the foot of the Sealed tab), from the static `LORCANA_PINS` / `LORCANA_LORE_COUNTERS` consts — there is no feed behind either.
Covers: ⚠ Release order is the ARRAY's order, not `n`.

- ⚠ Release order is the ARRAY's order, not `n` (2026-09-12)
- ⚠ Do NOT credit a photo source anywhere user-facing.
- ⚠ The Wilds Unknown TROVE counter is the Woody-and-Buzz one
- ⚠ Both are named for their ART, not their set, and that is load-bearing.
- ⚠ "Hunny Archmage" (Attack of the Vine! 40/207) is NOT "Hunny Wizard"
- ⚠ `EXPECTED_PINS` / `EXPECTED_COUNTERS` in `upload_collectible_photos.py` are the highest valid `n`, not a photo count

## Pins & Counters — a Collection tab of its own (2026-09-11)

Full notes: `docs/claude/pins-counters.md` (6 KB). **Read it before changing this area.**
Pins and lore counters were two sections of tiles at the foot of the Sealed tab.
Guards: `scripts/test_collectible_boards.mjs`.

- ⚠ `sync === "offline"` writes nothing to the account.
- ⚠ "Take off board" and Delete do NOT un-own anything — deliberate, and it left the boards one-way until 2026-09-13.
- ⚠ The armed key is `"<kind>|<n>"`, never a bare `n`.
- ⚠ The tray's × is a SIBLING of the draggable button, never a child

## Playmats — a Collection tab of its own (2026-09-27)

Full notes: `docs/claude/playmats.md` (9 KB). **Read it before changing this area.**
From the beta: *"I have all the prize wall and set champion mats and would love to log them."* Zaven's spec: TCGplayer listings, price history, and sections — retail, Set Championship, DLC, events.
Guards: `scripts/test_playmats.py`.

- ⚠ TCGplayer never says Top Prize or Prize Wall.
- ⚠ Both sealed value charts go through `fetchSealedValueHistory`, not the plain history fetch.
- ⚠ It is passed `noCut`
- ⚠ The history has a HOLE: 2026-05-12 .. 2026-09-25
- ⚠ Until this ships, the ETL (which runs from `main`) does not fetch the mats

## Collection's section strip is a SHELF — one row at every width (2026-09-27)

Zaven, off his phone: *"make these options all fit on one shelf. Move pins to end. Also, stylize
them, looks too sterile."* The fifth tab had pushed Playmats onto a second line beside Share, and
the tabs were bare text.

- **Order is `COLLECTION_SECTIONS`' order**: Cards · Sealed · Graded · Playmats · Pins & Counters.
  Pins sits last by that ruling.
- **One tray (`.cst-shelf`), a cubby per section**: a glyph over a Cinzel label
  (`COLLECTION_SECTION_TABS` carries the glyph: `cards` / `box` / `slab` / `mat` / `pin`), and a
  gold plate with a short gold lip under the tab you're on. Share is a cubby of its own at the far
  end. Same face as the nav chips, but boxed in a tray so it doesn't read as a third nav row.
- **⚠ It must not wrap.** Below 720px each cubby takes its label's width plus an even share of
  what's left (`flex:1 1 auto`). Equal grid columns clipped "Playmats" at 360px while "Pins" had
  room to spare.
- **Pins & Counters keeps its full name and stacks as two lines on phones** (`lines` on its
  `COLLECTION_SECTION_TABS` entry; one line from 721px up). It first shipped as a short "Pins";
  Zaven asked for the full name. The cubbies top-align on phones so the five glyphs stay level
  (centred, the two-line tab's glyph rode half a line high), and Share's top padding is the sum
  that puts its glyph on the same line.
- **Below 360px** the row is short of the full-size labels (19px short at 320, still 1px at 351),
  so Share drops its word, the labels go to 9px and the tabs' side padding to 1px. Measured with
  nothing clipped, the glyphs level and no sideways scroll at 320, 351, 359, 360, 375, 390, 412,
  480, 719, 721 and 1280px.
- The tour step (`.collection-section-tabs`) and the Help page say five sections now.

## Official Lorcana brand art (2026-09-12)

Full notes: `docs/claude/official-lorcana-brand-art.md` (6 KB). **Read it before changing this area.**
Ravensburger distributes a **"Complete Bundle"** of brand assets — 890 files, 313 MB: all 13 set logos, 21 ink badges (singles AND the 15 dual pairs), 9 rarity icons, the promo stamps printed on promo cards, the card-face glyphs, the Challenge badge, the card back, playmat and social borders, punch-…
Guards: `scripts/test_brand_art.mjs`.

- ⚠ A single-colour SVG must be rendered as a CSS MASK (`LorcanaGlyph`), never an `<img>`.
- ⚠ SET LOGOS ARE WORDMARKS
- ⚠ The First Chapter is black line art and always will be
- ⚠ `.gitignore`'s promo-kit rule must stay anchored (`/promo/`)

## Icons — there are no emoji in the UI (2026-08-24)

Full notes: `docs/claude/icons.md` (4 KB). **Read it before changing this area.**
**`uiIcon(key, size)`** (Index.html, right below `NAV_ICONS`) is the one accessor for every pictograph on the site.
Guards: `scripts/test_no_emoji.mjs`.

- ⚠ "No emoji" means no emoji-CAPABLE code point, not just the ones that look like one

## Location cards read landscape where you're READING one (2026-08-24)

Full notes: `docs/claude/location-cards-read-landscape-where-you.md` (9 KB). **Read it before changing this area.**
A Location is printed landscape, but every art source frames it portrait with the card turned on its side.
Guards: `scripts/test_deck_poster_grid.mjs`.
Covers: ⚠ A DECK POSTER's Locations SHARE A ROW WHEN THERE'S ROOM — a rotated card doesn't shrink.

- ⚠ A DECK POSTER's Locations SHARE A ROW WHEN THERE'S ROOM — a rotated card doesn't shrink (2026-09-18)
- ⚠ The box is IN FLOW, never absolutely positioned.
- ⚠ A Location's quantity badge sits ABOVE the card, right-aligned over its cost hexagon
- ⚠ The run's flex line is `alignItems:"flex-start"` and must stay so:
- ⚠ A cover-fit CROP to a portrait footprint is the other thing that was tried and rejected
- ⚠ The poster grid must stay `repeat(N, minmax(0,1fr))`, never a bare `1fr`.

## Top-level nav

Full notes: `docs/claude/top-level-nav.md` (7 KB). **Read it before changing this area.**
**Two-row icon nav** (restructured 2026-05-25).
Covers: Mobile top-nav structure (do NOT regress); iOS safe-area-inset (do NOT regress).

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- **Catalog lives in IndexedDB** (2026-07 offline rework): db `packsink`, store `kv`, key `catalog`, record `{v: CACHE_KEY, t, rows, latestDate}`. `CACHE_KEY` (`packsink:catalog:vN`) is still the version stamp — bump N whenever cached rows change. **⚠ A record from an EARLIER key (≥ `CATALOG_REPLAY_MIN_VERSION`, v57) is still SHOWN, marked stale, while the fetch replaces it** (2026-10-05). Treated as missing, every bump put every returning visitor on the full-screen "Loading the card database" card, and the key moved v57 → v65 in under three weeks. So a bump means "refetch now", not "never show the old rows" — if a future bump changes the row SHAPE in a way that would crash a render, raise `CATALOG_REPLAY_MIN_VERSION` to the new N in the same commit. 24h TTL with background refresh. **Full rows are stored — `img_large` and `text` are NOT stripped anymore** (that strip existed for the 5MB localStorage quota; IDB has no such ceiling). Body-text smart search therefore works on cache-replay sessions, including offline; the lazy text backfill only fires for rows migrated from a legacy localStorage cache.
- **⚠ The daily price wipe EXPIRES the two price_movers IDB snapshots, it does not delete them** (`wipePriceDerivedAuxCaches` rewrites them with `t: 0`), and Home keeps its movers rows in `_homeMoversMem` for the life of the page. Before, the day's first visit and every return to Home after the update was detected (`priceEpoch > 0` skipped the cache) sat on "Loading movers…" for the whole ~6-page fetch. A genuinely empty cache (first visit) draws `MoversSkeleton`, never a line of text.
- **Legacy migration**: `readCache()` falls back to the old localStorage `packsink:catalog:vN` entry, returns it, and one-shot migrates it into IDB, deleting the localStorage copy on success (frees ~2.5MB back to the aux caches). `writeCache()` falls back to the old slim localStorage write only when IDB is unavailable (old private-mode Safari). Both are async now — `loadFromSupabase` awaits `readCache()`.
- **IDB helpers** (Index.html top): `idbOpen/idbGet/idbSet/idbDel` — resolve (never reject); reads → `undefined`, writes → `false` on failure. `offlineMirrorWrite/offlineMirrorRead("<what>:<uid>", data)` wrap them for per-user offline mirrors (see "Offline support" below).
- **Freshness probe** (added 2026-05-24): every page load with a "still fresh by TTL" cache fires a single-row query against `card_prices_latest` for `max(price_date)`. If server > cache's stored `latestDate`, cache is invalidated and refreshed. Means daily visitors see today's prices within seconds of opening the site after the ETL, not 24h later. **When the probe detects an outdated catalog it also wipes every price-derived aux cache** (`packsink:*` except catalog/auth/install-prefs) — movers, sealed, history, setsMeta, colvalue all derive from price data and were going stale silently behind their 12h TTLs. On network failure the probe trusts the TTL and keeps the cached catalog (this is the offline path). **It also compares the `cards` row count** (a HEAD with `Prefer: count=exact`, stored as `cardCount` in the IDB record, 2026-09-18): Lorcast adds cards on its own clock, and Promo Set 4 landed after that day's prices, so a catalog saved that morning passed the date check and hid the whole set for up to 24h. Don't swap it for `max(updated_at)` — the daily Lorcast load touches nearly every row, which would cold-fetch everyone daily.
- **`AUX_CACHE_VERSION` sentinel** (Index.html top, added 2026-05-24): per-deploy stamp compared against `packsink:auxCacheVersion` on module load. Mismatch → one-shot wipe of every `packsink:*` key except catalog/auth/install-prefs. **Bump the string to force every existing user's next page load to refresh aux caches** — useful when an ETL/matview change makes those caches stale faster than their TTLs catch. Independent from `CACHE_KEY` (which only invalidates the catalog itself).
- **Visibility re-probe**: `visibilitychange` + `pageshow` listeners re-run `loadFromSupabase` when the tab/PWA becomes visible again (throttled 60s). Without this, PWA users who background the app would see stale data forever on resume — React tree never remounts.
- Per-view caches use `readJsonCache(key, ttlMs)` / `writeJsonCache(key, data)`:
  - `packsink:movers:v1` (12h), `packsink:screener-movers:v1` (12h), `packsink:following:v1:{uid8}` (30min), `packsink:home:tourneys:v1` (2h), `packsink:hist:v1:{pid}:{printing}` (12h), `packsink:sealed:v1`, `packsink:setsMeta:v1`, `packsink:colvalue:v2:{uid8}:{productsHash}:{rangeKey}`.
  - `packsink:setsMeta:v1` fetched on EVERY page load via independent useEffect (not bundled with catalog Promise.all) — `loadFromSupabase` returns early on fresh cache which would leave setsMeta empty and break home box-price + prerelease guard.
- **writeJsonCache QuotaExceededError eviction** drops `packsink:hist:` first, then home banners, then sealed. (The catalog no longer competes for localStorage quota — it's in IDB.)
- localStorage quota ~5MB (aux caches only now). Min rows for catalog: 4000 (`CACHE_MIN_ROWS`).
- **Symptom of quota exhaustion**: cache writes fail silently, every visit cold-fetches, per-view banners "unload" on tab switch. Diagnostic: `Object.entries(localStorage).reduce((s,[k,v])=>s+v.length,0)/1024/1024`.

## Offline support (2026-07 rework)

Full notes: `docs/claude/offline-support.md` (3 KB). **Read it before changing this area.**
The PWA works offline after one online visit.

## PostgREST gotchas

- `sbFetchAll` parallel range pagination **requires explicit `order=` param** — without it ranges overlap and rows duplicate.
- `sbFetchAll` with `limit=N` confuses its own pagination. For "does this column exist" probes, use direct `fetch()`.
- Anything hitting `prices_daily` should be a **materialized view**. Statement timeout is 10s; raw views over the ~3M-row table hit it.
- Matviews need a unique index for `REFRESH CONCURRENTLY`. Refresh functions fall back to non-concurrent on first run.
- **PostgREST default page size is 1000.** Paginate `.range()` for tables that could exceed.
- **Upserts return `{error}`, they don't throw.** Always check `.error`. For bulk upserts, `.select("any_col")` and compare returned count vs sent.
- **`ON CONFLICT DO UPDATE` rejects batches with duplicate conflict-target rows.** `Supabase.upsert()` dedupes automatically.
- **`sbFetchWithRetry` wraps every fetch** with 3 retries on 5xx — Supabase's 57014 (statement timeout) is intermittent. **But not every 5xx is transient**: `SB_NO_RETRY` short-circuits `55000` (`object_not_in_prerequisite_state` — an unpopulated matview), where the identical request fails identically until a human runs a REFRESH, so the ladder spent 3 requests and ~1.2s of backoff per page load to reach the answer it already had (observed live on the Screener while the market index sat empty). Add a code here only when retrying is *provably* pointless — 57014 must keep retrying. **⚠ The body is read off `r.clone()`**: the no-retry branch hands `r` back to the caller, which calls `.json()` on it, and a Response whose body was already consumed throws there instead.
- **`CREATE OR REPLACE FUNCTION` can't change a RETURNS TABLE signature.** Drop first, then create.
- **RLS broadening trap.** When a SELECT policy has `OR <condition non-owner can satisfy>`, an unfiltered select returns every visible row. Explicitly `.eq("user_id", user.id)` for "my own" reads.
- **`NOTIFY pgrst, 'reload schema';` at the end of every migration.**
- **`SECURITY DEFINER` functions must pin `search_path` to include `extensions`** if they use pgcrypto (`gen_random_bytes`, `gen_random_uuid`, etc.).
- **Long-running RPCs need explicit `statement_timeout`.** Every refresh function pins `set statement_timeout = '5min'`. Without it the RPC inherits PostgREST's role setting (anon 3s / authenticated 8s) and dies with 57014 — `service_role` has no `rolconfig` of its own, so it does NOT get a free pass. **Re-running an old migration silently reverts this.** Migration 16 was re-run after 25 and clobbered the pin off `refresh_sealed_prices_latest`, which then failed intermittently for weeks (fatal in `etl_tcgcsv_daily.py`, swallowed as non-fatal in `load_sealed_products.py`) until migration **109** restored it. When you re-run any historical migration, diff the function bodies against the newest migration that touched them.
- **When recreating a matview, re-grant SELECT to every role that needs it.** `grant select on X to anon, authenticated, service_role`. service_role does NOT inherit implicitly. Migration 45 retroactively grants on all 5 price matviews + prices_daily after a missing service_role grant broke the selfheal job on 2026-05-23.
- **Views authored as the dashboard user are SECURITY DEFINER by default** — triggers `0010_security_definer_view` linter alert. Create with `with (security_invoker = on)`.
- **`information_schema.role_table_grants` does NOT include matviews.** To check matview grants, use `has_table_privilege('role','public.matview','SELECT')` against `pg_matviews`.

## Auth state gotcha (do NOT regress)

**`sbClient.auth.updateUser()` fires an auth-state-change after every call**, creating a new `user` object reference. A `useEffect` syncing user_metadata via `updateUser()` with `user` in its deps → infinite loop throttled only by debounce. Supabase rate-limits `/auth/v1/user` quickly (429); the auth lock then stalls every other query.

The prefs-sync effect in `App.jsx` (writes `{themeMode, theme, tipsEnabled, avatarCardId}`) omits `user` from deps and uses `prefsHydrated.current`. Symptoms of regression: catalog fetch takes minutes, "Loading price database…" forever, every tab switch cold-loads.

## Theme: 6 named palettes + 3-mode resolver (2026-06-05 rewrite)

Full notes: `docs/claude/theme.md` (10 KB). **Read it before changing this area.**
State is **three independent pieces**, each persisted independently to localStorage AND synced to Supabase user_metadata (cross-device): - **`lightTheme`** (`packsink:lightTheme`) — which of the 4 light variants: `parchment` (default) | `sunrise` | `watercolor` | `daydream`.
Guards: `scripts/test_theme_contrast.mjs`.
Covers: Text on an accent fill is `--on-accent`, and muted text is sized to 4.5:1; ⚠ `color-scheme` is declared at the DOCUMENT level — don't scope it off again.

- ⚠ `color-scheme` is declared at the DOCUMENT level — don't scope it off again (2026-09-13)
- ⚠ Samsung Internet's forced dark mode CANNOT be opted out of from the page (2026-09-18).

## price_movers matview gotcha

Full notes: `docs/claude/price-movers-matview-gotcha.md` (5 KB). **Read it before changing this area.**
Computes Δ% across 6 windows (1D / 1W / 1M / 3M / 6M / 1Y) for both low and market.
Guards: `scripts/test_price_freshness.mjs`, `test_discord_bot.mjs`.
Covers: ⚠ A move has to be OBSERVED inside its window (migration 172, 2026-09-27).

- ⚠ A move has to be OBSERVED inside its window (migration 172, 2026-09-27)
- ⚠ It is that date and not `lastRawPriceDate` on purpose
- ⚠ Never pass it to a batch whose history is cached separately
- ⚠ Re-running an older price_movers migration reverts all of this

## Catalog merging — `transformSupabaseData` rules

Full notes: `docs/claude/catalog-merging.md` (6 KB). **Read it before changing this area.**
This is where catalog correctness lives.

## React key trap (SPLIT_BY_PRINTING_SETS)

`groupCards()` produces TWO group objects per LCP (C1) card (Prize Wall + Prize Foil) sharing the same `card_id`. If the tile loop uses `key=${g.card_id}`, React sees duplicate keys, picks one, and **leaves the other orphaned in the DOM forever** — those tiles then appear in every search regardless of filter (phantom tiles). Fix: append printing suffix for split groups: `key=${g.card_id + (g.isSplitPrinting ? "::"+(g.Printing||g.tcg_printing||"") : "")}`. Fixed 2026-05-23.

## Smart search

Full notes: `docs/claude/smart-search.md` (12 KB). **Read it before changing this area.**
`parseSearchQuery` extracts ink / rarity / set / classification / card_type / keyword / cost / strength / willpower / lore / inkable / legality / illustrator.
Covers: Single canonical matcher: `matchesCardFilter(row, f, parsed)`.

## Card search finds SEALED PRODUCT too, in its own section (2026-09-21)

Full notes: `docs/claude/card-search-finds-sealed-product-too.md` (7 KB). **Read it before changing this area.**
"What is a booster box going for" had no answer in any search box — sealed was reachable only from the Sealed collection tab, the Sealed movers row and the Screener in sealed mode, three places you have to already be in.
Guards: `scripts/test_sealed_search.mjs`.
Covers: ⚠ The home search bar must PARSE like the Cards box — fixed 2026-09-21; ⚠ A `contains` phrase of REPEATED words collapsed to one token.

- ⚠ A `contains` phrase of REPEATED words collapsed to one token (2026-09-21)
- ⚠ The home search bar must PARSE like the Cards box — fixed 2026-09-21
- ⚠ PRICED ROWS ONLY, and that single rule is what makes sealed safe next to card search.
- ⚠ Its own section BELOW the cards, computed independently of them.
- ⚠ The Cards-tab grid is sized for BOXES
- ⚠ Deliberately NOT `matchesCardFilter`

## Cards browse filter dimensions

Full notes: `docs/claude/cards-browse-filter-dimensions.md` (4 KB). **Read it before changing this area.**
Drawer + toolbar quick-filter chips (icon-only on toolbar): - Ink (6 colors + Inkable/Uninkable hexes) - Cost (1-9+ hex buttons) - Rarity (9 icon-only buttons using `RARITY_ICONS`) - Legality (Core / Infinity — mutually exclusive toggle) - ✓ Owned (filters to groups where any printing has `collectio…
Covers: Price ($) filters (added 2026-08-14).

## Screener filters

Full notes: `docs/claude/screener-filters.md` (9 KB). **Read it before changing this area.**
The Screener has parity with the Cards browse filters as of 2026-05-26 via the catalog joinback pattern (`catalogByCardId` Map).
Guards: `scripts/test_screener_graded_cols.mjs`, `scripts/test_graded_pop.mjs`.
Covers: Main (always visible); Advanced panel (collapsed by default — 2026-05-26 expansion); Mobile; PSA population columns in RAW mode; Graded PRICE columns in RAW mode.

- ⚠ The header row renders TWICE.
- ⚠ `overflow:clip` on `.price-db-tablebox`, never `hidden`
- ⚠ A HIDDEN Browser pane never delivers ResizeObserver callbacks
- ⚠ `rawPopPick`, not `gradedPopPick`.
- ⚠ `colPrefs[mode].known` — why eight new columns didn't appear for everybody.
- ⚠ Priced through THE ladder, `makeGradedPrintingLookup`, over the rollup keyed by card_id

## Screener saved views

`screener_views(user_id, name, payload jsonb)` — owner-only RLS. Hydrated on sign-in (newest-first); local-only views migrated up on first sign-in if remote table empty. Writes mirror to localStorage for unauth fallback. If migration 44 not deployed (PostgREST 42P01), client logs warning and stays localStorage-only.

- **`screenerPayload` is the ONE description of "what the Screener is showing"**, and all three consumers read it: Save view, the `?v=` URL writer, and Copy link. It used to be an inline object literal inside `saveCurrentView`, so adding a filter meant remembering to extend it. It now also carries `showSealed` / `filterSealedTypes` / `filterGraders` / `filterGrades`, and `applyView` restores them — a view that lands you in Sealed or Graded has to bring that mode's chips with it.
- **⚠ The memo must sit BELOW every filter `useState` it reads.** A `useMemo` callback runs at its own declaration point; parked next to `saveCurrentView` (where it reads most naturally) it threw `Cannot access 'minPrice' before initialization` and took the whole Screener to the error boundary. `saveCurrentView` keeps its position and closes over it — it only runs from a click, long after initialisation.

## Shareable Screener + Price Graphing state (`?v=` / `?g=`)

Full notes: `docs/claude/shareable-screener-price-graphing-state.md` (2 KB). **Read it before changing this area.**
Both views were unlinkable: a Screener query lived only in component state and `screener_views` (so it could be SAVED but never SENT), and an 18-card comparison died on refresh.
Guards: `scripts/test_screener_url.mjs`.

- ⚠ `showGraded` / `showSealed` come from `?v=` at INIT, not from a post-mount `applyView`.

## Watchlists (migration 127)

`watchlists` + `watchlist_items`, keyed on **`(card_id, printing)`** — the same key `collection_items` and `deck_cards` use, because a Cold Foil and its non-foil are different markets that often differ 10x. Sealed shares the table with `card_id` null and its pid instead (a CHECK requires one of the two), which is what lets a mixed list hand itself to Price Graphing.

- **State lives in App, not the Screener** — three surfaces read it: the star column, the graph handoff, and the alert evaluator. `null` until the first fetch settles, `[]` when the feature isn't deployed; the UI needs to tell loading from empty from not-migrated.
- **Mutators write through then re-read.** Lists are small and mutated by deliberate clicks, so the re-read costs nothing and removes a class of optimistic-update bugs.
- **The star has THREE states**: on the active list, on another list, on none. Without the middle one, starring a card you already track elsewhere reads as a dead click.
- **"Filter to list" composes** with the preset and every other filter rather than replacing them. Its membership memos sit **above** the `filtered` memo — same `useMemo`-runs-at-its-declaration rule as `screenerPayload`.
- **⚠ The sticky NAME column is `.th-name` / `.td-name`, NOT `nth-child(3)`.** The star column sits between the checkbox and the image, which made the third cell the IMAGE for signed-in users — the wrong column pinned and names scrolled away. `gripKeys` gains `watch` on exactly the renders that draw one, or every resize grip past it moves the column to its left.

## Market indices (migrations 128 + 130)

Full notes: `docs/claude/market-indices.md` (6 KB). **Read it before changing this area.**
`market_index_daily` + `market_index_latest`, scoped `all` / `set:<id>` / `rarity:<r>`.
Guards: `scripts/test_market_index.mjs`.

- ⚠ The day-qualifying floor is COVERAGE, not a count.
- ⚠ Every series is divided by its partition's own `first_value(cum)`, not just ×100.
- ⚠ Created WITH NO DATA, then populated via `select public.refresh_market_index();`.

## Price alerts (migration 129)

`price_alerts` (rules) + `alert_events` (firing ledger), built on watchlists because a rule needs a subject and that's the one the user already curated.

- **This is the rule store, NOT a delivery mechanism.** There is no web-push infrastructure (no VAPID, no subscription table, no sender — `pushManager` appears nowhere). Rules are evaluated CLIENT-SIDE against `price_movers` and land in an in-app inbox, which honestly answers "what happened while I was away" on open and nothing more. `alert_events.delivered_at` exists for a future server sender and is null forever until one is built. **Don't describe alerts to users as notifications.**
- **The ledger is a table, not localStorage**, so a firing is one event across devices. `alert_events_unique (alert_id, card_id, printing, price_date)` makes re-evaluation idempotent — keyed on the price date, because the snapshot is what the rule actually saw.
- **`evaluateAlerts` is pure** — `priceDate` and `nowMs` are arguments so two devices on the same snapshot reach the same answer. Guarded by `node scripts/test_alerts.mjs`.
- **`pct_down` fires on `observed <= -abs(threshold)`** — the user types `10` for "down 10%"; storing a negative would make the form ask for a minus sign nobody remembers.
- **Cooldown is per (rule, card)**, not per rule: one card cooling off must not silence the rest of a list. Without it, a card parked above its threshold alerts every day forever.
- **The unread badge is on the profile AVATAR, not a nav bubble.** A third bubble in right-cluster row 2 is the documented regression that tips ANALYTICS off the edge at ≤420px. `.profile-alert-badge` is absolutely positioned so it costs no layout width, and renders only when the count is non-zero.
- Retention: `cleanup_old_alert_events()` (180 days) runs in the selfheal job beside `cleanup_old_trades()`.

## Feedback replies (migration 138)

Full notes: `docs/claude/feedback-replies.md` (4 KB). **Read it before changing this area.**
The footer feedback box was one-way.
Guards: `scripts/test_feedback_threads.mjs`.

- ⚠ `packsink:feedback:` must never match `AUX_EVICTABLE_PREFIXES`.

## Price Graphing Compare

Full notes: `docs/claude/price-graphing-compare.md` (3 KB). **Read it before changing this area.**
Multi-product overlay chart.

## Graded data: `date` vs `price_date`

**Trap.** `graded_prices_daily.date` is the column. `graded_prices_latest` matview projects it as `price_date` to match `card_prices_latest`. Querying `graded_prices_daily` with `select("...price_date...")` errors 42703.

## Graded data: `printing` is part of the PK (migrations 49 + 50)

Both `graded_prices_daily` and `graded_collection_items` are printing-aware:

- **`graded_prices_daily` PK** (mig 49): `(tcgplayer_product_id, printing, grader, grade, date)`. The `printing` value came from the legacy feed's `variant` field — values are `"Normal"`, `"Cold Foil"`, `"Holofoil"`. Split-printing cards (TFC Cold Foil rares, LCP C1 Holofoils) arrived as multiple records sharing one `tcgplayer_id`; the retired ETL captured each variant as its own row instead of silently overwriting on upsert (pre-49 behavior caused foil/non-foil prices to conflate randomly). Still the shape of the frozen data the client reads.
- **`graded_collection_items` PK** (mig 50): `(user_id, card_id, printing, grader, grade)`. Users can own foil + non-foil graded copies of the same card_id as distinct slots. `get_shared_collection_graded(uuid, text)` RPC was recreated to project `printing` (drop-and-recreate; PostgREST RETURNS TABLE can't be altered).
- **`service_role` needs explicit `DELETE` on `graded_prices_daily`** for ETL overrides + the cleanup script. Granted in migration 49. Without this, every delete throws 403.
- All client queries against `graded_prices_latest` / `graded_prices_daily` must select `printing` and key lookups by `pid|printing|grader|grade`.
- **`lookupGradedPx(pid, grader, grade, preferredPrinting)` pattern**: try the preferred printing first, then fall back through `["Normal", "Holofoil", "Cold Foil"]` until a match is found. Used by the header totals and the chart's slot resolver. Without the fallback, Holofoil-only cards (Enchanteds, Iconics) whose owned items default to printing='Normal' (mig-50 backfill) find no matching rows and silently drop out.
- `buildGradedSeries(history, graderKey, gradeStr, label, printingKey)` accepts an optional 5th arg to filter to one printing — used by `GradedPricesTab` and the Compare flow so each printing graphs as a distinct line.

## A PROMO IS NOT A REPRINT (2026-09-01, Zaven)

Full notes: `docs/claude/a-promo-is-not-a-reprint.md` (3 KB). **Read it before changing this area.**
A **reprint is a second BOOSTER printing, and only that.** A promo is a *variant* of the booster card: you may always play it in place of the original, but it is not a new release of the card.
Guards: `scripts/test_reprints.mjs`.

## Card VERSIONS: what counts as one, and what it's called (2026-08-24)

Full notes: `docs/claude/card-versions.md` (6 KB). **Read it before changing this area.**
Two silent bugs shipped here, both on Peter Pan - Pirate's Bane (Enchanted, Into the Inklands).
Guards: `scripts/test_card_versions.mjs`, `scripts/test_printing_badge.mjs`.
Covers: `printingBadge` is the ONLY thing that decides a tile says "Foil".

- ⚠ The rule is NOT "is this a chase rarity", and the live catalog holds counterexamples in BOTH directions.
- ⚠ The Challenge words are looked up by BUCKET, never by the raw printing.
- ⚠ The graded tile's badge sits OVER the art, not in the meta row
- ⚠ And because it sits over the art it needs `.gmover-tile{isolation:isolate}`

## Graded UI: SPLIT_BY_PRINTING_SETS vs SECTION_SPLIT_SETS

Two top-level constants (defined near `AUX_CACHE_VERSION`):

- **`SPLIT_BY_PRINTING_SETS_GLOBAL`** (currently `{LCP (C1)}`): cards in these sets share one card_id between Normal and Holofoil printings. The catalog's `groupCards()` emits two raw rows per card_id (one per printing); the graded view emits two **tiles** per card_id (keyed `card_id|printing`). For every other set, the graded view collapses to **one tile per card_id** to prevent CONNECTING_FOILS companion rows from doubling the tile count.
- **`SECTION_SPLIT_SETS_GLOBAL`** (currently `{LCP (C1), LCP (C2)}`): sets where the set view renders Non-Foil and Foil as separate sections. C2 has distinct card_ids per printing (from Lorcast) so it naturally splits without `SPLIT_BY_PRINTING_SETS_GLOBAL`. Both `CollectionSetDetail` (raw) and `GradedCollectionView` (graded) respect this set.

When iterating `cardsForGoal` in the graded view's `grouped` useMemo: if the goal's set is in `SPLIT_BY_PRINTING_SETS_GLOBAL`, emit a tracked placeholder per `(card_id, tcg_printing)`. Otherwise dedupe to one placeholder per `card_id`. The owned-items loop must use the SAME dedupe (`SPLIT_BY_PRINTING_SETS_GLOBAL.has(meta.Set)` check) before bucketing, otherwise foil-owned items in non-split sets render as a second tile.

## Per-user graded value override (migration 51)

`graded_collection_items.custom_value numeric(12,2)` (nullable, added migration 51). When set, the user's owned slot uses this value instead of the graded market average — covers two cases: (a) low-volume cards with NO graded market data at all (the GradedPricesTab early-returns "No graded sales recorded" but the user still owns the slot), (b) any card where the user disagrees with the algorithmic price.

- **Surface**: `CardDetailModal` → graded focus → "Your Graded Copies" panel (gold box above the Price History / Graded tabs). For every owned slot, an inline `<CostDateInputs showCustomValue=${true}/>` renders three always-visible fields: **Paid** / **Acquired** / **Value**. The whole panel sits ABOVE the tab content, so it works even when GradedPricesTab early-returns on empty market data.
- **Plumbing**: `updateItemMeta({card_id, printing, grader, grade}, {custom_value: N|null})` writes through. Fetch path includes `custom_value` in the SELECT with a schema-tolerant fallback for pre-mig-51 environments. `get_shared_collection_graded` RPC was recreated (drop+create) to return `custom_value` too.
- **Read path**: any value computation should prefer `it.custom_value ?? lookupGradedPx(...)`. Search for `custom_value` in Index.html for the existing call sites (header totals, value chart, slot pills).
- **UI affordance**: when `custom_value` is set, the slot's price pill flips from green API price to gold `✎ $N` so the user can see at a glance which copies are overridden.
- **`CostDateInputs` props**: `currentPaid`, `currentDate`, `currentCustomValue`, `showCustomValue`, `onCommit(patch)`. The component is shared between sealed (no custom value) and graded (with). Don't pass `showCustomValue` for sealed.

## Graded pricing: legacy vs current

Full notes: `docs/claude/graded-pricing.md` (25 KB). **Read it before changing this area.**
Two graded price systems coexist.
Guards: `scripts/test_graded_slot_series.mjs`, `scripts/test_rematch_unmatched.py`, `scripts/test_variant_printing.py`, `scripts/test_printing_of.py`.
Covers: Portfolio chart: printing is part of the key (do NOT regress); Bad-sale defences; An unattributed sale is invisible FOREVER unless something re-asks; A named VARIANT is a printing, not a card_id; The DISPLAYED price never crosses a split — `makeGradedPrintingLookup`; ⚠ C1 has TWO prize vocabularies, and only one was readable; Price Graphing "By Graded" mode; Legacy graded feed — DELETED 2026-07-29.

- ⚠ C1 has TWO prize vocabularies, and only one was readable (2026-09-21)
- ⚠ It un-excludes only a row that can actually reach the rollup.
- ⚠ `CHALLENGE_CTX_RE` now includes `dlc`
- ⚠ Nothing in the ETL set that printing, so every such sale landed as `Normal` or NULL.
- ⚠ The TITLE is only ~93% reliable here, and the SLAB LABEL is the truth.
- ⚠ The Genie half is NOT detectable and must not be assumed to be.

## Graded view UX patterns

Full notes: `docs/claude/graded-view-ux-patterns.md` (2 KB). **Read it before changing this area.**
Covers: Persisted localStorage keys (graded view).

## Graded "Remove from tracking" (replaces Hidden feature)

The per-card Hide feature was killed 2026-05-26. It caused a class of bugs where adding a card to your collection silently failed to render the tile because its card_id was still in `packsink:graded:hidden` from a previous accidental × click — the value updated but the user couldn't see the card. **Replacement: "Remove from tracking"** with stricter invariants:

- **Composite (card_id, printing) keys** stored as `"cardId|printing"` strings in `packsink:graded:removed`. Critical for SPLIT_BY_PRINTING_SETS_GLOBAL (LCP C1: Let It Go, Dragon Fire, …) where the same card_id has both Normal and Foil printings as distinct tiles — removing the Foil must NOT also drop the Non-Foil. Helper `removedKey(cid, p)` builds the key; every `.has()` / `.add()` / clear site routes through it.
- **Owned tiles bypass the removal filter, structurally.** If you own any slot for `(card_id, printing)`, that tile always renders. The render-filter check is `if(!anyOwned && removedCardIds.has(removedKey(entry.card_id, entry.printing))) continue;` — owned-bypass is checked FIRST. Adding a card to your collection → tile reappears immediately.
- **No undo UI inside the graded view.** Recovery paths:
  1. Acquire the card → owned-bypass kicks in.
  2. Re-add the set goal → `addGoal()` clears `removedCardIds` entries for every (card_id, tcg_printing) tuple in the new goal's scope.
- **Goal denominator handling**: split-printing goals use the per-tile `dropRemovedTile(cid, p)` check (per-printing keying). Non-split goals use the per-card `dropRemovedCard(cid)` check (drops the card_id from the denominator if ANY of its printings is in `removedCardIds`, since non-split sets render one tile per card_id). Owned bypass exists for both.

The old `packsink:graded:hidden` key was swept by the AUX_CACHE_VERSION bump on the deploy that introduced this feature, so we don't inherit stale hidden state from the buggy original.

## Graded tracking goals

`graded_collection_goals(goal_id, user_id, set_id, extras_bucket, rarities[], display_name, printings[])`. **One of `set_id` or `extras_bucket` must be set** (CHECK constraint added in migration 46). **Migration 53** adds the `printings text[]` column.

- **Regular set goal**: `set_id` populated. Tracks all cards in that set's `cardsBySetId` matching the rarity filter AND the printings filter.
- **Extras goal**: `extras_bucket` populated with a variant_label string ("Deep Trouble" / "Palace Heist" / "Starter Deck Foil"). Tracks all cards in `extrasCardsByBucket.get(bucket)`. UI shows these under a synthetic section "Extras & Oddities — <bucket>" via key `__extras:<bucket>`, which sorts after mainline sets.
- **Goal modal contract (2026-05-26)**:
  - **Rarities required** — no default-to-all-rarities behavior. The Add button stays disabled until at least one rarity is picked. Most users don't want infinite placeholder cards they then have to remove.
  - **Printings filter** — when the user selects any *base* rarity (Common, Uncommon, Rare, Super Rare, Legendary), a Foil/Non-Foil chip group appears below rarity. At least one must be picked. Chase rarities (Epic, Enchanted, Iconic, Promo) are inherently single-printing and don't trigger the chip group. Persisted to the `printings text[]` column from migration 53.
  - **Schema-tolerant**: the goal-insert payload tries with `printings` first; on 42703 (column missing) the client retries without it. Safe to deploy pre-migration.

## Graded "Bulk Add" modal

`GradedBulkAddModal` (Index.html). Adds many graded cards in a single PostgREST upsert (vs N round trips for the single-add modal). Flow:

1. Pick a set + (optional) extras bucket
2. Pick rarities (multi-select chips)
3. Pick printings (Foil/Non-Foil) — required when rarities include any base rarity
4. Pick default grader + default grade dropdowns
5. Card list renders with one row per (card_id, printing) matching the filters
6. Per-row: checkbox + thumbnail + name + grader override + grade override (defaults to the modal-level defaults)
7. "Check all / Uncheck all" buttons for ergonomic batch selection
8. Submit → `bulkAddItems(rows)` does one upsert call with onConflict=`user_id,card_id,printing,grader,grade`

Mobile constraint: the per-row `<select>` elements need explicit `width:100%; box-sizing:border-box; min-width:0` styles, AND the grid template needs `minmax(0, 1fr)` for the name column (not plain `1fr`). Otherwise native select dropdowns render at their browser-determined natural width and overflow their column, clipping past the modal's `overflow:hidden`.

**Mobile entry point (2026-05-27):** there is ONE mobile FAB (`.gc-add-fab`, the `+` button, ≤700px) inside `.gc-add-fab-wrap`. Tapping it toggles `fabMenuOpen` which renders `.gc-fab-menu` (a popup above the FAB) with two items: **Add a graded card** (→ `setAddOpen`) and **Bulk add** (→ `setBulkAddOpen`). `.gc-fab-backdrop` is a transparent full-screen catcher that closes the menu on outside-tap; the FAB rotates the `+` into an `×` (`.gc-add-fab-open`) while open. There is NO separate bulk FAB — an earlier version stacked two FABs; the popup-menu pattern replaced it. Desktop still uses the header chips (`.gc-add-cta-desktop`: "＋ Bulk add" + "+ Add graded card").

## Graded display: avg_1d primary, avg_30d secondary

`graded_prices_latest` exposes three eBay-windowed averages: `ebay_avg_1d`, `ebay_avg_7d`, `ebay_avg_30d`. **The display contract changed 2026-05-26: `avg_1d` is primary, `avg_30d` is secondary, `avg_7d` is the last-resort fallback.** Previously `avg_7d` was preferred which was the "weird average" user complaint — for low-volume cards (chase rarities especially) the 7d window collapses a single sale and several stale days into one number that doesn't reflect anything users want.

- The 8 inline fallback chains throughout Index.html (~lines 1687, 1696, 8432, 9893, 9965, 10257, 10294, 10538) all switched from `ebay_avg_7d ?? ebay_avg_1d ?? ebay_avg_30d` → `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d`.
- The GradedPricesTab detail table renders all three columns explicitly (header reads "Latest avg · 7d avg · 30d avg") so users can inspect the windowed history — only the SINGLE-PRICE displays elsewhere on the site swapped.
- "Last Sale + Avg of last 5" was the user's literal request. **Since shipped** for premium viewers off the in-house `graded_sales` per-sale table (the old feed only exposed daily aggregates, which is why it was impossible then). Non-premium users still see the frozen legacy averages.

## CardDetailModal foil checkbox auto-hide

Chase rarities (Enchanted / Iconic / Epic / Promo) have only one printing per card_id — usually stored under `group.foil`. The "Show foil" checkbox previously rendered whenever `group.foil` existed, even on these single-printing cards. Side effect: if the user had unchecked Foil from a prior visit, the chart would zero out when they opened a chase card.

Fix (`effectiveShowFoil = (group.normal && group.foil) ? showFoil : true`):
- The checkbox is hidden when only one printing exists (both `group.normal && group.foil` must be truthy for it to render).
- `buildHistorySeries` receives `showFoil: effectiveShowFoil` so the foil line forces-on when there's no Normal to compare against.
- The Foil legend swatch also reads `effectiveShowFoil` so it stays in sync.

## Graded tab — featured chart + inline expand

Card detail modal's Graded tab:
- **Top featured chart**: 12-month LineChart defaulting to PSA 10 (falls back to first available combo if no PSA 10 history).
- **Per-row sparkline buttons**: click any row's sparkline → expands a full LineChart inline beneath that row. Multiple rows can expand at once for grade-premium comparison.
- Helper: `buildGradedSeries(history, grader, grade, label)`. Color map: PSA red, CGC blue, BGS purple, SGC green, TAG orange.

## Retailer-exclusive sealed product (2026-09-20)

Full notes: `docs/claude/retailer-exclusive-sealed-product.md` (5 KB). **Read it before changing this area.**
`SEALED_EXCLUSIVES` — a box you can only buy at one chain, which therefore has no TCGplayer listing, no pid, no price and no `sealed_prices_latest` row.
Guards: `scripts/test_amazon_links.mjs`.

- ⚠ `set_id` is NULL, which files it under "Other / Promo"
- ⚠ `n` is a stable hand-assigned id.
- ⚠ This is the one static catalog whose rows can become REAL TCGplayer products — and the first one did, in four days.
- ⚠ NOTHING flags that moment.
- ⚠ It runs over a FIXTURE entry spliced into the real `.map`

## Sealed product info + Collection set grid (2026-09-30)

Full notes: `docs/claude/sealed-product-info.md`. **Read it before changing this area.**

- `SEALED_PRODUCT_INFO` (keyed by TCGplayer pid) drives **About this product**; every entry was read off a named source, and an unverifiable field is ABSENT, never guessed. Retailer claims are published to users.
- A promo set absent from `SET_ORDER` is never drawn in the Collection grid. A new promo set needs `SET_ORDER`, `UNIFIED_TILE_SETS`, `PROMO_RARITY_SETS`, `NUMBERED_PROMO_SETS`, `DREAMBORN_CN_SUFFIX_SETS`, then `node discord/tools/extract_site.mjs`.

## /box — the invite-only Ink.Box page (2026-10-02)

Full notes: `docs/claude/box.md`. **Read it before changing this area.**

- **⚠ `box.html` is GENERATED** from the Ink.Box repo (`python tools/packsink.py build`, copy `dist/box.html`). Rotating `SUPABASE_URL` / `SUPABASE_KEY` / `DECK_ENC_KEY_B64` in Index.html means rebuilding it; `scripts/test_box_page.mjs` goes red until you do.
- Not for normal people: noindex + robots Disallow + no links + `is_inkbox_user()` gate (migration 177). The RPC gate is the real one.

## Sealed enhancements (2026-06-05 — modal + Δ% + Screener)

Full notes: `docs/claude/sealed-enhancements.md` (4 KB). **Read it before changing this area.**
Three parallel additions made sealed feel like graded:

## Cost & date tracking (sealed + graded collection)

Full notes: `docs/claude/cost-date-tracking.md` (3 KB). **Read it before changing this area.**
Migration 48 added optional `amount_paid numeric(12,2)` + `acquired_date date` to both `sealed_collection_items` and `graded_collection_items`.

## Collection Value chart: phantom-spike smoothing (migration 55)

Full notes: `docs/claude/collection-value-chart.md` (6 KB). **Read it before changing this area.**
TCGCSV's `low_price` is a published aggregate, not a sale price (and NOT the listing floor — see the TCGCSV notes) — it detaches from what is actually trading and pins Low at $99 / $200 / $2,140 for days while NM Market never moves (Black Cauldron Cold Foil 2026-05-14 → 2026-05-26 is the canonical e…
Covers: Algorithm (`scripts/smooth_low_prices.py`); Wiring; Tunables; Synthetic test cases (run before changing the algorithm).

## Analytics tab (reorganized 2026-08-20: 8 tabs → 5)

Full notes: `docs/claude/analytics-tab.md` (12 KB). **Read it before changing this area.**
`MARKET_SUBS` = overview / ev / trade / avg ("Set Breakdown") / setval / sim / swiss / lore / dice / ticker (+ elo, hidden unless pinned).
Guards: `scripts/test_csp_headers.mjs`.

- ⚠ Both embeds need a `_headers` carve-out or the tab renders the browser's gray broken-page icon.
- ⚠ `/ticker` must keep having NO worker route.
- ⚠ The Low / NM Market toggle ALWAYS opens on Low, and is NOT persisted

## Trade Comparison tool (Analytics » Trade Compare)

Full notes: `docs/claude/trade-comparison-tool.md` (11 KB). **Read it before changing this area.**
`TradeView` (Index.html).
Guards: `scripts/test_promo_single_printing.mjs`.
Covers: Shareable trade links (DB-backed); Promo sets are named by the PRINTED suffix.

- ⚠ A filled-in pid reaches the `cards` rows only when the script runs FROM `main`.
- ⚠ Delete a retired `art` file only AFTER the rows point at TCGplayer
- ⚠ Check Lorcast before hand-writing any promo's stats.
- ⚠ Nothing official says they are foil

## duels.ink is the art source for stand-ins (2026-09-30)

Full notes: `docs/claude/duels-ink-is-the-art-source.md` (2 KB). **Read it before changing this area.**
A stand-in built from a pasted screenshot (`import_pasted_cards.py`) is the weakest art we carry: tilted, still in the reveal photo's yellow backdrop, cut off at an edge, or 125px wide (RPH #1/#2/#3/#5 were).
Guards: `scripts/test_import_duels_art.py`, `test_scanner_asset_cache.mjs`.

## Illumineer's Quest cards are NOT promos (2026-10-03)

An Illumineer's Quest is a co-op board game in a box. The cards in its scenario
deck (Ursula's, Jafar's, the Vine's) are game pieces, so they never take the
Promo rarity and never sit with the promo sets (Zaven). Rarity **"Quest"**, three
sets in `QUEST_SETS`, a ruled-off **Illumineer's Quests** section at the foot of
the Collection grid, out of the headline completion %, the reveal reel and the
Discord movers report. Guarded by `node scripts/test_quest_cards.mjs` and
`python scripts/test_import_quest_cards.py`.

- **Q3 The Great Hunny Rescue** is Lorcast's (`Hunny Rescue – Illumineer's Quest`,
  mapped in `SET_DISPLAY_NAMES`). Lorcast files it as Promo; `load_lorcast.py`
  writes "Quest" for any set code `Q<n>`. TCGplayer is listing its singles in
  waves (group 24734); `TCGCSV_GROUP_SET_ALIASES` binds that group to the set,
  so `link_preorder_pids.py` links each one as it appears, every ETL run.
- **Q1 Deep Trouble (31) and Q2 Palace Heist (35)** Lorcast never indexed.
  `python scripts/import_quest_cards.py [--commit]` loads them from LorcanaJSON
  into hand-minted sets `set_quest_q1` / `set_quest_q2` (migration 179, codes
  Q1/Q2, so a later Lorcast copy is skipped by the code-collision check), ids
  `crd_quest_<q>_<n>`, official art copied to `card-art/quests/`. TCGplayer sells
  them (groups 23528 / 24257, already priced as sealed "Promo Single" rows), so
  the pid gives them a price.
- **Oversized cards** (boss card, Reforged Crown, double-sided battlegrounds)
  come from TCGplayer's listing via the same script: `crd_quest_<q>_os<k>`
  (numbered by product id, so stable), no collector number, "(Oversized)" in the
  version. Q3 has none listed yet; re-run the script when it does.
  TCGplayer has NO photo for three Palace Heist pieces (Reforged Crown, both
  battlegrounds: 403 at every size); `ART_OVERRIDES` takes CardTrader's scans.
- **A Battleground is landscape, like a Location**: its image is stored on its
  side (the importer turns a landscape scan a quarter turn) and
  `isLandscapeCard` turns it back upright.
- The three Quest BOXES now file under their quest set in the Sealed tab (the
  ETL's group→set mapping matches them by name), not "Other / Promo".
- The foil promo cards packed in the boxes (Mickey - Playful Sorcerer, Bolt -
  Superdog ...) are playable cards and stay in Extras & Oddities.

## Set conventions

Full notes: `docs/claude/set-conventions.md` (14 KB). **Read it before changing this area.**
`.github/workflows/catalog-watch.yml`, daily at 03:30 UTC (after the ETL window), running `python scripts/reconcile_catalog.py --watch`.
Guards: `scripts/test_watch_sources.py`, `scripts/test_catalog_watch.py`.
Covers: Catalog watch — the thing that tells you a new set exists; ⚠ `missing_set` is an ID test, and a set id is not a set; Source watch: the sites we research from; The PSA population refresh — weekly, and half of it cannot be automated.

- ⚠ `missing_set` is an ID test, and a set id is not a set (2026-09-13)
- ⚠ A red run cannot get redder, so new findings are called out separately (2026-09-30).
- ⚠ It checks the DATA's age, not a calendar, and that is the whole reason it is not a `reviews` entry.
- ⚠ The ack key carries the last pull's DATE (`psa:2026-09-22`), never a bare `psa`.
- ⚠ Every failure of the check is SILENCE.
- ⚠ Never automate the collectors.com sign-in, and never retry past a wall.

## Inks & dual-ink cards

Six single inks + dual-ink cards (late 2025+). Lorcast exposes duals as `inks: ["Emerald","Sapphire"]` with `ink: null`. **Always read `meta.inks` first, fall back to `[meta.ink]`**.

- Migration 27 adds `inks text[]`.
- `load_lorcast.py` writes both `ink` (= inks[0]) and `inks`.
- Backfill: `scripts/patch_card_inks.py`.

**Rendering:** dual-ink character's pie/curve bucket keys on joined ink names ("Emerald/Sapphire"). Pie uses flat slate (`DUAL_INK_PIE_COLOR`) + "dual" pill in legend. Cost-curve bar uses 135° diagonal gradient. Deck-row ink swatch is a 14px circle with hard mid-line divider. **`checkDeckLegality`** treats duals as contributing both colors (Emerald/Sapphire dual + Amber single = 3 inks = over cap).

## Deck-build limit exceptions

Default 4-of-any-card. `SPECIAL_DECK_LIMITS` in Index.html:
- `"Dalmatian Puppy - Tail Wagger"` → 99 (Puppy Power; variants share total)
- `"Microbots"` → Infinity (UI caps at 99)

`getDeckLimit(name)` returns cap. `getDeckLimitForUI(name)` clamps Infinity to 99. `checkDeckLegality` sums by Product Name across variants before comparing. DB constraint relaxed to `quantity <= 99` in migration 28.

## Ink-limit exceptions ("Gather the Party" cards, 2026-09-16)

Some cards grant **OTHER** characters of a named classification an exemption from the
2-ink cap — Christopher Robin - Hunny Sage's "Gather the Party" ("You can have other
Hunny characters in your deck regardless of ink type") is the shipping example. A
6-Hunny-ink Christopher Robin deck was reporting `6 inks — limit is 2` and reading as
invalid, because `checkDeckLegality`'s ink `Set` summed every card's ink with no
exceptions at all — unlike the quantity cap, which already had `SPECIAL_DECK_LIMITS`.

- **`partyClassificationOf(text)` detects the grant from the card's OWN `text`**
  (`PARTY_RULE_RE`), not a hardcoded name→classification map — so a future printing of
  the same mechanic (a different classification) works with no code change, the same
  reasoning `keywords` extraction uses.
- **"Other" is load-bearing.** The exemption is matched by `grantorName !== name` (both
  Product Name, not card_id, so any printing of the granting card still excludes
  itself) — the granting card's OWN ink still counts toward the limit. Only a
  DIFFERENT card sharing the named classification is exempt.
- `checkDeckLegality` gathers every grant in the deck first (`partyGrants`), then skips
  a card's ink contribution when its `classifications` include a grant it didn't itself
  make. Multiple different granting cards (present or future) compose for free.

## Decks tab — logged-out access (2026-06-05)

Full notes: `docs/claude/decks-tab.md` (2 KB). **Read it before changing this area.**
The Decks tab is **usable without signing in**.

## Deck version history (migration 125)

Full notes: `docs/claude/deck-version-history.md` (2 KB). **Read it before changing this area.**
**A version is one EDITING SESSION, not one keystroke.** The editor already snapshots the deck when you enter edit mode (`editSnapshot`, which powers "Undo changes"); leaving edit mode writes that pre-edit state as the next version — but only if `deckCardsSignature` says something actually changed.
Guards: `scripts/test_deck_versions.mjs`.

## Deck tiles: Preview is the corner button, and it opens the IMAGE (2026-08-24)

- **`.deck-card-preview`** is a 44px button pinned bottom-right of every deck tile (owned,
  Discover, tournament). "Show me the deck" is the most-wanted thing on a tile and it was one
  small chip among seven. `.deck-card-actions` carries `padding-right:52px` so a wrapping action
  row never runs underneath it.
- **`DeckPosterModal` takes `viewOnly`** and renders a full-screen preview instead of the export
  screen: a bar (Copy / Save / **Options** / x) over a `.poster-view-stage` that clips and
  centres the poster. The poster is a FIXED-WIDTH document on purpose (so the exported PNG is
  identical on every device), so fitting it to the viewport is a measured `transform: scale()`,
  not a responsive layout — a `ResizeObserver` plus a 6s keepalive (card art lands after mount
  and changes the height). `fit` starts at 0 and the stage stays transparent until the first
  measure, so a full-size flash never paints. **Options** flips to the old export modal.
- **The toolbar's Decklist button copies straight to the clipboard.** It used to open a modal
  holding a textarea and a Copy button — nobody wanted to READ the list. The modal is now only
  the fallback for when `navigator.clipboard` refuses, which is the one case where showing the
  text IS the answer.

## Print proxies: one scroll surface, and the watermark is not optional (2026-08-24)

- **The card list has NO nested scroll.** A scroll box inside a scrolling modal is what made this
  unusable — the list was a ~130px peephole because a flex item with `overflow-y:auto` gets
  `min-height:0` and collapsed far below its own `max-height`. The modal body is now the only
  scroll surface; the list is a grid (`--proxy-cols`, set per deck: 1 column under 9 cards, +1
  more past 1000px) so most decks fit whole. Measured: a 15-unique deck shows all 15 with no
  scrolling at all on desktop.
- **`.proxy-foot` is sticky** — summary, the Scale:100% warning and Build PDF stay put, so the
  button is never below the fold on a 60-unique deck.
- **The "None" watermark option is GONE.** An unmarked proxy is indistinguishable from a real
  card in a photograph, and the corner tag was already the discreet choice. An old stored pref of
  `"none"` falls through to the default.

## Deck action buttons — one system (2026-08-24)

The deck toolbar and all three tile variants (owned / Discover / tournament) share `.deck-act`. Before this they were a mix of emoji labels and per-button inline styles where every button carried the same weight and nothing said which ones belonged together.

- **Icons are drawn SVG (`DECK_ICONS`, `VIS_ICONS`), never emoji.** Emoji can't take `currentColor`, so they stayed full-colour on a themed button, and they render at a different size and metric in every font stack — that's what made the row look ragged. `_deckSvg` is the `_navSvg` pattern at 14px.
- **`.deck-act-sep` is the point.** A hairline between clusters turns eleven equal buttons into five things you might want to do. Toolbar order: **Edit/Import/Undo · Share/Notes/History · Mulligan · Image/Proxies/Decklist · Duplicate/Delete**. Tiles: **Link/List/Image/Preview · Rename/Duplicate/Delete**, so a wrap on a narrow tile lands on the group boundary instead of mid-thought. Dividers are hidden at ≤520px, where the row is several lines anyway and they read as noise.
- Export labels drop the verb the group already implies (`Export Image` → **Image**, `Print Proxies` → **Proxies**, `Export Decklist Text` → **Decklist**); the `title` keeps the full phrasing. Desktop went 2 rows → **1**.
- `.deck-act--danger` colours on **hover**, not at rest — a row of red buttons makes Delete no more careful than Duplicate.
- **⚠️ One `class` attribute per element.** htm keeps the LAST and silently drops the first, which is how the Notes button lost `deck-act` and kept its emoji through a whole verification pass. If a class needs to be conditional, build the whole string in one expression.

## Deck-tile copy actions (🔗 / 📋 / 🖼)

Full notes: `docs/claude/deck-tile-copy-actions.md` (4 KB). **Read it before changing this area.**
Every deck-card tile in DecksView (owned, Discover, Favorites, Following, the per-tournament tile inside TournamentDetailView) carries three actions.
Covers: Headless deck-poster autoCopy; TournamentDetailView is deck tiles, not a list.

## Cards-tile magnify button + enlarged-card overlay

Full notes: `docs/claude/cards-tile-magnify-button-enlarged-card.md` (3 KB). **Read it before changing this area.**
Every `CardTileImpl` — browse mode AND deck-builder card browser — has a tiny `.tile-magnify-btn` (22×22, inline Lucide-style SVG circle+line) in the bottom-left of the image wrap.

## SPA navigation: `<a href>` not `<button>` so modifier-clicks work

User complaint: "you can't ctrl+click or right-click open in new tab on links, tabs, etc". A `<button onClick={navigate}>` intercepts EVERY click — Ctrl/Cmd/Shift/Alt-click and middle-click silently fall through to the same SPA navigation instead of opening a new tab, and right-click context menu doesn't offer "Open in new tab".

Fix: nav targets are `<a href={deepLink}>` with module-scope helpers:

```js
const isModifiedClick = (e) =>
  e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || (e.button != null && e.button !== 0);

const navCapture = (e) => {
  if(e.target !== e.currentTarget && e.target.closest("button, a, input, select, label, textarea")){
    e.preventDefault();
  }
};

const navHandler = (fn) => (e) => {
  if(isModifiedClick(e) || e.defaultPrevented) return;
  e.preventDefault();
  fn(e);
};
```

`navHandler(fn)` is the standard `onClick` for a nav `<a>`. `navCapture` goes on `onClickCapture` whenever the `<a>` wraps nested `<button>`s (deck tiles, tournament-detail tiles) — a nested button's `stopPropagation` doesn't cancel the `<a>`'s browser-default navigation, so without `navCapture` the browser would navigate AFTER the button's handler fired.

**Surfaces converted:** top-nav tabs (Collection / Cards / Decks / Screener / Price Graphing / Analytics), logo home button, tournament cards in the Decks → Tournaments tab list, owned deck tiles, external deck tiles, tournament-detail deck tiles.

The nested-interactive HTML (button inside `<a>`) is technically invalid but every browser in practice tolerates it, AND the user gets every link affordance: modifier-click opens new tab via browser default, right-click shows "Open in new tab", middle-click works, hover shows the destination URL in the status bar, devtools can copy the link.

**Common bug**: when converting `<button>` → `<a>`, also flip the matching `</button>` → `</a>`. The first pass missed the closing tag on `.tournament-card` and the page broke until the close tag was flipped.

## Home panels: the title is a link, and the width decides where to (2026-09-06)

Full notes: `docs/claude/home-panels.md` (4 KB). **Read it before changing this area.**
You could not link anyone to one box on the home page — "the tournament box" was "scroll down".
Guards: `scripts/test_share_links.mjs`.

- ⚠ `useMaxWidth(1100)` is a HOOK

## Shareable sub-tab URLs — `?s=` / `?f=` / `?m=` / `?c=`

Full notes: `docs/claude/shareable-sub-tab-urls.md` (5 KB). **Read it before changing this area.**
Decks' sections and the Screener's mode were localStorage-only, so every one of them lived at `/decks` or `/screener` and **none could be linked to** — "here's the Coconut feed" was not a sendable thing.
Guards: `scripts/test_share_links.mjs`.
Covers: "Copy link to this page".

## [Format Coconut] starter decks + Discover's third tab (2026-08-22)

Full notes: `docs/claude/format-coconut-starter-decks-discover-s.md` (12 KB). **Read it before changing this area.**
**`DISCOVER_FORMATS`** is now the single source for Discover's sub-tabs — `core` / `infinity` / `coconut`, keyed on exactly what `checkDeckLegality()` stamps as `format`.
Guards: `test_coconut_legality.mjs`, `test_coconut_legality.mjs`.
Covers: A Coconut reveal is news for a fortnight.

- ⚠ They are the OLDEST public decks on the site, and that is what made them disappear.
- ⚠ The starter fetch must NOT feed the `<12` fallback count.
- ⚠ A dual-ink leader's `LEADERS` entry is a TUPLE of both inks
- ⚠ It keys on an explicit `revealed:"YYYY-MM-DD"` on the entry, NOT on `cn`.
- ⚠ A reveal date in the FUTURE is ignored rather than trusted.
- ⚠ The tile is gated on the row being in `raw`

## Deck sharing model

Three visibility states, each with a 22-char URL-safe `share_token` (~128 bits):

| Visibility | Direct read RLS | URL behavior | Discovery |
|---|---|---|---|
| Private | owner only | none | excluded |
| Unlisted | owner only | `?deck=<id>&token=<x>` works | excluded |
| Public | owner OR anyone | `?deck=<id>` works | included |

- Non-owner reads of unlisted decks go through SECURITY DEFINER `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` RPCs (token-gated). **The RPC's RETURNS TABLE must include every column the client reads.** Migration 30 added `youtube_url` via drop-and-recreate.
- Flipping a deck to a LESS-visible state auto-rotates the share token via the `rotate_share_token_on_private` trigger (migration 65 widened it from "→ private only" to **any visibility decrease** — public→unlisted and public→private and unlisted→private). Every in-the-wild URL for that deck stops working instantly. Going MORE visible (e.g. unlisted→public) does NOT rotate.
- Owner-only `regenerate_deck_share_token(uuid)` RPC for manual revocation.
- Favorites of unlisted decks store the token at favorite-time (`deck_favorites.share_token`); rotation drops the favorite gracefully.
- Discovery surfaces: Favorites, Following (user_follows), Discover (all public, cursor-paginated), Creator profile (`?user=<uuid>`).
- Aggregate metrics via SECURITY DEFINER RPCs (`deck_favorite_counts(uuid[])`, `deck_view_counts(uuid[])`) return totals only.

## Collection sharing

Mirrors deck sharing but with three independent visibility axes (raw / sealed / graded). `profiles.collection_raw_visibility` + `collection_sealed_visibility` + `collection_graded_visibility` + shared `profiles.collection_share_token`.

- Non-owner reads always go through SECURITY DEFINER RPCs (`get_shared_collection_raw/sealed/graded(uuid, text)`). Direct table reads stay owner-only via RLS.
- `get_collection_visibility(uuid, text)` returns the three per-section booleans.
- One token across all three sections; trigger rotates when all three go private simultaneously.
- **`profiles.collection_share_token` is NOT readable via the table API** (migration 63). The `profiles` table grant was narrowed from full-row SELECT to a safe-column allow-list (everything EXCEPT the token); the owner reads their own token via the `get_my_collection_settings()` SECURITY DEFINER RPC (auth.uid()-scoped, authenticated-only). A bare column REVOKE does NOT work against a table-level grant — must drop the table SELECT and re-grant columns. Never add `collection_share_token` back to a client `profiles` select (it 403s).
- **Shared-collection RPCs do NOT expose `amount_paid` / graded `custom_value`** (migration 65) — only the owner sees their own purchase cost (direct table reads). `get_shared_collection_sealed/_graded` return quantity + `acquired_date` (needed for viewer value-chart gating) but no price the owner paid.
- Owner-only `regenerate_collection_share_token()` RPC.
- Viewer mode = `?collection=<uuid>` in URL. Fetches via visibility-gated RPCs.
- **`paginateRpc` is required** for `get_shared_collection_*` (PostgREST caps RPC table-returns at 1000).
- **InlineCounter in read-only mode** renders qty without +/- buttons (don't return empty div — breaks grid alignment).
- Viewer-mode comparison stats need viewer to be signed in.

## Tournaments

Full notes: `docs/claude/tournaments.md` (3 KB). **Read it before changing this area.**
Admin-gated bulk-upload.

## Deck view / edit modes

Full notes: `docs/claude/deck-view-edit-modes.md` (9 KB). **Read it before changing this area.**
Click own deck → defaults to **view** (no card browser, no rename); toolbar has **✎ Edit** toggle.
Covers: Deck focus — the second desktop edit layout; Deck editor mobile bottom bar; HIGHLIGHT MISSING (flipped logic 2026-05-26); Deck row mobile compaction.

- ⚠ The thumbnail must NOT be `loading="lazy"`.

## Deck import — text parser

Full notes: `docs/claude/deck-import.md` (4 KB). **Read it before changing this area.**
`parseDeckText(text, raw)` — used by Bulk Upload, import deck text, tournament rows.
Guards: `scripts/test_deck_text.mjs`, `test_coconut_legality.mjs`, `test_reprints.mjs`.
Covers: The decklist round trip; One card, however it's spelled — `cardFamilyKey`.

- ⚠ The export is a PLAIN list — no `# Section` headers, no blank lines

## Deck poster export

`DeckPosterModal` renders the poster as live HTML, snapshots via html2canvas on Copy/Save.

- **Always renders at desktop width (`min-width: 1000px`).** Wrap is `overflow-x: auto` so mobile users can swipe-scroll the preview — but exports always produce the desktop layout regardless of viewport. (Previous `@media (max-width:560px)` vertical-stack broke mobile exports.)
- **Header layout**: title + costs (left) | stats + cost-curve (middle) | logo + QR stacked (top right).
- **Cost curve and stats align at x=0** — curve SVG has `padL=0` and bar formula skips leading `gap/2` so first bar starts flush with "60 CARDS".
- **Logo + QR vertical stack** on the top right (96px each, 8px gap). Width was 192px (side-by-side); now ~96px → stats get the freed horizontal room.
- **Options grouped**: Layout (Background + Columns), Show (Stats + Cost curve), Costs (Non-Foil/Foil/Max Rarity $), Share (QR + URL footer; locked + click-to-make-unlisted when deck is Private and viewer is owner).
- **Bottom row**: `packs.ink · <date>` (left) + URL (right).

## Print proxies (deck → print-and-cut PDF)

Full notes: `docs/claude/print-proxies.md` (12 KB). **Read it before changing this area.**
`ProxyPrintModal` (Index.html, just after `DeckPosterModal`).
Guards: `scripts/test_proxy_pdf.mjs`, `test_brand_art.mjs`.
Covers: Blank-art face — the real card, art window left blank; Printer-friendly face — the card REDRAWN in outline.

## Artist Alley poster

`window.open` opens a self-contained poster in a new tab. Plain `<img>` tags + same-origin `/img-proxy/*` for Lorcast art (canvas exports work cleanly).

- **`.brand-footer`** at bottom with Packs.Ink logo (110px) + "packs.ink" wordmark. Stays visible in screen + print + html2canvas capture.
- **Copy as Image**: html2canvas → single tall PNG → clipboard.
- **Save JPG**: html2canvas → adaptive scale + q=0.85 → recompress (q=0.78 → 0.55) until under 9.5MB (Discord cap).
- **Print PDF path** preserves dark poster via `print-color-adjust: exact`. `break-inside: avoid` on figures. Pinned to 6 cols via `!important` in `@media print`.

## Copy-to-clipboard image exports

Full notes: `docs/claude/copy-to-clipboard-image-exports.md` (5 KB). **Read it before changing this area.**
Three "copy this as an image" features.
Covers: Why card exports moved off html2canvas; Surfaces; In-modal "Price changes" panel (not an image — the live DOM panel); html2canvas-1.4.1 gotchas (apply to the mover tile + ANY future html2canvas export).

## PWA install nudge

Auto-opens `InstallHelpModal` on visits 3 and 4 (counter at `localStorage["packsink:installVisits"]`; window bumped from 2–3 on 2026-08-21 — "the 3rd time they open it and haven't installed" was the ask, so newcomers get two visits of grace). Skipped entirely when already standalone, on desktop, or after the user clicked "Don't show this again" (`packsink:installDismissed`). Modal title/copy is framed as **"Packs.Ink is an app"** — you're on the website, it also installs (home-screen icon, full screen, offline, nothing from a store) — not as a generic install plea.

Modal accepts `onDismissForever`; only passed on visit ≥4 so the dismiss link appears the second time the modal pops. Existing users whose counter is already past 4 never see the auto-nudge again (intended — the manual 📲 bubble and settings remain).

## First-time sign-in onboarding

Two prompts fire in sequence on a fresh sign-in:

1. **Display name prompt** (`showNamePrompt` state in App): opens whenever `profiles.display_name` is empty for the signed-in user. Triggers via the `useEffect` that hydrates the profile row. Closes via `saveDisplayName` (which writes the name and flips the flag).
2. **Avatar picker** (`AvatarPicker` component): auto-opens 200ms after the user finishes step 1, gated by `localStorage["packsink:avatarPromptShown"]` and `!avatarCardId`. Picks ANY card from the catalog as the user's profile picture (writes `avatarCardId` to user_metadata + localStorage). The 200ms defer keeps the name-prompt unmount animation from fighting the picker mount.

The avatar gate is one-shot — closing the picker once flips `packsink:avatarPromptShown` so returning users without an avatar aren't pestered on every visit. Settings-popover edits to display name DON'T trigger the avatar prompt (the trigger is gated on `wasFirstTime = showNamePrompt` at save time).

## Home page surface

Full notes: `docs/claude/home-page-surface.md` (29 KB). **Read it before changing this area.**
Zaven, off his phone: *"Reimagine this section, its ugly."* It was a five-column table that stacked into orphaned numbers under misaligned headers, with four amber Amazon pills down the right edge and two native checkboxes (`<$1→$0`).
Guards: `scripts/test_home_layout.mjs`, `scripts/test_sealed_movers.mjs`.
Covers: Recent set EV — one card per set; Configurable layout; Your Graded Movers is a movers ROW, not a panel; Pairing a panel with a movers banner; The at-the-table shortcuts are `fixed` panels; Artist Alley poster: columns follow the CARD COUNT; Movers-banner chip filters (`MoverChipGroup`); Sealed Movers; Mobile: the movers stack is ONE row plus a chip strip; The news box collapses, and un-collapses itself.

- ⚠ The box price lives INSIDE TCGplayer's own button
- ⚠ Every layout switch is a CONTAINER query on the panel (`hev`), never a media query
- ⚠ The set logo sits in a FIXED slot
- ⚠️ Changing a panel's default `col` does NOT reach existing users.
- ⚠️ The marquee renders `cards` TWICE
- ⚠ The Rare–Legendary key carries the news feed

## Mobile top-nav

Whole top bar is a single horizontal scroll container on phones (`overflow-x: auto`). Logo is `position: sticky; left: 0` so it stays pinned to the left edge. Tabs + username pill + theme toggle all scroll together → reclaims width that was previously fixed-right cluster space.

Settings popover is force-pinned to `position: fixed; top: 56px; right: 8px` on mobile so the parent `overflow-x: auto` doesn't clip it (CSS spec forces overflow-y when overflow-x is non-visible).

## Translucent popovers — `--bg-card` vs `--bg-modal`

**`--bg-card` is translucent in dark mode** (`rgba(255,255,255,0.06)`). Don't use it for modal/popup backgrounds — they're unreadable in dark mode. Use **`--bg-modal`** (opaque in both themes) for popovers/menus.

Audited 2026-05-24 — all menus/popovers now use `--bg-modal`: `.cards-bulk-menu`, `.price-db-batchmenu`, `.price-db-multimenu`, `.smart-suggest-pop`, `.deck-notes-popover`, `.deck-share-popover`, `.deck-view-popover`. `.home-quick-search-list`, `.collection-share-popover`, `.settings-popover` (via `--bg`), `.modal`, `.name-prompt`, `.card-detail`, `.drawer` were already opaque.

## Screener sticky NAME column

The 3rd column is `position: sticky; left: 0` with `background: var(--bg-modal)` + right-edge `box-shadow: 1px 0 0 var(--border), 6px 0 8px -6px rgba(0,0,0,0.35)`. The shadow makes other columns visually pass UNDER the sticky column when scrolling horizontally (prevents header overlap that the previous translucent `--bg-surface` background caused).

## Fonts — ask for a RANGE, or the site has no bold (2026-09-14)

Full notes: `docs/claude/fonts.md` (3 KB). **Read it before changing this area.**
Two families, two files: **Cinzel** (`h1,h2,h3,.title-font`, the display face) and **Nunito Sans** (everything else).

- ⚠ That is not a size optimisation, it is the only reason `font-weight:700` does anything.
- ⚠ Narrowing either family back to a `;`-list silently flattens bold again

## ⚠ A hover preview must be MOUSE-ONLY (2026-09-21)

Touch fires a synthetic `mouseenter` and **never a matching `mouseleave`**, so any
hover preview opened by a tap floats over the page until something else is tapped —
scrolling does not clear it, and the thing it covers is the list you were reading.
Reported from the Collection set-detail rows: nudging a card's `+` left a full card
image parked over the rows, because the counter sits inside `.sd-row`, whose
`onMouseEnter` fired from the tap.

- **`mouseHoverOnly(fn)`** (beside `uiIcon`) is the one accessor: it wraps the ENTER
  and MOVE halves and runs them only for `e.pointerType === "mouse"`. The LEAVE half
  stays **unwrapped**, so anything that did somehow open can always close itself.
- Same rule the calendar's `useCalHoverCard` already followed; this generalises it.
- Converted: the Collection set-detail row (`.sd-row-preview`), the Screener's row
  thumbnail, the deck editor's list row, the deck quick-add row, and the graded-sales
  admin table. **⚠ The quick-add row's `setCursor(i)` rides the same gate** — a touch
  has no cursor to move, and its tap already adds the card.
- **⚠ Not every `onMouseEnter` is this bug.** `Tip` is deliberately tap-toggleable with
  its own 4s auto-hide, the smart-search dropdown's is a keyboard-cursor highlight, and
  the movers marquees' `hoverRef` pause is wanted on touch. Only a FLOATING PREVIEW that
  nothing on screen can dismiss needs the gate.
- **⚠ Verify it by dispatching `pointerover`/`pointerenter`, not `mouseenter`** — React
  simulates enter/leave from the over/out pair, so a bare `pointerenter` reaches nothing.
  Measured in the live page: touch leaves no `.deck-hover-preview`, mouse creates one,
  and `pointerout` removes it.

## CSS pitfalls

- **`mask-image` on a container softens child `<img>`s** by forcing offscreen compositing. Use absolutely-positioned gradient pseudo-elements for edge fades. Same caution: `will-change: transform`, `filter: blur(0)`, `transform: translateZ(0)`, `opacity: 0.99`.
- **`image-rendering: crisp-edges`** is for pixel-art. Default `auto` for card photos.
- **Conditional grid cells break `grid-template-columns` alignment.** Always render a wrapper element for the slot, conditionally render the content inside. Example: `<span class="sd-row-rarity-slot">${RARITY_ICONS[r] && html\`<img.../>\`}</span>`.
- **`-webkit-overflow-scrolling: touch` is a no-op on iOS 13+.** Modern iOS Safari auto-applies inertial scroll. Audits will recommend adding this property defensively; it's harmless but doesn't actually fix anything on the user's test devices (iPhone 17 Pro / iOS 18+). Don't burn time on cargo-cult additions.
- **Two `@media` queries with overlapping breakpoints fight each other on cascade tiebreaker.** The EV and Sealed views used to have BOTH a `@media (max-width:780px)` block AND a `@media (max-width:820px)` block defining `.ev-row` / `.sealed-row` layout. Both matched on iPhone width; only one of the rules' overrides won per property, depending on source order. Removed the 820px block on 2026-05-26. **One canonical mobile breakpoint per surface.** Default = 640px for general mobile, 780px for tables with many columns, 1100px when collapsing a sidebar-grid to flex column.
- **Default rules with same specificity as `@media` rules MUST come BEFORE the `@media` block.** Otherwise source order makes the default win at the matching breakpoint, defeating the override. Tripped this on `.ev-row-val-lbl-inline{display:none}` initially — had to move it above its `@media` override.

## Tables → labeled card stacks on mobile

Three multi-column tables on the site (EV rows, Sealed rows, Price Graphing "compare stats" table) all hit the same problem: head-row labels get `display:none` at narrow widths to save space, then data rows show floating numbers with no column context. The pattern:

- **EV rows** (`.ev-row` data rows): each value cell gets an inline label `<span class="ev-row-val-lbl-inline">` (e.g. "per box", "per pack", "box price", "EV − box"). Hidden on desktop (head row carries labels there), shown via the mobile @media rule. The 6-window delta pills are hidden on mobile entirely via `.ev-rows .ev-row-deltas, .ev-row .ev-row-deltas { display: none !important; }` (specific selector beats the top-level `.ev-row-deltas{display:grid}` independent of !important — defends against caching layers that strip the important annotation during stylesheet parse).
- **Sealed rows** (`.sealed-row`): same delta-pill hide; set pill kept visible on mobile since sections aren't always obvious when scrolling fast.
- **Compare stats table** (`.compare-stats-table` at Price Graphing bottom): full pivot to per-row card stack at ≤640px. `tr { display: grid; }`, `thead { display: none; }`, each `<td>` gets an injected `::before` label ("Start", "End", "Change") via `nth-child(5/6/7)`. Replaced an earlier `overflow-x:auto` scroller that users couldn't tell was scrollable (iOS hides scrollbars).

If you add a new multi-column table that needs to work on mobile, follow the same pattern — don't fall back to horizontal-scroll-only.

## Segmented control wrap on mobile

`.seg-toggle` (the rounded-pill multi-button group used for Price Graphing tabs, range buttons, foil mode toggle, etc.) has `overflow:hidden` on desktop. At ≤640px the `@media` rule converts each button into an independently-rounded chip and lets the group `flex-wrap: wrap` so a 7-button row (Since Release / 1Y / 6M / 3M / 1M / 1W / Custom) flows onto two rows instead of getting clipped. 4-button groups stay on a single row visually. New seg-toggle uses get this for free.

## Home page panel layout (sticky behavior)

`.home-feed` (the Following panel and Tournament Results banner — both render as `<aside class="home-feed">`) is **NOT sticky** on any viewport as of 2026-05-26.

It was previously `position: sticky; top: 8px` on desktop so the Following panel pinned while the main column scrolled. That broke when the left column ended up containing TWO `.home-feed` instances (Following + the desktop Tournament Results banner) — two sticky elements at the same top offset stack on top of each other once both reach the constraint, with Following visually covering Tournament Results. The mobile @media override (`position: static`) also occasionally lost the cascade race when service-worker caches went stale, producing residual overlap with the CollectionPanel's "Your Top Movers" table on phones.

Letting both panels scroll naturally with the page sidesteps the conflict on both platforms. Don't re-add sticky to `.home-feed` without making it specific to ONE of the two panels — and bear in mind that bumping `sw.js CACHE_VERSION` is mandatory whenever the rule changes, otherwise PWA users will keep painting the old stylesheet.

**`.home-grid-right` was a SECOND sticky, fixed 2026-05-27.** The right column (EV strip + CollectionPanel) has `position: sticky; top: 8px` on desktop — intentional, so the portfolio panel pins while the movers feed scrolls. But the original 2026-05-26 de-sticky fix only touched `.home-feed`, not `.home-grid-right`. On mobile the grid collapses to one column, so the sticky right column pinned the CollectionPanel to the viewport and the Following panel (`.home-left-col`, order:3) scrolled UNDER it — both have translucent `--bg-surface` backgrounds, so it read as a ghost overlap of "FOLLOWING" over "Your Top Movers". Fix: `.home-grid-right{position:static;top:auto;}` inside the `@media (max-width:1100px)` block. Desktop sticky preserved. **Lesson: when killing a sticky-overlap bug, audit EVERY sticky element in that grid, not just the obvious one.**

## Rarity icons

`RARITY_ICONS` maps each canonical rarity to an SVG in `Logos/rarity/`. 9 files: common, uncommon, rare, super_rare, legendary, enchanted, epic, iconic, promo. Common/Rare/SR/Leg/Ench/Epic/Iconic use the "Color" variants (gradient); Uncommon uses Outlined (its Color variant is pure white = invisible on light bg); Promo is Outlined (generic catch-all).

`<RarityTag rarity=... [hideText]>` helper renders an icon + text inline. `.chip-rarity-only` is the icon-only chip class used in filter chips (toolbar + drawer + screener + Add Set Tracking modal).

## Conventions

- No comments unless the *why* is non-obvious. No multi-line docstrings.
- Don't add backwards-compat shims when you can change the code.
- Set release dates: two flags per set — `LGS Release` and `Retail Release`. Source: Wikipedia.
- "<$1 → $0" toggle: cards under $1 count as 0 **before** averaging (mirrors `avg_low_nc` / `avg_market_nc`).
- Earliest price data: 2024-02-08. Sets released before show `*` asterisk.
- Time display: `relativeTime(iso)` for compact, `absoluteLocalTime(iso)` for hover tooltip. Both use browser local TZ.
- **⚠ A calendar date for a QUERY comes from `localYmd()`, never
  `new Date().toISOString().slice(0,10)`.** That form is the UTC day, so west of UTC it names
  TOMORROW from early evening onward (19:00 CDT on). Every date column we filter on
  (`sold_date`, `price_date`, `start_datetime`) is a calendar date, so the skew doesn't widen a
  window — it asks for a day no row can carry yet. Invisible at 30 days and TOTAL at one: the
  graded movers row's 1D window read "no graded sales match this filter" every evening until
  2026-09-13. `localYmdDaysAgo(n)` is the N-days-back form.

## Browser back/history pattern

Sub-pages push their own history entries so browser back returns to the parent grid.

- **Entering**: `window.history.pushState({...}, "", url-with-param)` BEFORE state update. Params: `?deck=<id>`, `?set=<name>`, `?tourney=<id>`, `?user=<uuid>`, `?collection=<uuid>` (+ optional `&token=<x>` for unlisted).
- **Popstate listener** inside each view syncs `selectedDeckId` / `selectedSet` / `selectedTournamentId` from URL.
- **Existing wrappers**: `openDeckInMode(id, mode)`, `openTournament(tid)` in `DecksView`; `useEffect` on `selectedSet` in `CollectionView`. Add new sub-page nav through these or you'll regress the back button.
- **Top-nav clicks strip view-specific deep-link params** before pushing new pathname.

## SQL editor syntax

Postgres functions invoked from `SELECT`, not bare statements:

```sql
SELECT public.refresh_card_prices_latest();
SELECT public.refresh_rarity_avg_daily();
SELECT public.refresh_price_movers();
SELECT public.refresh_sealed_prices_latest();
SELECT public.refresh_graded_prices_latest();
```

## TCGCSV / Lorcast notes

Full notes: `docs/claude/tcgcsv-lorcast-notes.md` (4 KB). **Read it before changing this area.**

- ⚠ `low_price` is NOT the listing floor, and the old "any condition" story is WRONG.
- ⚠ TCGCSV took its public price ARCHIVE offline (found 2026-09-27).

## Raw eBay sales — the ~24 promos TCGplayer cannot price (2026-09-20)

Full notes: `docs/claude/raw-ebay-sales.md` (16 KB). **Read it before changing this area.**
`card_prices_latest` is an INNER JOIN on a TCGplayer product, so a card TCGplayer has never recorded a sale for shows **nothing**, and one it froze on shows a fossil.
Guards: `scripts/test_raw_match.py`.
Covers: The asymmetry that drives every rule; The three gates, and what each cost to learn; Things that wear a card's NAME and beat every identity gate; The backfill — real data before a single page is scraped; Storage, rollup and the client; On a raw-priced card the hierarchy INVERTS; Running it — DAILY since 2026-09-26; On the card page (reworked 2026-09-26, Zaven: "use the last sold/avg 5 as the main metric. have the sales graph be more like the one for graded").

- ⚠ A name search is a NET, not an identity.
- ⚠ So the searches pair a name with a PROMO token, and they were MEASURED (2026-09-27).
- ⚠ A per-card search that is a subset of a net is redundant
- ⚠ `terapeak_match.match_one` stays the ONLY matcher.
- ⚠ PRICE MAY NEVER ATTRIBUTE A SALE.
- ⚠ Every word was cleared against card names

## Price standing — "is this actually a good price?" (2026-09-10)

Full notes: `docs/claude/price-standing.md` (4 KB). **Read it before changing this area.**
The competitive read, in one line: a restock feed can tell you a box is in stock at $130; it cannot tell you whether $130 is good.
Guards: `scripts/test_price_standing.mjs`.

- ⚠ It reads `market_price`, NEVER `low_price`.
- ⚠ It is a PERCENTILE, not a minimum.
- ⚠ The window's LABEL must be one the data can support.
- ⚠ Ties count as "at or below", and that needs the spread floor.

## Amazon Associates (approved 2026-09-10, tag `packsink-20`)

Full notes: `docs/claude/amazon-associates.md` (32 KB). **Read it before changing this area.**
Amazon **complements** TCGplayer here rather than competing with it, and the split is clean enough to state as a rule: **TCGplayer owns singles, Amazon owns everything TCGplayer barely stocks** — sealed gift sets, the Ravensburger jigsaw puzzles, and above all **accessories**, a category the site ha…
Guards: `scripts/test_amazon_links.mjs`.
Covers: ⚠ LINK-ONLY TODAY — because we have no API keys, NOT because prices are banned; Two different sale thresholds — don't conflate them; When the keys do land — the design that stays compliant; How a link is resolved; Where it is wired; `/gear` — the directory page; Product photos cut out of their white sweep; Every sealed photo goes through `ProductPhoto`; The home shelf — "Lorcana on Amazon"; Out of stock, or scalped → hidden, by a MANUAL daily check (migration 137); The home bar — removed; The Amazon link is a BUTTON, and it never touches a price; Disclosure; The ASINs are unverified by CI, del….

- ⚠ LINK-ONLY TODAY — because we have no API keys, NOT because prices are banned
- ⚠ The photos and prices you DO see on Amazon-linked tiles are TCGplayer's (2026-09-10).
- ⚠ Sources are secondary.
- ⚠ But `ETL → Supabase → localStorage` is exactly what breaks it.
- ⚠ Rules match on TOKENS, never on a whole name.
- ⚠ A set name typo'd against `MAINLINE_SETS` can never match

## /picks — the unlisted affiliate page (2026-09-10)

Full notes: `docs/claude/picks.md` (5 KB). **Read it before changing this area.**
`picks.html`, a **standalone page like `/swiss` and `/ticker`**, not an SPA view: it is a personal link page rather than part of the product, so it has no business inside Index.html, the nav, or the sitemap.
Guards: `scripts/test_picks_page.mjs`, `test_amazon_links.mjs`.
Covers: The grading queue is the one high-intent placement.

- ⚠ "Unlisted" is THREE mechanisms and losing any one quietly puts it in Google
- ⚠ Every link is a tagged SEARCH, and for this page that is the whole design.
- ⚠ `AMAZON_TAG` is DUPLICATED from Index.html
- ⚠ Send the PAGE, never the product links.
- ⚠ Sources are secondary
- ⚠ It is gated on `toSubmit > 0`, and that gate is the whole difference between a fact and an advert.

## Discord digest (`scripts/discord_digest.py`, 2026-09-10)

Full notes: `docs/claude/discord-digest.md` (5 KB). **Read it before changing this area.**
A daily post to a Discord webhook.
Guards: `scripts/test_discord_digest.py`.

- ⚠ The standing maths MUST match the site.
- ⚠ The freshness gate is what makes duplicate posts impossible.
- ⚠ A mover must have been PRICED inside its window

## Discord bot (`discord/`) — 2026-09-27

Full notes: `docs/claude/discord-bot.md` (28 KB). **Read it before changing this area.**
Zaven's ask: call a card in Discord and get its picture and price history, plus trend reports, with **plain-English, typo-tolerant lookup as the main requirement** — "people will say mowgli and not know the subtitle, but there is one main one that is played, or spell mowgli slightly wrong".
Guards: `scripts/test_discord_bot.mjs`, `scripts/test_discord_reports.py`.
Covers: v2: /trade, /set, /open, /meta, boards you browse; 2026-09-29: four commands retired, /meta by ink pair, send now, card text; 2026-09-30: what a reply LEADS with; The channel report's layout.

- ⚠ `discord/src/site.generated.js` is Index.html code copied VERBATIM
- ⚠ Not on a graded reply or a raw-eBay promo
- ⚠ The tile is UPLOADED with the reply, not linked
- ⚠ Charts are uploaded too
- ⚠ It runs when an ETL run FINISHES
- ⚠ Every component in a message needs a DIFFERENT custom_id

## The guards RUN now — `.github/workflows/guards.yml` (2026-09-21)

The repo carries **79 guard tests** as of 2026-09-30 (55 `scripts/test_*.mjs`, 24 `scripts/test_*.py` +
`scripts/elo/test_*.py`; the workflow globs them, so a new one runs without an edit) and until this workflow **nothing executed a single one of them**
— every one was "run it when you remember", which for a file this size means a silent
regression ships between the day a guard is written and the day someone thinks to run it.
It runs them on every PR and on every push to `main` (a PR commit used to run the suite twice).

- **All 52 were green when it landed**, so it starts from a true baseline rather than
  normalising a red build — which is the failure this repo already names elsewhere ("a red
  job everyone learns to ignore is worse than a script you run when you touch the catalog").
- **⚠ Every guard is offline BY CONSTRUCTION, and that is the entry requirement.** No
  network, no secrets. The nine Python guards that name `SUPABASE_*` set them via
  `os.environ.setdefault()` with stub values. A guard needing a real key is one that goes
  red for reasons nobody can fix from a PR, so don't add one.
- **It reports EVERY failure, not the first.** Both steps loop, print the failing guard's
  tail, emit a `::error` annotation, and exit non-zero at the end — stopping early means a
  second broken guard hides behind the first for another round.
- The Python step is `if: always()`, so a node failure doesn't hide the Python results.

## Ops

### ETL reliability (post 2026-05-24 rework)

**Primary trigger: cron-job.org** (external pinger). GitHub Actions `schedule:` cron was consistently delayed 2-4h during high-load windows; an external HTTP cron firing `workflow_dispatch` against the GitHub REST API runs within seconds of schedule. Five cron-job.org jobs (UTC) match the original cadence:

- **20:30 UTC** (3:30 PM CDT) — `both` — primary daily ETL (prices + graded)
- **22:00 UTC** (5:00 PM CDT) — `selfheal` — matview sweep #1
- **22:30 UTC** (5:30 PM CDT) — `both` — ETL retry #1
- **01:00 UTC** (8:00 PM CDT) — `both` — ETL retry #2
- **06:00 UTC** (1:00 AM CDT) — `selfheal` — overnight matview sweep

cron-job.org account uses a fine-grained GitHub PAT scoped to `zaventorian/Packs.Ink` with `actions: write` only. PAT lives in each job's `Authorization: Bearer <token>` header — rotate every 90 days.

**Safety net: GitHub `schedule:` cron**, intentionally minimal:
- **01:30 UTC daily** — ETL fallback (catches today if cron-job.org outage)
- **06:30 UTC daily** — selfheal fallback
- **21:00 UTC daily** — Lorcast metadata refresh (bumped weekly→daily 2026-08; `etl.yml` is the source of truth for these three)

Every external ping (cron-job.org) arrives as a `workflow_dispatch` event, so the prices/graded/selfheal jobs' `if:` filters accept both `schedule` (with the matching daily fallback cron) AND `workflow_dispatch` (with the matching `inputs.job` value).

**No spam emails for "TCGCSV hasn't published yet"** — that's exit 0 in the script (normal, not failure). Only real script failures (network, RPC, etc.) email.

**For the site to show stale data**, both cron-job.org AND the GH safety-net cron would have to fail. cron-job.org alerts on failure to user email; GH cron failures surface as workflow failures.

`permissions: contents: read` is pinned at the workflow level — required when repo workflow permissions setting is anything other than "Read and write".

**Phantom-spike smoothing ETL** (`smooth_low_prices.py`, added 2026-05-30) is chained `needs: prices` after the TCGCSV daily ETL. See "Collection Value chart: phantom-spike smoothing" for details. Idempotent; safe to fire alongside cron-job.org + GH safety-net pings.

### What fails loudly now (2026-09-30)

An audit found several failures that ended a green run. Each now speaks:

- **Every job has `timeout-minutes`.** A hung TCGCSV or Lorcast call used to hold the `etl` concurrency group for GitHub's six-hour default and queue every later ping behind it.
- **`synthetic_monitor.py` checks five more relations are populated** (`POPULATED`: sealed prices, graded rollup, market index, rarity averages, events), each against a floor near half its size. The market index once sat empty for three weeks with every read a 500 and nothing red.
- **`discord_reports.py` exits 1 when EVERY owed post failed** (a bad token), and warns when some did. One channel refusing is that server's business and stays on `/reports status`.
- **A short event pull turns `discover_scs.yml` red at its LAST step** (`partial_pull` output), so the roster and history steps after discovery still run.
- **The Discord bot skips a rebuild that would change nothing**: after an ETL run, a `gate` job asks the live Worker for its `priceDate` and `built`, and skips when it has today's prices and was built under six hours ago. The daily schedule and a manual run always build; any doubt builds.

### Running SQL: two routes, and Claude runs it (2026-09-30)

Zaven: *"im fine with claude having access to do everything."* Migrations, data fixes and drops are applied by the session that wrote them, then recorded in the ledger. Nothing is staged "for a paste" any more unless something outside the database must happen first.

1. **The Supabase connector** (`apply_migration` for DDL, `execute_sql` for the rest). Its tools are DEFERRED in most sessions: load them with ToolSearch (`supabase apply_migration execute_sql`) before concluding there is no database access. Apply migrations ONE AT A TIME: several in parallel collide on the version timestamp.
2. **`python scripts/sql.py`** when the connector is missing or refuses a statement: `-c "select ..."` prints rows, a `.sql` path runs the file. It calls the service-role-only `admin_exec_sql()` RPC (migration 177), so it needs only the service key, which `scripts/.env` holds locally (a worktree falls back to the main checkout's copy) and the agent proxy injects in a cloud session. No BEGIN/COMMIT, VACUUM or CREATE INDEX CONCURRENTLY: it runs inside a function.

- **`admin_exec_sql` must stay service-role only.** EXECUTE is granted to `service_role` alone and the body checks `auth.role()` again; the publishable key answers 42501 (verified). Granting it wider hands DDL to every visitor.
- Before a drop, look at what is being dropped and say so in the ledger entry. A drop that deletes user data (the poll tables, say) still wants a sentence to Zaven first.

### Routines: the scheduled Claude tasks on Zaven's desktop (2026-09-30)

`docs/automation.md` is the map of which workflow is automatic, which is prepared for a "push", and which still starts with a chat. Three scheduled tasks (each is a `SKILL.md` under `~/.claude/scheduled-tasks/<id>/`; they run while the desktop app is open):

- **`graded-scrape`**, daily ~12:11: graded and raw eBay sales.
- **`psa-pop-weekly`**, Wednesdays ~3:10 PM: `pop_run.ps1`, dry run, sanity check, then `-Commit`. It never signs in and stops at a wall; the `pop_stale` finding is still the backstop.
- **`packs-ink-intake`**, daily ~8:36 AM: works the overnight catalog / source / calendar findings in its own worktree, applies only the guarded steps `docs/automation.md` lists, leaves everything else as commits on a local `intake/<date>` branch, and writes a news draft to `drafts/news/`. **It never pushes, merges or deploys, and never confirms a calendar row.**

A change to what a routine may do on its own is a change to its SKILL.md AND to `docs/automation.md`, in the same sitting.

### Auth / grants

- **Required GitHub Actions secrets**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY` (used as read fallback in `matview_self_heal.py` when service_role gets 403). `TCGPRICELOOKUP_API_KEY` is **no longer used** (graded feed retired 2026-06-30) and can be deleted from the repo secrets.
- **service_role MUST have explicit SELECT grants on all matviews + prices_daily** (migration 45). Missing this breaks selfheal with HTTP 403.

### PWA + caches

- **`sw.js CACHE_VERSION`** (current `packsink-v416`; `styles.css?v=416`, `logo.js` held at `?v=348` — content unchanged, so the lockstep is deliberately split. Historical note follows from the 2026-06-27 audit at v254 — 2026-06-27 audit: core libs react/react-dom/htm/supabase **+ html2canvas VENDORED same-origin under `/vendor/`** (was unpkg) to kill the CDN-outage blank-page crash ("ReactDOM is not defined" / "window.supabase.createClient" undefined in Sentry); precached in `sw.js` CORE_ASSETS at `?v=254`; `styles.css?v=254` bumped, `logo.js`/`scanner*.js` intentionally held at `?v=253` (content unchanged, so the lockstep is split — that's fine, the SW caches per exact URL). Earlier 2026-06-27: scanner OCR swap Tesseract.js → PP-OCRv3 (det+rec) via onnxruntime-web in a dedicated `scanner-ocr-worker.js` (WASM single-thread+SIMD, NO WebGPU); the 2 onnx models + `ppocr_keys_v1.txt` ship in `scanner/` and are runtime-cached (NOT precached — admin-gated/lazy); styles.css/logo.js/scanner*.js at `?v=251`, catalog cache `v45`): bump on ANY meaningful Index.html / styles.css / logo.js change. Activate handler purges old caches (`skipWaiting` + `clients.claim`) — EXCEPT `packsink-img-v1` (the deploy-surviving image cache; see "Offline support"). HTML requests are **network-first**. **Gotcha (2026-05-27):** bumping once at the start of a session does NOT invalidate later edits — the SW only re-caches when the version string changes. Bump again (or use an incognito window — the SW is registered on localhost too) when iterating heavily. The three things that must stay in lockstep: `sw.js CACHE_VERSION`, `styles.css?v=N` in Index.html `<link>` + sw.js CORE_ASSETS, `logo.js?v=N` in Index.html `<script>` + sw.js CORE_ASSETS.
- **App-shell is network-first (styles.css + logo.js), fixed 2026-05-28.** Previously these were cache-first while HTML was network-first → after a deploy that changed CSS, a returning visitor got the **fresh Index.html paired with the STALE cached stylesheet** → home-page mover tiles rendered at giant natural-image size until they hard-refreshed. Now `sw.js` serves `styles.css`/`logo.js` network-first (cache fallback only when offline), matching the HTML, so the app shell can't split across versions. **Belt-and-suspenders: the asset URLs are versioned** (`styles.css?v=N`, `logo.js?v=N` in Index.html `<link>`/`<script>` AND in the SW `CORE_ASSETS` precache list, kept in sync with `CACHE_VERSION` — currently **v181**). The `?v=N` closes the one-time transition gap on the deploy that carries an SW change: the *old* (still cache-first) SW cache-misses on the new URL and fetches fresh. Going forward the network-first behavior handles freshness, so for FRESHNESS you don't strictly need to keep bumping `?v=N`, but keeping it == `CACHE_VERSION` is the convention. **⚠ But bump `styles.css?v=` on EVERY deploy anyway, changed bytes or not — it is the deploy workflow’s FINGERPRINT.** The verify step curls an uncacheable path and compares the served `styles.css?v=` against the one it just built; hold it back because the CSS did not change and the two match trivially, the step passes against the PREVIOUS shell, and the run proves nothing. That is the same blind spot the 2026-09-08 v377 collision documents, reached from the other direction — and it fired for real on 2026-09-21 (v464 shipped with `?v=463`, warning: *“v463 now names two different shells”*). The deploy still WORKS (`CACHE_VERSION` is the master switch and the app shell is network-first), so nothing is broken for users; what is lost is the one check that separates *deployed* from *deployed but the edge is stale*. `logo.js` / `scanner*.js` are genuinely free to lag — nothing reads them as a fingerprint.
- **Catalog cache version**: `packsink:catalog:vN` (current **v45**). Bump when row shape changes, OR when forcing all users to cold-fetch. Note: `text` is STRIPPED from the cache on write to keep the 5MB quota free for aux caches — the in-memory backfill in `loadFromSupabase` (see "Smart search" — Card body text in the haystack) restores body-text search on cache-replay sessions without growing the cache. `keywords` IS in the cached rows, so bumping this version is the way to force the new keyword derivation onto existing users.
- **PWA icon refresh**: icon URLs include `?v=N` query (current **v=5**; v=4 was the 2026-05-26 full-booster-pack rebake, v=3 the bare-wordmark dark-blue rebake earlier the same day). Bump the version in both `Index.html` <link rel="icon"> entries AND in `manifest.json` whenever the icon bytes change. Also bump `sw.js CACHE_VERSION` since the SW precaches icon paths sans query string.
- **PWA icons baked from `Logos/packs-ink-logo.png`** via `scripts/rebake_icons.py` (Pillow). The script composites the full booster-pack artwork over `#0f0d20` with a 12% inset margin (keeps art clear of iOS/Android squircle masks). 6 outputs: apple-touch-icon.png (180), favicon-16/32/64.png, icon-192.png, icon-512.png. Idempotent — re-run when the source logo changes. Don't rely on `manifest.background_color` for transparent icons; iOS save-to-home-screen ignores it.
- **PWA orientation: `"any"`** (manifest.json). Installed PWAs rotate to landscape now. Was `"portrait"` which locked the orientation — dev-tools rotation emulator worked because that's a tab not a PWA. iOS users need to remove + re-add the home-screen icon to pick up manifest changes (iOS caches the manifest at install time).
- **mobile-web-app-capable** meta tag added alongside the legacy `apple-mobile-web-app-capable` tag — Chrome deprecated the apple-prefixed variant.
- **Dev server cache header**: `dev_server.py` sends `Cache-Control: no-store` on HTML/CSS/JS.

### Misc

- **Sentry browser SDK** loaded via CDN lazy-init on first error. User attribution via `Sentry.setUser`.
- **UptimeRobot** pings prod every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest.max(price_date)` on load, flashes ⚠ if > 30h past the 21:00 UTC snapshot (same threshold as `synthetic_monitor.py`).
- **Privacy policy**: standalone `privacy.html` at repo root (no JS — Google's OAuth verification crawler doesn't execute JS). Pretty URL `/privacy → /privacy.html` via `_redirects` + `dev_server.py`. Static `<noscript>` link in `Index.html` body for the home page's pre-JS HTML payload.

## Privacy page, analytics and the disclaimer (2026-09-04 audit)

Full notes: `docs/claude/privacy-page-analytics-and-the-disclaimer.md` (4 KB). **Read it before changing this area.**

## Disclaimer

Lives in the site footer (every SPA view), on `privacy.html`, and on the **How It Works** page: "Packs.Ink is an unofficial fan site. Disney Lorcana TCG is a trademark of Disney; the game is operated by Ravensburger. This site is not affiliated with, endorsed by, or sponsored by Disney or Ravensburger."

## Elo weekly refresh — set rotation is the failure mode (2026-09-08)

Full notes: `docs/claude/elo-weekly-refresh.md` (20 KB). **Read it before changing this area.**
`.github/workflows/elo_weekly_refresh.yml` (Mon 11:00 UTC) runs `scripts/refresh_elo.py`: download the canonical SQLite from Supabase Storage → ingest → renames → aliases → recompute → export to Supabase → upload the DB back.
Guards: `scripts/elo/test_season_seed.py`, `scripts/elo/test_sc_template.py`, `scripts/elo/test_excluded_stores.py`, `scripts/elo/test_results_integrity.py`.
Covers: Set Championships are recognised by RPH's template, not only the title; Adding ONE event by hand; Taking a store OUT of scope; …but a store cut from Elo STAYS on Store Status; Results integrity — the refresh checks what it holds, not just what it adds.

- ⚠ The board froze at the Attack of the Vine! rotation and NOTHING went red.
- ⚠ The ingest MUST happen inside a refresh run.
- ⚠ Scope is derived TWICE, and the list has to reach both
- ⚠ Both of these were true at once, and a store excluded months earlier was still on the Scout tab
- ⚠ Only the explicit list is deleted — drift is REPORTED.
- ⚠ It is deliberately NOT written into `elo_tracked_stores`.

## Intentional draws — flat, not skipped (2026-09-08)

Full notes: `docs/claude/intentional-draws.md` (9 KB). **Read it before changing this area.**
An ID is a scheduling decision, not evidence about who is better, and because IDs happen at the top tables it is the leaderboard's best players whose ratings get dragged toward whoever they shook hands with.
Guards: `scripts/elo/test_intentional_draws.py`.

- ⚠ Flat rows, never a skip.
- ⚠ The 0-0 half takes NO position gate
- ⚠ A round holding a draw is NEVER elimination, and `cut_rounds()` has to be told so.
- ⚠ A hand-edit of `is_intentional_draw` in the DB does NOT survive

## Linking one person's two accounts (2026-09-08)

Full notes: `docs/claude/linking-one-person-s-two-accounts.md` (2 KB). **Read it before changing this area.**
`suggest_aliases.py` proposes exact/normalized matches and fuzzy pairs at **ratio >= 0.85**, so two handles that differ by more than that are never suggested and never will be — `heyzeusvee` on melee against `heyzeus` on RPH is the shape.
Guards: `scripts/elo/test_manual_merges.py`.

- ⚠ It is applied on EVERY refresh, from a committed file, and that is the point.

## Chicagoland Elo — Stores tab (2026-08-19)

Full notes: `docs/claude/chicagoland-elo.md` (14 KB). **Read it before changing this area.**
`EloView`'s inner tabs are `leaderboard | tournaments | stores | upcoming | scout`, mirrored to `?sub=<tab>` (plus `?p=`/`?e=`/`?store=` for the player / event / store-report leaf views) — the KEYS are unchanged; only the labels read **Tournament Results** and **Store Status** now.
Guards: `scripts/elo/test_attendance_targets.py`, `scripts/test_elo_store_activity.mjs`, `scripts/test_attendance_privacy.mjs`.

- ⚠ The client reads `rph_event_attendance` by pseudonym only (`person_key`, `played`; migration 188). Never select a name, account id or standing there: migration 189 (STAGED) takes them away from anon.
- ⚠ `.elo-innertabs` is `flex-wrap:nowrap` + `overflow-x:auto`, and must stay that way (2026-09-12).
- ⚠ History and attendance refresh on `discover_scs.yml`'s DAILY schedule — and until 2026-09-10 attendance was refreshed by nobody.

## Scouting is a TEAM tool now (migration 143, 2026-09-12)

Full notes: `docs/claude/scouting-is-a-team-tool-now.md` (24 KB). **Read it before changing this area.**
"Who is in this room, what are they playing, and what did they play last time?" Two open text fields — **deck** and **notes** — per PLAYER per EVENT, shared across the scouting team, readable from three surfaces and durable across events so next month's roster arrives pre-annotated: *9/12 · Gemini G…
Guards: `scripts/test_scout.mjs`.
Covers: Access is an EMAIL allowlist, and it is NOT the store-report gate; One note per (event, player) — shared, attributed, and it OUTLIVES the event; Scope: tracked stores, ANY event kind — plus anything a scout adds by hand; The slate keeps an event for 24 HOURS past its start (migration 147); Scouting an event outside the bubble (migration 148, 2026-09-12); Where it renders; Pulling a roster on demand; ⚠ A failed Edge Function call hides its reason — read `error.context`; Scouting an event that ALREADY HAPPENED; ⚠ The sheet's Elo column: the rating is DATA, the link is an AFFORDANCE.

- ⚠ The sheet's Elo column: the rating is DATA, the link is an AFFORDANCE (2026-09-13)
- ⚠ A failed Edge Function call hides its reason — read `error.context` (2026-09-13)
- ⚠ The event label (`event_name` / `event_date` / `event_tz` / `store_name`) is DENORMALISED onto the note.
- ⚠ The panel lists the roster UNIONED with this event's notes (migration 144), not the roster alone.
- ⚠ The bulk roster sweep is deliberately NOT widened to match
- ⚠ The slate is no longer all-future, so a started row has to SAY so.

## Upcoming-events finder — a SECTION of the calendar tile (2026-09-13)

Full notes: `docs/claude/upcoming-events-finder.md` (16 KB). **Read it before changing this area.**
It was its own home panel until 2026-09-12, a full-screen overlay for a day, and is now **a section inside the calendar tile** (`<UpcomingSCsBox embed/>` at the foot of `CalendarPanel`).
Guards: `scripts/test_event_search.mjs`.
Covers: One box, no country picker — postal code OR town; The country control is built from what RESOLVES, not what could; "Not Chicago?" is the TOWN axis only.

- ⚠ Loosening `scZipReady` turned a mount effect into search-as-you-type — fixed 2026-09-14
- ⚠ It shares the tile's `subs`, and that is the point.
- ⚠ NOT rendered while the App overlay is up
- ⚠ A result tile STACKS at rail width
- ⚠ A `?sczip` deep link now opens the OVERLAY.
- ⚠ The mode travels in localStorage, never a `?scmode=` link

## The event map — two surfaces, one component (2026-09-22)

Full notes: `docs/claude/the-event-map.md` (34 KB). **Read it before changing this area.**
`EventMapView` (beside `scMergePins` in Index.html) draws many events on one OSM map.
Guards: `scripts/test_event_map.mjs`, `scripts/elo/test_events_archive.py`.
Covers: ⚠ Only what can be SEEN is rendered, and the box MEASURES itself; The date on the pin, and why placement is a FIT; ⚠ The map defaults to ALL events, and yours is the FILTER; Dragging it, and the kind chips; `/calendar?cv=map`, the fourth mode; Getting TO the map, and getting DOWN to a town; The pins wear the calendar's marks, and the map lists what is on screen; A map you can SEND — `?scview` and `?cmap`; How the finder itself works.

- ⚠ The map defaults to ALL events, and yours is the FILTER (2026-09-22)
- ⚠ Only what can be SEEN is rendered, and the box MEASURES itself (2026-09-22)
- ⚠ `mapHere` (`mapOn && !inTile`) is a different question from `mapOn`
- ⚠ `CAL_MAP_H` was already taken
- ⚠ INTERSECTION, not centre-in-frame.
- ⚠ `labelSides` is indexed BY POSITION

## Lorcana Calendar (`/calendar` + home panel) — 2026-09-12

Full notes: `docs/claude/lorcana-calendar.md` (80 KB). **Read it before changing this area.**
**It is the "Lorcana Calendar" everywhere a user reads it** — the h1, the home panel, the layout editor, the `.ics` name and the exported picture.
Guards: `scripts/test_calendar.mjs`, `scripts/test_csp_headers.mjs`, `scripts/test_share_links.mjs`.
Covers: Sets that are announced but not dated; Where the curated data comes from; Region, the map, and what a set release is called; What each kind LOOKS like — one icon per kind of THING, not per chip; Set 14, and products that are not a set; Hiding one event; Per-store event kinds; The home panel's list pager; The map's tiles are NOT lazy; Keeping it current; ⚠ disneylorcana.com's qualifier list is SPLIT ACROSS LOCALES; Timeline mode - the season on one axis; Region rows are a PICK, not the layout; The chart's typography; The filter row, and what it can now say; One chip system, one casing rule; Hov….

- ⚠ The season seed is short one Challenge, and five dates are disputed (2026-09-14)
- ⚠ disneylorcana.com's qualifier list is SPLIT ACROSS LOCALES (2026-09-14)
- ⚠ The page OPENS ON THE MONTH GRID
- ⚠ A `?cv=` link is checked BEFORE the stamp is spent
- ⚠ Set releases are DERIVED from `SET_RELEASE_DATES`, not seeded into the table
- ⚠ Only `kind='set'` rows participate in that merge.

## Swiss simulator (`/lab/swiss`) — unlisted, added 2026-08-20

Full notes: `docs/claude/swiss-simulator.md` (6 KB). **Read it before changing this area.**
Monte Carlo odds for Lorcana Swiss events.
Guards: `scripts/test_swiss_engine.mjs`.

## Stream ticker (`/ticker`) — OBS overlay, added 2026-08-21

Full notes: `docs/claude/stream-ticker.md` (15 KB). **Read it before changing this area.**
Built for streamers (vVonderland's Discord ask): a scrolling bottom-of-stream bar of the top %-movers.
Guards: `scripts/test_ticker_query.mjs`.
Covers: Promo videos — 16:9 and 9:16.

- ⚠ The floor is on the price the card STARTED the window at
- ⚠ The credit is placed on the PLAN, before any query runs, so it must be placed AGAIN after empty sections drop
- ⚠ The tab's settings live in the PAGE's address, not only the frame's (2026-09-26).
- ⚠ The cut is measured in BARS of the backing track, not in seconds.
- ⚠ The track is a commercial Disney recording
- ⚠ All three bullet beats show the configurator beside the copy

## Tier List (`/tierlist`) — added 2026-10-05

Analytics sub-tab with its own path (`MARKET_SUB_PATHS`, like `/ticker`): rank a set's Enchanteds +
Iconics in S/A/B/C/D, then copy a canvas-drawn picture (logo, title, QR, `packs.ink/tierlist`) or the
link. `TierListView` + `buildTierListBlob` sit just above "Home (landing)" in Index.html.
Guards: `scripts/test_tier_list.mjs`.

- **The URL IS the list**, no table: `?ts=` set number (MAINLINE index + 1), `?tl=` tiers, `?tn=` title,
  `?tt=` renamed labels (`_`-joined, only when not S/A/B/C/D). Owned at `/tierlist` in App's view sync
  (`TIER_URL_KEYS`), stripped everywhere else.
- **⚠ Cards are encoded by COLLECTOR-NUMBER OFFSET, and the code CARRIES ITS BASE** (`tl=223-j0.72..h`:
  offsets from #223, one base-36 char a card, tiers split by "."), never by card_id: prestaged sets
  swap their stand-in ids for Lorcast's. The base is in the code because a set still being revealed
  can gain a LOWER-numbered chase card, which would shift every link read against "the pool's first
  card". First-day codes with no base (v523) still read that way. Device storage
  (`packsink:tierlist:v1`) and the account row use the same code (`tierToStored` / `tierFromStored`);
  v523's id-keyed device lists still read and are rewritten on their next edit.
- **Link previews** (Discord, iMessage...): `worker/tierlist.mjs`, bots only, and deliberately BARE —
  the list's title and one line ("18 Enchanted · 2 Iconic · make your own at packs.ink/tierlist"),
  no picture (the image tags are REMOVED and `twitter:card` set to `summary`, or apps draw the site
  banner). The first version listed every tier and showed a full-size card, which repeated the pasted
  image in a second, bigger block (Zaven 10/5: "remove all this excess"). ⚠ Its `TIER_SETS` must equal
  `MAINLINE_SETS` (`ts=` indexes it); the guard checks that, and that the worker decodes the client's
  own codes.
- **⚠ A link is SHOWN, not saved** (the "a link may choose for you, never over you" rule): opening
  someone's list leaves your own list for that set alone until you move a card. A link that equals
  your saved list (a refresh — the address bar carries it) is just your list, no "shared" banner.
- **A finger drags too: press and hold a card `TIER_HOLD_MS` (280ms), then drag** — a finger that moves
  first is scrolling and is left alone. The touch listeners are NATIVE and non-passive (React's touch
  handlers are passive, and only a cancelable touchmove stops the page scrolling under the card).
  Edge auto-scroll only runs toward the edge being dragged at, or a card picked up near the bottom of
  the screen scrolls the page away before it moves. ⚠ Every coloured button here restates its colour
  for `:hover` — the site-wide `button:hover` outranks one class, and a phone keeps :hover on the last
  thing tapped, which greyed out the tier button you had just pressed (reported 10/5).
- Mouse/pen drag (pointer events + `elementFromPoint`, edge auto-scroll). A click/tap opens the card
  FULL SCREEN (`TierCardViewer`): tier buttons, ‹ › through the cards, and a TCGplayer affiliate
  button (`tcgUrl`, or a `tcgSetSearchUrl` name search for a card with no product yet). Placing an
  card from there ALWAYS moves on (next unranked card while any are left, else the next on the board),
  with a "Placed X in S" flash, the picture keyed by card so it swaps at once, and the next cards
  preloaded; Previous / Next are a labelled row under the card, and a swipe on the card steps too. So
  a phone ranks a whole set without
  leaving the view. Cards keep `touch-action:manipulation`, so the page still scrolls on a phone.
  Keys: 1–5 place, 0 unranks, ←/→ reorder (board) or step (viewer), Esc closes.
- Copy link copies a LINE + the link (`tierShareText`): "Check out my <set> Chase Card Tier List on
  Packs.Ink ✨🏆". The two emoji are built with `String.fromCodePoint` so the served source stays
  emoji-free for `test_no_emoji.mjs`. Copy image is image only (apps disagree on which half of an
  image+text clipboard they paste). Touch: one share sheet with the PNG and the line together.
- **Saved to the account when signed in — `tier_lists` (migration 180, APPLIED 2026-10-05)**, one row
  per (user, set) in the link's own shape (code / title / labels). On sign-in the newer side of each
  set wins and device-only lists are carried up; edits write through, debounced 900ms. Missing table =
  device-only, silently. A signed-out visitor gets a small sign-in nudge after a copy/share/save, once
  per visit (`sessionStorage packsink:tierlist:nudgeDismissed`), never on load.
- Unranked cards are not in the picture, like TierMaker; an empty board won't export. Ranking the last
  unranked card from the viewer closes it with an "every card is ranked" toast. iOS needs a
  non-passive `touchmove` listener present BEFORE a touch starts (dnd-kit's fix), so the view keeps a
  no-op one registered while mounted. Account saves debounce PER SET.

### Custom lists, My lists, Community (2026-10-05)

Zaven's feedback: "make your own tier list" from any cards, mass-add with our filters, publish like
a public decklist, a user-made section, and the Following feed. The page is three tabs now
(`?tv=chase|mine|community`); `TierChaseView` is the set chase list above, unchanged in behaviour.
The board, drag, viewer and share/export buttons are shared components (`TierBoard`,
`useTierShare`), so a fix to either mode lands in both.

- **A custom list is five tiers PLUS its own pool** (picked, not yet ranked), and the pool travels in
  the link: a list with nothing ranked is a template somebody else can rank. One code, `?tc=`:
  tokens split on "." — `_14` switches set, `223` is a card in it, `*` starts the next group (tiers,
  then pool), `-<base64url>` is a card keyed by card_id. **Keyed by printed SET CODE + COLLECTOR
  NUMBER** (`_setCodeById`), never card_id, for the prestage-swap reason above. Two card_ids sharing a
  code + number (an Extras foil, a labelled one-off): the plain card keeps the short key, the other is
  keyed by id (`tierCardIndex`). Variant clones (`::`) are left out. Cap `TIER_CUSTOM_MAX` (300).
- **⚠ The page waits for the set codes (`codeN > 0`), not just the catalog.** Decoded without them
  every card reads as missing, and the next edit would save the list without them.
- **Saved lists: `custom_tier_lists` (migration 181, APPLIED 2026-10-05)**, keyed by a 10-char slug
  the CLIENT mints, so a list made signed out keeps its id when carried up. Short link
  `?tid=<slug>`. Visibility: private / unlisted (default) / public. Public rows are readable by
  anyone (RLS); an unlisted one only through `get_custom_tier_list(slug)`; Community reads
  `list_public_tier_lists(scope, user, limit, before)` (scope `following` = people you follow).
  Verified in a rolled-back transaction: another user can't read private, update, or insert as you.
  A private list's Copy link is the long `?tc=` link (it carries the list itself).
- **Device ⇄ account sync (`useTierCustomStore`)**: each list carries `r` = the account it was last
  confirmed on. On sign-in: newer side wins; a device list with no `r` is carried up; one whose `r`
  is this account but is gone remotely was deleted on another device and is DROPPED (without `r`,
  every other device would resurrect it); another account's lists stay on the device untouched.
  Verified headless on the demo account (rows cleaned up by slug).
- **Somebody else's list (link or `?tid=`) is shown, and the first edit makes a COPY** (`fork`,
  `forked_from` recorded) — the chase lists' rule. Two buttons say so up front: "Rank these cards
  yourself" (same pool, all unranked) and "Start from this ranking".
- **Adding cards**: the picker routes through `parseSearchQuery` + `matchesCardFilter` (AND mode),
  plus set / rarity / ink chips; "Add all N". An empty filter lists nothing on purpose. A set filter
  also matches that set's promos, like the Cards tab. (A "Start from" box of one-tap starters
  shipped in the first cut and was removed the same day at Zaven's request.) `updateList` sets
  `listRef.current` itself so two edits in one tick compose instead of the second overwriting.
- **2 to 10 tiers** ("+ Add a tier", an x on each tier label), chase AND custom lists. **⚠ The
  count travels in the LABELS**: five default tiers send no `?tt=`; any other list sends one label
  per tier, so the label count IS the tier count (`tierCountOf`, `tierNormLabels`). The codes split
  tiers by "." and cannot say how many there are on their own, so every decode takes the count from
  the labels — including the worker's (`tierCountFromLabels`). A removed tier's cards go back to the
  pool, with Undo. Colours are positional (TIER_DEFAULTS has ten). Migration 182 widened both
  `labels` checks to 160 characters for ten renamed tiers.
- **Likes and views (migration 182, APPLIED 2026-10-05)**: `custom_tier_list_likes` (one row per
  list + person; `like_count` kept by a trigger), `view_count` bumped by `bump_tier_list_view(slug)`
  once per browser session and never for the owner. You can like any list you can open (the insert
  policy calls a DEFINER check, `tier_list_likeable`, because the caller's own RLS hides unlisted
  rows). **The owner cannot write the counters**: authenticated has column-level INSERT/UPDATE on
  the editable columns only (PostgREST's upsert names every payload column in its DO UPDATE SET,
  so `slug` and `user_id` are in that grant). Community sorts Newest / Most liked. All of it
  verified in a rolled-back transaction.
- **A creator's public lists show on their profile page** (`CreatorTierLists`, under their decks;
  `list_public_tier_lists(p_user)`), and open through `openTierListSlug`.
- A list opened with "New tier list" and left with no card, title or renamed tier is deleted on
  the way out — read off the STORED entry, never the decoded one.
- **Following feed**: public lists by people you follow ride the home Following panel ("Tier list"
  tag); a click goes through `openTierListSlug` → App's `packsink:open-tierlist` listener, which
  writes `/tierlist?tid=` BEFORE switching views so the page reads it on mount.
- Link previews (`worker/tierlist.mjs`): `?tc=` and `?tid=` get the same bare title + one line,
  `?tid=` via a GET of the STABLE RPC. Guards: `scripts/test_tier_list.mjs` (codec, store shape,
  worker counts, 2-10 tiers).

## Brand assets

- `Logos/` ships at runtime.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons.
- `Logos/rarity/{common,uncommon,...}.svg` — 9 rarity icons (added 2026-05-23).
- `Logos/packs-ink-logo.png` — site wordmark (top bar @ 60px height, footer @ 48px).
- `Logos/Logo on Black.png` — Ink & Lore logo (base64-embedded as `LOGO_B64` in logo.js). **Removed from the footer 2026-08-21 (user request)** — logo.js still ships (SW-precached, boot-order sentinel), just nothing renders it.
- `Logos/PacksInk.ai` + `Logos/PacksInk.pdf` — source files for the commissioned wordmark (not used in deploy).
- Custom SVG glyphs: `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` (shared `<HexFrame/>`).

## Pending / roadmap

Full notes: `docs/claude/pending-roadmap.md` (38 KB). **Read it before changing this area.**
**Pre-launch batch 2026-07-14 (commit `b94eb68`, SW v272 — NOT pushed yet):** SEO/social head meta (title/description/OG/Twitter/JSON-LD; `og-image.png` baked by `scripts/make_og_image.py`; per-view `document.title`+canonical via `VIEW_TITLES`); `robots.txt`+`sitemap.xml`; onboarding tours reworked…

- ⚠ Its `statement_timeout` is a function-level `SET` clause, not a `set local`
- ⚠ It was WRITTEN as 150 and renumbered before merge
- ⚠ It is a SEED, not a reconciler.
- ⚠ A wrong address fails SILENTLY
- ⚠ Its NUMBER collides

