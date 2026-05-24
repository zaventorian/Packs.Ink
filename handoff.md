# Handoff — 2026-05-24

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-22 → 2026-05-24)

Heavy multi-theme session. Eight themes:

1. **Graded backfill** — full one-time catch-up. 3,782 historical graded snapshots inserted across 677 cards with TCGPriceLookup data. Elsa - Spirit of Winter (Enchanted) PSA 10 went from 6 days of flat history to 45 days of real movement.
2. **Graded tab visual upgrade** — featured PSA 10 chart at top of every card's Graded tab + click-to-expand inline charts per (grader, grade) row. Compare grade premiums (PSA 10 vs PSA 9) at a glance.
3. **Rarity icons everywhere** — 9 official SVGs in `Logos/rarity/`. Icon-only rarity chips in Cards toolbar + drawer + Screener + Add Set Tracking modal. Inline `<RarityTag>` helper for icon+text. Fixed the long-broken sd-row icon slot (PNG paths pointed at non-existent files).
4. **Cards browse filter UX** — strength/willpower/lore numeric buckets in drawer; ✓ Owned toggle in toolbar; Core/Infinity promoted from drawer to toolbar quick-filter row; ink+cost+rarity grouped on one row with dividers. Smart search Enter no longer auto-applies the first suggestion (was eating fuzzy queries).
5. **ETL bulletproofing** — was a single 21:00 UTC cron at the mercy of GitHub's flaky free-tier scheduler. Now 3 idempotent retry firings (21:00 / 22:30 / 01:00 UTC) + 4 selfheal sweeps. Script exits 0 when TCGCSV hasn't published yet (no more false-alarm emails). Migration 45 re-granted matview SELECT to service_role (was the 403 root cause).
6. **Catalog freshness probe** — biggest UX-correctness win. Every page load with a "still fresh by TTL" cache fires a single-row probe against `card_prices_latest`. If server has newer data, cache invalidates and refreshes. Daily visitors now see today's prices within seconds of opening the site after the ETL, not 24h later. Visibility-change listener does the same on PWA resume.
7. **Mobile + popover polish** — mobile top-nav is now one horizontal scroller (logo sticky-left, tabs + username + theme all scroll together). 5 dropdowns switched from translucent `--bg-card` to opaque `--bg-modal` (the CLAUDE.md gotcha we keep tripping on). Screener sticky NAME column got an opaque bg + right-edge shadow so headers don't overlap when scrolling horizontally.
8. **Deck poster + Artist Alley export overhaul** — Packs.Ink logo top-right + QR stacked below. Cost-curve aligns at x=0 with stats. Mobile poster export now produces desktop-layout image (was producing vertical stack). Artist Alley poster gained a 110px Packs.Ink logo at bottom-right.

Plus several smaller wins: SPLIT_BY_PRINTING_SETS phantom-tile bug (LCP C1 cards appearing in every search regardless of filter, root caused to React key collision); Dreamborn deck import format (`4 Name (3-16)`); PWA install nudge on visit 2/3; Supabase MCP server wired up.

## What landed (rough order)

### Graded backfill

1. **`scripts/backfill_graded_history.py --pids` flag** — targeted re-backfill for specific cards instead of walking the full catalog.
2. **Full catalog backfill run** — 677 cards processed, 3,782 historical graded snapshots inserted. Cards with active eBay PSA/CGC/BGS sales gained 30-90 days of real history. Thinly-traded cards (e.g. some Enchanted PSA 10s with only ~6 days of pre-existing entries) didn't change much — TCGPriceLookup's `/history` doesn't fabricate sales it didn't see.
3. **Diagnostics**: `scripts/check_graded_depth.py`, `scripts/probe_graded_history.py`, `scripts/dump_graded_history.py` for one-card audits.
4. **Confirmed upstream cap**: TCGPriceLookup `/history` maxes at ~1 year. Period values bigger than `1y` silently fall through to short defaults.

### Graded tab — featured chart + inline expand

5. **`buildGradedSeries(history, grader, grade)`** helper + `GRADER_COLOR` map (PSA red, CGC blue, BGS purple, SGC green, TAG orange).
6. **Featured chart at top of Graded tab** — full 12-month LineChart defaulting to PSA 10; falls back to first available combo if no PSA 10 history.
7. **Per-row sparkline buttons** — click any row's sparkline → full LineChart expands inline beneath that row. Multiple rows can expand at once. Active row gets a subtle bg highlight.

