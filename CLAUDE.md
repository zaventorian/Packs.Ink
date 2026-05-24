# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## Stack

- **Frontend**: `Index.html` + `styles.css` + `logo.js`, React via `htm` template literals, no build step. Served by `python scripts/dev_server.py` (port 8766 — AnkiConnect squats 8765). Prod is **Netlify free tier**. Domain at Netlify; transfer to Cloudflare blocked until 2026-06-08 (ICANN 60-day lock). CSS extraction is deliberate for caching + editor sanity — do NOT inline CSS back into Index.html.
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog**: `cards`, `sets`, `prices_daily`, `sealed_products`, `graded_prices_daily`.
  - **User**: `profiles` (carries collection-sharing visibility + share_token cols), `collection_items`, `sealed_collection_items`, `graded_collection_items`, `graded_collection_goals`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`, `screener_views`.
  - **Tournament**: `tournaments`, `tournament_decks`, `tournament_admins`, view `tournament_results_v` (security_invoker on).
  - **Matviews**: `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`, `graded_prices_latest`.
- **ETL** (`.github/workflows/etl.yml`):
  1. `scripts/etl_tcgcsv_daily.py` — TCGCSV → `prices_daily`, then refreshes the 4 raw-price matviews. Idempotent: skips fetch when today's snapshot is already loaded; exits 0 (not error) when TCGCSV hasn't published yet (>95% byte-identical to yesterday's).
  2. `scripts/etl_tcgpricelookup_daily.py` — TCGPriceLookup Trader tier → `graded_prices_daily`, refreshes `graded_prices_latest`. Chained `needs: prices`.
  3. Weekly Lorcast metadata refresh: Sundays 22:00 UTC.
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed catalog**: `scripts/load_sealed_products.py`.
- **MCP**: `.mcp.json` configures Supabase MCP server (`mcp.supabase.com/mcp?project_ref=...`). Loads on session start; gives the agent direct DB query/mutation access without paste-back.

## Top-level nav

`Home · Screener · Price Graphing · Analytics · Cards · Collection · Decks`

- **Screener** = sortable financial-database table (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface.
- **Price Graphing** = per-card history + multi-card Compare (handoff from Screener batch action).
- **Analytics** = umbrella for calculator-y tools (EV, Card Averages, Playset Cost, Heatmap, Sealed, Simulate).

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- **Catalog key**: `packsink:catalog:vN` (currently **v40**). Bump N whenever cached row shape changes — old entries silently ignored on version mismatch. 24h TTL with background refresh.
- **Freshness probe** (added 2026-05-24): every page load with a "still fresh by TTL" cache fires a single-row query against `card_prices_latest` for `max(price_date)`. If server > cache's stored `latestDate`, cache is invalidated and refreshed. Means daily visitors see today's prices within seconds of opening the site after the ETL, not 24h later.
- **Visibility re-probe**: `visibilitychange` + `pageshow` listeners re-run `loadFromSupabase` when the tab/PWA becomes visible again (throttled 60s). Without this, PWA users who background the app would see stale data forever on resume — React tree never remounts.
- **`img_large` is STRIPPED from catalog cache on write** (writeCache `slim = rows.map(({img_large, ...rest}) => rest)`). Saves ~30%. Sites that prefer it (deck poster, hover preview, detail modal) fall back to `img_normal` gracefully. Don't add img_large back — the 5MB quota is tight.
- **writeCache does three-pass eviction**: (1) `removeItem` before `setItem`, (2) on failure evict every other `packsink:*` key except auth/prefs, (3) retry.
- Per-view caches use `readJsonCache(key, ttlMs)` / `writeJsonCache(key, data)`:
  - `packsink:movers:v1` (12h), `packsink:screener-movers:v1` (12h), `packsink:following:v1:{uid8}` (30min), `packsink:home:tourneys:v1` (2h), `packsink:hist:v1:{pid}:{printing}` (12h), `packsink:sealed:v1`, `packsink:setsMeta:v1`, `packsink:colvalue:v2:{uid8}:{productsHash}:{rangeKey}`.
  - `packsink:setsMeta:v1` fetched on EVERY page load via independent useEffect (not bundled with catalog Promise.all) — `loadFromSupabase` returns early on fresh cache which would leave setsMeta empty and break home box-price + prerelease guard.
- **writeJsonCache QuotaExceededError eviction** drops `packsink:hist:` first, then home banners, then sealed. Catalog is NOT in this list (most expensive to rebuild).
- Quota ~5MB. Min rows for catalog: 4000.
- **Symptom of quota exhaustion**: cache writes fail silently, every visit cold-fetches, per-view banners "unload" on tab switch. Diagnostic: `Object.entries(localStorage).reduce((s,[k,v])=>s+v.length,0)/1024/1024`.

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
- **Long-running RPCs need explicit `statement_timeout`.** Every refresh function pins `set statement_timeout = '5min'`.
- **When recreating a matview, re-grant SELECT to every role that needs it.** `grant select on X to anon, authenticated, service_role`. service_role does NOT inherit implicitly. Migration 45 retroactively grants on all 5 price matviews + prices_daily after a missing service_role grant broke the selfheal job on 2026-05-23.
- **Views authored as the dashboard user are SECURITY DEFINER by default** — triggers `0010_security_definer_view` linter alert. Create with `with (security_invoker = on)`.
- **`information_schema.role_table_grants` does NOT include matviews.** To check matview grants, use `has_table_privilege('role','public.matview','SELECT')` against `pg_matviews`.

## Auth state gotcha (do NOT regress)

**`sbClient.auth.updateUser()` fires an auth-state-change after every call**, creating a new `user` object reference. A `useEffect` syncing user_metadata via `updateUser()` with `user` in its deps → infinite loop throttled only by debounce. Supabase rate-limits `/auth/v1/user` quickly (429); the auth lock then stalls every other query.

The prefs-sync effect in `App.jsx` (writes `{theme, tipsEnabled, avatarCardId}`) omits `user` from deps and uses `prefsHydrated.current`. Symptoms of regression: catalog fetch takes minutes, "Loading price database…" forever, every tab switch cold-loads.

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
9. **`CHINA_ONLY_NONFOIL`** — `{name|cn: image path}` for non-foil printings that exist only in China. Currently Dragon Fire #25, Let It Go #41. Gets `variant_label: "Chinese Exclusive"`, null prices, local image.
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
- **Classification soft match** — card qualifies if EITHER classifications include the word OR product name includes the word. Without this, "elsa spirit" zeroes out (Elsa - Spirit of Winter has no Spirit subtype). Other dimensions stay hard.
- **Enter key does NOT auto-apply the first suggestion.** `suggestIdx` starts at -1; only arrow keys / hover arm a suggestion. Pressing Enter on free text just commits the typed query (fuzzy matching). Prevents accidental "contains" chip conversion.
- Catalog must have `cards.strength / willpower / lore / move_cost` columns (migration 43). Cold load probes for `lore`; silently omits all four from `CARDS_COLS` if missing.

## Cards browse filter dimensions

Drawer + toolbar quick-filter chips (icon-only on toolbar):
- Ink (6 colors + Inkable/Uninkable hexes)
- Cost (1-9+ hex buttons)
- Rarity (9 icon-only buttons using `RARITY_ICONS`)
- Legality (Core / Infinity — mutually exclusive toggle)
- ✓ Owned (filters to groups where any printing has `collection[card_id:printing] > 0`)

Drawer-only: Strength / Willpower / Lore (numeric buckets), Type, Set, Keywords, Classifications, Artist.

## Screener saved views

`screener_views(user_id, name, payload jsonb)` — owner-only RLS. Hydrated on sign-in (newest-first); local-only views migrated up on first sign-in if remote table empty. Writes mirror to localStorage for unauth fallback. If migration 44 not deployed (PostgREST 42P01), client logs warning and stays localStorage-only.

## Graded data: `date` vs `price_date`

**Trap.** `graded_prices_daily.date` is the column. `graded_prices_latest` matview projects it as `price_date` to match `card_prices_latest`. Querying `graded_prices_daily` with `select("...price_date...")` errors 42703.

## Graded tracking goals

`graded_collection_goals(goal_id, user_id, set_id, extras_bucket, rarities[], display_name)`. **One of `set_id` or `extras_bucket` must be set** (CHECK constraint added in migration 46).

- **Regular set goal**: `set_id` populated. Tracks all cards in that set's `cardsBySetId` matching the rarity filter.
- **Extras goal**: `extras_bucket` populated with a variant_label string ("Deep Trouble" / "Palace Heist" / "Starter Deck Exclusive Foil"). Tracks all cards in `extrasCardsByBucket.get(bucket)`. UI shows these under a synthetic section "Extras & Oddities — <bucket>" via key `__extras:<bucket>`, which sorts after mainline sets.

## Graded tab — featured chart + inline expand

Card detail modal's Graded tab:
- **Top featured chart**: 12-month LineChart defaulting to PSA 10 (falls back to first available combo if no PSA 10 history).
- **Per-row sparkline buttons**: click any row's sparkline → expands a full LineChart inline beneath that row. Multiple rows can expand at once for grade-premium comparison.
- Helper: `buildGradedSeries(history, grader, grade, label)`. Color map: PSA red, CGC blue, BGS purple, SGC green, TAG orange.

## Set conventions

- **`MAINLINE_SETS`** = booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Playset Cost, Price Graphing, Card Averages, Heatmap, Home "newest set".
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. `reverse()` puts mainlines on top.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased. Drives Core Constructed rotation.
- Decks pick up format automatically (`checkDeckLegality`): core-legal sets → "Core Constructed"; structurally legal → "Infinity"; otherwise → "Invalid Deck".

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

## Deck sharing model

Three visibility states, each with a 22-char URL-safe `share_token` (~128 bits):

| Visibility | Direct read RLS | URL behavior | Discovery |
|---|---|---|---|
| Private | owner only | none | excluded |
| Unlisted | owner only | `?deck=<id>&token=<x>` works | excluded |
| Public | owner OR anyone | `?deck=<id>` works | included |

- Non-owner reads of unlisted decks go through SECURITY DEFINER `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` RPCs (token-gated). **The RPC's RETURNS TABLE must include every column the client reads.** Migration 30 added `youtube_url` via drop-and-recreate.
- Flipping a deck TO Private auto-rotates the share token via `rotate_share_token_on_private` trigger. Every in-the-wild URL stops working instantly.
- Owner-only `regenerate_deck_share_token(uuid)` RPC for manual revocation.
- Favorites of unlisted decks store the token at favorite-time (`deck_favorites.share_token`); rotation drops the favorite gracefully.
- Discovery surfaces: Favorites, Following (user_follows), Discover (all public, cursor-paginated), Creator profile (`?user=<uuid>`).
- Aggregate metrics via SECURITY DEFINER RPCs (`deck_favorite_counts(uuid[])`, `deck_view_counts(uuid[])`) return totals only.

## Collection sharing

Mirrors deck sharing but with three independent visibility axes (raw / sealed / graded). `profiles.collection_raw_visibility` + `collection_sealed_visibility` + `collection_graded_visibility` + shared `profiles.collection_share_token`.

- Non-owner reads always go through SECURITY DEFINER RPCs (`get_shared_collection_raw/sealed/graded(uuid, text)`). Direct table reads stay owner-only via RLS.
- `get_collection_visibility(uuid, text)` returns the three per-section booleans.
- One token across all three sections; trigger rotates when all three go private simultaneously.
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
- **Home Tournament Results banner** below Following. Top 4 decks per tournament, newest first, capped 16 total.

## Deck view / edit modes

Click own deck → defaults to **view** (no card browser, no rename); toolbar has **✎ Edit** toggle. Brand-new decks open straight into edit.

- `DecksView` uses `openDeckInMode(id, "view"|"edit")`. Click → "view"; createDeck → "edit"; duplicate → "view".
- Owner controls (Share/Duplicate/Delete/Export) gate on `isOwnDeck`. Import + rename + Saved + CardBrowser gate on `!readOnly`.
- Three list layouts (View ▾): compact list, image grid, stacked pile.

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

## Artist Alley poster

`window.open` opens a self-contained poster in a new tab. Plain `<img>` tags + same-origin `/img-proxy/*` for Lorcast art (canvas exports work cleanly).

- **`.brand-footer`** at bottom with Packs.Ink logo (110px) + "packs.ink" wordmark. Stays visible in screen + print + html2canvas capture.
- **Copy as Image**: html2canvas → single tall PNG → clipboard.
- **Save JPG**: html2canvas → adaptive scale + q=0.85 → recompress (q=0.78 → 0.55) until under 9.5MB (Discord cap).
- **Print PDF path** preserves dark poster via `print-color-adjust: exact`. `break-inside: avoid` on figures. Pinned to 6 cols via `!important` in `@media print`.

## PWA install nudge

Auto-opens `InstallHelpModal` on visits 2 and 3 (counter at `localStorage["packsink:installVisits"]`). Skipped on visit 1 (no ambush), and entirely when already standalone, on desktop, or after the user clicked "Don't show this again" (`packsink:installDismissed`).

Modal accepts `onDismissForever`; only passed on visit ≥3 so the dismiss link appears the second time the modal pops.

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
- Low price can be contaminated by foreign-language listings — prefer Market when in doubt, but for set-level averages the `processData` fallback means Low is more inclusive.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded URL>`. The `tcgUrl()` helper wraps every TCGPlayer link — never link directly.
- **Lorcast's API key for inkable is `inkwell`**, not `inkable`. Our column is `inkable`; loader translates.
- **TCGPriceLookup `/history` endpoint caps at ~1 year.** `period=2y`/`5y`/`all`/`max` silently fall through to a short default. They simply don't have data older than that. Confirmed via `scripts/probe_graded_history.py`.
- **TCGPriceLookup's `/history` graded coverage is sparse for low-liquidity cards** (e.g. Cinderella - Ballroom Sensation Enchanted has 0 PSA 10 entries across a year). Only cards with regular eBay PSA sales build a real history.
- **`scripts/backfill_graded_history.py --pids 510153,527802`** for targeted re-backfill. Without `--pids` walks the full catalog (~677 cards w/ graded data, ~12-15 min at 1 req/sec).
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

### Auth / grants

- **Required GitHub Actions secrets**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TCGPRICELOOKUP_API_KEY`, `SUPABASE_ANON_KEY` (used as read fallback in `matview_self_heal.py` when service_role gets 403).
- **service_role MUST have explicit SELECT grants on all matviews + prices_daily** (migration 45). Missing this breaks selfheal with HTTP 403.

### PWA + caches

- **`sw.js CACHE_VERSION`** (current `packsink-v19`): bump on ANY meaningful Index.html / styles.css / logo.js change. Activate handler purges old caches. Pre-cache uses `cache.add().catch(null)` per asset. HTML requests are **network-first**, so users get fresh Index.html every visit when online.
- **Catalog cache version**: `packsink:catalog:vN` (current **v40**). Bump when row shape changes, OR when forcing all users to cold-fetch (e.g. emergency push of fresh data).
- **PWA icon refresh**: icon URLs include `?v=2` query so browsers treat them as new resources.
- **Dev server cache header**: `dev_server.py` sends `Cache-Control: no-store` on HTML/CSS/JS.

### Misc

- **Sentry browser SDK** loaded via CDN lazy-init on first error. User attribution via `Sentry.setUser`.
- **UptimeRobot** pings prod every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest.max(price_date)` on load, flashes ⚠ if > 36h behind.
- **Privacy policy**: standalone `privacy.html` at repo root (no JS — Google's OAuth verification crawler doesn't execute JS). Pretty URL `/privacy → /privacy.html` via `_redirects` + `dev_server.py`. Static `<noscript>` link in `Index.html` body for the home page's pre-JS HTML payload.

## Disclaimer

Lives only on the **How It Works** page: "Packs.Ink is an unofficial fan site. Disney Lorcana TCG is a trademark of Disney; the game is operated by Ravensburger. This site is not affiliated with, endorsed by, or sponsored by Disney or Ravensburger."

## Brand assets

- `Logos/` ships at runtime.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons.
- `Logos/rarity/{common,uncommon,...}.svg` — 9 rarity icons (added 2026-05-23).
- `Logos/packs-ink-logo.png` — site wordmark (top bar @ 60px height, footer @ 48px).
- `Logos/Logo on Black.png` — Ink & Lore footer logo (base64-embedded as `LOGO_B64`).
- `Logos/PacksInk.ai` + `Logos/PacksInk.pdf` — source files for the commissioned wordmark (not used in deploy).
- Custom SVG glyphs: `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` (shared `<HexFrame/>`).

## Pending / roadmap

**Top of the list:**

- **Domain transfer Netlify → Name.com → (optional) Cloudflare** for WAF + Bot Fight Mode in front of Netlify. Blocked until **2026-06-08** (ICANN lock). Netlify only transfers to Name.com per their partnership.
- **Card scanner (phone)** — vision-based identification. Scan → identify → price + history.

**Nice to have:**

- Sim a pack inline button on each row in Playset Cost / Set Values.
- Deck-list cost-curve sparklines on the Decks tab list (currently only in editor).
- More Extras & Oddities curation — re-run audit scripts periodically.
- Floor-coverage indicator on Screener (1 lonely listing vs 10 sellers at the floor). Needs TCGCSV `/products`.
- Stale-data warning per row on Screener — flag rows whose `low_today` is > 3 days old.

**Quality / operational:**

- Re-run [supabase/diagnostics/index_usage_audit.sql](supabase/diagnostics/index_usage_audit.sql) once stats age past ~13 days, drop unused.
- EV % change pills can underreport for newest set (`evFromBucket` reads `rarity_avg_daily` with no Low↔Market fallback).
- Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6 in `etl.yml`.
