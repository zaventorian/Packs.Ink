# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

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

- **Frontend**: `Index.html` + `styles.css` + `logo.js`, React via `htm` template literals, no build step. Served by `python scripts/dev_server.py` (port 8766 — AnkiConnect squats 8765). CSS extraction is deliberate for caching + editor sanity — do NOT inline CSS back into Index.html.
- **Prod is the Cloudflare Worker** (`packs-ink`), not Netlify — cutover 2026-08-04. Netlify still exists only to serve `www`'s 301 → apex; see `scripts/CLOUDFLARE_MIGRATION.md`.

### ⚠️ Deploying — a git push does NOT ship the site

`wrangler.toml` says to set the build command in the Cloudflare dashboard so pushes deploy. **That was never done.** Every deployment in the Worker's history is "Manually deployed" via Wrangler. Confirmed 2026-08-10, when prod was found frozen at `packsink-v309` for 5 days while `main` had reached v314 — pushing changed nothing.

```
node scripts/build_dist.mjs && npx wrangler@4 deploy
```

- `build_dist.mjs` is an explicit include-list → `dist/` (55 files). It refuses to build if the native/worker markers go missing.
- **A deploy is safe with respect to `.env`.** The runbook warns that Wrangler auto-loads it; verified via `wrangler deploy --dry-run` that the only binding is `env.ASSETS` — no vars, no secrets, and `dist/` contains no `.env` or service key. Re-check with `--dry-run` if `wrangler.toml` ever grows a `[vars]` block.
- **Then purge the Cloudflare cache, or the HTML stays stale.** The deploy updated `sw.js` immediately but `/` kept serving the old document (`CF-Cache-Status: HIT`) with the previous `styles.css?v=`. Because the SPA fallback means every route and query-string variant caches its own copy of the HTML, a by-URL purge misses most of them — use **Purge Everything** (Caching → Configuration). Traffic is ~0.1 req/sec, so the origin-load cost is nil. To tell a stale edge from a stale origin, curl a path that cannot be cached: `curl -s https://packs.ink/__nope-$RANDOM | grep -o 'styles.css?v=[0-9]*'` hits the SPA fallback and shows what the Worker is really serving.
- Rollback: grey-cloud `A packs.ink → 75.2.60.5` in the dashboard. Instant, no redeploy.

**You can also deploy without a laptop: `.github/workflows/deploy.yml` (Actions → Deploy to Cloudflare → Run workflow).** It runs the exact two commands above, purges the cache, then verifies the edge. `workflow_dispatch` ONLY — deliberately never `on: push`, because batching deploys is the point, not an oversight. Type `deploy` in the confirm box; `dry_run` builds and validates without publishing.

- Needs three repo secrets: **`CLOUDFLARE_API_TOKEN`** (Workers Scripts:Edit + Account Settings:Read + Cache Purge:Purge), **`CLOUDFLARE_ACCOUNT_ID`**, **`CLOUDFLARE_ZONE_ID`**. The token is scoped so it cannot touch DNS — it can never perform the grey-cloud rollback, which stays a dashboard action.
- **⚠️ The token is missing `Zone → Workers Routes → Edit`, and that made every real run of this workflow "fail" after a SUCCESSFUL deploy** (found 2026-08-20). wrangler uploads the script first, then reconciles `wrangler.toml`'s `routes` against the zone; that second call 403s (`Authentication error [code: 10000]`, `/zones/*/workers/routes`) and the bare non-zero exit skipped the purge and the verify — shipping code behind a stale edge, the exact failure this workflow exists to catch. Runs #2 (2026-08-18) and #3 both did this; run #1 only "passed" because it was a dry run, so **no real deploy had ever completed through Actions**. The deploy step now swallows that one case (upload succeeded AND the error names `workers/routes`) and lets verify be the judge. **Granting the token that permission is the real fix** and makes the warning stop.
- **The verify step is the point of the workflow, not decoration.** It curls `packs.ink/__deploy-check-<random>` — a path that cannot be cached, so it hits the SPA fallback and reports what the Worker is really serving — and fails the run if the served `styles.css?v=` doesn't match what was built. That is the difference between "deployed" and "deployed but the edge is still stale", which is exactly the failure that froze prod at v309 for five days.
- It also warns (never blocks) when the `Index.html` / `sw.js CORE_ASSETS` / `CACHE_VERSION` trio fall out of lockstep.
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog**: `cards`, `sets`, `prices_daily`, `sealed_products`, `graded_prices_daily`.
  - **User**: `profiles` (carries collection-sharing visibility + share_token cols), `collection_items`, `sealed_collection_items`, `graded_collection_items`, `graded_collection_goals`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`, `screener_views`.
  - **Tournament**: `tournaments`, `tournament_decks`, `tournament_admins`, view `tournament_results_v` (security_invoker on).
  - **Events (RPH)**: `lorcana_events` (migration 113) — EVERY upcoming Ravensburger Play Lorcana event (~17k), `kind` ∈ `sc|prerelease|other`. What the site's "Upcoming near me" box reads. `set_championships` is the SC subset kept in lockstep for the Elo pipeline only. `prerelease_events` was DROPPED 2026-08-22 (migration 123). See "Upcoming-events finder".
  - **Misc**: `trades` (token-keyed shareable Trade Compare payloads; RLS-locked, access only via `create_trade` / `get_trade` RPCs — migration 54). **30-day retention** via `cleanup_old_trades()` (migration 65), called daily by the selfheal job in `matview_self_heal.py`.
  - **Matviews**: `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`, `graded_prices_latest`.
- **ETL** (`.github/workflows/etl.yml`):
  1. `scripts/etl_tcgcsv_daily.py` — TCGCSV → `prices_daily`, then refreshes the 4 raw-price matviews. Idempotent: skips fetch when today's snapshot is already loaded; exits 0 (not error) when TCGCSV hasn't published yet (>95% byte-identical to yesterday's).
  2. Daily Lorcast metadata refresh: 21:00 UTC (bumped weekly→daily so a pre-order set fills in within a day of each spoiler; deliberately NOT fired by `job=='both'`, which pings thrice daily).
  3. **RETIRED 2026-06-30 — there is no graded ETL.** The third-party graded feed was discontinued; the legacy client paths were deleted 2026-07-29 and `graded_prices_daily` / `graded_prices_latest` were **DROPPED 2026-08-22** (migration 112; archive on Desktop). All graded value comes from the in-house `graded_sales` scrape (see "Graded pricing: legacy vs current"). `scripts/etl_tcgpricelookup_daily.py`, `scripts/graded_overrides.json`, and the `probe_/backfill_/cleanup_*graded*` scripts remain on disk for reference but are **invoked nowhere and cannot run** (the API is gone). Don't wire them back up; don't chase "graded is stale" alerts.
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed catalog**: `scripts/load_sealed_products.py`.
- **MCP**: `.mcp.json` configures Supabase MCP server (`mcp.supabase.com/mcp?project_ref=...`). Loads on session start; gives the agent direct DB query/mutation access without paste-back.

## Native app (Capacitor) — groundwork 2026-07-17

Android/iOS shell around the SAME zero-build web app. **Read `native/README.md` before touching it** (architecture decision, phase roadmap, store checklists). Invariants:

- **appId `ink.packs.app`** — permanent once the first Play upload happens.
- Bundle = `native/www/` (gitignored), generated by `native/sync.mjs` (include-list copier; renames Index.html → index.html; excludes sw.js, scanner models, vendor/ort). `npm run app:sync` after ANY web-file edit — the installed app does NOT pick up Netlify deploys.
- **`IS_NATIVE_APP` / `SITE_ORIGIN` / `PROXY_ORIGIN`** consts in Index.html (defined just above `lorcastToProxy`) are the native shims: skip SW registration, absolutize `/img-proxy` + `/tcg-img-proxy` to packs.ink (rides Netlify edge cache; ACAO:* on both proxy routes in `_headers` keeps canvas exports untainted), force copied share links to say packs.ink, stub OAuth sign-in with a toast (Google blocks OAuth in WebViews — phase-2 Custom-Tab + deep-link + PKCE flow), keep + tag native Sentry events despite the localhost filter. All inert on web. `sync.mjs` refuses to build if these markers disappear from Index.html.
- **Never register the service worker in native builds** — registration is guarded AND sw.js is excluded from the bundle.
- `node_modules/` + `native/www/` gitignored; the `android/` project IS committed. Icons/splashes regenerate via `npm run app:assets` from `native/assets/logo.png`.

## Card scanner — PUBLIC BETA 2026-08-04

Camera → identify → review → save. **Identification is 100% on-device**: `scanner.js` + `scanner-cv.js` (OpenCV in `scanner-worker.js`) + PP-OCRv3 ONNX in `scanner-ocr-worker.js`, matched against index files the browser downloads once. No frame is ever sent anywhere to be read — say this plainly in any user-facing copy, it's the feature's best property and it's true.

Accuracy work (round-by-round history, replay harness, the miss taxonomy) lives in the **`project-scanner-spec` memory** — read its NEW-SESSION HANDOFF before touching the matcher. This section is only the shipping/consent surface.

### Gating

- **`canScan = true`** in App — everyone gets the 📷 button. It was `isGradedAdmin || isScannerTester`; the client-side `is_scanner_tester()` probe is GONE (it fired on every sign-in to answer a question no longer asked).
- **`scanner_testers` + `is_scanner_tester()` are NOT dead code.** Migration 98's `scan_samples` RLS still uses them server-side to decide who may read OTHER people's samples. Don't drop them as orphans.
- **`SCANNER_QA_ONLY` stays `true`.** The name reads like a testing switch but review-before-save is the shipping UX. Flipping it to the auto-add flow needs ✓-row precision honestly measured against the ≥95% bar first — and per round 11 you **cannot** get that from labelled rows (testers only touch rows they must fix, so the corrected-rate over reviewed ✓ rows is meaningless). Photo-verify a random sample of *unreviewed* shown-✓ rows.

### Consent + the upload opt-out (migration 114)

- **`scanner_consents(user_id pk, version, accepted_at, uploads_enabled, updated_at)`** — owner-only RLS on select/insert/update, no admin read branch. One row per user, updated in place: we need the CURRENT preference on every scan, not an audit trail.
- **`SCAN_BETA_VERSION`** (next to `SCANNER_BUILD`) is the accepted-notice version. **Bump ONLY when the substance changes** — what's uploaded, why, retention, who sees it. It re-prompts everyone; re-prompting for typo fixes trains users to click through the one screen that has to be read.
- **The gate blocks the camera, not just the view.** The `// mount: index + camera + worker` effect early-returns on `!consentOk` and its deps are `[consentOk]`, so `getUserMedia` cannot fire before acceptance. Verified: no `<video>` in the DOM pre-accept. Don't "simplify" this into a render-only overlay.
- **The opt-out reads `uploadsOnRef`, never the state.** `uploadSample`, `labelSample`, and the end-of-session telemetry insert all run from queue tails and deferred looks holding pre-toggle closures. All three bail when off — including the photoless session row, deliberately: "I turned that off" has to mean all of it.
- Reachable twice: the first-run notice, and a checkbox in the review screen (`.scanner-qa-privacy`).

### Retention — a promise with a cron behind it

`scripts/cleanup_scan_samples.py`, wired into etl.yml's **selfheal** job with `if: always()`. The beta notice and privacy.html both promise deletion after 12 months; this script is the only thing making that true, so it exits non-zero rather than shrugging.

- **Storage first, rows second.** The row is the only index of where the photos live — drop it first and a failed storage call strands JPEGs nothing points at.
- **Three objects per sample**, not one: the rectified card (`image_path`), `_raw` (the full camera frame) and `_strip` (the approach filmstrip). The last two are in `debug.rawPath` / `debug.stripPath`. Miss them and you delete the crop while keeping the wider shot — backwards, privacy-wise.
- `--user <uuid>` is the erasure path (account deletion, or "delete my photos but keep the feature"). Also sweeps the account's storage folder for orphans — an upload whose row insert failed, the class migration 105 fixed.

### Storage cost + the abuse cap (migration 115)

**Every scan is ~400 KB** — three storage objects at ~149 KB each. Four allowlisted testers put **500 MB** in the bucket before launch. Budget for public traffic accordingly; this is the scanner's main running cost, and the 12-month retention job is what stops it compounding.

- **1000 rows / user / rolling 24h**, enforced by TWO triggers on `scan_samples`. The BEFORE ROW one is the cheap common path; the AFTER STATEMENT one is the backstop, because rows from the same command aren't visible to a BEFORE trigger and PostgREST accepts bulk array bodies — without it, one `insert … select generate_series` walks straight through.
- Chosen against real data: the largest genuine session on record is **343** scans, so the cap is ~3x that. Don't tighten it below ~500 without checking `scan_samples` daily maxima first — throttling a tester running physical binders is the exact behaviour we want.
- Hitting it is invisible to the user: `uploadSample` swallows insert errors, identification is local, and the collection-save path never touches `scan_samples`. Under abuse the flywheel is the right thing to shed.
- **If storage becomes the problem**, the lever is the `_raw` frame + `_strip` filmstrip — they're 2/3 of the objects and only the rectified crop is needed for matcher replay. But raw frames are what detection tuning runs on (the #1 remaining accuracy lever), so sample them, don't drop them.

### Where the user-facing copy lives

Three places, keep them consistent: the in-scanner notice (`consentPanel`), **privacy.html `#scanner`**, and the Help page's "Card scanner (beta)" section. `Permissions-Policy: camera=(self)` in `_headers` already allows the camera — don't tighten it.

## Top-level nav

**Two-row icon nav** (restructured 2026-05-25). Row 1 = "my stuff", Row 2 = "market intel". Home tab removed — the logo IS the home click target.

- **Row 1**: Collection · Cards · Decks · Scan
- **Row 2**: Screener · Price Graphing · Analytics · Help

Icons live in `NAV_ICONS` (Index.html) — hand-coded inline SVG (Tabler/Lucide-style line glyphs), `stroke="currentColor"` so they inherit theme color. To add/swap an icon: edit the `path` for that key in NAV_ICONS, no asset file needed.

- **Scan** (added 2026-08-04, gated on `canScan`) is the one tab rendered as a `<button>`, not an `<a href>` — the scanner is a modal with no route, so there's no URL for a modifier-click to open. Everything else in the nav must stay an `<a>` (see "SPA navigation"). It went in **row 1, not row 2**: both rows are 217px wide at the mobile sizing, so a 4th chip on row 2's longer labels (PRICE GRAPHING / ANALYTICS) is what pushed ANALYTICS off the edge on ≤420px phones before. It carries a `.nav-tab-beta` "BETA" flag, absolutely positioned over the icon so it costs no layout width — `.tabs` is a horizontal scroller on mobile, and because `overflow-x:auto` forces the cross axis to clip too, a badge hanging outside the chip would be cut off rather than drawn.
- **The top-bar 📷 bubble is GONE** (2026-08-10, user request). It predated the Scan tab and was kept as a second entry point; once the tab shipped it was a redundant control competing for the crowded right cluster. `.tabs-grid` carries `padding-right:8px` on mobile so the last chip in a row isn't flush against the scroller's right edge (which read as clipping). That gutter belongs on the scrolled CHILD, not on `.tabs` — padding on a scroll *container* is dropped at the end of the scroll range in several engines.