### Rarity icons

8. **9 SVGs in `Logos/rarity/`** — copied from commissioned set: Common/Rare/SR/Leg/Ench/Epic/Iconic = the "-Color" gradient variants; Uncommon = "-Outlined" (color version is pure white = invisible on light bg); Promo = "-Outlined" generic catch-all.
9. **`RARITY_ICONS` map** repaired — old PNG paths (`Logos/rarity/COMMON.png` etc.) pointed at files that never existed. The set-detail row's rarity icon slot was silently 404ing for months.
10. **`<RarityTag rarity= [hideText]>`** helper for inline icon+text rendering. Used in Cards browse list rows, graded picker dropdowns.
11. **`.chip-rarity-only`** class for icon-only chips. Applied in Cards drawer rarity section, toolbar quick-filter rarity strip, and Add Set Tracking modal.

### Cards browse filter UX

12. **Toolbar restructure** — removed the row-break that put inks on row 1 and costs on row 2. Now row 1 = search box only; row 2 = `[6 inks] [Inkable/Uninkable hexes] │ [cost 1-9+] │ [9 rarity icons] │ [Core] [Infinity] [✓ Owned]` + sort/filters/alley/view/count.
13. **Strength / Willpower / Lore filter buckets** in drawer (chip toggles). Matchers in `matchesCardFilter`; null stats fail any non-null filter.
14. **✓ Owned toggle** — filters to groups where `collection[card_id:printing] > 0` for any printing. Stacks with other filters.
15. **Core / Infinity** promoted from drawer to toolbar (mutually-exclusive toggles, same pattern as Inkable/Uninkable hexes).
16. **Smart search Enter** no longer auto-applies the first suggestion. `suggestIdx` starts at -1; only arrow keys / hover arm a suggestion. Enter on free text just commits the query for fuzzy matching.

### React key fix (phantom tiles)

17. **SPLIT_BY_PRINTING_SETS bug** — `groupCards()` produces two group objects per LCP C1 card (Prize Wall + Prize Foil) sharing the same `card_id`. The Cards tile map used `key=${g.card_id}` — React saw duplicate keys, picked one, **left the other orphaned in the DOM forever**. Those tiles then appeared in every search regardless of filter.
18. **Fix**: key generation now appends printing suffix for split groups: `key=${g.card_id + (g.isSplitPrinting ? "::"+(g.Printing||g.tcg_printing||"") : "")}`.

### ETL reliability rework

19. **Migration 45**: re-grants SELECT on all 5 price matviews + prices_daily to anon, authenticated, service_role. Fixes the HTTP 403 on selfheal job. `information_schema.role_table_grants` doesn't include matviews — check via `has_table_privilege` against `pg_matviews`.
20. **Idempotent `etl_tcgcsv_daily.py`** — skips fetch when today's prices_daily is already loaded (probes via single-row select). Still runs matview refresh in case it failed on a prior run. Duplicate-snapshot guard now exits 0 (no spam) when TCGCSV hasn't published yet — that's normal, not a failure.
21. **Workflow restructure** — 3 daily prices+graded firings (21:00, 22:30, 01:00 UTC) + 4 selfheal sweeps (21:30, 23:15, 01:30, 06:00 UTC). Was 1 prices + 24 hourly selfheals (which produced 22 no-op runs / day on the free-tier scheduler that often dropped triggers anyway).
22. **`permissions: contents: read`** pinned at workflow level — repo-level setting changing to "Read-only" was breaking checkout (`fatal: could not read Username`).
23. **`matview_self_heal.py`** anon-key fallback — if service_role gets 403 on a read, retries with anon key. RPC writes still require service_role; this is read-side resiliency. Needs `SUPABASE_ANON_KEY` secret in repo settings.

### Catalog freshness probe (CRITICAL UX fix)

24. **The problem**: 24h TTL meant daily visitors saw yesterday's prices for up to 24h after each ETL run.
25. **The fix**: `writeCache` now stores `latestDate` (max `price_date` from server) alongside rows. On page load, if cache is "still fresh by TTL", probe `card_prices_latest?select=price_date&limit=1` (~50ms). If `server > cache.latestDate`, invalidate and refresh.
26. **`PRICE_COLS`** updated to include `price_date` so the max can be computed at fetch time.
27. **`visibilitychange` + `pageshow` listeners** re-run `loadFromSupabase` when tab/PWA becomes visible (throttled 60s). Critical for PWA users who background the app — without this, React tree never remounted, and the probe never fired on resume.

### Mobile + popover polish

28. **Mobile top-nav** = single horizontal scroller. Logo `position: sticky; left: 0`. Tabs + username pill + theme toggle all scroll together. Reclaims width that was previously fixed-right space.
29. **Settings popover on mobile** = `position: fixed; top: 56px; right: 8px` so the parent's `overflow-x: auto` doesn't clip it (CSS spec forces overflow-y when overflow-x is non-visible).
30. **5 popovers** switched from translucent `var(--bg-card)` to opaque `var(--bg-modal)`: `.cards-bulk-menu`, `.price-db-batchmenu`, `.price-db-multimenu`, `.smart-suggest-pop`, `.deck-notes-popover`, `.deck-share-popover`, `.deck-view-popover`. Shadow bumped 0.18 → 0.35 for visual lift.
31. **Screener sticky NAME column** — bg switched from translucent `--bg-surface` to opaque `--bg-modal`. Added right-edge `box-shadow` so other column headers visually pass UNDER the sticky column when scrolling right.

### Deck poster export

32. **Logo top-right + QR stacked below** — was QR alone in top-right and a small logo bottom-left. Now logo (96px) + QR (96×96) stack vertically in the right cluster. Width 96px (was 192px side-by-side) → stats get more horizontal breathing room.
33. **Cost curve alignment** — `padL=0` on the cost-curve SVG + bar formula drops leading `gap/2`. First bar now starts flush with `x=0` of the SVG container, matching where "60 CARDS" stat starts in the stats row above.
34. **Options grouping** — was a jumbled chip strip. Now grouped: Layout (Background + Columns), Show (Stats + Cost curve), Costs (Non-Foil/Foil/Max Rarity $), Share (QR + URL footer). Share section locked when deck is private; owner clicks → switches visibility to Unlisted right from the modal.
35. **Mobile poster export** = desktop layout. Was rendering vertical-stack on phones due to a `@media (max-width:560px)` rule, which html2canvas captured as-is → users got tall thin junk PNGs. Now `min-width: 1000px` always; wrap is `overflow-x: auto` so mobile preview swipe-scrolls but the export is always the desktop layout.
36. **Bottom row simplified** — just `packs.ink · <date>` (left) + URL (right). Logo moved up to header.

### Artist Alley poster

37. **`.brand-footer`** at bottom-right with 110px Packs.Ink logo + "packs.ink" wordmark. Stays visible in screen + print + html2canvas capture (the floating action buttons get hidden in those contexts; brand footer stays).

### Deck import — Dreamborn format

38. **`parseDeckText`** now accepts the suffix `(N-CN)` where N = 1-based MAINLINE_SETS index and CN = collector number. Example: `4 Piglet - Pooh Pirate Captain (3-16)` resolves to Into the Inklands #16 even if a card with that name exists in other sets. When the suffix is present, exact lookup via `candidatesBySetCN[N|CN]` wins over name scoring. Without the suffix, existing scoring logic applies.

### PWA install nudge

39. **Auto-opens `InstallHelpModal`** on visits 2 and 3 (counter at `localStorage["packsink:installVisits"]`). Skipped on visit 1 (no ambush), and entirely if already standalone, on desktop, or after the user clicked "Don't show this again" (`packsink:installDismissed`).

### Logos + PWA icons

40. **Top-nav logo** bumped 44 → 60px.
41. **Footer** now has two logos: Packs.Ink (48px) + Ink & Lore base64 logo, in a `.footer-logos` flex cluster.
42. **Deck poster header logo** 80px (later moved to top-right).
43. **PWA icon refresh** — icon URLs in manifest + `<link>` tags include `?v=2` query so browsers treat them as new resources. Forces phone home-screen icons to refresh on next install.
44. **`Logos/PacksInk.ai` + `Logos/PacksInk.pdf`** — commissioned source files added (not used in deploy; PNG remains the runtime asset).