- **Screener** = sortable financial-database table (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface. Has a prominent **Raw Prices / Graded mode toggle** (segmented buttons) above the preset chips — flips the table between TCGCSV raw + graded data.
- **Price Graphing** = per-card history + multi-card Compare (handoff from Screener batch action).
- **Analytics** = umbrella for calculator-y tools — **5 sub-tabs since the 2026-08-20 consolidation**: Expected Value · Trade Compare · Set Breakdown · Playset Cost · Simulator (+ hidden pinnable Elo). Sub-tab is reflected in the URL (`?a=<sub>`) — see "Trade Comparison tool" and "Analytics tab" below.

### Mobile top-nav structure (do NOT regress)

- Scroll lives on `.tabs` (middle), NOT on the whole top-nav. Logo + right cluster stay anchored as flex peers.
- Right cluster on mobile is `flex-direction:column` with two rows:
  - **Row 1**: profile/sign-in pill (collapses to avatar-only on ≤640px) **+ install bubble** (📲, conditional on `!isStandalone && (isIOS || isAndroid)`)
  - **Row 2**: help bubble (?) + theme toggle bubble (🌙/☀)
- The install bubble lives in row 1 next to the profile because it **disappears** once the user installs the PWA (`isStandalone` flips true). Having it pair with the profile avatar means row 1 naturally collapses to just-the-avatar post-install, no layout shift. Putting install in row 2 (its old location) pushed row 2 to 3 bubbles wide (~116px) and tipped `ANALYTICS` off the right edge of the scrolling tabs container on phones ≤420px.
- **Help is a bubble in the right cluster's bubble row** (as of 2026-05-26), NOT a peer chip in tabs row 2. The previous "Help chip inside the tabs row" layout collided with the sign-in pill / profile chip on phones — the chip sat at the right edge of the scrolling tabs row and overlapped the anchored right cluster. Moving Help to `.top-nav-right-row--bubbles` puts it in the same flex container as install + theme, where it can't bump into the sign-in pill above it. Implemented as `<button class="theme-toggle theme-toggle--help">` (inherits bubble shape; `.active` paints accent when view=faq).
- **Gear badge on the avatar** (`.profile-gear-badge`, added 2026-08-04): a 13px gear pinned to the top-right of the profile button's avatar, so the button reads as "account **and** settings" rather than just "me" — theme, home layout, offline images and sign-out all live behind it and people weren't finding them. Purely decorative; `.profile-btn > *{pointer-events:none}` already makes the button the sole click target. Lights accent on hover and while `aria-expanded="true"`.
- Every container in the right cluster has `background: var(--bg)` explicitly so the sticky header paints opaquely over scrolled content.
- **Mobile tap-target floor: 36px** on every top-nav control (`.signin-btn`, `.profile-btn`, `.theme-toggle`, `.theme-toggle--help`). Apple HIG recommends 44pt; 36px is the compromise that keeps the two-row nav from growing too tall. Was 26–28px before 2026-05-25 and the profile pill was nearly impossible to hit on iPhone — don't shrink back below 36px.

### iOS safe-area-inset (do NOT regress)

Index.html has `<meta viewport-fit=cover>` + `apple-mobile-web-app-status-bar-style=black-translucent`, which tells iOS to extend content edge-to-edge under the Dynamic Island / home indicator. Every page-level element that sits near a screen edge MUST honor `env(safe-area-inset-*)` or it lands under the unsafe zone on notched iPhones (14 Pro+, 15/16/17 Pro/Pro Max).

- **`body` padding** uses `max(designed, env(safe-area-inset-*))` on all four sides — desktop and non-cutout devices see 0 from env() so the designed 24px / 14px floor applies; notched devices pad outward to clear unsafe zones.
- **`.card-detail-close`**: `top: max(10px, env(safe-area-inset-top))` so the X stays tappable on iPhone (Photo 3 regression).
- **`.settings-popover` mobile pin**: `top: calc(56px + env(safe-area-inset-top))` so the menu doesn't open under the Island when tapping the avatar.
- **`.gc-add-fab` (graded mobile FAB)**: `bottom: calc(18px + env(safe-area-inset-bottom))` so the Add button isn't clipped by the home indicator.

Any new sticky / position-fixed / position-absolute element near a viewport edge should add `env(safe-area-inset-*)` to its offsets.

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- **Catalog lives in IndexedDB** (2026-07 offline rework): db `packsink`, store `kv`, key `catalog`, record `{v: CACHE_KEY, t, rows, latestDate}`. `CACHE_KEY` (`packsink:catalog:vN`, currently **v50**) is still the version stamp — bump N whenever cached row shape changes; a mismatched `v` is treated as missing and the next write replaces it. 24h TTL with background refresh. **Full rows are stored — `img_large` and `text` are NOT stripped anymore** (that strip existed for the 5MB localStorage quota; IDB has no such ceiling). Body-text smart search therefore works on cache-replay sessions, including offline; the lazy text backfill only fires for rows migrated from a legacy localStorage cache.
- **Legacy migration**: `readCache()` falls back to the old localStorage `packsink:catalog:vN` entry, returns it, and one-shot migrates it into IDB, deleting the localStorage copy on success (frees ~2.5MB back to the aux caches). `writeCache()` falls back to the old slim localStorage write only when IDB is unavailable (old private-mode Safari). Both are async now — `loadFromSupabase` awaits `readCache()`.
- **IDB helpers** (Index.html top): `idbOpen/idbGet/idbSet/idbDel` — resolve (never reject); reads → `undefined`, writes → `false` on failure. `offlineMirrorWrite/offlineMirrorRead("<what>:<uid>", data)` wrap them for per-user offline mirrors (see "Offline support" below).
- **Freshness probe** (added 2026-05-24): every page load with a "still fresh by TTL" cache fires a single-row query against `card_prices_latest` for `max(price_date)`. If server > cache's stored `latestDate`, cache is invalidated and refreshed. Means daily visitors see today's prices within seconds of opening the site after the ETL, not 24h later. **When the probe detects an outdated catalog it also wipes every price-derived aux cache** (`packsink:*` except catalog/auth/install-prefs) — movers, sealed, history, setsMeta, colvalue all derive from price data and were going stale silently behind their 12h TTLs. On network failure the probe trusts the TTL and keeps the cached catalog (this is the offline path).
- **`AUX_CACHE_VERSION` sentinel** (Index.html top, added 2026-05-24): per-deploy stamp compared against `packsink:auxCacheVersion` on module load. Mismatch → one-shot wipe of every `packsink:*` key except catalog/auth/install-prefs. **Bump the string to force every existing user's next page load to refresh aux caches** — useful when an ETL/matview change makes those caches stale faster than their TTLs catch. Independent from `CACHE_KEY` (which only invalidates the catalog itself).
- **Visibility re-probe**: `visibilitychange` + `pageshow` listeners re-run `loadFromSupabase` when the tab/PWA becomes visible again (throttled 60s). Without this, PWA users who background the app would see stale data forever on resume — React tree never remounts.
- Per-view caches use `readJsonCache(key, ttlMs)` / `writeJsonCache(key, data)`:
  - `packsink:movers:v1` (12h), `packsink:screener-movers:v1` (12h), `packsink:following:v1:{uid8}` (30min), `packsink:home:tourneys:v1` (2h), `packsink:hist:v1:{pid}:{printing}` (12h), `packsink:sealed:v1`, `packsink:setsMeta:v1`, `packsink:colvalue:v2:{uid8}:{productsHash}:{rangeKey}`.
  - `packsink:setsMeta:v1` fetched on EVERY page load via independent useEffect (not bundled with catalog Promise.all) — `loadFromSupabase` returns early on fresh cache which would leave setsMeta empty and break home box-price + prerelease guard.
- **writeJsonCache QuotaExceededError eviction** drops `packsink:hist:` first, then home banners, then sealed. (The catalog no longer competes for localStorage quota — it's in IDB.)
- localStorage quota ~5MB (aux caches only now). Min rows for catalog: 4000 (`CACHE_MIN_ROWS`).
- **Symptom of quota exhaustion**: cache writes fail silently, every visit cold-fetches, per-view banners "unload" on tab switch. Diagnostic: `Object.entries(localStorage).reduce((s,[k,v])=>s+v.length,0)/1024/1024`.

## Offline support (2026-07 rework)

The PWA works offline after one online visit. Layers:

- **Shell**: SW precaches Index.html + vendored libs + styles; navigations fall back to cached Index.html. (Pre-existing.)
- **Catalog**: IndexedDB (see "Client cache rules") — Cards browse, search (incl. body text), and cached prices render offline. Boot-error screen shows an offline-specific message (`isOnline` in App) when there's no catalog at all.
- **User data mirrors**: every successful fetch of collection / sealed(+meta) / pack-arts / graded items+goals / graded_prices_latest / own decks (incl. `deck_cards`, decoded) writes an IDB mirror (`offlineMirrorWrite("<what>:<uid>")`); the same fetch's failure path hydrates from the mirror. Decks mirror at `refreshDecks` covers both the list and opening a deck (DeckEditor reads from `decks` state). Offline is READ-ONLY: mutators fail → existing rollback + an offline-aware toast. Screener graded ownership + home portfolio chart intentionally NOT mirrored (market surfaces, online-only).
- **Images**: SW caches every `destination === "image"` request (plus lorcast.io) into **`packsink-img-v1`** — a cache that SURVIVES deploys (activate purge keeps it). Two critical gotchas fixed 2026-07: (1) opaque (no-cors cross-origin) responses have `res.ok === false` — the old `if (res.ok)` guard meant NO image was ever cached; use `cacheable(res)` (`ok || type === 'opaque'`). (2) The image branch runs BEFORE the data-API skip so Supabase-storage prestaged art is cacheable; PostgREST responses are never destination "image" so data stays uncached. Catalog `img_normal` URLs are same-origin `/img-proxy/...` paths, so cache keys line up between browsing, the downloader, and tile requests.
- **Image pack downloader**: settings popover → "Offline card images". `startOfflineImagePack(urls, scope)` + `OfflineImagesPanel` (Index.html, above App). Module-level task singleton (popover close doesn't abort), 6-worker pool, skips already-cached, no-cors fetches into `packsink-img-v1`, progress/cancel/clear UI, `~45KB/image` estimate, last-run stamp in `localStorage["packsink:offlineImages"]`. Signed-in users also get a "My collection" scope.
- **Offline UX**: `isOnline` state in App (online/offline listeners; regaining connectivity re-runs `loadFromSupabase`). `.offline-pill` (styles.css) shows "Offline — showing saved data". One-shot `navigator.storage.persist()` request shields IDB + caches from eviction. `fetchCardHistory` serves an expired hist cache entry when the fetch fails (`readCardHistCache(..., ignoreTtl)`).
- **Testing gotcha**: Chrome defers ALL `loading="lazy"` images while `document.visibilityState === "hidden"` — a backgrounded preview pane shows every tile image "pending" forever. Not an app bug; test with the pane visible or force `img.loading = "eager"`.

## PostgREST gotchas

- `sbFetchAll` parallel range pagination **requires explicit `order=` param** — without it ranges overlap and rows duplicate.
- `sbFetchAll` with `limit=N` confuses its own pagination. For "does this column exist" probes, use direct `fetch()`.
- Anything hitting `prices_daily` should be a **materialized view**. Statement timeout is 10s; raw views over the ~3M-row table hit it.
- Matviews need a unique index for `REFRESH CONCURRENTLY`. Refresh functions fall back to non-concurrent on first run.
- **PostgREST default page size is 1000.** Paginate `.range()` for tables that could exceed.
- **Upserts return `{error}`, they don't throw.** Always check `.error`. For bulk upserts, `.select("any_col")` and compare returned count vs sent.
- **`ON CONFLICT DO UPDATE` rejects batches with duplicate conflict-target rows.** `Supabase.upsert()` dedupes automatically.
- **`sbFetchWithRetry` wraps every fetch** with 3 retries on 5xx — Supabase's 57014 (statement timeout) is intermittent.
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

State is **three independent pieces**, each persisted independently to localStorage AND synced to Supabase user_metadata (cross-device):
- **`lightTheme`** (`packsink:lightTheme`) — which of the 4 light variants: `parchment` (default) | `sunrise` | `watercolor` | `daydream`.
- **`darkTheme`** (`packsink:darkTheme`) — which of the 3 dark variants: `velvet` (default) | `aurora` | `black`.
- **`themeMode`** (`packsink:themeMode`) — `"light" | "dark" | "system"`. Picks which family is currently active.

Resolution at render time:
- `themeMode === "light"` → `lightTheme`
- `themeMode === "dark"` → `darkTheme`
- `themeMode === "system"` → `osDark ? darkTheme : lightTheme` (matchMedia driven, re-resolves at OS night-shift / sunset).

The `resolvedTheme` (aliased `theme` for back-compat) is what gets written to `<html data-theme>`. The CSS file has one `html[data-theme="..."]` block per named theme — picking one swaps the entire palette atomically.

**Top-bar moon/sun toggle**: behavior depends on `themeMode`:
- Light or Dark mode: flips `themeMode` to the other side. The user's persistent `lightTheme` / `darkTheme` picks determine which exact variant renders.
- System mode: applies a **transient in-memory override** (`systemOverride` state, NOT persisted). The override clears on the next OS pref change (matchMedia listener) OR on page reload. Matches spec: "you can override it with the moon, but it will switch back next time system switches."

**Migration paths** (one-shot on first load after this rewrite):
- If localStorage `themeMode` held a specific theme name (e.g. `"velvet"`), the init infers the family and migrates: `themeMode → "dark"`, `darkTheme → "velvet"`.
- Old `packsink:lastDarkVariant` / `packsink:lastLightVariant` keys are read as fallback during init.
- Old `packsink:theme` key is also honored for the same family-inference.
- Supabase user_metadata hydration mirrors the same logic — old metadata with `themeMode === "aurora"` migrates the same way.

**Theme classification helpers** (`Index.html` ~line 22519):
- `LIGHT_VARIANTS = ["parchment","sunrise","watercolor","daydream"]`
- `DARK_VARIANTS  = ["velvet","aurora","black"]`
- `DARK_THEMES` Set includes the legacy `"dark"` alias; light membership is derived from `LIGHT_VARIANTS` (the `LIGHT_THEMES` Set was removed as unused — only `isDarkTheme`/`DARK_THEMES` are consumed).
- `isDarkTheme(t)` is checked at every site that branches on theme (e.g. `inkTint`, deck gradient builder). **Never check `theme === "dark"`** — that would miss `aurora` / `velvet` / `black`. Use `theme !== "light"` or `isDarkTheme(t)` or `DARK_THEMES_GLOBAL.has(t)` (the module-scope mirror used by `inkTint`).

**Gradient themes** (sunrise / watercolor / daydream / aurora) hold a CSS `linear-gradient(...)` or `radial-gradient(...)` as their `--bg` value (instead of a hex color). To make this work end-to-end:
- `body { background-color: var(--bg); }` (NOT `background:`). When `--bg` is a gradient value, `background-color` silently drops it (gradients aren't valid color values) — so the body stays transparent.
- `body::before { background: var(--bg); position: fixed; inset: 0; z-index: -2; }` — this fullscreen layer is the only thing that actually paints the gradient. Anchored to viewport, scrolls-fixed.
- The body is `max-width: 1300px`. If body's own `background` rendered a gradient, the 1300px column would seam visibly against the fullscreen `::before`. The `background-color` trick avoids that seam for gradient themes while still working for solid themes.

**Ink tints in dark/gradient modes** (`Index.html` ~line 2420, `INK_TINT_DARK`): values were retuned 2026-06-05 to land on the deep purple Velvet canvas (`#180a22`). Amber/Emerald previously muddied against purple at the old 16% opacity — now sit at 22% with brighter base hues. `INK_TINT_DARK` is also used for the gradient themes (any non-light theme).

**Settings popover layout** (gear/profile dropdown):
- **Mode**: 3-button segmented control `[Light] [Dark] [System]`
- **Light theme**: 4-button swatch grid (Parchment / Sunrise / Watercolor / Daydream)
- **Dark theme**: 3-button swatch grid (Velvet / Aurora / Black)
- The light-theme grid + dark-theme grid are ALWAYS visible regardless of current mode — picking one updates that family's pref and changes the toggle pair without changing mode.

**`showTopBarTheme`** pref (`packsink:showTopBarTheme`): toggle to hide the quick theme bubble in the top-nav right cluster. Default ON.

## price_movers matview gotcha

Computes Δ% across 6 windows (1D / 1W / 1M / 3M / 6M / 1Y) for both low and market. **`low_prev` is "most recent non-null low BEFORE low_today's own date"** — migration 26 fixes the original bug that collapsed pct_1d to 0 for sparse-listing chase cards.

## Catalog merging — `transformSupabaseData` rules

This is where catalog correctness lives. Structural cleanups:

1. **Holofoil mislabel rule** — TCGCSV sometimes publishes a card's in-pack foil under `printing=Holofoil` instead of `Cold Foil`. When a non-chase, non-extras card has a Holofoil row, that's the canonical foil and any separate Cold Foil/Foil row is suppressed as stale.
2. **`EXTRAS_MAP`** — `tcgplayer_product_id` → `{originSet, variantLabel, [excludeFromBaseSet], [standalone]}`. Three active buckets: "Starter Deck Exclusive Foil" (12 cards across Wilds Unknown/Fabled/Whispers), "Deep Trouble" (5 cards), "Palace Heist" (4 cards). `excludeFromBaseSet:true` suppresses from origin set. `standalone:{...}` includes cards Lorcast doesn't index (rows come from `patch_pid_overrides.py`).
3. **`CONNECTING_FOILS`** — `base_product_id` → `foil_product_id` for cards whose foil is a separate TCGPlayer SKU. 24 entries (Winterspell, Wilds Unknown, Reign of Jafar). Foil row emitted under base card's `card_id`; companion suppressed.
4. **`CUSTOM_VARIANTS`** — for cards Lorcast doesn't index that live INSIDE a mainline set (Genie - On the Job Two Swords, Peter Pan - Pirate's Bane Text Error). Clones base row with distinct `card_id` (`<base>::variant::<slug>`), null prices.
5. **`CUSTOM_CARDS`** — placeholder; currently empty. Kept as infra.
6. **`SET_DISPLAY_NAMES`** — `{"Challenge Promo": "Lorcana Challenge Promo (C1)", "Lorcana Challenge Year 3": "Lorcana Challenge Promo (C2)"}`. **All in-code set comparisons use the DISPLAY name.**
7. **`COLLECTOR_NUMBER_OVERRIDES`** — keyed by `<set_id>|<lorcast_cn>`. Currently renumbers Challenge Promo's Lorcast #25/41/42/43 → community #1/2/3/4.
8. **`UNIFIED_TILE_SETS`** — collapses Normal/Foil/Enchanted to one row in Collection grid: Promo Set 1/2/3, D23 Collection, EPCOT Festival of the Arts. **C1 and C2 are NOT here** — both have real Non-Foil/Foil splits.
9. **`CHINA_ONLY_NONFOIL` + `JAPAN_ONLY_NONFOIL`** — `{name|cn: image path}` for non-foil printings that exist only in a regional market. Get `variant_label: "Chinese Exclusive"` / `"Japanese Exclusive"`, null prices, local image, no TCGPlayer link. Currently CN: Dragon Fire #25, Let It Go #41. JP: Snow White - Unexpected Houseguest #41 (Promo Set 1, added via migration 52). Pattern works only when the card row exists in `cards` table — Lorcast-indexed cards just need the map entry; non-Lorcast cards need a `cards` insert too (see migration 52).
10. **`TCG_PID_OVERRIDES` is authoritative** — overrides Lorcast even when Lorcast has a (wrong) value. Used for Hiro Hamada #24/24B pid swap. **Applied client-side in `transformSupabaseData` AND server-side via `scripts/patch_pid_overrides.py`** — the latter writes them into `cards` so the matview JOIN picks them up. Client-only overrides don't help the matview.
11. **Image fallback in `buildRow`** — `img_normal || img_large || img_small`, etc. Lorcast occasionally populates only `image_large` (LCP C1 Dragon Fire, Let It Go, Cinderella, Rapunzel). **Downstream surfaces reading `price_movers` directly (home banners, Screener) DON'T see buildRow fallback** + `img_large` is stripped from catalog cache. Look up `raw[i].img_normal` (contains the large URL via fallback) and inject as `image_normal` on the matview row.
12. **Low ↔ Market fallback in `processData`** — collects samples from both `low_price` and `market_price`. When a card has one but not the other, the missing side falls back so it still contributes to rarity averages.
13. **`PROMO_RARITY_SETS`** — every card in the 7 promo-only sets (Promo Set 1/2/3, LCP C1, LCP C2, D23 Collection, EPCOT Festival) gets rarity overridden to `"Promo"` in `buildRow`.
14. **`YEAR3_PRINTING_BY_NUMBER`** — LCP (C2) cards each exist as exactly ONE printing per collector number. TCGCSV emits both Normal and Cold Foil under every pid (ghost rows). Map declares the canonical printing per number so the bogus one is suppressed.
15. **`SPLIT_BY_PRINTING_SETS`** (in `groupCards`) — sets where Normal and Foil are economically distinct and render as separate tiles. Currently `{LCP (C1)}`. Group key suffix-appends `::Normal` / `::Foil`. `card_id` stays untouched. C2 is NOT here — its printings have distinct card_ids from Lorcast.
16. **`SECTION_SPLIT_SETS`** (in `CollectionSetDetail`) — non-foil/foil section split in the set-detail view. Currently `{LCP (C1), LCP (C2)}`.

**Rarity normalization invariant** — `cards.rarity` MUST be canonical: `Common, Uncommon, Rare, Super Rare, Legendary, Enchanted, Epic, Iconic, Promo`. Lorcast publishes Super Rare as `"Super_rare"` — `scripts/load_lorcast.py` normalizes on insert. Migration 42 retroactively fixed stored values. Client also normalizes on read via `normalizeRarity()` as defensive guard.

Audit scripts: `audit_holofoils.py`, `audit_connecting_foils.py`, `audit_missing_foils.py`. Diagnostics: `supabase/diagnostics/`.

**`scripts/patch_pid_overrides.py`** — bridge between client-side maps and the `cards` table. Run after editing `TCG_PID_OVERRIDES` or adding Extras-style standalones. Idempotent.

**Why client-side overrides aren't enough for prices.** `card_prices_latest` is `cards INNER JOIN prices_daily ON tcgplayer_product_id`. If `cards.tcgplayer_product_id` is null/wrong, no matview row → no price. Run the patch script.

## React key trap (SPLIT_BY_PRINTING_SETS)

`groupCards()` produces TWO group objects per LCP (C1) card (Prize Wall + Prize Foil) sharing the same `card_id`. If the tile loop uses `key=${g.card_id}`, React sees duplicate keys, picks one, and **leaves the other orphaned in the DOM forever** — those tiles then appear in every search regardless of filter (phantom tiles). Fix: append printing suffix for split groups: `key=${g.card_id + (g.isSplitPrinting ? "::"+(g.Printing||g.tcg_printing||"") : "")}`. Fixed 2026-05-23.

## Smart search

`parseSearchQuery` extracts ink / rarity / set / classification / card_type / keyword / cost / strength / willpower / lore / inkable / legality / illustrator. Remaining tokens become the name query.

- **Numeric stat operators**: `cost`, `strength`, `willpower`, `lore` accept equality + comparison. Value at `filters[statKey]`, operator at `filters[statKey + "Op"]` (`=`, `>`, `>=`, `<`, `<=`). Forms accepted: `lore 3`, `3 lore`, `lore>=2`, `lore >= 2`, `lore2`. Matchers use `_cmp(rowVal, want, op)`. Null stats fail any non-null filter.
- **Classification + keyword filters are STRICT (declared only)** — flipped 2026-06-09. A `characteristic: princess` chip or typed `princess` token matches ONLY cards whose `classifications` array literally contains Princess. A `keyword: bodyguard` chip or typed `bodyguard` matches ONLY cards that DECLARE Bodyguard (see "Keyword extraction" below). Was previously soft-matched against product name too ("elsa spirit" rescue) — that overshot for explicit-dimension users ("characteristic: princess" pulled in every card with "princess" anywhere in the name). Known regression: typed `elsa spirit` now returns 0 cards (Elsa - Spirit of Winter has no Spirit classification — "Spirit" is just in her version). Workaround: type more specific terms (e.g. `elsa winter`) or use the `contains:` chip.
- **Keyword extraction in buildRow uses line-start matching, NOT `\bX\b`** (fixed 2026-06-09). A card DECLARES a keyword iff an ability line STARTS with the keyword name, optionally followed by either a numeric value (`Shift 4`, `Resist +1`, `Challenger +2`, `Singer 5`) or a reminder-text paren (`Bodyguard (An opposing character...)`). The old naive `\bBodyguard\b` regex tagged any card whose text MENTIONED the keyword — including Wipe Out! ("Put chosen character with Bodyguard..."), Fortisphere ("gains Bodyguard..."), and Bo Peep - Caring Shepherd ("Your characters named Woody gain Bodyguard"). KEYWORD_NAMES_SORTED iterates longest-first so `Puppy Shift` / `Universal Shift` / `Sing Together` win over their containees. `row.keywords` is part of the catalog cache — bumping CACHE_KEY (v43 → v44) forces all existing users to cold-fetch with the new derivation.
- **Partial-rarity prefix matching** via `resolveRarityPrefix(token)` (Index.html ~line 2232). Any ≥3-char unambiguous prefix of a canonical rarity resolves: `ench`/`enchant`/`enchante` → Enchanted, `leg`/`lege`/`legen` → Legendary, `epi`/`epic`, `ico`/`icon`/`iconi`, `pro`/`prom`/`promo`, `rar`/`rare`, `com`/`comm`/`common`, `unc`/`unco`/`uncom`. **Super Rare is intentionally excluded** — `sup` collides with the `super` classification subtype (Big Hero 6 Super characters). Use `sr` / `super rare` / `superrare` for that one explicitly.
- **Card body text in the haystack** — `buildRow` carries `text` from `cards.text` onto every row. `matchesCardFilter`'s name-fallback haystack includes `(row.text||"").toLowerCase()` so "gets" / "gains" / "draws" / "banish" / etc surface every card whose printed ability text says that word. Text is stripped on cache write (see "Client cache rules") so a cached-replay session would silently degrade to name+type+classification matching — `loadFromSupabase` defends against this by lazy-fetching `(id, text)` from the cards table after a cache hit and merging into `raw[]` in memory (keyed by `r.card_id`, NOT `r.id` — buildRow renames the cards-table PK). 1-2 MB one-time per session; doesn't touch localStorage so the aux-cache quota math stays unchanged. Body-text search lights up a few seconds after page load.
- **`matchMode: "any" | "all"`** — `emptyFilter()` carries `filter.matchMode` persisted to `localStorage["packsink:cardBrowser:matchMode"]` (default `"any"`). FilterDrawer top section "Match terms" radio chips flip it. CardsView's parsed useMemo writes `parsed.matchMode = filter.matchMode || "any"`; `matchesCardFilter` reads it for three things: (a) the `parsed.filters.classifications` array — any-mode `some`, all-mode `every`; (b) `parsed.filters.keywords` array — same; (c) the `parsed.name` haystack token fallback — `tokens.some` vs `tokens.every`. **Back-compat default**: other consumers of parseSearchQuery (deck builder picker, Compare, Price Graphing) pass `parsed` without matchMode, and the matcher defaults to `"all"` when `parsed.matchMode` is undefined — preserves their existing token-AND behavior so only CardsView changes default.
- **Multi-chip classifications + keywords** — CardsView's chip merge pushes characteristic chips into `parsed.filters.classifications: string[]` and keyword chips into `parsed.filters.keywords: string[]` (was overwriting per chip — "princess + queen" silently dropped princess pre-fix). parseSearchQuery's singletons `parsed.filters.classification` / `parsed.filters.ability_keyword` get promoted into the same arrays at merge time so the matcher only walks one path. matchesCardFilter checks the array first; falls back to the singleton for non-CardsView callers.
- **Enter on the smart-search input auto-picks `suggestions[0]`.** Pre-fix Enter no-op'd unless the user had arrow-keyed onto a suggestion first. Suggestions are dimension-aware first (color / rarity / characteristic / etc.) with `contains: <text>` as the always-present fallback, so Enter picks the most specific interpretation. Empty input still falls through to "close dropdown + blur".
- **`smartSplitSuggestion` — the name-plus-dimension row (2026-08-04).** Every other suggestion matches only the LAST token, so the dropdown's only whole-input option was `contains:` — and `contains:` searches the haystack (name + type + body text + classifications), which a rarity/ink/set word is never in. So `rapunzel promo` + Enter returned **zero cards**, which is exactly how most people type. `smartSplitSuggestion(raw)` runs `parseSearchQuery` over the whole input and, when it splits into ≥1 dimension plus leftover name text, is unshifted to the FRONT of the list and becomes Enter's default (after `exactDim`, before `contains`). Applying it commits the dimension chips **and** a `contains:` chip for the residual name in one go.
  - **It only triggers on `_SPLIT_TRIGGER_DIMS` = ink / rarity / set / legality / inkable** — the dimensions that live in columns and therefore can't be in the haystack. Classification / keyword / card-type words CAN appear there (and `matchesCardFilter` already soft-matches them against name+type when `parsed.name` is set), so `elsa spirit` keeps its working `contains:` behaviour. Widening the trigger set breaks that.
  - Bails entirely if the parse produced a filter with **no chip equivalent** (`strength` / `willpower` / `lore`, or a non-`=` cost operator) — better to leave the query alone than to silently drop half of it on commit.
  - **Price is a trigger dimension too, and the ONLY one that fires with no leftover name** (2026-08-14). A price lives in a column the haystack can't see, so `elsa under $5` + Enter used to commit `contains: elsa under $5` → zero cards. It now splits into a `price:` chip (kind `price`, carrying `priceMin`/`priceMax`; `value` is the human label AND the dedupe key — build it with `priceSmartChip`) plus the residual name. Unlike the other dims it's also offered when the parse leaves NO name (`amber over $200` is all dimensions), because the price *words themselves* are what `contains:` would otherwise search for. The other dims keep the `!p.name → null` bail.
- **`cardVersionTerms(row)` puts version labels in the haystack (2026-08-04).** `Prize Wall` / `Top Prize` (C1) and `variant_label` values (`Two Swords Variant`, `Text Error`, `Japanese Exclusive`, `Format Coconut`, …) are printed on the tile but live nowhere in `Product Name`, so `cinderella prize wall` matched nothing. Added to BOTH haystacks in `matchesCardFilter` (the `parsed.name` fallback and the `parsed.contains` phrase check). **Finish words are deliberately excluded** — putting `foil` / `cold foil` / `holofoil` in there would make a search for "foil" match half the catalog. C1 rows resolve foil-vs-not from `row.foil` on a group or `row.Printing` on a flat row.
- **`name:` pill renamed to `contains:`.** `summarizeParsedQuery` was labeling free-text + contains-chip merged text as `name:` while the matcher actually walked name + body text + classifications + card_type via the haystack fallback. The label was lying about the behavior — fixed by renaming to `contains:`. CardsView's parsedSummary also suppresses the duplicate pill when a `contains:` chip is the only contains source (the chip strip already renders it).
- **`SET_NICKNAMES` deliberately does NOT include single-token character names** ("ursula", "jafar") even though the sets are "Ursula's Return" and "Reign of Jafar". Those tokens are character names too — typing `ursula` in the deck builder should search for the *card*, not promote to the whole set. The longer/unambiguous forms still work (`ursulas`, `ursulas return`, `reign`, `reign of jafar`). Set suggestion dropdown still surfaces the set via prefix match, so users can click through if they meant the set.
- Catalog must have `cards.strength / willpower / lore / move_cost` columns (migration 43). Cold load probes for `lore`; silently omits all four from `CARDS_COLS` if missing.

### Single canonical matcher: `matchesCardFilter(row, f, parsed)`

Every card-search surface in the app **must** route through `matchesCardFilter` (defined at the top of Index.html, ~line 2691). It's the only function that knows about the strict classification/keyword checks, the haystack fallback for free-text name search, and the union of every filter dimension. Inline custom matchers will drift from the canonical behavior and produce subtle UX bugs.

**Signature:**
- `row` — the card or group object (must have `Product Name`, `Rarity`, `ink`, `Set`, classifications[], etc.)
- `f` — chip-state filter object (may have `inks`, `rarities`, `costs`, `cardTypes`, `inkable`, `classifications`, `keywords`, etc., all Sets). Required (not null-safe).
- `parsed` — the output of `parseSearchQuery(searchString)`. Optional — pass `null` if there's no search input.

**Surfaces that route through it** (audited 2026-05-26):
- Cards view main browse (`visibleGroups` ~line 5162)
- Decks editor card browser (via Cards groups)
- Price Graphing "By Card" picker (`flatMatches` ~line 7672)
- Price Graphing FilterDrawer reuse (`cardPassesHistoryFilter` ~line 7660)
- Collection set-detail view (`visibleGroups` ~line 6815) — unified 2026-05-26 from a local 3-field reduced matcher

**Surfaces that intentionally do NOT use it:**
- Set-name search inputs (Price Graphing's "Search sets…" — filters set names, not cards)
- Sealed product picker (Price Graphing's sealed mode — filters sealed catalog, not cards)
- Artist typeahead (Cards drawer + History drawer — artist-only)
- Decks list search (filters deck names, not cards)

**Screener uses it via catalog joinback** — `price_movers` matview rows only carry name/version/rarity/ink/set_id, but the Screener has access to `raw` (the catalog) and builds a `catalogByCardId` Map. The filter pass looks up the catalog row by `card_id` and runs `matchesCardFilter(catalogRow, chipFilter, parsed)` against it. This gives the Screener every dimension Cards has — partial rarity, body text, classifications, cost/stat operators, inkable, legality, illustrator, exclusion phrases. Chip filters (filterRarities / filterInks / filterSet) pass through as `f` — clicking the Iconic chip then typing "enchanted elsa" returns zero because the parsed rarity (Enchanted) AND the chip rarity (Iconic) both have to hold.

**Anti-pattern:** Don't re-implement the soft-match or stat-op logic inline. If a new view needs a small filter shim (e.g. chip-only filtering with no parsed query), pass `{inks: chipInks, rarities: chipRarities}` as `f` and `null` as `parsed`.

## Cards browse filter dimensions

Drawer + toolbar quick-filter chips (icon-only on toolbar):
- Ink (6 colors + Inkable/Uninkable hexes)
- Cost (1-9+ hex buttons)
- Rarity (9 icon-only buttons using `RARITY_ICONS`)
- Legality (Core / Infinity — mutually exclusive toggle)
- ✓ Owned (filters to groups where any printing has `collection[card_id:printing] > 0`)

Drawer-only: **Price** (see below), Strength / Willpower / Lore (numeric buckets), Type, Set, Keywords, Classifications, Artist.

### Price ($) filters (added 2026-08-14)

Four fields on the filter object — `priceMin`, `priceMax` (inclusive $ bounds, null = open end), `priceBasis` (`any` | `low` | `market`), `unpricedOnly` (bool). They live in `emptyFilter()`, so every `matchesCardFilter` caller gets them, and `serializeFilter`/`deserializeFilter` carry them for free (they're plain scalars, not Sets).

- **A card matches a max via its CHEAPEST printing and a min via its DEAREST.** `_cardPriceRange(row, basis)` returns `{min,max}` across normal+foil, so "Under $1" keeps a card whose non-foil is $0.40 even when its foil is $30, and "$100+" keeps the same card via the foil. This is the pre-existing typed-search semantic ("under $5" / "over $20"); the chips just reuse it. Don't "fix" it into an all-printings test — the tile shows both prices and users are shopping for the cheap side.
- **`priceBasis`** picks which number a printing contributes: `low` = TCGCSV's lowest active listing (any condition), `market` = NM Market, `any` = `Low ?? Market` (the widest net, and the historical behaviour — callers that pass no basis get it). It applies to the TYPED price too: the parsed-price branch in `matchesCardFilter` reads `f.priceBasis`, so a `$5` in the search box respects the drawer's pick instead of silently comparing a different number.
- **`unpricedOnly`** is the inverse lens — cards with no price at all on the chosen basis (regional exclusives, unlisted variants, freshly spoiled cards). It wins over any bound in the matcher, and the drawer also clears/disables the bounds so the two can't disagree.
- **`PRICE_BANDS`** (Under $1 / $1–$5 / $5–$20 / $20–$50 / $50–$100 / $100+) is the single source of truth for the preset buckets. The drawer renders it as chips; the Collection set-detail toolbar renders the same list as a `<select class="setdet-price-band">`. Add a band once, both surfaces get it.
- **Collection per-set view** keeps its own `priceBand` state (a PRICE_BANDS key, not persisted — same lifetime as its ink/rarity chips) and folds it into the non-allMode `chipFilter`. Because it narrows `visibleGroups`, the completion meters, the Owned/Missing value stats and the **"Shop N missing cards" bulk-buy link all follow it** — "what am I still missing under $1" is the workflow this exists for. `searchOrFilterLabel` takes the band as its 6th arg so the shop link says which band. The Collection **All Cards** view uses the full drawer instead, so it deliberately has no select.
- **URL-backed on the Cards tab**: `pmin`, `pmax`, `pbasis`, `unpriced` in `CARD_URL_KEYS` — a price search is shareable/refreshable like the rest.
- `countActiveFilters` counts a bound ONCE whether one or both ends are set; `priceBasis` alone never counts (it's a modifier on a bound, not a filter).

**Ink filter chips render as bare ink shields**, no chip wrapper (no dark circular fill, no per-ink colored border). The shared `.chip.ink-icon-chip` rule (styles.css) hard-overrides `background: transparent !important; border: none !important; border-radius: 0 !important; box-shadow: none !important` so the visual matches the deck-row inkable shields. Active state retains full color; inactive uses `filter: grayscale(0.6) opacity(0.55)`; hover removes the grayscale. The 30×30 hit area is preserved for tap ergonomics. 4 call sites still pass `style={{background: INK_COLORS[ink].bg, borderColor: INK_COLORS[ink].border}}` inline JSX — keeping them lets us rip the inline props in a future cleanup without re-touching the CSS, but the `!important` overrides keep the bare-shield look regardless.

## Screener filters

The Screener has parity with the Cards browse filters as of 2026-05-26 via the catalog joinback pattern (`catalogByCardId` Map). Three filter tiers:

### Main (always visible)
- Mode: Raw Prices / Graded (toggle)
- Preset chips: All / Movers / Gainers / Losers / Buyouts / Crashing / Discount / Premium
- Window chips: 1D / 1W / 1M / 3M / 6M / 1Y
- Collection filter (signed-in): All / Owned / Missing
- Signal filter chips: BUY / CRSH / DISC / PREM / TRND
- **Foil / Non-Foil chips** — turn off either to drop those printings from results. Chase rarities (Epic / Enchanted / Iconic / Promo) **bypass** the foil/non-foil filter — they have no foil/non-foil duality and always appear regardless of which chip is on. Persisted in saved views.
- Smart-search input — routes through `matchesCardFilter(catalogRow, chipFilter, parsed)`
- Set dropdown
- Ink multi-select
- Rarity icon chips — **always shows every canonical rarity** (CARDS_RARITIES) regardless of which appear in current results, so users can filter to "commons only" even when commons aren't in the top gainers.

### Advanced panel (collapsed by default — 2026-05-26 expansion)
- Min/Max price (uses `priceMode` to apply to Low vs NM Market)
- Min/Max Δ% in chosen window
- **Type chips** — Character / Action / Item / Location / Song
- **Cost hex chips** — 1-9+
- **Inkable** 3-way (Any / Inkable / Uninkable)
- **Legality** 3-way (Any / Core / Infinity)
- **Strength / Willpower / Lore** numeric bucket chips
- **Keywords** multi-select dropdown (Rush, Evasive, Bodyguard, …)
- **Classifications** multi-select dropdown (Hero, Villain, Princess, …)
- All advanced filters route through `matchesCardFilter` via `chipFilter` and persist in saved views.

### Mobile

- ≤720px: hide the checkbox column (invisible behind sticky NAME anyway), tighten NAME column to 110-135px max. Default no-scroll view fits NAME + Low + NM Market + 1W on a 360px phone. Batch-select via checkbox stays available on tablet/desktop.
- Filter chips wrap to multiple rows naturally.
- **Rarity icon chips fit on one line (2026-05-27):** at ≤720px `.price-db-raritybtns` gap drops to 2px and `.price-db-raritybtn-icon` padding drops to `4px 5px` so all 9 canonical rarity chips fit a single row on a ~375px phone (the 9th, Promo, was wrapping at the desktop `4px 10px`/`3px gap` sizing).
- **Landscape / short viewport (2026-05-27):** `.price-db-tablewrap` normally caps at `max-height: calc(100vh - 280px)` with an internal scroll. On a landscape phone (~411px tall) that left only ~1.5 rows. At `@media (max-height:600px)` the cap is removed (`max-height:none`) so the table flows into natural page scroll instead of a nested "sub-menu". Tradeoff: the sticky `thead` only pins within its scroll container, so once you scroll past the table top the column headers scroll off with it (pinning headers to viewport while keeping horizontal scroll needs a header/body structural split — deferred). Horizontal scroll on the wrap is preserved (table is wider than the viewport).

## Screener saved views

`screener_views(user_id, name, payload jsonb)` — owner-only RLS. Hydrated on sign-in (newest-first); local-only views migrated up on first sign-in if remote table empty. Writes mirror to localStorage for unauth fallback. If migration 44 not deployed (PostgREST 42P01), client logs warning and stays localStorage-only. Saved view payload now includes `showFoil`, `showNonFoil`, and every Advanced filter field.

## Price Graphing Compare

Multi-product overlay chart. Items in `compareCards` array, each: `{kind, card_id, productId, printing, name, sub, image}` where kind ∈ `card | sealed | set`. Drives both the chart and the bottom stats table.

- **COMPARE_MAX = 18** (raised from 8 on 2026-05-26). Picker `Up to N` and `Graph full` tooltips read from the constant so they stay in sync. COMPARE_COLORS cycles through 12 colors — past 12, hues repeat (acceptable; the legend chip's name distinguishes).
- **`+ variants` button** on each card chip (`.compare-add-variants` class). Scans `raw` for every row sharing the same Product Name and adds each (card_id, printing) tuple as its own series. Covers both: (a) Normal vs Foil printings of the same card_id (LCP C1 split-printing), and (b) different rarity prints of the same character (Common → Enchanted, distinct card_ids that share the name).
- **Synthetic card_ids for variants**: `realCardId + "::" + printing` (Normal printings keep the real id). Dedupe runs on the actual matview key `(productId, printing)` so clicking "+ variants" twice on the same item is idempotent. Only `kind === "card"` items get the button (sealed/set don't have variants in this sense).
- **Mover banner drag-to-scroll** (desktop only): `MoversBanner` has a `useEffect` wiring mousedown/mousemove/mouseup on `.movers-wrap`. 5px movement threshold separates a click-on-tile from a drag-pan (so single clicks still open the card detail modal). 250ms click-suppression window after a drag ends prevents the synthesized click from opening whatever tile you released over. Touch devices keep their native momentum scroll (the listeners are mouse-only).
- **Pickers** (card / sealed / graded / set) all route through their respective canonical matchers — see "Single canonical matcher" section. Graded picker uses a hybrid: parsed dimensional tokens via `matchesCardFilter` against the card meta, residual parsed.name checked against `(name + set + grader + grade)` blob so "mickey psa 10" works alongside "ench elsa".

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

Two graded price systems coexist. `GradedPremiumContext` selects between them.

**The allowlist is retired — graded is public.** `canViewGradedPremium` is hardcoded `true` (2026-07-14) and `can_view_graded_premium()` / `graded_premium_viewers` (migration 73) are **dead code, called from nowhere**. The provider value is `canViewGradedPremium && gradedTosOk`, so the only live gate is **ToS acceptance** (`GRADED_TOS_VERSION`, surface-triggered — see the tours/ToS notes). Every premium data source (`graded_sales`, `graded_sales_rollup`) is already anon-readable, so nothing server-side gates it either. `is_graded_admin()` is a SEPARATE thing and IS enforced server-side across ~10 RPCs and several RLS policies — don't conflate them.

- **Legacy (frozen, MID-DELETION).** `graded_prices_daily` → `graded_prices_latest`, per `(pid, printing, grader, grade, date)`. Third-party feed **discontinued 2026-06-30**; newest row is forever `2026-06-30`. Display contract is `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d`. Still read only by the pre-ToS graded UI, which stamps a `gradedAsOf` date. **See "Legacy graded deletion — in progress" below before touching any of it.**
- **Current.** `graded_sales` — our own per-sale eBay record (Terapeak scrape; the routine is the **`/graded-scrape` skill**, `.claude/skills/graded-scrape/`, Stages 1–4 driven by `scripts/graded_run.ps1`) → `graded_sales_rollup`. Because it stores individual sales rather than daily aggregates, it supports real **Last Sold** + **Avg of last 5** instead of a rolling average.

### Portfolio chart: printing is part of the key (do NOT regress)

`computeSalesValueHistory` / `computeSalesValueHistoryAvg5` value a slab at its **most recent sale, forward-filled** — so ONE wrong row IS the user's portfolio for days. Two invariants keep that honest, both in `makeGradedSlotSeries`:

1. **Match on printing, not just `(card_id, grader, grade)`.** Challenge Promo (C1) cards share one `card_id` across Top Prize foil and Prize Wall non-foil, which are different markets (Cinderella - Stouthearted PSA 10: **$1,707 foil vs $280 non-foil**). Keying without printing let a $33,493 Top-8 foil sale value a ~$450 non-foil slab — a two-day $67k spike on a $35k collection (2026-07-17). Vocabularies differ between tables (sales say `Foil`/`Non-Foil`/null, owned slots say `Normal`/`Holofoil`/`Cold Foil`), so both sides go through `gradedSlotBucket`, which keeps **unknown distinct from Non-Foil** and leaves version variants (Two Swords / Text Error) exact.
2. **Only enforce the split on cards that actually have two labelled printings.** With ≤1 known printing, every row (including unclassified) values the slot regardless of what it stored — the same fallback `lookupGradedPx` does, because foil-only chase cards have slots stamped `printing='Normal'` by the migration-50 backfill and a strict match would silently zero them.
3. **The split decision comes from the ROLLUP, not from sale labels, whenever the rollup is loaded** (2026-08-12). `gradedKnownBuckets(rollupRows)` builds per-tier bucket sets from `graded_sales_rollup` — whose `printing` column encodes the curated `cards.split_printing` / `foil_split` flags via `graded_sale_pkey()` — and is passed as the `knownBuckets` arg to `makeGradedSlotSeries` / `computeSalesValueHistory*` / `addUnsoldSlabsToSeries` (base series and missing-slab detection MUST share the same map). When present it is **authoritative, not unioned with the window's labels**, because labels fail both ways: a short window misses one side of a real split (C1 at 1M read one-printing → Prize Wall slab valued at Top Prize foil price), and a long window invents splits from stray seller language — "foil" on an all-foil card — which valued 2x Elsa SoW Enchanted PSA 10 at $89.10 against a ~$3,000 market at "All". Same-day sale ties sort by `scraped_at` to mirror the rollup's `rn=1` ordering (`fetchGradedSalesFor` selects it), and `computeSalesValueHistory*` append a forward-filled point at TODAY so every range ends on the same date. Net effect, verified against the largest real collection (224 slots, 34,949 sales): the endpoint is identical to the cent at 1M/3M/6M/1Y/All. Wired on home `CollectionPanel`, Collection-tab `GradedValueChart`, and the home graded movers' `isSplit`.

**`fetchGradedSalesFor` MUST filter `excluded: "is.false"`.** It didn't until 2026-07-29, so the chart rendered 8.3k quarantined rows (foreign-language, autographs, lots) that `graded_sales_rollup` and the card-detail scatter both correctly skip. Every other `graded_sales` read path filters it; audited 2026-07-29.

Guarded by `node scripts/test_graded_slot_series.mjs`, which extracts the real function text out of Index.html so it can't drift from what ships. Run it after touching any of these three functions.

### Bad-sale defences

Attribution is title-based, so wrong rows are inevitable. Three layers, in pipeline order:

1. **`terapeak_load.py`** — `exclude_reason_for()` (foreign / troll / auto) + `is_nonsingle()` (lot / set / pack / demo) decide `excluded` at load. `printing_of()` also reads the Challenge prize tiers: `Top Prize`/`Top N`/`Continentals` → Foil, `Prize Wall`/`Side Event` → Non-Foil. The foil side additionally requires C1/C2/challenge context because **Set Championship promos also say "Top Prize"** and aren't C1 foils.
2. **`scripts/backfill_graded_printing.py`** — re-derives `printing` + `exclude_reason` on existing rows from their titles. Only ever ADDS a printing where NULL (never overwrites a hand-corrected value). New exclusions are gated behind `--apply-exclusions` because hiding a sale is user-visible and the foreign-language rule can strand a regional-only card (Mickey - True Friend #25ja) with no sales at all.
3. **`scripts/flag_graded_outliers.py`** — the ingest guard; the graded analogue of `smooth_low_prices.py`. Per `(card_id, printing bucket, grader, grade)`, compares each sale to the **median of its ≤12 nearest-in-time neighbours within ±120 days** and quarantines beyond 6x / ÷6. Median not mean, and neighbours-in-time not whole-series, so a genuine ramp (Baymax $180 → $500 in two months) is not flagged. Needs ≥5 neighbours or it has no opinion, which also means it can never strand a card. Has a `--self-test` that runs automatically and **refuses to touch real data if it fails**; `--unflag` reverses every outlier decision in bulk.

**`graded_sales.exclude_reason`** (migration 111) is what makes that reversible: before it, `excluded` was a bare boolean, so a mis-set threshold couldn't be undone without also undoing every hand-reviewed exclusion. Values: `outlier`, `lot`, `foreign`, `auto`, `troll`, `cn-conflict`, `nomatch`, `manual`; NULL for rows excluded before 111.

**Counting `#NNN` occurrences does NOT detect multi-card lots** — sellers append PSA cert and inventory numbers in the same form, so the rule flagged 574 ordinary single-card sales against 1 real lot. Don't reintroduce it; the note is in `terapeak_match.py`.

### Price Graphing "By Graded" mode

Ported off the frozen legacy feed onto `graded_sales` 2026-07-29 (it had been graphing lines that all flat-lined at 2026-06-30 for every user).

- **Picker** reads `graded_sales_rollup`, joined to the catalog by **`card_id`** — not `tcgplayer_product_id`, which is null or wrong for a chunk of promos. Rows show `last_sold_price` + `sale_count` + the C1 `Top Prize`/`Prize Wall` variant label.
- **Series** are per-sale from `graded_sales`, filtered `excluded=is.false` **and on printing** — same trap as the portfolio chart: C1 cards share a `card_id` across two very different markets, and unfiltered they plot as one zig-zag. The rollup stores an unclassified printing as `""` while the sales table stores `NULL`, so the fetch maps `""` → `printing=is.null`.
- **The Low / NM Market toggle is repurposed**, because a slab has neither: `low` = each individual sale, `market` = the rolling mean of that sale and the 4 before it. Both the toggle buttons and `priceLabel` relabel to **Sale price / Avg of last 5** when `mode === "graded"`, and revert for every other mode.
- **`gradedCompareId(g)` is the single source of truth for the compare-list key.** The picker's selected-state test and the built item's `card_id` used to be computed independently and disagreed about whether printing was in the key — so a graded tier could never be un-checked and clicking twice added a duplicate line. Never inline that template string again.

### Legacy graded feed — DELETED 2026-07-29

The third-party TCGPriceLookup feed (discontinued 2026-06-30) and everything that read it are gone. `graded_sales` → `graded_sales_rollup` is now the ONLY graded price source.

**Client:** deleted `fetchGradedPrices`, `fetchGradedHistoryFor`, `computeGradedValueHistory`, `computeGradedDeltas`, `GradedPricesTab` (~260 lines), `buildGradedSeries`, both `gradedAsOf` staleness stamps, and the orphans that fell out (`latestPrices`, `gradedSynth`, `gradedByPid`, `gradedHistoryRows`, `ownedGradedSlotsByKey`, `tileHistory`, `gradedCurrentValue`). Every `gradedPremium ? new : legacy` collapsed to the new side. 28 + 6 dead `.graded-*` CSS rules removed from styles.css.

**The ToS gate stays.** `gradedPremium` resolves to `gradedTosOk`, so where the legacy UI used to render, `<GradedTosGate/>` now does — a compact "Review terms" card that re-fires `signalGradedSurface()`. Live on the card-detail Graded tab and the Screener in graded mode. Collapsing the gate instead would have shown licensed data to users who never accepted the terms.

**DB:** `supabase/112_drop_legacy_graded_feed.sql` — **APPLIED 2026-08-22** (all three legacy relations verified 404 via REST). All 70,990 rows archived to `Desktop/graded_prices_daily_archive_20260729.jsonl` beforehand, because `graded_sales` is wider (2023-06-19..present, 7,704 tiers vs 1,761) but **not a superset — 103 legacy tiers have no rows in it** (their last reference price lives only in that archive).

**Scripts:** all 8 retired helpers deleted; `etl.yml` + the `etl-debug` skill de-referenced (the skill had advertised `job=graded` as valid long after that job ceased to exist).

Things that survived the cull and must NOT be "cleaned up" later:

- **`gradedRowValue` and its `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d` chain.** Those are the field names `priceByKey`'s synthesizer emits (`rowOf` sets `ebay_avg_1d = avg_last_5`), NOT columns on any table. Deleting them breaks premium valuation and the Last/Avg-5 toggle. `GradedCollectionAddModal` was the last place poking them directly and now goes through `gradedRowValue(row, "avg5")`.
- **`.graded-tab`, `.graded-tab-explain`, `.graded-qty-btn`, `.graded-printing-toggle`** — look legacy, still used by `GradedSalesTab` / the owned-copies panel.
- **`!premiumGraded` in the Screener is NOT a legacy signal.** `premiumGraded = showGraded && gradedPremium`, so it is also true in Raw and Sealed mode; the signal chips and Non-Foil/Foil chips are gated on it and must keep rendering there. Left untouched deliberately.

**One-shot IDB eviction shipped.** The old code mirrored legacy prices to `offlineMirrorWrite("gradedprices")` and read them back whenever the fetch came up empty — after the drop that would have served frozen June prices from IndexedDB forever. The fetch, the write and the read are gone, plus a guarded `idbDel("mirror:gradedprices")` behind `packsink:evictedGradedPricesMirror`. `graded:` / `gradedgoals:` / `gradedown:` are separate buckets — don't wipe those.

Verified in-browser: app boots clean, no console errors; Screener graded shows the rollup columns (Last Sold / Avg Last 5 / Sold / Raw Low / Raw Mkt) with ToS accepted and `<GradedTosGate/>` without; card-detail graded renders the per-sale scatter; Price Graphing graded plots identical coordinates to its pre-rip baseline. `node scripts/test_graded_slot_series.mjs` passes.

## Graded view UX patterns

- **`.gc-caps-*` class family** (header chips): uppercase, letter-spaced 10px font matching `.gc-stat-lbl` so the whole header row reads as one chip set. Includes `.gc-caps-btn`, `.gc-caps-cta`, `.gc-caps-seg`, `.gc-caps-flag`, `.gc-caps-select`. New header controls should adopt these classes for visual consistency.
- **`.gc-caps-tip` tooltip**: custom popover on the ⓘ icon. More reliable than native `title=` (no delay, multi-line, mobile-friendly). On ≤700px switches to `position: fixed` + full-width-minus-margins so wrapping parents / `overflow:hidden` ancestors can't clip it. Use this pattern for any non-trivial tooltip in the graded view.
- **`.gc-add-fab` mobile FAB**: at ≤700px, the inline "+ Add graded card" chip is hidden via `.gc-add-cta-desktop` and replaced by a `position:fixed` bottom-right FAB. Standard pattern for high-frequency mobile actions when the header is too crowded.
- **Two-tap remove** (`armedRemove` state + `.gc-slot-armed` red pulse class): clicking an owned slot pill arms it for ~3s; second click within window confirms. Replaces `window.confirm()`. Reusable pattern — same state machine works for any destructive single-click action.
- **Quick-add on tracked tile** (`.gc-slot-quickadd` button): clicking the "+ PSA 10" pill on a tracked-only tile logs a PSA 10 instantly (one-tap goal progress). Shift-click opens the full Add modal for non-default grader/grade.
- **`grader_collection_items` does NOT have RLS for printing** — anyone with the owner's `share_token` can read all printings via the RPC. No additional gating needed; the RPC is already SECURITY DEFINER + token-checked.

### Persisted localStorage keys (graded view)

- `packsink:graded:collapsed` — array of set_ids that are collapsed
- `packsink:graded:display` — "grid" | "compact"
- `packsink:graded:trackCosts` — "1" | "0"
- `packsink:graded:removed` — array of `"cardId|printing"` composite keys (cards user removed from tracking). Replaces the old `packsink:graded:hidden` key (per-card hide feature was killed 2026-05-26 — see "Remove from tracking" section below).
- `packsink:graded:visFilter` — "all" | "owned" | "tracked"
- `packsink:graded:sectionSort` — "release" | "complete" | "value"

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
- **Extras goal**: `extras_bucket` populated with a variant_label string ("Deep Trouble" / "Palace Heist" / "Starter Deck Exclusive Foil"). Tracks all cards in `extrasCardsByBucket.get(bucket)`. UI shows these under a synthetic section "Extras & Oddities — <bucket>" via key `__extras:<bucket>`, which sorts after mainline sets.
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

## Sealed enhancements (2026-06-05 — modal + Δ% + Screener)

Three parallel additions made sealed feel like graded:

**1. `SealedDetailModal`** (`Index.html` ~line 9636) — clicking any sealed tile (in `SealedCollectionView`) opens a popup with:
- Image + name + set + product-type meta
- Current Low + NM Market side-by-side
- Owned-qty `+/-` controls when signed in (calls `updateSealedQty(pid, n)`)
- Optional `CostDateInputs` row when qty > 0 + trackCosts is on
- 6-window Δ% grid (LOW row × MKT row × 1D/1W/1M/3M/6M/1Y) from `computeSealedDeltas`
- Inline `LineChart` of `prices_daily` history (lazy-loaded via `fetchCardHistory(pid, "Normal")`)
- TCGPlayer affiliate buy link
- Reuses `.card-detail-overlay` + `.card-detail-close` patterns + ESC handler from CardDetailModal
- Also opened from the Screener row click when the row is a sealed synth row (see #3)

**2. Sealed-tile Δ% toggle** in `SealedCollectionView`:
- New `Show Δ%` toolbar checkbox (`packsink:sealedColl:showDeltas`)
- When on, fetches 365 days of `prices_daily` for the user's owned sealed pids via `fetchCollectionPriceHistory(ownedSealedPids, since)` (one batched call)
- Renders a 4-cell `1D / 1W / 1M / 1Y` grid beneath the price line on each OWNED tile
- Compute via `computeSealedDeltas(history)` → Map of pid → row
- Scoped to owned pids only (~typically <20 SKUs); for unowned products users get full history via the modal

**Tiles also show Low + Market simultaneously** when both exist (was previously priceMode-gated). The priceMode toggle still drives the total-value sort + header totals, but the tile surface always renders both numbers so users don't have to flip the toggle to compare.

**3. Screener Sealed mode** — third toggle button alongside Raw/Graded:
- `showSealed` state (`packsink:screener:showSealed`), mutually exclusive with `showGraded` (mutex useEffect on both)
- Fetches 365 days of `prices_daily` for ALL sealed pids on first toggle-on, cached in `sealedHistory` state
- `sealedSynth` memo builds rows shaped like `price_movers` rows (synthetic `card_id: "sealed::<pid>"`, image_small/normal from `image_url`, `display_type` from `deriveSealedDisplayType`, every `pct_*` + `mkt_pct_*` window from `computeSealedDeltas`, plus `_sealedProduct` ref for modal open)
- Filter chain in sealed mode is parallel to raw/graded but uses sealed-specific predicates:
  - Name substring search (no `matchesCardFilter` — sealed has no card catalog)
  - Set dropdown (uses `setNameById`)
  - Product-type chips (`filterSealedTypes`, persisted in `packsink:screener:filterSealedTypes`) backed by `SEALED_DISPLAY_TYPE_ORDER` — Booster Boxes, Booster Packs, Sleeved Booster Packs, Booster Pack Art Bundles, Illumineer's Troves, Prerelease Packs, Starter Decks, Gift Sets, Bundles, Quests, Sealed, Collector's Edition, Cases & Displays
  - `collFilter` (All/Owned/Missing) chips check `sealedCollection[pid] > 0` for sealed
  - Universal price + Δ% bounds + Crashing/Discount/Premium presets work uncapped
- UI hides Raw-only chips when sealed: ink dropdown, rarity icon chips, foil/non-foil chips
- Column header shows "Type" instead of "Rarity" in sealed mode; row's printing sub-line shows `display_type`
- Row click → `SealedDetailModal` via the same `openModal()` helper (detects `_sealedProduct` ref OR `"sealed::"` card_id prefix)
- `PriceDatabase` props extended: `sealedPrices`, `sealedCollection`, `sealedMeta`, `updateSealedQty`, `updateSealedMeta`

**Shared helper** `computeSealedDeltas(history)` (`Index.html` ~line 1796) — mirrors `computeGradedDeltas` shape. Takes `prices_daily` rows for sealed pids and returns rows with `low_today`, `market_today`, and per-window `pct_*` (Low-driven) + `mkt_pct_*` (Market-driven). Sealed has no foil duality so printing is always `"Normal"`. Uses the same `low_price_smoothed ?? low_price` coalesce as the catalog (migration 55).

## Cost & date tracking (sealed + graded collection)

Migration 48 added optional `amount_paid numeric(12,2)` + `acquired_date date` to both `sealed_collection_items` and `graded_collection_items`. Both nullable. **Migration 65 removed `amount_paid` (and graded `custom_value`) from the shared-collection RPCs' RETURNS TABLE** — purchase cost is owner-only now; viewers get `acquired_date` (for value-chart gating) but no paid price. The owner reads their own cost via direct table queries.

- **UI**: per-section "Track cost & date" toggle (`packsink:sealedColl:trackCosts` / `packsink:graded:trackCosts` localStorage). Off by default. When on, a `CostDateInputs` component renders below each owned row/slot. Both fields stay optional even when the toggle is on; clearing them writes NULL.
- **Shared component**: `CostDateInputs` (Index.html, just above `SealedCollectionView`) — `$ paid` + date inputs, commit on blur or Enter. Used by sealed (per-row, keyed by pid) and graded (per-slot, keyed by card_id + grader + grade).
- **State plumbing**:
  - Sealed: parallel `sealedMeta = {[pid]: {amount_paid, acquired_date}}` map at App level. `updateSealedMeta(pid, patch)` callback. Flows through `CollectionView` → `SealedCollectionView` AND through `HomeView` → `CollectionPanel` (the chart needs it).
  - Graded: rows already include `amount_paid` / `acquired_date` (no parallel state needed). `updateItemMeta({card_id, grader, grade}, patch)` callback.
- **Schema-tolerant fetches**: both fetch paths probe with the new columns, retry without on 42703 (column missing) so the frontend still works pre-migration. Safe to deploy code before applying the migration.
- **Chart gating** (`computeCollectionValueHistory` + `computeGradedValueHistory`): per-key acquired_date map. A slot contributes $0 to dates strictly before its acquired_date so historical value reflects only what the user actually owned at the time. Slots without acquired_date keep the existing earliest-snapshot behavior.
- **Graded chart backward-fill (two places)**: the legacy graded history is extremely sparse (avg 10 rows/slot/year, median slot's first row is months into a 1y window). **(1) Per-section:** `computeGradedValueHistory` seeds each slot's `prev` with its first known price so a slot is always represented once we have ANY data for it. Without this, plain forward-fill produced an artificial ramp ($100 → $2500) as more slots came online with their first data point. **(2) Combined-chart sum:** the combined-line builder in `CollectionPanel`'s `chartSeries` memo seeds each section's cursor with `s.sorted[0]?.value` so dates BEFORE a section's earliest data point still receive that section's earliest value. Without this, the combined line dropped to (cards + sealed only) on early dates and then jumped up when graded's first datapoint hit — even though the individual graded line in split mode was flat across the entire range. The two backward-fills compose: per-slot inside graded's own series, then per-section across the sum. Acquired_date gating still wins on the per-slot side.

## Collection Value chart: phantom-spike smoothing (migration 55)

TCGCSV's `low_price` is the lowest active listing, not the lowest sale — a single mispriced LP listing pins Low at $99 / $200 / $2,140 for days while NM Market never moves (Black Cauldron Cold Foil 2026-05-14 → 2026-05-26 is the canonical example: ~$14 → $2,140 → $99 → $15 across 13 days, Market stayed $13.62-$14.15 the whole time). Without intervention that single bad listing renders as a multi-thousand-dollar windfall/crash on the Collection Value chart. **Migration 55 adds `prices_daily.low_price_smoothed`** (nullable numeric); the nightly `scripts/smooth_low_prices.py` ETL writes smoothed values for days it identifies as phantom spikes; `computeCollectionValueHistory` reads `r.low_price_smoothed ?? r.low_price` so unflagged days pass through untouched.

**Scoped to the Collection Value rollup ONLY.** Every other surface — card detail Price History, Price Graphing, Compare, Screener, mover banner, `price_movers` matview, "Your Top Movers" home tiles — keeps reading raw `low_price`. Phantom spikes are real market events worth seeing in those views; smoothing only kicks in for "what was my portfolio actually worth on day X" where honesty matters more than realtime signal. The user explicitly wants the spike to appear on the per-card history; only the portfolio rollup should be denoised.

### Algorithm (`scripts/smooth_low_prices.py`)

Two-phase per `(tcgplayer_product_id, printing)` series:

1. **Mark anomalous days.** For each day D with ≥ 15 days of `low_price` data in [D-30, D-1], compute the rolling median. Day is anomalous if `low(D) ≥ 2.5 × median` OR `low(D) ≤ 0.4 × median`.
2. **Group into stretches** — consecutive anomalous days, tolerating gaps ≤ 3 days (brief mid-phantom returns to baseline like Black Cauldron's May 16 = $13 between May 15 = $119 and May 18 = $61 are part of the same phantom).
3. **Per-stretch evaluation.** For each stretch `[start, end]`:
   - **Duration cap:** if `end - start + 1 > 14` days → real move (meta hype etc), leave raw.
   - **Outer baselines:** median of `[start-30, start-1]` (≥ 15 samples) and `[end+8, end+21]` (≥ 10 samples). Post window starts at end+8 so any tail of the phantom doesn't pollute the post-median.
   - **Snap-back check:** post within ±30% of pre (`0.7 ≤ post/pre ≤ 1.3`). If not → real move, leave raw.
   - **Substitution:** every day in the stretch (including intermediate gap days) gets `low_price_smoothed = (pre + post) / 2`.

Median (not trimmed mean) is used throughout for robustness — even when 6 of 20 days in a window are spikes, the median still picks a normal-day value.

**Per-day algorithms don't work — must be stretch-based.** A per-day check can't distinguish "phantom that lasted 13 days" from "real move that lasted 13 days, now over": both look identical (pre ≈ post ≈ old baseline) if pre/post windows reach beyond the deviation. The duration cap is the only thing separating phantom from meta-hype, and it has to be measured against the *full stretch*, not a single day. (Initial implementation was per-day; failed the 14-day-true-move synthetic test case — both endpoints had pre/post matching old baseline.)

**Settling lag is intentional.** Today's row is never smoothed — we can't tell if a current spike is real or phantom yet. The script walks the trailing 60 days but stops at `today - RECENT_SKIP (=7)`. A spike won't be smoothed until ≥ 10 days of post-window data exist AND the median confirms snap-back, so Black Cauldron's May 14-26 stretch starts getting smoothed ~2026-06-13. User explicitly accepts the lag — "chart honesty in the moment matters more than instant historical revision."

### Wiring

- **ETL:** `.github/workflows/etl.yml` `smooth` job, `needs: prices`, fires on the daily safety-net cron + `workflow_dispatch` (job=prices|both). Idempotent — re-runs the trailing 60 days and overwrites as needed. Days outside the eval window stay frozen.
- **Client:** `fetchCollectionPriceHistory` adds `low_price_smoothed` to the SELECT with schema-tolerant 42703 retry (fetch still works pre-migration). `computeCollectionValueHistory` swaps in the coalesce. Other paths (`fetchCardHistory`, the EV/sealed price-history fetch at ~line 6439) intentionally keep `select: "...low_price..."` raw.
- **Cache invalidation:** `packsink:colvalue:v2:...` → `v3` (rollup logic changed); `AUX_CACHE_VERSION = "2026-05-30-low-price-smoothed"` wipes every existing user's aux cache on next page load; `sw.js` CACHE_VERSION → `packsink-v111`; `?v=110` → `?v=111` on styles.css/logo.js.

### Tunables

All at the top of `scripts/smooth_low_prices.py`. If outcomes feel off:

- `MAX_PHANTOM_DURATION_DAYS = 14` — phantom-vs-trend dividing line.
- `UP_SPIKE = 2.5` / `DOWN_SPIKE = 0.4` — anomaly thresholds vs rolling median.
- `SNAP_LOW = 0.7` / `SNAP_HIGH = 1.3` — post/pre snap-back band.
- `GAP_TOLERANCE_DAYS = 3` — max gap between anomalous days inside a single stretch.
- `RECENT_SKIP = 7` — minimum days between today and the most-recent smoothable day.

The FAQ ("Tracking your collection" section, Help bubble `?`) explains this user-facing in plain English. If the algorithm gets retuned, update both the script comments AND the FAQ paragraph.

### Synthetic test cases (run before changing the algorithm)

`scripts/smooth_low_prices.py` exposes `compute_smoothed_for_series(series, eval_start, eval_end)`. Four cases must all hold:

1. **13-day phantom (Black Cauldron shape):** all 13 days smoothed to the surrounding baseline.
2. **30-day sustained move ($3 → $30 → $3):** 0 days smoothed (duration > 14).
3. **3-day pump ($3 → $100 → $3):** all 3 days smoothed.
4. **Step-up with no return ($3 → $30 forever):** 0 days smoothed (post never snaps back).

## Analytics tab (reorganized 2026-08-20: 8 tabs → 5)

`MARKET_SUBS` = ev / trade / avg ("Set Breakdown") / setval / sim / swiss (+ elo, hidden unless pinned). The consolidation:

- **Swiss Odds (`swiss`, added 2026-08-20)** embeds the standalone `swiss.html` page as `<iframe src="/swiss?embed=1">` (canonical path is `/swiss` — Workers Assets pretty-URL handling 307s `/swiss.html` and the worker's legacy `/lab/swiss` route to it, DROPPING the query, so never point the iframe at `/lab/swiss`) — the sim stays a separate file on purpose (its Monte Carlo engine is a hot loop ordinary visitors shouldn't download inside Index.html; see the commit that added it). `?embed=1` sets `data-embed` on the page root pre-paint, hiding its own brand/flag/theme chrome, then strips the param via replaceState so the page's Copy-link never leaks `embed=1`. The header's "Open full page ↗" escape hatch was removed 2026-08-21 (user call — redundant once the embed worked; `/swiss` stays reachable by URL and the embed's own Copy-link shares it). swiss.html links `/styles.css` UNVERSIONED (network-first SW keeps it fresh; a `?v=` there would drift from the bump-cache lockstep, which doesn't know about this file).

- **Set Breakdown (`avg`) = Card Averages + Heatmap merged.** One rarity×set table with a metric toggle (`packsink:market:avgMetric`): `$ per card` averages, or `% of box EV` with the old heatmap's cell shading. **The share lens uses per-set `getPull(set)` — the deleted `HeatmapView` used the flat v1 `PULL` for every set, which was simply wrong for Wilds Unknown onward** (6 Legendaries not 4, 2.5 Epics not 1.5, 0.333 Enchanted not 0.25). Default selection = 4 newest sets (all-sets was a 1,655px-wide table); the `All` chip restores everything; exactly 2 selected still reveals the Diff column (pp units in share mode). The per-rarity "Pull rate" column is gone — rates differ per set now, so each cell's `title` tooltip carries its set's exact rate.
- **Simulator (`sim`) = Pack + Box + Monte Carlo merged.** Mode lives in `packsink:market:simkind` (`pack | box | bulk`); "Odds" (bulk) is the old `MonteCarloView`, mounted as a mode. The `sim-kind-bar` `<select>` is gone — a `.market-sim-kind` segmented control sits in the shared header.
- **Sealed tab DELETED — the Screener's Sealed mode superseded it.** `SealedView` is gone from Index.html and its `.sealed-view/.sealed-row*/.sealed-set-*` CSS from styles.css. The display-type classifier helpers (`SEALED_DISPLAY_TYPE_ORDER`, `deriveSealedDisplayType`, `isHiddenSealedListing`, `SEALED_PUZZLES`, `cleanSealedName`) **stay** — Screener sealed mode + SealedCollectionView consume them.
- **Legacy `?a=` keys must keep resolving** (old links exist in the wild): `MARKET_SUB_ALIASES = {heatmap→avg, montecarlo→sim, sealed→ev}`. App's `marketSub` initializer additionally one-shots the mode preset (`heatmap` writes `avgMetric=share`, `montecarlo` writes `simkind=bulk` to localStorage before the view mounts), and **`?a=sealed` redirects to the Screener**: a mount effect writes `packsink:screener:showSealed=1` / `showGraded=0` and `setView("screener")`. The popstate handler resolves aliases too.
- **Sub-tabs are `<a href="/analytics?a=…">`** via `navHandler` (SPA-nav convention — modifier-click opens a tool in a new tab). On ≤640px the bar is a single scrolling row (was a 3-row 127px wrap); the trailing gutter is a `::after` flex child per the scroll-container-padding gotcha. The 36px tap floor moved from `.market-subtabs > button` to `> .market-subtab`.
- **Shared chrome**: `MarketHeader` (the EV header pattern as a component — emits `.ev-header.mkt-header`) + `MarketExplainer` (collapsible "ⓘ How this works", collapsed by default, persisted per tool at `packsink:market:explain:<id>`). Every tool now has the header; the always-on `.market-explainer` walls are gone. `MARKET_SUB_TITLES` gives each sub-tab its own `document.title`.
- **EV rows carry a `⚄ Sim` chip** (`.ev-row-simbtn`) → `simulateSet(setName)` jumps to Simulator/Box with the set preselected. The set selection is SHARED across the three sim modes: MarketView owns `simSet`, each mode consumes it as `presetSet` in its `useState` initializer (modes remount on switch) and reports picks back via `onSetChange` — so Pack ↔ Box ↔ Odds keeps the set. BoxSim's `onOpenOdds` flips to bulk mode. The EV row's `onKeyDown` guards `e.target===e.currentTarget` so Enter on a focusable child doesn't also fire the row's open-history.
- **The tab bar also renders a right-aligned "Sealed ↗" pointer chip** (`.market-subtab-ext`) — a muscle-memory bridge to the Screener's Sealed mode. It and the `?a=sealed` redirect share App's `openScreenerSealed` callback (writes the two screener localStorage flags, then `setView("screener")` — must run before the Screener mounts, since its mode flags are read in `useState` initializers).
- **Coachmark fixes that shipped with this work** (tour infra, not Analytics-specific): an open auto-tour now DISMISSES on top-nav view change instead of following the user into a view where its selectors match nothing (context-free floating card; dismissal does NOT stamp `sectionTourSeen` — abort semantics). And the tip re-measures on a slow keepalive for its whole life instead of stopping 1.1s after mount, so async data reflowing the page can't strand the spotlight.
- Dead code cleaned with it: the unused v1 `CompareView` (absorbed into Card Averages long ago), `.trade-intro`, `.card-avg-chip-reset`, `.sim-kind-*` CSS.

## Trade Comparison tool (Analytics » Trade Compare)

`TradeView` (Index.html). Two-sided card-value comparison for working out a trade between two people. Search routes through the canonical `matchesCardFilter` (so the same smart-search works). Each side is a `[{key, qN, qF}]` array; the tool sums Low + NM Market and shows the difference.

- **Group key**: `tradeGroupKey(g)` = `card_id` (+ `::Normal`/`::Foil` suffix for SPLIT_BY_PRINTING_SETS cards). Cards re-resolve from a `groupByKey` Map so a stale cache can't carry dead references.
- **Default quantities on add**: a card with BOTH printings starts at **0/0** (the adder can't know which the other party means — they pick). Single-printing cards (chase: Epic/Enchanted/Iconic/Promo, or normal-only) default that one printing to **1**.
- **Per-card controls**: ± per printing, a **move-to-other-side** (⇄) button (merges quantities if the card already sits on the destination), remove (×). Header has per-side **Clear** + a **Clear all**. Clicking the card art/name opens the standard `CardDetailModal` (TradeView receives `theme/user/collection/updateQty/onSignIn` from MarketView for this).
- **Layouts** (`packsink:trade:layout` = `cards`|`compact`): compact drops the image + set/ink line and lays the two printings **side-by-side** (one condensed row) on all widths. The mobile (≤760px) breakpoint also forces side-by-side printings for every card.
- **Sort** (`packsink:trade:sort` = `added`|`price-desc`|`price-asc`|`name`|`release`): display-only, never mutates the side's stored order (so "Added" is restorable). Unpriced cards sink to the bottom for price sorts.
- **Tooltips + links**: Low/NM tags use the shared `Tip` (`TIP_LOW`/`TIP_MARKET`); each printing has a `↗` per-SKU TCGplayer affiliate link via `tcgUrl(pid, printing)`.

### Shareable trade links (DB-backed)

The trade is **persisted in the `trades` table keyed by a token**, not stuffed into the URL — the old inline `?trade=<base64>` blob blew past Discord's 2000-char message cap (~16 cards/side). Now the link is a fixed ~45 chars regardless of trade size.

- **Migration 54** (`supabase/54_trade_share_links.sql`): `trades(token pk, payload jsonb, user_id, created_at)`. RLS **on with no policies** — all access via two SECURITY DEFINER RPCs granted to anon+authenticated: `create_trade(p_token, p_payload)` (validates token shape `^[A-Za-z0-9_-]{16,64}$`, caps payload <100KB) and `get_trade(p_token)`.
- **Share** (`shareTrade`): generates a 22-char token client-side (so the clipboard write is **synchronous** inside the click — reliable in Safari), copies `packs.ink/?t=<token>`, and persists via `saveTradeRecord` in the background. Payload = `{a:[[key,qN,qF],...], b, n:[nameA,nameB]}` (`tradePayloadObj`).
- **URL form is `?t=<token>`, NOT `/t/<token>`.** A two-segment path breaks every **relative** asset URL (`styles.css`, `logo.js`, ink-icon preloads) — the browser resolves them against `/t/` → SPA fallback serves HTML → `LOGO_B64 is not defined` crash. The single-segment `?t=` keeps the path at `/` so relative assets resolve. (To ever use the pretty `/t/` path, every asset URL must first be made root-absolute.)
- **Open**: `App.initialUrlParams.tradeToken` (via `getTradeShareToken()`, captured in `useMemo` before the URL-cleanup effect runs) forces `view="market"`; `marketSub` inits to `"trade"`; `TradeView` fetches via `get_trade`, hydrates, and the App view-sync effect cleans the path to `/analytics`. Token is passed down as a **prop** (`shareToken`) — NOT re-read from the URL in the hydration effect, because the catalog loads async and the URL is cleaned before then. Legacy `?trade=` blobs still decode (`decodeTrade`).
- **Analytics sub-tab routing**: `marketSub` lives in App, mirrored to `?a=<sub>` (added to `dirtyParams` so it's stripped when leaving Analytics). First sync uses `replaceState`, user tab clicks use `pushState` (Back/Forward step through tabs); a popstate handler syncs `marketSub` from `?a=`. This is why refresh keeps the tab. The `if(cur===want) return` guard in the sync effect prevents the popstate→setState→push loop.
- **localStorage**: `packsink:trade:v1` (`{a,b,nameA,nameB}`) auto-saves the in-progress trade locally; a `?t=` share link takes precedence over it on load.

## Set conventions

- **`MAINLINE_SETS`** = booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Playset Cost, Price Graphing, Card Averages, Heatmap, Home "newest set".
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. `reverse()` puts mainlines on top.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased. Drives Core Constructed rotation.
- Decks pick up format automatically (`checkDeckLegality`): core-legal sets → "Core Constructed"; structurally legal → "Infinity"; otherwise → "Invalid Deck".
- **`TCGCSV_GROUP_SET_ALIASES` (`scripts/tcgcsv_common.py`) is how a TCGplayer group binds to a Lorcast set when their names don't match.** Both `etl_tcgcsv_daily.update_set_group_mapping` (writes `sets.tcgplayer_group_id`) and `load_sealed_products.build_group_to_setid` (writes `sealed_products.set_id`) resolve through `group_name_candidates()`, which tries the alias, then the literal group name, then the post-colon form ("Disney Lorcana: Fabled" → "Fabled"). An unmatched group is quietly expensive: `link_preorder_pids.py` only walks sets that HAVE a `tcgplayer_group_id`, so that set's new cards never get a pid linked and stay priceless/invisible until Lorcast fills `tcgplayer_id` itself. Seeded with `"d23 promos" → "D23 Collection"` — TCGplayer files every D23 drop (2024 #1-9, 2026 #10-15, both years' sealed collection SKUs) under one "D23 Promos" group. Add an entry whenever a new promo group appears under a name that isn't the set's.
- **Check one product with `python scripts/reconcile_catalog.py --pid <id>`** — reports it across TCGCSV / `cards` / `sealed_products` / `prices_daily` and exits 1 if it's in neither catalog table. The daily sweep can't answer this for a brand-new SKU (it only looks at pids priced in the last 14 days).

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

## Decks tab — logged-out access (2026-06-05)

The Decks tab is **usable without signing in**. The 5 sub-sections behave differently:

- **Discover** (public decks) — works fully without auth. Default landing section when signed out.
- **Tournaments** — works fully without auth.
- **Your Decks** / **Favorites** / **Following** — each section's body renders an inline sign-in CTA (a styled `.empty-state` block with a Sign-In-with-Google button + explanation) instead of crashing or loading empty. Section tabs ARE clickable when signed out (so the structure is discoverable).

Implementation:
- The unconditional `if(!user) return ...sign-in CTA...` at the top of `DecksView` was removed. The user-section CTAs live inside the per-section render branches.
- Initial `deckSection` defaults to `"discover"` for signed-out users (vs `"yours"` for signed-in). A separate `useEffect` watches the user prop and bumps signed-out users off any user-specific section onto Discover (without touching the saved-section pref, so signing back in restores their last pick).
- `decks` state is `null` until first fetch settles. References use `decks?.length || 0` to avoid the brief null-window crash for signed-out users.
- Per-deck action buttons (Follow / Favorite / Duplicate, in the external-deck banner): `onClick` now falls back to `onSignIn` when `!canAct` (i.e. no user). Previously the buttons rendered "Sign in to favorite" text but the onClick still pointed at the real action (silent no-op or crash). The external-deck `<DeckEditor>` renderer at line ~20089 already had `onToggleFavorite={user ? real : onSignIn}` wired — extended the same pattern to the in-banner buttons.

Public deck access paths (no auth needed):
- `externalDeck` flow — set via `openExternalDeckEntry()` when a Discover card is clicked. The SECURITY DEFINER RPCs `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` handle the fetch without auth.
- Incoming URL deep-links (`?deck=<id>` or `?deck=<id>&token=<x>`) hit the same fetch path BEFORE the gate logic — already designed for logged-out shared-link visitors.

## Deck-tile copy actions (🔗 / 📋 / 🖼)

Every deck-card tile in DecksView (owned, Discover, Favorites, Following, the per-tournament tile inside TournamentDetailView) carries three actions. They live inside `.deck-card-actions`, which got `flex-wrap: wrap` to handle the now ≥5-button row on ~260px tiles.

- **🔗 Copy link** — `copyDeckLinkToClipboard(d)` (owned + external) / `copyDeckLinkFromResult(r)` (tournament-detail). Uses `buildShareUrlFor(d)` for owned/external (`null` for private decks → "switch to Unlisted/Public" toast); tournament rows build inline from `r.deck_id` + `r.deck_share_token`. Public decks get a clean `?deck=<id>` (no token); unlisted + tournament decks get `?deck=<id>&token=<x>`.
- **📋 Copy list** — `copyDeckListToClipboard(d)` (cards already loaded) / `copyDeckListFromResult(r)` (async fetches via `fetchTournamentDeckForCopy` then formats with the existing `deckToText` helper).
- **🖼 Copy image** — see "Headless deck-poster autoCopy" below. Async lazy fetch on tournament tiles since the `tournament_results_v` feed carries metadata only.

**DeckEditor toolbar Copy-link button (non-owners).** When a non-owner opens a shared deck via deck-editor, the toolbar shows `🔗 Copy link` gated `${!isOwnDeck && shareUrl && ...}`. Reuses the existing `shareUrl` useMemo + `copyShareUrl` callback + `copied` state — flashes "🔗 Copied ✓" same as the owner's Share popover. Owners still see the full `↗ Share` popover (visibility radios + URL row + regenerate-token).

### Headless deck-poster autoCopy

`DeckPosterModal` has `autoCopy` + `onAutoCopyDone(success, blob|err)` props. The poster JSX was extracted into a `posterDom` const so both the visible modal-backdrop branch and the headless branch share the same DOM + the same `wrapRef`/`posterRef`. In autoCopy mode the outer wrap is:

```html
<div aria-hidden="true" style="position:fixed;left:-100000px;top:0;
  width:1200px;pointer-events:none;z-index:-1">
  ${posterDom}
</div>
```

useEffect waits for two animation frames (React commit + layout) → awaits every `<img>` inside `posterRef` to finish loading → calls `snapshot()` (the existing html2canvas chain) → `canvas.toBlob` → reports outcome via `onAutoCopyDone`.

**Caller pattern (mirrors mover-tile camera button — the user-activation rule):**

```js
flashToast("Copying image…", 12000);
let resolveBlob, rejectBlob;
const blobPromise = new Promise((res, rej) => { resolveBlob = res; rejectBlob = rej; });
navigator.clipboard.write([new ClipboardItem({"image/png": blobPromise})])
  .then(() => flashToast("Deck image copied to clipboard"))
  .catch(() => flashToast("Couldn't copy image — try the editor's Export button"));
setPosterAutoState({deck, creatorName, onDone: (ok, blobOrErr) => {
  setPosterAutoState(null);
  if(ok) resolveBlob(blobOrErr);
  else   rejectBlob(blobOrErr || new Error("snapshot failed"));
}});
```

The `clipboard.write` call is SYNCHRONOUS inside the user-gesture click, and the browser accepts the blob that resolves seconds later. Verified end-to-end: ~4.4s wall time, 2400×1970 canvas, ~5.5 MB PNG → clipboard. Without ClipboardItem support, `onDone` falls back to a `<a download>` save.

### TournamentDetailView is deck tiles, not a list

The old `tournament-result-row` list (`.tournament-result-open` button + 4-column grid) was replaced with `.deck-card.external.tournament` tiles in a `.deck-list` grid. Background gradient uses module-scope `INK_TINT_DARK` / `INK_TINT_LIGHT` + `DARK_THEMES_GLOBAL` so theme switching matches DecksView's tournament tiles. Place + player render in the trophy line; when `deck_name` is just an ink-only autofill ("Amber/Emerald") the player name promotes to the tile title (same dedupe as the home Tournament Results banner). Lazy deck-fetch uses `tournamentDeckCache = useRef(new Map())` keyed by deck_id so a 2nd copy-button click on the same tile is instant.

The orphaned `.tournament-result-*` and `.tr-*` rule clusters were already gone from styles.css (confirmed 2026-06-27 audit) — nothing left to clean up here.

## Cards-tile magnify button + enlarged-card overlay

Every `CardTileImpl` — browse mode AND deck-builder card browser — has a tiny `.tile-magnify-btn` (22×22, inline Lucide-style SVG circle+line) in the bottom-left of the image wrap. Opens `openEnlargedCard(group)` directly, skipping the detail-modal popup. Hover-only on desktop (`opacity:0; pointer-events:none` resting → `opacity:0.9; pointer-events:auto` on `.card-tile:hover` / `:focus-within`); always-visible on touch via `@media (hover:none)`. In deck mode where the `⤢` expand button is also at `bottom:6px; left:6px`, the `.card-tile:has(.tile-expand-btn) .tile-magnify-btn{bottom:42px}` rule lifts the magnifier above it so both are tappable. **Don't re-gate the magnify on `openModal` truthy** — the initial implementation gated it that way assuming deck mode didn't pass `openModal`, but it does (the expand button needs it), so the gate was a no-op AND a stale-comment trap. Current code unconditionally wires `onMagnify` and the JSX `${onMagnify && ...}` is the always-truthy presence check.

**Don't re-introduce the double-click path.** Pre-fix the same intent was wired as `onDoubleClick` on the tile, with a `packsink:close-card-detail` window event the detail modal listened for to dismiss itself. Unreliable because the SINGLE-click that fires first opens the detail modal — on slow devices the modal flashes and the dblclick lands on a freshly-rendered tile underneath. The magnify-button affordance avoids the race.

**Enlarged image must scale UP**. `.enlarged-card-img` now sizes via `width: min(92vw, calc(92vh * 5 / 7), 720px); height: auto; max-height: 92vh`. The pre-fix `max-width: min(92vw, 720px)` left the image at the source's natural ~488×681 (Lorcast `image_normal`), so the "enlarged" view wasn't actually enlarged. The `calc(92vh * 5 / 7)` is the 5:7 card aspect ratio derived width — keeps the image inside the viewport on tall screens.

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

## [Format Coconut] starter decks + Discover's third tab (2026-08-22)

**`DISCOVER_FORMATS`** is now the single source for Discover's sub-tabs — `core` / `infinity` / `coconut`, keyed on exactly what `checkDeckLegality()` stamps as `format`. Before it existed the tab list was a hardcoded pair, so a published Coconut deck classified as neither and **was invisible in Discover** from migration 110 until this shipped. The empty-state copy and the one-shot auto-fallback both read the list, so a fourth format needs no other edits.

**18 house starter decks, one per leader**, published by `scripts/seed_coconut_starter_decks.py` from the plain-text lists in `scripts/coconut_starter_decks/`. Edit a `.txt`, re-run with `--commit`, done.

- **Ownerless** (`user_id = null`), like tournament decks — so they stay out of everyone's Your Decks, and (same rule) are stored **plaintext**: the deck-obfuscation codec only covers user-authored decks.
- **Deck ids are a UUIDv5 of the leader slug**, so a re-run REPLACES a deck instead of publishing a second copy. `deck_cards` is deleted before re-insert, otherwise a card cut from the list would linger. Never change the `NS` namespace — that orphans all 18 and republishes them as duplicates.
- **`tags = ['packs-ink-starter', 'coconut:<slug>']`.** `isStarterDeck(d)` keys the "by Packs.Ink" byline (tile + the shared-deck banner) and the amber `.deck-card-starter` leader strip off that first tag; without it they read "by anonymous", which makes a curated launch feed look abandoned. The strip names the LEADER, never the word "starter" — the deck names are thematic (Sherwood Volley, Everything the Ink Touches, Four Pawpsicles), so the leader is the part a reader still needs.
- The seeder re-checks **every rule `checkDeckLegality()` enforces** (60 cards, ≤3 inks incl. the leader's, singleton except the associated 4-of and the leader's own exceptions) before writing. A starter deck that renders with a ⚠ badge is worse than no starter deck.

**Robin Hood's bonus card.** `COCONUT_CARDS` entries may carry `bonus: "<Product Name>"` — a card the leader plays from OUTSIDE the deck ("from your collection"). It is **display-only**: it costs no deck slot and does NOT consume the singleton allowance, so a normal Robin's Bow may still sit among the 60. `coconutBonusMeta(coconut, cardById)` finds its catalog row (scan by Product Name — the bonus is named in card text, not by id); the deck showcase and the poster both tuck it behind the leader.

- **The tilt is `rotate(8deg)` about `top left`, and the card sits LOW (`bottom:7%`), not high.** Anchoring a clockwise tilt anywhere on the right swings the top-right corner ~30px past the stack, out through the showcase's border and (in the poster) into the neighbouring card tile; anchored top-left the swing goes down-left instead. Sitting low is what puts the bonus card's rules text below the leader's bottom edge where some of it is actually readable — the point of showing the card at all. The leader gives up width for it (76% in the showcase, 78% in the poster).
- **Every `<img>` rendering `coconutArtUrl()` passes `crossOrigin="anonymous"`, including the ones that never touch a canvas.** The bucket sends `ACAO:*`, so the CORS request always succeeds — but Chrome caches a no-cors response separately, and a later canvas-bound request for the same URL reuses it and fails with `naturalWidth 0`. That is exactly how the deck poster's leader came out blank whenever the (non-CORS) showcase loaded first.

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

Admin-gated bulk-upload. N player rows → N public decks linked to tournament. Tournament decks have **`user_id = null`** (ownerless) so they don't pollute uploader's My Decks / Following.

- Migrations 35/37: tables + `tournament_results_v` view (security_invoker on).
- Admin gate: `is_tournament_admin(uuid)` SECURITY DEFINER helper.
- Bulk upload RPC: `bulk_upload_tournament(p_name, p_event_date, p_format, p_num_players, p_rows jsonb) returns uuid`. One transactional round-trip.
- Admin ops: `admin_delete_tournament`, `admin_update_tournament_meta`, `admin_update_tournament_deck`, `admin_replace_tournament_deck_cards`, `admin_add_tournament_deck`, `admin_delete_tournament_deck`. All SECURITY DEFINER, gated on admin.
- **`TournamentBulkEditModal`** is the canonical editor (replaces meta-only `TournamentEditModal`).
- **Discover tile**: when `tournamentByDeckId[d.id]` is set, byline swaps to player name and prepends 🏆 strip. Don't show "Unfollow {creator}" for ownerless decks.
- **CSS gotcha**: tournament-result row grid layout lives on `.tournament-result-open` (inner button), NOT `.tournament-result-row` (outer wrapper).
- `decks.user_id` nullable (migration 37). "My decks" / "Following" / creator-profile queries filter on `user_id = X` and naturally exclude tournament decks.
- Per-row inks computed client-side from `parseDeckText` + catalog meta, sent in row payload.
- **Deck detail tournament badge**: `DeckEditor` accepts `tournamentContext` + `onOpenTournament`. Builds lookup once via `tournamentByDeckId = useMemo(... )`.
- **Home Tournament Results banner.** Top 8 decks for each of the 4 most-recent non-empty events, newest first. **ONE mount site as of 2026-08-04** — it's a configurable home panel (`tournaments`, default column `left`) like every other, so there is no breakpoint-dependent mount and no `useMaxWidth` / `isNarrow` gate any more. Always rendered `collapsible`, so the `home-feed-collapse-btn` chevron works on desktop too; state persists in `packsink:home:tourneyCollapsed`. List caps at `max-height:560px`, dropping to 340px at ≤1100px where the panel is half a column wide.
  - The dead `.home-tourney-col` / `.home-tourney-col--desktop` wrapper classes and the `chaseStyleTitle` mobile styling are gone; the modifier class is now `.home-feed--tourney` (was `--tourney-mobile`, which stopped being true once the desktop mount used it too).
  - **Two earlier side-by-side attempts were ripped out** (`ChaseRowWithTourney`, pairing it with Rare–Legendary in a 2-col mobile grid height-locked via `position:absolute;inset:0`). The current pairing is NOT that: it's a plain `grid-template-columns:repeat(2,minmax(0,1fr))` with `align-items:start` on `.home-left-col` at ≤1100px, so Following and Tournament Results sit at their natural heights with nothing absolutely positioned. Falls back to one panel per row at ≤360px. If you touch it, keep it height-lock-free — that's what broke both predecessors.

## Deck view / edit modes

Click own deck → defaults to **view** (no card browser, no rename); toolbar has **✎ Edit** toggle. Brand-new decks open straight into edit.

- `DecksView` uses `openDeckInMode(id, "view"|"edit")`. Click → "view"; createDeck → "edit"; duplicate → "view".
- Owner controls (Share/Duplicate/Delete/Export) gate on `isOwnDeck`. Import + rename + Saved + CardBrowser gate on `!readOnly`.
- Three list layouts (View ▾): compact list, image grid, stacked pile.
- **CardBrowser ink pre-fill**: `DeckEditor` passes the deck's current `inkColorsInDeck` (1-2 colors) as the `defaultInks` prop. `CardBrowser`'s initial filter state seeds `filter.inks` from that prop *once on mount*. Re-opening the editor re-mounts CardBrowser → re-applies the deck's inks. Edits to chips during the session win after that. Gated to length 1-2 so a malformed/in-flux deck with 3+ inks doesn't auto-apply a weird filter.

### Deck editor mobile bottom bar

At ≤700px the editor renders a `.deck-editor-mobile-tabs` toggle bar that's `position: fixed; bottom: 0; left: 0; right: 0; z-index: 40`. **Was previously sticky top:60px** which got clipped by the variable-height (~80-90px) two-row top-nav, leaving the toggle perpetually half-hidden. Bottom-fixed dodges that entirely and puts the toggle in the thumb zone.

- The bar uses `bottom: -1px` (1px overshoot off-screen) to dodge subpixel rendering gaps where the page background was bleeding through a hairline on some Android renderings.
- `padding-bottom: calc(9px + env(safe-area-inset-bottom))` — buttons stay above the iPhone home indicator.
- `body:has(.deck-editor-mobile-tabs){padding-bottom: calc(70px + env(safe-area-inset-bottom))}` reserves vertical space at the page level so the bar doesn't overlay the last deck rows / footer. `:has()` scope means other pages don't get phantom bottom padding.
- **Tab labels**: edit mode = `Deck` / `Cards`. Read-only = `Deck` / `Deck Info` (the latter shows stats/charts panel since there's no card browser).
- **CSS rule**: `.deck-editor-grid.readonly.mobile-tab-cards .deck-editor-panel{display:block}` + `.deck-view-list{display:none}` overrides the base `.mobile-tab-cards .deck-editor-panel{display:none}` so the Deck Info tab actually shows the panel in read-only mode.
- **Toolbar gating**: on the Cards mobile tab, the toolbar action row collapses to just Done + Delete buttons. Other actions (Share / Notes / Mulligan / Export / Import / Duplicate) hide via the `.hide-on-cards-tab > *:not(.deck-toolbar-keep)` CSS rule at ≤700px. Keeps the toolbar from competing with the card browser for vertical real estate.

### HIGHLIGHT MISSING (flipped logic 2026-05-26)

The pill toggle on `DeckEditor`'s list view (`packsink:deckview:highlight` localStorage).

**Current behavior** (flipped):
- Cards you're **missing** copies of get **faded** (opacity 0.45, `.missing-fade` class on `.deck-row` / `.deck-grid-tile` / `.deck-stack-tile`).
- Cards you **own** (have all needed copies) render **normally**.
- X/Y badge on tiles: **green** (`.deck-tile-owned-frac.complete`) when fully owned, **red** (`.deck-tile-owned-frac.incomplete`) when missing.

**Old behavior** (pre-flip): faded owned cards, highlighted missing with a red border (`.missing-pop` class). Removed because the user wanted owned cards to visually pop, not the missing ones. The `.missing-pop` CSS rules were deleted; `.owned-dim` was renamed to `.missing-fade` (the class name now matches what it does post-flip — fades MISSING cards, not owned).

### Deck row mobile compaction

At ≤700px:
- Cost shield column: 32px → 26px
- Cost shield icon height: 28px → 24px
- Inline ink shield: kept (provides a second visual confirmation of ink color alongside the row tint)
- Grid gap: 8px → 6px
- Row horizontal padding: 8px → 6px
- Price chip: smaller font + tighter padding
- Counter buttons: 18px → 20px (slightly bigger for tap-target ergonomics)

## Deck import — text parser

`parseDeckText(text, raw)` — used by Bulk Upload, import deck text, tournament rows. Accepts:

- `4 Name`
- `4x Name`, `4× Name`, `4 - Name`
- **`4 Name - Subtitle (3-16)`** — Dreamborn export format. `(N-CN)` = (1-based MAINLINE_SETS index, collector number). When present, exact lookup via `candidatesBySetCN[N|CN]` wins over name scoring — useful for disambiguating chase/base printings.

Name scoring (when no exact-pid hint):
- `+100` if Set ∈ MAINLINE_SETS
- `-80` if Rarity ∈ {Enchanted, Iconic, Epic} (demote chases vs base)
- `-60` if isCustomVariant
- `-40` if isCustomCard
- `-20` if any variant_label
Highest wins, tiebreak by iteration order.

## Deck poster export

`DeckPosterModal` renders the poster as live HTML, snapshots via html2canvas on Copy/Save.

- **Always renders at desktop width (`min-width: 1000px`).** Wrap is `overflow-x: auto` so mobile users can swipe-scroll the preview — but exports always produce the desktop layout regardless of viewport. (Previous `@media (max-width:560px)` vertical-stack broke mobile exports.)
- **Header layout**: title + costs (left) | stats + cost-curve (middle) | logo + QR stacked (top right).
- **Cost curve and stats align at x=0** — curve SVG has `padL=0` and bar formula skips leading `gap/2` so first bar starts flush with "60 CARDS".
- **Logo + QR vertical stack** on the top right (96px each, 8px gap). Width was 192px (side-by-side); now ~96px → stats get the freed horizontal room.
- **Options grouped**: Layout (Background + Columns), Show (Stats + Cost curve), Costs (Non-Foil/Foil/Max Rarity $), Share (QR + URL footer; locked + click-to-make-unlisted when deck is Private and viewer is owner).
- **Bottom row**: `packs.ink · <date>` (left) + URL (right).

## Print proxies (deck → print-and-cut PDF)

`ProxyPrintModal` (Index.html, just after `DeckPosterModal`). DeckEditor toolbar → **🖨 Print Proxies**. Renders each card to a canvas, encodes JPEG, and writes a PDF: 9 cards per page at true card size (63×88mm), colour or B&W, PROXY watermark, crop marks, Save / Open-and-print.

**The PDF writer is hand-rolled — deliberately.** `buildProxyPdfBlob` emits raw PDF syntax and embeds each JPEG as a `/DCTDecode` image XObject, which means the JPEG bytes pass through verbatim and the whole writer is ~100 lines. The alternative was vendoring jsPDF (~350KB) into `/vendor/` and lazy-loading it, which buys nothing here: the only PDF feature used is "place image at rect". Same reasoning as the canvas card posters — it ships inside Index.html (network-first) so a stale service worker can't break it.

- **The watermark is painted into the card's PIXELS, not laid over the page.** It survives whatever the user does with the PDF afterwards. `drawProxyWatermark` — `subtle` = a corner tag, `bold` = tag + repeated diagonal, `none`. The corner tag renders in all modes except `none`.
- **White ground before drawing art.** Lorcast art is transparent outside the rounded corners and JPEG has no alpha — skip the `fillRect` and every card prints four black corners.
- **Identical copies share ONE embedded image.** A 60-card deck carries ~20 XObjects, not 60. `indexOf` maps card_id → image index; the page slots reference it repeatedly. Dropping this multiplies file size ~3x.
- **B&W applies a gamma lift** (`pow(g/255, 0.58)`, the "Lighten" checkbox). A straight luminance conversion turns a full-bleed dark Lorcana frame into a toner-soaked black rectangle with unreadable rules text.
- **Cards butt together (no gutter); crop marks live in the MARGINS only.** One straight cut separates two neighbours, and no ink lands on a card face. Marks are 4mm — the Letter vertical margin is only ~7.7mm, so longer marks would fall in the printer's unprintable band.
- **`PROXY_RENDER_PX = 744`** = 63mm at 300dpi. Lorcast `/large/` art is 734px wide, so this is a ~1% upscale — effectively native, and genuinely 300dpi on paper. Don't raise it; you'd be inventing pixels and tripling the file.
- **The "Scale: 100%" note in the modal is load-bearing.** Browsers default print dialogs to "Fit to page", which shrinks the cards so they don't match real ones — the single most likely way a user gets a bad result.
- Options persist to `localStorage["packsink:proxyPrint:v1"]`. The blob URL is revoked on unmount and on rebuild, never in a `result`-keyed effect (that would pull the URL out from under a Save click in the same tick).

**Guarded by `node scripts/test_proxy_pdf.mjs`**, which extracts the real writer out of Index.html. The two ways this breaks are silent and total — a wrong xref byte offset or a wrong stream `/Length` makes the file unopenable in every reader with no clue why — and both are arithmetic that shifts the moment anyone edits what the writer emits. It caught an off-by-one in `objCount` that emitted a phantom xref row. Verified end-to-end in Chromium's PDFium viewer, and the embedded streams check out as baseline (SOF0) 3-component JPEGs at the declared dimensions.

**htm fragments are `` html`<${React.Fragment}>…</>` ``, never `` html`<>…</>` ``.** htm compiles a bare `<>` to `h("", …)` and `React.createElement("")` throws. Cost a debugging cycle here; the rest of the file already uses the `React.Fragment` form.

## Artist Alley poster

`window.open` opens a self-contained poster in a new tab. Plain `<img>` tags + same-origin `/img-proxy/*` for Lorcast art (canvas exports work cleanly).

- **`.brand-footer`** at bottom with Packs.Ink logo (110px) + "packs.ink" wordmark. Stays visible in screen + print + html2canvas capture.
- **Copy as Image**: html2canvas → single tall PNG → clipboard.
- **Save JPG**: html2canvas → adaptive scale + q=0.85 → recompress (q=0.78 → 0.55) until under 9.5MB (Discord cap).
- **Print PDF path** preserves dark poster via `print-color-adjust: exact`. `break-inside: avoid` on figures. Pinned to 6 cols via `!important` in `@media print`.

## Copy-to-clipboard image exports

Three "copy this as an image" features. **The two card exports are now drawn on a `<canvas>`; only the mover banner tile still uses html2canvas.** Read this before touching any of them.

### Why card exports moved off html2canvas (2026-05-28)
html2canvas *screenshots the live DOM*, so its output depends on `styles.css` being the right version in the browser. The PWA service worker serves CSS cache-first, so a **stale cached stylesheet** rendered the off-screen poster with missing rules → wrong width, ungridded stats, card art at full natural size. Every CSS fix was invisible until the SW updated. **Fix: draw the card exports by hand on a canvas.** This ships inside Index.html (network-first → always fresh) and paints with explicit geometry + theme colors read live via `getComputedStyle`, so a stale `styles.css` can't break it — and it's instant (no DOM clone, no CDN fetch). The shared canvas drawing engine lives near `buildCardPosterBlob`: helpers `posterPalette()`, `posterPctColor()`, `roundRectPath()`, `drawImageCover()` (object-fit:cover), `wrapPosterText()`, `drawPosterLegend()`, `drawPosterChart()`, `loadPosterImage()`.

### Surfaces
- **Card poster** (`CardDetailModal` → Price History tab "Copy image" button, `.card-detail-copy-btn`) → `copyCardPosterImage(opts)` → `buildCardPosterBlob(opts)`. **Canvas-drawn, landscape:** top 2/3 = card art (left) + price-change stat cards (right, one per printing/variant via `statRows`); bottom 1/3 = price chart (`drawPosterChart`, reflects live range/Low/Market/Foil toggles) + inline legend; footer = logo + "packs.ink · date".
- **Card banner tile** (`CardDetailModal` image column, `CardTilePreview`) → `drawCardTileCanvas(canvas, opts)`. **Canvas-drawn, compact portrait** (the front-page mover-tile look): art → name → "Rarity · Foil" → Low/Mkt → 1D/1W/1M Δ% grid → footer. **The on-screen preview IS the canvas**, so the preview and the copied image are pixel-identical. Camera button `.card-tile-cam` copies the already-drawn canvas (`canvas.toBlob`). Replaces the plain modal image once price history loads (`tileRow` = Normal-preferred printing); falls back to a plain `<img>` for cards with no history.
- **Mover banner tile** (`MoverTile`, front-page banners): camera button `.mt-export-btn` → `copyMoverTileImage(tileEl)` → `captureMoverTileBlob` (**still html2canvas**). Captures the tile + a normally-hidden footer (`.mt-export-footer`, `display:none` live, flipped to flex in the `onclone`).

### In-modal "Price changes" panel (not an image — the live DOM panel)
`.card-detail-screener` renders below the card info, always visible. `ScreenerStatsRow` shows a banner-tile-style delta grid (6 windows × LOW/MKT) per printing, computed client-side from price history via `computeSeriesDeltas(rows, "low_price"|"market_price")` (windows in `CARD_DELTA_WINDOWS`). Each row has a **"Buy on TCGplayer"** affiliate link (`.cd-stat-buy`, via `tcgUrl(productId, printing)` — correct per-printing SKU). A **"Show all variants"** button (`variantRows`, fetched on expand) adds a row for every other (card_id, printing) sharing the Product Name. Catalog reached via `CatalogContext` (provided at the App root, value = `raw`). The same `statRows` array feeds the canvas card poster.

### html2canvas-1.4.1 gotchas (apply to the mover tile + ANY future html2canvas export)
1. **Clipboard write must be SYNCHRONOUS within the user gesture.** Capture fn returns `Promise<Blob>`; the click handler calls `navigator.clipboard.write([new ClipboardItem({"image/png": blobPromise})])` *immediately* (handler NOT async). The canvas exports keep this same sync-clipboard pattern.
2. **`ignoreElements` to avoid cloning the whole document.** Else html2canvas decodes every `<img>` in the clone — the Cards grid is ~41k nodes / ~3k imgs. (The old card-poster "20s hang" was actually the cold ~200KB html2canvas CDN fetch inside the click, not the render; capture itself is <1s WITH ignoreElements.)
3. **Off-screen capture needs explicit `width`/`height`/`windowWidth`/`windowHeight`** or it reflows tall-and-narrow.
4. **No flex `gap` / `justify-content:space-between` / empty styled marker spans** — use inline-block+margins, text-align, text glyphs (`●`/`━`/`┅`).
5. **Image URLs absolute + CORS-safe** — `window.location.origin + "/Logos/..."`; Lorcast art via `/img-proxy/` + `crossOrigin="anonymous"`, awaited before capture.

`flashToast()` (module-level) is the transient bottom-center toast all three flows use. Footer/brand text uses `--accent` (gold) so it reads in both themes.

## PWA install nudge

Auto-opens `InstallHelpModal` on visits 3 and 4 (counter at `localStorage["packsink:installVisits"]`; window bumped from 2–3 on 2026-08-21 — "the 3rd time they open it and haven't installed" was the ask, so newcomers get two visits of grace). Skipped entirely when already standalone, on desktop, or after the user clicked "Don't show this again" (`packsink:installDismissed`). Modal title/copy is framed as **"Packs.Ink is an app"** — you're on the website, it also installs (home-screen icon, full screen, offline, nothing from a store) — not as a generic install plea.

Modal accepts `onDismissForever`; only passed on visit ≥4 so the dismiss link appears the second time the modal pops. Existing users whose counter is already past 4 never see the auto-nudge again (intended — the manual 📲 bubble and settings remain).

## First-time sign-in onboarding

Two prompts fire in sequence on a fresh sign-in:

1. **Display name prompt** (`showNamePrompt` state in App): opens whenever `profiles.display_name` is empty for the signed-in user. Triggers via the `useEffect` that hydrates the profile row. Closes via `saveDisplayName` (which writes the name and flips the flag).
2. **Avatar picker** (`AvatarPicker` component): auto-opens 200ms after the user finishes step 1, gated by `localStorage["packsink:avatarPromptShown"]` and `!avatarCardId`. Picks ANY card from the catalog as the user's profile picture (writes `avatarCardId` to user_metadata + localStorage). The 200ms defer keeps the name-prompt unmount animation from fighting the picker mount.

The avatar gate is one-shot — closing the picker once flips `packsink:avatarPromptShown` so returning users without an avatar aren't pestered on every visit. Settings-popover edits to display name DON'T trigger the avatar prompt (the trigger is gated on `wasFirstTime = showNamePrompt` at save time).

## Home page surface

- **No "Lorcana Market" h1 or "Click a card for details" subtitle** — both removed 2026-05-26. The search bar sits directly under the top nav. The logo IS the home click target (the title was redundant).
- **Your Top Movers tiles show a printing badge** when the moving row is the foil printing — class `.panel-movers-foil-tag`, accent-color chip with text "Foil" / "Cold Foil" / "Holo" (Holofoil shortens to "Holo" to fit the tight column). Logic: `row.tcg_printing && row.tcg_printing !== "Normal" && row.tcg_printing !== "Non-Foil"` → render. Lets users tell foil-vs-non-foil movers of the same card apart.
- **Tournament Results panel: `.ht-place` is `white-space: nowrap`** and `.home-tourney-deck` grid is `auto minmax(0,1fr) auto` (was `28px 1fr auto`). The 28px column wasn't wide enough for `"Top 4"` / `"Top 8"` — the place text wrapped to two lines, doubling row height on the narrow signed-in mobile home grid. Auto-width + nowrap keeps each row on a single line; player column's `minmax(0,1fr)` still shrinks with ellipsis when needed.

### Configurable layout (2026-08-04)

Every home section except the movers stack is a **user-arrangeable panel**: show/hide, move between columns, reorder within a column. Edited from the settings popover ("Home page layout"), persisted to `localStorage["packsink:homeLayout"]` as an ordered `[{key, col, on}]`.

- **`HOME_PANELS`** declares the panels + their default column; **`HOME_COLUMNS`** the four targets: `announce` (full-width strip under the search box) · `left` · `main` · `right` (labels: Top strip / Left rail / Below movers / Right rail). **`tools` ("Analytics toolbox", added 2026-08-20, default = top of `right`)** is `HomeToolboxPanel` — six `<a href>` chips into the Analytics tools via App's `openAnalyticsTool(subKey)`, with hand-coded `_navSvg`-style line icons (`HOME_TOOL_ICONS`, accent-colored — NO emoji, per user) and a collapsible header (`packsink:home:toolboxCollapsed`, same chevron pattern as the tournaments panel). Because `normalizeHomeLayout` APPENDS new keys at the bottom of existing layouts, it shipped with a one-shot hoist stamp (`packsink:homeLayoutToolbox`, same pattern as the news-rail fix) that moves it to the top of the right rail once; a later user re-position sticks.
- **Movers banners are reorderable in edit mode (2026-08-21)**: each rendered banner gets a `.home-edit-card--banner` bar with ▲▼ only. Order persists at `packsink:homeBannerOrder` (`HOME_BANNER_KEYS` = valuable/chase/rareLeg/promo/graded, normalized by `normalizeBannerOrder`); **null = the built-in hot-aware order** (newest-set banner floats top during release week, bottom after) — the first ▲▼ materializes the order the user is looking at and retires the heuristic. The rareLeg entry moves the whole `rl-news-row` (news feed rides along); banners with no node (signed-out graded, no newest set) render no bar. The movers stack now returns a **Fragment, not a wrapper div**, so banners are direct children of `.home-grid-main` and the edit-mode freeze dims each one while its bar stays live. Banner order shares the edit lifecycle: snapshot on entry, Cancel restores, Reset nulls it.
- **On-page layout edit mode (2026-08-21)** replaced the cramped settings-popover editor (which is now just an "✎ Edit home layout" launcher → `startHomeEdit()`). The "✎ Edit layout" chip under the home search enters editing: every panel gets a dashed `.home-edit-card` control bar — ▲▼ reorder, a column `<select>`, Hide/Show — rendered as a SIBLING above the panel, **never a wrapper** (the `.home-left-col > .home-feed` child-selector rule still stands). Hidden panels keep a dimmed bar at the bottom of their column so they're restorable in place. Live panels get `pointer-events:none` + dimming via `.home-editing` so a stray tap can't navigate. The sticky control row (Reset / Cancel / ✓ Done) pins at `top:96px` on phones (below the two-row nav, same trick as `.cards-bulk-bar`). Edits apply live; entering snapshots the layout so **Cancel restores it** (`homeLayoutDraftBase` ref in App); navigating away mid-edit keeps changes and exits. **`normalizeHomeLayout(val)`** is the only way state enters — it drops unknown keys, appends missing ones at their default column, resets bad column names, and never throws. Both App (on load) and HomeView (on render) run it, so a hand-edited or half-migrated value can't render a broken page.
- **Migration**: the old visibility-only `packsink:homePanels` map is read once on first load and folded into the new shape. Both keys are `localStorage`-only — deliberately NOT in the `user_metadata` prefs-sync effect, since a phone and a desktop wanting different arrangements is normal, not drift to reconcile.
- **⚠️ Changing a panel's default `col` does NOT reach existing users.** The layout is persisted on EVERY page load, and `normalizeHomeLayout` keeps any stored column that is still a valid column name — so a browser that visited once holds that column forever. This bit the news feed: it defaulted to `announce` from `927ca7b` until `f1e5819` flipped it to `left`, and every browser from that window kept rendering it as a lone 420px `.home-announce` card under the search box with the whole grid shoved below (reported 2026-08-14 from a long-lived signed-in profile; a fresh profile on the same machine looked correct). Fixed by a **one-shot stamped migration** in App's `homeLayout` init (`packsink:homeLayoutNewsRail`) — stamped, not coerced, because `announce` is still an offered column and a permanent coercion would make picking "Top" for news snap back on reload. Do the same for any future default-column change: one-shot keyed on a fresh stamp, never a standing rewrite in `normalizeHomeLayout`. Guarded by `node scripts/test_home_layout.mjs`, which extracts the real code out of Index.html so it can't drift.
- **News feed** (`news` panel, reworked 2026-08-12) bundles the pre-release News tile, any live `EVENT_TILES` convention tile, and the Format Coconut tile — in that order (dated things first, the standing Coconut notice last, per user request). ONE tile list renders into TWO CSS-gated mounts of the same `.home-news-feed` aside: the `--rail` copy is a normal column panel (default = top of the LEFT rail; the column picker governs only this copy), and the `--rl` copy rides the Rare–Legendary movers banner as the right-hand cell of the `.rl-news-row` grid (`minmax(0,1fr) minmax(150px,32%)`) — the same geometry the old mobile tournament column used. `@media (max-width:1100px)` flips which copy displays: ≤1100px the rail columns sink below the movers, so the rl copy is the visible one (per user: desktop = left column, mobile = beside the movers; the old full-width announce tiles ate half a phone screen). Natural heights only (`align-items:start`, list scrolls inside `max-height` — `min(70vh,560px)` rail / `min(66vh,520px)` rl) — do NOT height-lock the pair; that's what killed both `ChaseRowWithTourney` predecessors. **The cap is viewport-relative on purpose** (was a flat 340px on the rl mount): a pixel cap clipped the list hundreds of px short of the room the row actually had on a tall phone. The aside is the `NewsFeed` component (just above `HomeView`) rather than inline JSX because the clip needs an affordance — phones hide their scrollbars, so a half-cut tile reads as a broken box. `edge` state (`""|top|bot|both`, from a scroll + `ResizeObserver` sync) drives a `news-edge-*` class that masks the clipped end and shows a ⌄ chip. The fade is `mask-image`, NOT a gradient overlay: four themes hold a gradient in `--bg`, which can't be a colour stop — and the mask is only safe here because these tiles are text-only (see the CSS-pitfalls note on masks softening child `<img>`s). In the movers loading/error/no-direction branches the rl copy renders full-width above the status message so announcements never vanish behind a data hiccup on phones. The `announce` strip (full-width, under the search box) still exists as a column target; nothing defaults there anymore.
- **Empty side columns are omitted from the tree**, and `.home-grid` gets `hg-no-left` / `hg-no-right` which narrow `grid-template-columns` to match — otherwise hiding everything on the left left a 240px hole. Columns are **auto-placed in DOM order**; don't reintroduce `grid-column:1` on `.home-left-col` or the omission breaks.
- `moveHomePanel` swaps with the nearest neighbour that is **both in the same column AND visible**. Plain index±1 would swap past a panel in another column (or a hidden one) and read as a dead button.
- Panels are keyed on the component (`key="following"` etc.), not wrapped in a div — several CSS rules are `.home-left-col > .home-feed` child selectors that a wrapper would break.

### Movers-banner chip filters (`MoverChipGroup`)

Two banners carry a multi-select chip group in their `controls` slot. Both use the shared `MoverChipGroup` + `toggleChipKey` + `readChipPref` trio — **don't hand-roll a third one.**

- **Chase Movers** — `CHASE_RAR_ORDER` (Epic / Enchanted / Iconic), persisted at `packsink:home:chaseRars`.
- **Rare–Legendary Movers** — `RL_PRINTING_ORDER` (`normal` / `foil`, labelled Normal / Cold Foil), persisted at `packsink:home:rlPrintings`. Was a one-of-N `Both | Normal | Cold Foil` seg-grp keyed `packsink:home:rlPrinting` until 2026-08-02; the old key is still read once as a migration (`"all"` falls through to the default). `MOVER_FOIL_PRINTINGS` buckets Holofoil under foil, so there's no third state.

Invariants:

- **The last active chip can't be turned off.** An empty selection renders an empty banner whose only way back is the chip you just used to empty it. `toggleChipKey` returns `selected` unchanged in that case, and the chip's tooltip explains why.
- **Filter AFTER sorting, before `.slice(0,20)`** — so the top 20 comes from the selected tiers, not from whatever survived a slice of the full pool.
- **The banner subtitle and the title-click Screener jump both read the selection.** Chase passes `filterRarities`; rare–leg passes `showFoil` / `showNonFoil`. Both are in the buckets `useMemo` deps.
- **These keys are preferences, not caches.** They live under `packsink:home:` but do NOT match any `AUX_EVICTABLE_PREFIXES` entry (`packsink:home:tourneys:` is the tournament *cache* — note the trailing colon, and that `packsink:home:tourneyCollapsed` deliberately doesn't match it). Don't add a bare `packsink:home:` prefix to that list or every home preference resets on the next `AUX_CACHE_VERSION` bump.
- Persistence is **per browser (localStorage), not per account** — these aren't in the `user_metadata` prefs-sync effect, so picks don't follow a signed-in user across devices.

## Mobile top-nav

Whole top bar is a single horizontal scroll container on phones (`overflow-x: auto`). Logo is `position: sticky; left: 0` so it stays pinned to the left edge. Tabs + username pill + theme toggle all scroll together → reclaims width that was previously fixed-right cluster space.

Settings popover is force-pinned to `position: fixed; top: 56px; right: 8px` on mobile so the parent `overflow-x: auto` doesn't clip it (CSS spec forces overflow-y when overflow-x is non-visible).

## Translucent popovers — `--bg-card` vs `--bg-modal`

**`--bg-card` is translucent in dark mode** (`rgba(255,255,255,0.06)`). Don't use it for modal/popup backgrounds — they're unreadable in dark mode. Use **`--bg-modal`** (opaque in both themes) for popovers/menus.

Audited 2026-05-24 — all menus/popovers now use `--bg-modal`: `.cards-bulk-menu`, `.price-db-batchmenu`, `.price-db-multimenu`, `.smart-suggest-pop`, `.deck-notes-popover`, `.deck-share-popover`, `.deck-view-popover`. `.home-quick-search-list`, `.collection-share-popover`, `.settings-popover` (via `--bg`), `.modal`, `.name-prompt`, `.card-detail`, `.drawer` were already opaque.

## Screener sticky NAME column

The 3rd column is `position: sticky; left: 0` with `background: var(--bg-modal)` + right-edge `box-shadow: 1px 0 0 var(--border), 6px 0 8px -6px rgba(0,0,0,0.35)`. The shadow makes other columns visually pass UNDER the sticky column when scrolling horizontally (prevents header overlap that the previous translucent `--bg-surface` background caused).

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

- categoryId 71 = Lorcana. Archive starts 2024-02-08.
- TCGCSV daily snapshot lands ~20:00 UTC.
- **`low_price` is a sticker, not a sale.** For high-value cards the lowest active listing often sits unchanged for weeks. Use `market_price` / `mkt_pct_*` for short-window (≤7d) movement; reserve `low_price` for medium-to-long windows.
- **`low_price` is ANY-condition, not NM-only.** TCGCSV mirrors TCGPlayer's `lowPrice` field verbatim, which is the lowest active listing across any condition (NM/LP/MP/HP/DMG). For a high-value card with a single LP copy listed below the NM floor, `low_price` will read like the LP listing. There is no per-condition pricing in TCGCSV's feed — TCGPlayer's public pricing API simply doesn't expose it. **Use `market_price` ("NM Market") as the NM-quality reference.** UI labels: "Low" (no NM qualifier) and "NM Market" (explicitly NM). Documented on the How It Works page so users have the same mental model.
- Low price can also be contaminated by foreign-language listings — prefer Market when in doubt, but for set-level averages the `processData` fallback means Low is more inclusive.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded URL>`. The `tcgUrl()` helper wraps every TCGPlayer link — never link directly.
- **Lorcast's API key for inkable is `inkwell`**, not `inkable`. Our column is `inkable`; loader translates.
- **The legacy graded feed (retired 2026-06-30) capped `/history` at ~1 year and was very sparse for low-liquidity cards** — which is why the graded value chart needs its backward-fill. Kept only to explain that backward-fill's existence; the API and the tables are gone (see "Legacy graded deletion").
- **Image sizes**: small (200w), normal (400w), large (734w). Use `img_normal` for tiles ≤200px; `img_large` for hover/modal/poster; `img_small` ≤80px thumbs. `img_large` NOT in catalog cache (stripped); fallback to img_normal.

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
- **01:00 UTC daily** — ETL fallback (catches today if cron-job.org outage)
- **06:00 UTC daily** — selfheal fallback
- **Sundays 22:00 UTC** — weekly Lorcast metadata refresh (stays on GH cron — once-a-week tolerates GH cron delay)

Every external ping (cron-job.org) arrives as a `workflow_dispatch` event, so the prices/graded/selfheal jobs' `if:` filters accept both `schedule` (with the matching daily fallback cron) AND `workflow_dispatch` (with the matching `inputs.job` value).

**No spam emails for "TCGCSV hasn't published yet"** — that's exit 0 in the script (normal, not failure). Only real script failures (network, RPC, etc.) email.

**For the site to show stale data**, both cron-job.org AND the GH safety-net cron would have to fail. cron-job.org alerts on failure to user email; GH cron failures surface as workflow failures.

`permissions: contents: read` is pinned at the workflow level — required when repo workflow permissions setting is anything other than "Read and write".

**Phantom-spike smoothing ETL** (`smooth_low_prices.py`, added 2026-05-30) is chained `needs: prices` after the TCGCSV daily ETL. See "Collection Value chart: phantom-spike smoothing" for details. Idempotent; safe to fire alongside cron-job.org + GH safety-net pings.

### Auth / grants

- **Required GitHub Actions secrets**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_ANON_KEY` (used as read fallback in `matview_self_heal.py` when service_role gets 403). `TCGPRICELOOKUP_API_KEY` is **no longer used** (graded feed retired 2026-06-30) and can be deleted from the repo secrets.
- **service_role MUST have explicit SELECT grants on all matviews + prices_daily** (migration 45). Missing this breaks selfheal with HTTP 403.

### PWA + caches

- **`sw.js CACHE_VERSION`** (current `packsink-v254` — 2026-06-27 audit: core libs react/react-dom/htm/supabase **+ html2canvas VENDORED same-origin under `/vendor/`** (was unpkg) to kill the CDN-outage blank-page crash ("ReactDOM is not defined" / "window.supabase.createClient" undefined in Sentry); precached in `sw.js` CORE_ASSETS at `?v=254`; `styles.css?v=254` bumped, `logo.js`/`scanner*.js` intentionally held at `?v=253` (content unchanged, so the lockstep is split — that's fine, the SW caches per exact URL). Earlier 2026-06-27: scanner OCR swap Tesseract.js → PP-OCRv3 (det+rec) via onnxruntime-web in a dedicated `scanner-ocr-worker.js` (WASM single-thread+SIMD, NO WebGPU); the 2 onnx models + `ppocr_keys_v1.txt` ship in `scanner/` and are runtime-cached (NOT precached — admin-gated/lazy); styles.css/logo.js/scanner*.js at `?v=251`, catalog cache `v45`): bump on ANY meaningful Index.html / styles.css / logo.js change. Activate handler purges old caches (`skipWaiting` + `clients.claim`) — EXCEPT `packsink-img-v1` (the deploy-surviving image cache; see "Offline support"). HTML requests are **network-first**. **Gotcha (2026-05-27):** bumping once at the start of a session does NOT invalidate later edits — the SW only re-caches when the version string changes. Bump again (or use an incognito window — the SW is registered on localhost too) when iterating heavily. The three things that must stay in lockstep: `sw.js CACHE_VERSION`, `styles.css?v=N` in Index.html `<link>` + sw.js CORE_ASSETS, `logo.js?v=N` in Index.html `<script>` + sw.js CORE_ASSETS.
- **App-shell is network-first (styles.css + logo.js), fixed 2026-05-28.** Previously these were cache-first while HTML was network-first → after a deploy that changed CSS, a returning visitor got the **fresh Index.html paired with the STALE cached stylesheet** → home-page mover tiles rendered at giant natural-image size until they hard-refreshed. Now `sw.js` serves `styles.css`/`logo.js` network-first (cache fallback only when offline), matching the HTML, so the app shell can't split across versions. **Belt-and-suspenders: the asset URLs are versioned** (`styles.css?v=N`, `logo.js?v=N` in Index.html `<link>`/`<script>` AND in the SW `CORE_ASSETS` precache list, kept in sync with `CACHE_VERSION` — currently **v181**). The `?v=N` closes the one-time transition gap on the deploy that carries an SW change: the *old* (still cache-first) SW cache-misses on the new URL and fetches fresh. Going forward the network-first behavior handles freshness, so you don't strictly need to keep bumping `?v=N`, but keeping it == `CACHE_VERSION` is the convention.
- **Catalog cache version**: `packsink:catalog:vN` (current **v45**). Bump when row shape changes, OR when forcing all users to cold-fetch. Note: `text` is STRIPPED from the cache on write to keep the 5MB quota free for aux caches — the in-memory backfill in `loadFromSupabase` (see "Smart search" — Card body text in the haystack) restores body-text search on cache-replay sessions without growing the cache. `keywords` IS in the cached rows, so bumping this version is the way to force the new keyword derivation onto existing users.
- **PWA icon refresh**: icon URLs include `?v=N` query (current **v=4**, bumped 2026-05-26 with the full-booster-pack rebake; v=3 was the bare-wordmark dark-blue rebake earlier the same day). Bump the version in both `Index.html` <link rel="icon"> entries AND in `manifest.json` whenever the icon bytes change. Also bump `sw.js CACHE_VERSION` since the SW precaches icon paths sans query string.
- **PWA icons baked from `Logos/packs-ink-logo.png`** via `scripts/rebake_icons.py` (Pillow). The script composites the full booster-pack artwork over `#0f0d20` with a 12% inset margin (keeps art clear of iOS/Android squircle masks). 6 outputs: apple-touch-icon.png (180), favicon-16/32/64.png, icon-192.png, icon-512.png. Idempotent — re-run when the source logo changes. Don't rely on `manifest.background_color` for transparent icons; iOS save-to-home-screen ignores it.
- **PWA orientation: `"any"`** (manifest.json). Installed PWAs rotate to landscape now. Was `"portrait"` which locked the orientation — dev-tools rotation emulator worked because that's a tab not a PWA. iOS users need to remove + re-add the home-screen icon to pick up manifest changes (iOS caches the manifest at install time).
- **mobile-web-app-capable** meta tag added alongside the legacy `apple-mobile-web-app-capable` tag — Chrome deprecated the apple-prefixed variant.
- **Dev server cache header**: `dev_server.py` sends `Cache-Control: no-store` on HTML/CSS/JS.

### Misc

- **Sentry browser SDK** loaded via CDN lazy-init on first error. User attribution via `Sentry.setUser`.
- **UptimeRobot** pings prod every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest.max(price_date)` on load, flashes ⚠ if > 36h behind.
- **Privacy policy**: standalone `privacy.html` at repo root (no JS — Google's OAuth verification crawler doesn't execute JS). Pretty URL `/privacy → /privacy.html` via `_redirects` + `dev_server.py`. Static `<noscript>` link in `Index.html` body for the home page's pre-JS HTML payload.

## Disclaimer

Lives only on the **How It Works** page: "Packs.Ink is an unofficial fan site. Disney Lorcana TCG is a trademark of Disney; the game is operated by Ravensburger. This site is not affiliated with, endorsed by, or sponsored by Disney or Ravensburger."

## Chicagoland Elo — Stores tab (2026-08-19)

`EloView`'s inner tabs are `leaderboard | tournaments | stores | upcoming | scout`, mirrored to `?sub=<tab>` (plus `?p=`/`?e=`/`?store=` for the player / event / store-report leaf views). Adding a tab means touching four places: `applyUrlToState`, the state→URL effect, the `.elo-innertabs` nav, and the render list. `eloUrlFor` also has to know the target or `EloLink`'s href points at the wrong view on a middle-click — it deletes `store` along with `p`/`e`/`sub` for exactly that reason. `.elo-innertabs` is `flex-wrap:wrap` — at 5 tabs it clipped on phones, and a clipped tab reads as a deleted feature.

**Stores** answers, for a chosen window of sets: how many events did this shop run, how many distinct people came through the door, how many tickets (seats) did that add up to. **It covers EVERY event we've ingested for the store — SCs, locals, league nights, drafts — not just Set Championships.** Every number is derived at render time; there is no per-store table anywhere.

- **Sources**: `lorcana_events_history` (every event a store has run) for the event count, and **`rph_event_attendance`** (migration 122, one row per person per event) for Tickets AND Fans.
- **Tickets and Fans are both about PLAYERS, and both come from the roster.** RPH defines Event Tickets as "the total number of players across all events" and Unique Fans as "individuals that have played in at least 1 event". So the attendance rows are filtered server-side to people who actually sat down — a final standing, or any recorded match (`RPH_PLAYED_FILTER`, kept identical to `played()` in `scrape_event_attendance.py` and to `PLAYED` in `report_store_tiers.py`). Tickets is the row count; Fans is the distinct people. **`lorcana_events.registered_user_count` answers neither** and must not come back: it is pre-registration frozen at the last listing before the event ran, so it misses walk-ins (a store reading ~1 ticket per event is a walk-in scene, not an empty one) and counts no-shows. `elo_matches` is likewise gone from this tab — it only covers the SC-shaped Elo ingest, so most of a store's events contributed nobody.
- **An unscraped event is reported, not zeroed.** `scanned` (from `rph_event_attendance_scans`) drives a per-row `unscanned` count rendered as a `†`; a silent zero reads exactly like a quiet week. Measured 2026-08-19: coverage is complete — 0 unscraped of 3,743 events in the four-set window.
- **The played rule is PER EVENT, with a registrations fallback — and the site-wide average is what hid the need for it.** Where an event has any recorded result, only people with results count. Where it has none, every COMPLETE registration counts instead (`rphCompleteReg`, marked `~` in the UI). Seven Out Cards took **19 registrations across 5 events including a Set Championship and entered results for none**, so the strict rule scored the shop 0 tickets and 0 fans for a season it demonstrably ran; verified against RPH directly — all 5 rosters read HTTP 200 with registrations intact. **The aggregate says the rule is fine (93% of registrations carry a result, only 8% of events dark) and the aggregate is the wrong statistic**: this is a per-store metric and the failure is concentrated, not spread — nearly every store records results and the few that don't are zeroed outright. Don't re-tighten it on the strength of a site-wide percentage. The fallback does admit no-shows for those events; that is the lesser error, since a zero reads as "this shop is dead" next to a tier bar. The two passes MUST stay disjoint (guard on the played event-id set) or every player at a normal event doubles.
- **`buildEloStoreActivity` keeps player ids PER SEASON, and never pre-counts them.** The set filter has to re-answer "how many distinct people" for any window, and that is a **union** (`eloStoreTotals`), never a sum — a regular who plays all four sets is one person. Pre-counting per store is what the first cut did and it makes the filter impossible. The tfoot shows `—` under Players for the same reason: distinct players can't be summed across stores either.
- **Attendance rows carry no store or season of their own**, so a person only counts once their event survived the history pass (tracked store, not storeless). A guest plays without an account, so `rphPersonKey` falls back to the lowercased display name — without the case fold one regular becomes several.
- **Season columns are derived, newest first** — ordered by each season's earliest event date, labelled with the set half of the season string (`"Wilds Unknown Summer 2026"` → `Wilds Unknown`) via longest-prefix match against `MAINLINE_SETS`. A new set adds a chip and a column pair on its own.
- **Default scope is the `ELO_RECENT_SETS` (4) newest sets, totals only.** Persisted at `packsink:elo:stores:prefs` as `{mode, keys, breakdown}` — the **mode** is stored, not just the keys, so a saved "Last 4" still means last 4 after the next set releases. As in the home movers' chip groups, the last active set chip can't be switched off.
- **Layout: totals come BEFORE the per-set detail.** They sit immediately right of the pinned store name so they never scroll off; expanding the breakdown appends detail to the right instead of shoving the numbers people came for off the edge. That was the first cut's bug.
- **Wide tables get `.elo-stores-wrap--wide` (a `max-height`).** A table wider than the viewport puts its horizontal scrollbar at the bottom of a 30-row table, so reaching it means scrolling the whole page past the data — a mouse user simply cannot scroll sideways. Capping the height puts both scrollbars in one viewport-sized box. Same short-viewport escape as the Screener. Only fires past the default window; at 4 sets the table fits.
- **The sticky store column must use `--bg-modal`.** `--bg-card` is translucent in the dark themes and `--btn-bg` is transparent in *every* theme, so either lets the scrolling season columns show straight through the pinned cell. Same rule as the Screener's sticky NAME column. The name clamp lives on an inner `.elo-stores-nametxt` block, not the `<td>` — `table-layout:auto` treats a cell `max-width` as a hint.
- Store names link to the gated store report only when `can_view_store_report()` passes; everyone else sees plain text. The tab itself is public — it aggregates data the Tournaments tab already lists per-event.
- **RPH tier verdicts (`RPH_TIERS` / `rphTierFor`)** are the doc's published bars over "the four most recent set seasons" — Standard 25/25/250, Legendary 50/50/500 (events / unique fans / tickets). All three are scored now that Fans is a real head count. The window still matters — three sets can't clear a four-set bar and ten sets clears it trivially — so the legend warns when the selection isn't four sets rather than blanking the column. The **Prerelease requirement is NOT scored**: `Pre` counts sets the store ran a prerelease for, but not which sets RPH considered available to it, hence the asterisk.
- **The pro-rated lens scores ONE season, not the selection.** The memo's 8/8/80 is 1/6 of Legendary over a two-month window — one set season's worth of activity, not four — so applying it to a four-set window cleared it for everybody. `eloProSeasonKey` picks the most recent *completed* set (seasons are newest-first; index 0 is the set still running) and the lens overrides the set chips while it's on, so the numbers shown and the verdict come from the same window.
- **Guarded by `node scripts/test_elo_store_activity.mjs`**, which extracts `buildEloStoreActivity` + `eloStoreTotals` out of Index.html so they can't drift. Run it after touching the pivot or the rollup.

## Upcoming-events finder (home "Upcoming near me" box)

`UpcomingSCsBox` (Index.html). ZIP/postal + radius + optional date, three modes: **All / Set Champs / Prereleases**. Reworked 2026-07-30 so **All means literally every Lorcana event RPH lists** — locals, league nights, draft nights — not just the two classified subsets.

- **One table, one query.** All three modes read `lorcana_events` through the `get_nearby_lorcana_events(lat, lng, radius_mi, kind, max_series, max_occurrences)` RPC; a mode is just the `kind` filter. Before, "all" merged two tables client-side, so a mis-classified event could appear in one tab and not the other. `p_kind` is `null` for All.
- **Results are SERIES, not events.** 68% of upcoming events are the same weekly repeating (measured 2026-07-30: 4050 of 5953 in a 3-week window), so Los Angeles at 50mi is ~1.8k rows but only ~58 real listings. The RPC groups and the tile reads "Every Thu 6:00 PM · 4 upcoming ▾", expanding to the individual dates. Grouping server-side is deliberate — client-side would ship a half-MB of near-duplicates to a phone.
- **Series key = store + kind + format + local weekday + local start time.** Explicitly NOT the title: stores stamp the date into it ("7/30/26 Lake Forest Lorcana Core Constructed Thursday"), which would split every weekly into one-offs. A genuine one-off is just a series of length 1. Cadence itself is re-derived client-side from the real dates (`scCadence`) so a biweekly isn't mislabelled weekly; irregular spacing falls back to "N dates".
- **Pins and the modal are per-series / per-occurrence.** `packsink:scPinned` now holds `series_key` strings (was event ids — old numeric pins simply stop matching, which is the intended lapse). The modal takes `{series, occ}`: venue/format/geo from the series, date + entry + capacity + the registration link from the one date clicked.
- **No date ceiling.** The RPC returns everything upcoming; series collapsing is what makes that readable. `p_max_series` caps at 400 listings, `p_max_occurrences` caps each series' expanded date list at 24 (`occurrence_count` stays the true total).
- **Deep links**: `?sczip/scc/scdist/scdate/scmode`. `SC_DEEP_LINKED` gates force-rendering the box when the home panel is hidden — `scmode` was missing from that list until 2026-07-30.
- **`safe_local_ts(ts, tz)`** wraps `at time zone` so one malformed RPH timezone can't fail the whole query.

**Discovery: `scripts/elo/discover_events.py`** (daily, `.github/workflows/discover_scs.yml`). ONE scan of the ~17k-row upcoming index → classifies every event → writes both `lorcana_events` (all kinds) and `set_championships` (SC subset, unchanged, because the Elo pipeline binds to that table). Replaced two full scans of the same index.

- Classification is **imported, not reimplemented**: `is_sc()` from `discover_wu_scs.py`, `classify()` from `discover_prereleases.py`. Everything both reject is `kind='other'`. Those two scripts stay on disk — they own the logic and still work for targeted single-set re-pulls.
- **Gate the prerelease classifier on `via`, never on the returned set name.** `classify()` returns `(None, "name")` for "definitely a prerelease, but I can't tell which set" — the NORMAL case outside a launch window, where `fetch_launch_sets()` is empty so there's no default set. Gating on the name demotes clearly-titled prereleases to `other` (6 live events on 2026-07-30: "Second Chance PreRelease (Sealed)", "Hyperia City PreRelease", …). `set_name` is nullable for exactly this. `discover_prereleases.py`'s own `main()` still has the bug — it only ever hid because `prerelease_events` was written during launch windows and never pruned.
- **RPH's own `event_type` cannot do this job** — it reads `LOCALS` for ~99% of events (1972 of the soonest 1991, measured 2026-07-30). Same for `gameplay_format`: an SC and a league night are both Core Constructed.
- `set_name` stays **NULL for `kind='other'`** unless the title names a set. A Thursday league night belongs to no set and must not claim one.
- **Past events are ARCHIVED, not deleted (migration 121).** `archive_past_events()` copies every already-happened row into `lorcana_events_history` before the sweep touches it, and **the sweep is skipped entirely unless that archive succeeded** — including when the table doesn't exist yet, in which case past rows just accumulate in `lorcana_events`. Delete-then-archive would strand them permanently: RPH's feed is `display_statuses=upcoming`, so nothing can re-pull an event that already happened. This is what makes "every event this store has run" answerable at all — **RPH store tiers score Total Events / Unique Fans / Event Tickets over the four most recent set seasons across EVERY event type**, and `elo_events` can't answer it (it's the curated, SC-shaped, hand-compiled Elo ingest, driven by `season_files/*.xlsx`, not by discovery). `registered_user_count` IS the Event Tickets metric — but it's frozen at the last pull that saw the event listed, i.e. roughly the day before, so treat it as a floor, not a final count. **It does not backfill** what earlier sweeps already deleted; recovering that depends on whether RPH will serve past events at all (`scripts/elo/probe_rph_history.py`, read-only, must run somewhere that can reach `api.ravensburgerplay.com`). `HISTORY_COLS` in the script and the column list in migration 121 are a straight copy — add to one without the other and the archive silently drops the column. Guarded by `python scripts/elo/test_events_archive.py` (stubbed HTTP, no network): ordering, the skip-on-failure modes, paging, and the column contract.
- **Pruning (new).** Every upsert stamps `last_seen_at`; after the pull, upcoming rows this run didn't see are deleted, plus rows older than 30 days. Guarded by `MIN_PULL_ABSOLUTE` (4000) **and** `MIN_PULL_RATIO` (70% of the upcoming rows on file) — a partial pull from a network flake must never mass-delete live events. `--no-prune` skips it entirely. The two subset tables never pruned, which is why stale SCs accumulated.

## Swiss simulator (`/lab/swiss`) — unlisted, added 2026-08-20

Monte Carlo odds for Lorcana Swiss events. **Standalone `swiss.html`, NOT part of the SPA** — the
engine is ~15KB of hot loop that no ordinary visitor should download, and keeping it out of
Index.html avoids fighting the concurrent-session churn there. Links `styles.css` for tokens, so
all seven themes work with no extra CSS, and reuses Index.html's pre-paint theme boot verbatim.

- **Route**: `/lab/swiss` → `swiss.html`, rewritten in BOTH `worker/index.js` (prod) and
  `scripts/dev_server.py` (local). Listed in `build_dist.mjs`, `Disallow`d in robots.txt, `noindex`
  in the head. "Hidden" here means undiscoverable, **not access-controlled** — anyone with the URL
  can load it. Don't put anything sensitive on it.
- **The Analytics embed only works because `_headers` carries a `/swiss` rule** detaching the
  site-wide `X-Frame-Options: DENY` + enforced `frame-ancestors 'none'` and re-setting them to
  SAMEORIGIN / `'self'` — the `/*` block refuses framing even from packs.ink itself, which
  rendered the iframe as the gray broken-page icon on prod until 2026-08-21. Local dev never
  shows this (dev_server.py doesn't apply `_headers`) — verify framing changes with
  `npx wrangler@4 dev`, which applies the file like prod. Any NEW same-origin iframe surface
  needs the same carve-out, and the parent side needs `frame-src 'self'` (already in the
  report-only policy) or enforcement will block it from the other end.
- **The engine is one self-contained `swissEngine()`** stringified into a Blob worker, so the
  worker and the main-thread fallback literally run the same text and can't drift. Flat typed
  arrays, not an object per player; counting sort into point brackets; the intentional-draw
  guarantee check reads a precomputed suffix histogram, making it O(1) instead of O(N) per pairing.
  Benchmarked **9.5x the reference tool** (databorn.ink) at 256p/8r, and it uses up to 8 workers.
- **Odds come from pooling every simulated player who held your record**, not from tracking one
  player — under equal skill they're interchangeable, so a 10k-sim run yields ~10^5 samples per
  record instead of ~10^4, and changing your record re-reads the pool with **no re-simulation**.
  This is also why the numbers are path-aware: a 4-1 who loses cuts ~16% while 4-2 overall cuts
  ~6.7%, because their tiebreakers are better.
- **Guarded by `node scripts/test_swiss_engine.mjs`** (extracts the real engine out of swiss.html,
  house pattern): Swiss-triangle exactness at 64p/6r, conservation across odd fields/drops/IDs/tiers,
  flagship ID behavior (the 5-0 pair always IDs into 5-0-1 and cuts), tie-inclusive tier payouts,
  and determinism. Run it after touching the engine, pairing, ID rule, or sharding.
- **Reproducibility is exact, cross-device — keep it that way.** The run is split into a FIXED
  ≤16-shard plan (`shardPlan`) with seeds derived from the shard index, workers pull shards off a
  queue, and results fold IN SHARD ORDER. Counts are exact in f64, but the tiebreaker accumulators
  are float sums, so fold order is part of the guarantee — folding on arrival order (or splitting by
  `hardwareConcurrency`, as v1 did) makes the same Copy link give different numbers on a 4-core
  phone vs an 8-core desktop (measured: 137026 vs 137027 vs 136949 for one cell).
- **The ID guarantee counts the OPPONENT as a threat** when the post-draw opponent can still tie or
  beat you (`bMin` floor in the engine) — a same-bracket opponent ties you forever, and excluding
  them let knife-edge pairs "safely" draw each other into a 9th-place tiebreaker. Ties with third
  parties already counted (>= not >). Don't simplify either away.
- **`pct()` only says 100%/0% when literally every/no sample hit** — near-certain values render as
  >99.9% / <0.1% bands. On a draw-safety tool, rounding 99.5% up to "100%" is the one dishonesty
  that matters.
- **A click during a run queues one rerun** (`PENDING` in run()/done()) — the IDs seg and tier
  toggle update visually on click, so dropping the request would leave the UI disagreeing with the
  results forever.
- **The theme toggle is transient when the stored mode is "system"** (attributes only, no
  localStorage write), matching the main app's deliberate system-mode semantics. Explicit
  light/dark persists to the shared keys.
- **Drops default OFF on purpose.** They're supported, but modelling attrition removes dropped
  players from the conditional pools (64p/6r at 3 losses halves the sample), which makes losing
  records read "no data". The threshold list is regenerated from the round count — you can't lose
  an eighth match in a seven-round event.
- **Prize tiers (toggle, off by default)** cover payouts past the cut — Nats cuts to 16 but 32 and
  64 also collect. They are **tie-inclusive**: a tier's cutoff is the point total of the player
  sitting at that placement, and everyone level with them is paid, so "Top 16" pays ~18 people at
  136/8. That rule is also why it needs no sorting — the final-points histogram answers
  `pts >= cutoff` directly. The **cut stays strict** (only N enter the bracket), so the two numbers
  differ on purpose: a 6-2 at 136/8 makes the cut 77% of the time but takes Top-16 prizing 100% of
  the time. Every surface that shows both must label them or it reads as a bug.
- **There is deliberately no on-the-play setting.** If who plays first is a coin flip, a first-player
  win rate of w makes each match 0.5w + 0.5(1-w) = 0.5 regardless of w, so it cannot move any output.
  Verified empirically at 50/55/60/70% — identical record distributions. It was removed rather than
  left as a knob that appears to do something. A real version would have to model winning the die
  roll more often than half the time, which the pooled-odds design can't express.
- **No awarded-byes setting either.** A bye for one player is statistically invisible once the odds
  pool the whole field, and a bye is just a win for record purposes. The meaningful version is
  "N players receive a first-round bye", which changes the field's point spread — not built.
- Every match is 50/50 — this measures bracket structure, not decks. Say so in any UI copy.
- Not built: PlayHub standings import. It needs a server-side fetch (PlayHub is CORS-blocked); the
  Cloudflare worker is the natural place, mirroring the existing `/img-proxy` pattern.

## Stream ticker (`/ticker`) — OBS overlay, added 2026-08-21

Built for streamers (vVonderland's Discord ask): a scrolling bottom-of-stream bar of the top
%-movers. **Standalone `ticker.html`, NOT part of the SPA** — same reasoning as swiss.html, plus
an OBS Browser Source should not boot the whole app. `?bar=1` renders ONLY the bar (transparent
page, every size keyed off `--tkh` = bar height, so the streamer scales it purely by sizing the
OBS source); without it the page is a configurator with live preview + "Copy overlay URL".

- **Route: `/ticker` has NO worker route on purpose.** Workers Assets' pretty-URL handling serves
  `ticker.html` for it through the asset fall-through with the query intact. Do NOT add a worker
  route that fetches `/ticker.html` — the assets layer 307s that to `/ticker` and DROPS the query
  string, and `?bar=1&…` IS the overlay's configuration (this is the same 307 that moved swiss to
  `/swiss`). Dev route in `dev_server.py`; listed in `build_dist.mjs`; robots-disallowed + noindex
  (shared by link, not nav-linked). No sw.js involvement — the page never registers it and OBS's
  browser profile never visits the SPA.
- **The reel is SECTIONS, cycling (windows × rarity groups)** — reworked same day on Zaven's
  feedback. `buildTickerPlan(cfg)` emits one section per (time frame × group) in window-major
  canonical order, each introduced by an IN-REEL header ("1D Risers" over the group name) — the
  brand cap is just logo + "packs.ink", no window label. Groups mirror the home movers banners:
  Chase (Enchanted/Epic/Iconic) · Rare – Legendary · Promos · All Rarities. Defaults: 1D + 1W ×
  Chase + Rare–Legendary, risers, **NM Market basis** (Low sits frozen for weeks and would lie on
  short windows), 15 cards/section, **$5 floor** (user-settable; keeps 10-cent cards' +300% "moves"
  out — matches the Screener's default).
- **Data**: one PostgREST query per (section × direction) against `price_movers`, server-side
  `order={pct_col}.desc&limit=n` — never the full 5.8k-row matview on a stream machine. Params:
  `w`/`g` (csv, canonical-order sets), `foil=0`/`nf=0`, `m/dir/n/min/img/brand/speed/bg/fg` — the
  URL is the whole config, so a pasted OBS URL is set-and-forget. A failed query drops only its
  own section for the round and retries in 60s — an already-rendered strip is never blanked.
- **Refresh = once a day at 5:00 PM America/Chicago** (`nextTickerRefreshMs`, pure layer):
  prices change once daily (ETL 20:30 UTC ≈ 3:30 PM Chicago), and Zaven wants exactly one safe
  post-ETL check, not polling. Intl supplies Chicago's wall clock so DST is handled (CDT/CST both
  covered in the guard test); the initial page load still fetches immediately, and failed fetches
  retry in 60s. Don't turn it back into an interval.
- **The "powered by packs.ink" credit is REQUIRED** — flush bottom-RIGHT on the bar (a 22%-of-
  `--tkt` bottom row with NO band or border, right padding `min(24px, 30% of --tkt)` so it hugs
  the corner at any bar height; the movers row gets the rest as `--tkh`), always rendered, no
  param, no checkbox; the left cap (PACKS.INK stacked over the logo) is the optional one
  (`brand=0`). That attribution is the price of a free overlay riding our data — keep it. In
  transparent mode the credit sits in its own scrim pill.
- **Double-clicking ticker.html from disk works** — that's how Zaven first tested it. Asset URLs
  are RELATIVE (file sits at site root, so they resolve the same at `/ticker` and on `file://`);
  on file:, card art hotlinks cards.lorcast.io directly (no /img-proxy route exists), the Copy URL
  is forced to `https://packs.ink/ticker` (a file:/// URL pasted into OBS breaks for anyone else),
  and `history.replaceState` is try/catch-guarded. Chip active-state styling carries hard token
  fallbacks + `!important` so toggles stay legible even with styles.css missing. No theme-toggle
  button (removed as confusing — the page follows the saved/system theme via the boot script).
- **Foil/Non-Foil toggles carry the Screener's chase bypass**: single-printing rarities
  (Enchanted/Epic/Iconic/Promo) ignore the printing filter — enforced server-side via
  `or=(printing.in.(…),rarity.in.(bypass))` on mixed groups, and by skipping the filter entirely on
  all-chase groups, else "non-foil only" silently empties every chase section. Verified live: the
  quoted in-lists inside `or=()` are valid PostgREST.
- **Marquee**: one `.tk-seq` duplicated until it spans ≥2 viewports, then `translateX` by exactly
  one sequence width, linear infinite — that equality is what makes the loop seamless. Duration =
  seqWidth / speed so `speed` is true px/s at any bar height. Thumbnails get explicit
  `aspect-ratio:5/7` + height so layout doesn't shift as images load (the measured width feeds the
  animation). Re-measures on resize and `document.fonts.ready`.
- Items render via `createElement` + `textContent` (card names are DB text — no innerHTML), as a
  3-line stack — name / version / rarity pill — with the price and its Δ%+arrow stacked to the
  right. **The rarity pill says "· Foil" ONLY for base-rarity foil variants** (`tickerRarityLine`
  owns the rule): chase rarities (Enchanted/Epic/Iconic/Promo) are inherently foil and never say
  it, and "Holofoil"/"Holo" never appear on this surface (TCGCSV's Holofoil label covers what are
  physically cold-foil printings — the holofoil-mislabel rule). `bg=transparent` keeps a
  translucent scrim on the brand cap and section headers so they stay readable over gameplay.
- **Guarded by `node scripts/test_ticker_query.mjs`** (extracts `parseTickerCfg` +
  `buildTickerPlan` + `tickerRarityLine` out of ticker.html, house pattern): section ordering +
  header text, window/metric → real matview column names, group rarity filters, foil-toggle
  bypass shapes, the rarity-line foil rule, both-mode split, min=0 not-null guard, clamps. Run it
  after touching the config layer.
- Not built: sealed products (client-computed in the SPA, no matview), per-card deep links from
  the bar, a nav/Toolbox entry (needs an Index.html touch — do it with a regular cache-bump batch).

## Brand assets

- `Logos/` ships at runtime.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons.
- `Logos/rarity/{common,uncommon,...}.svg` — 9 rarity icons (added 2026-05-23).
- `Logos/packs-ink-logo.png` — site wordmark (top bar @ 60px height, footer @ 48px).
- `Logos/Logo on Black.png` — Ink & Lore logo (base64-embedded as `LOGO_B64` in logo.js). **Removed from the footer 2026-08-21 (user request)** — logo.js still ships (SW-precached, boot-order sentinel), just nothing renders it.
- `Logos/PacksInk.ai` + `Logos/PacksInk.pdf` — source files for the commissioned wordmark (not used in deploy).
- Custom SVG glyphs: `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` (shared `<HexFrame/>`).

## Pending / roadmap

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

**Migration ledger (drops need a human — the auto-mode classifier refuses `DROP TABLE` / `DROP MATERIALIZED VIEW` through automation, so agents stage the SQL and Zaven pastes it):**
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
- **Card scanner** — SHIPPED as a public beta 2026-08-04 (see "Card scanner" above). Remaining: measure ✓-row precision against the 95% bar on real public traffic, then decide on `SCANNER_QA_ONLY`; on-device detection tuning; foil/glare reads.

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