### Graded tracking — Extras & Oddities support

45. **Migration 46**: adds `extras_bucket text` to `graded_collection_goals`, makes `set_id` nullable, CHECK constraint enforces one of (set_id, extras_bucket).
46. **`GradedCollectionGoalModal`** — Set dropdown now includes "Extras & Oddities" (when buckets exist in catalog). Selecting it reveals a second "Extras bucket" picker with live options ("Deep Trouble", "Palace Heist", "Starter Deck Exclusive Foil").
47. **`extrasCardsByBucket`** Map (variant_label → cards) — built once from `raw`. `grouped` useMemo handles Extras goals by pulling from this map instead of `cardsBySetId`.
48. **Synthetic section bucketing** — Extras-tracked cards group under `__extras:<bucket>` set_id, render as "Extras & Oddities — <bucket>", sort to the end.

### Supabase MCP

49. **`.mcp.json`** at repo root configures Supabase MCP server. Authed via `claude /mcp` in CLI; loads on next session start.

### Migrations applied to prod (run order)

35 → 36 → 37 → 38 → 39 → 40 → 41 → 42 → 43 → 44 → **45 (applied 2026-05-23)** → 46 (needs to apply)

**Migration 46 is NOT yet applied to prod.** Apply via Supabase SQL editor:
```sql
-- paste supabase/46_graded_goals_extras_bucket.sql
```

### Cache version bumps

- **`CACHE_KEY = "packsink:catalog:v40"`** (was v37). Bumped three times during the session: v37 → v38 (rarity normalization), v38 → v39 (filter shape add), v39 → v40 (force-invalidate to push freshness probe to all users immediately).
- **`sw.js CACHE_VERSION = "packsink-v19"`** (was v5). Bumped a lot — every meaningful CSS/JS change today triggered one.

## Verified live

- Daily ETL: ran successfully today 2026-05-23 at 21:00 UTC after migration 45 + manual trigger. Selfheal job is now green-on-no-op.
- Cards browse: strength/willpower/lore filters work; Owned toggle filters correctly; Core/Infinity in toolbar function as expected.
- Phantom-tile bug: search "stitch" now returns 31 tiles in DOM matching the 31 count display (was 45 DOM / 31 count).
- Smart search: Enter on "elsa spirit" no longer auto-converts to chip; fuzzy matching takes over.
- Graded tab: PSA 10 chart auto-loads at top of Elsa - Spirit of Winter modal showing the deep history from backfill.
- Mobile top-nav: username pill + theme toggle scroll with the tabs as one row.
- Dreamborn import: `4 Piglet - Pooh Pirate Captain (3-16)` resolves cleanly to Into the Inklands #16.
- Catalog freshness probe: console logs `Catalog cache out of date (server: ..., cache: ...). Refreshing...` when cached date is stale.
- Deck poster export: cost curve aligns with stats; logo top-right + QR below; mobile export produces desktop-layout PNG.

## Useful invariants when debugging

- **Phantom tiles in Cards browse?** React key collision on SPLIT_BY_PRINTING_SETS groups. Check that the Cards tile map key formula appends printing suffix for split groups.
- **Stale prices for repeat visitors?** Freshness probe didn't fire. Console log should show `Catalog cache out of date...` when the probe detects newer data. If not, check (a) cache exists, (b) `cached.stale === false` (forces probe path), (c) probe URL returns 200.
- **PWA stuck on yesterday's data?** Visibility listener didn't refresh. Check `document.visibilityState === "visible"` event firing.
- **Selfheal failing with 403?** Re-run migration 45. Verify with `has_table_privilege('service_role', 'public.<matview>', 'SELECT')` for each of the 5 price matviews. `role_table_grants` doesn't include matviews.
- **Daily ETL failing on every retry?** Check the auth/grants chain: `permissions: contents: read` on workflow, repo Settings → Actions → Workflow permissions ≥ Read, GITHUB_TOKEN auto-injected by checkout@v4, SUPABASE_SERVICE_KEY secret exists, matview grants in place.
- **Email spam on ETL runs?** Script is exiting non-zero on a "no-op" condition. Check that the duplicate-snapshot guard exits 0 (not sys.exit with message).
- **Rarity icon missing on a chip?** Check `RARITY_ICONS[rarity]` returns a path. SVGs in `Logos/rarity/` should be 9 files: common, uncommon, rare, super_rare, legendary, enchanted, epic, iconic, promo.
- **Translucent popover in dark mode?** Used `var(--bg-card)` instead of `var(--bg-modal)`. The audited 5 popovers are all fixed but new ones may regress.
- **Graded chart shows flat line spanning days?** Card has thin history in TCGPriceLookup — they don't fabricate sales. Confirm via `scripts/probe_graded_history.py <pid> --grader psa --grade 10`. If `matched < 30`, that card just doesn't sell often enough.
- **CLAUDE.md performance warning?** This file was at 52k chars (>40k threshold) at session start. Pruned to ~35k in this handoff session. Watch the warning on session start and prune again when it returns.

## Blocked / waiting on user

- **Apply `supabase/46_graded_goals_extras_bucket.sql`** in Supabase SQL editor — Extras tracking won't work until this lands.
- **`SUPABASE_ANON_KEY` secret** — should be added to GitHub Actions secrets so the selfheal anon-fallback works.
- **Google OAuth consent screen verification** — still pending. Domain ownership via Search Console TXT record + form re-submit.
- **Domain transfer** still blocked until 2026-06-08 (ICANN lock).

## Next up (priority order)

1. Apply migration 46 (Extras goals).
2. Watch tomorrow's daily ETL fire cleanly at 21:00 UTC. If it does, the reliability rework is verified end-to-end.
3. **Card scanner (phone)** — vision-based identification. Lowest priority but most-requested feature direction.
4. Domain transfer after 2026-06-08 → Cloudflare WAF + Bot Fight Mode.
5. Bump `actions/checkout@v4` → v5 + `actions/setup-python@v5` → v6 to clear Node.js 20 deprecation warning.

## Files most recently touched

- `Index.html` — RarityTag helper + rarity icons everywhere, strength/willpower/lore filters, ✓ Owned toggle, Core/Infinity in toolbar, freshness probe, visibility re-probe, SPLIT key fix, Enter behavior, Dreamborn import, GradedPricesTab featured chart + inline expand, DeckPosterModal overhaul (logo top-right, QR stacked, cost-curve alignment, mobile fixed-width, options grouping, locked share with click-to-make-unlisted), ArtistAlleyModal brand footer, GradedCollectionGoalModal Extras bucket, PWA install nudge, top-nav logo 60px, footer logo cluster, PWA icon cache-bust.
- `styles.css` — rarity icon classes, chip-rarity-only, ink/cost/rarity grouped row with dividers, mobile top-nav single scroller, settings popover fixed positioning on mobile, opaque popover backgrounds (5 selectors), screener sticky-column shadow, .deck-poster min-width + wrap overflow, footer-logos cluster.
- `sw.js` — `CACHE_VERSION = packsink-v19`.
- `manifest.json` — icon URLs `?v=2`.
- `.mcp.json` (new) — Supabase MCP server config.
- `scripts/etl_tcgcsv_daily.py` — idempotency check + duplicate-guard exits 0 + `_refresh_matviews()` helper.
- `scripts/matview_self_heal.py` — anon-key fallback on 403.
- `scripts/backfill_graded_history.py` — `--pids` flag for targeted backfill.
- `scripts/check_graded_depth.py`, `scripts/probe_graded_history.py`, `scripts/dump_graded_history.py` (new) — graded diagnostics.
- `.github/workflows/etl.yml` — 3 daily prices crons, 4 selfheal sweeps, `permissions: contents: read`, `SUPABASE_ANON_KEY` env.
- `Logos/rarity/{common,uncommon,rare,super_rare,legendary,enchanted,epic,iconic,promo}.svg` (new).
- `Logos/PacksInk.ai` + `Logos/PacksInk.pdf` (new) — commissioned source.
- `supabase/45_matview_grants_service_role.sql` (new) — applied 2026-05-23.
- `supabase/46_graded_goals_extras_bucket.sql` (new) — **not yet applied**.
- `CLAUDE.md`, `handoff.md` — refresh (this commit). CLAUDE.md pruned from 52k → ~35k chars.
