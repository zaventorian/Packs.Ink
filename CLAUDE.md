# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## ⚠️ Push policy — NEVER push without explicit user OK

Netlify is on a metered build plan and Zaven is on limited credits. Every `git push origin main` triggers a deploy that costs build minutes. **Default behavior: commit locally, then STOP and ask before pushing.** Batch pushes to the end of a session (or across multiple sessions) so one deploy carries multiple commits.

The classifier reinforces this: even with `Bash(git push:*)` in `.claude/settings.json`, the classifier may still block individual pushes when it judges them unauthorized. Treat the rule above as the source of truth — don't try to push silently just because the rule allows it.

Exception: explicit user instruction in the current turn ("push it", "ship this", "deploy now"). Anything less = commit only and report what's staged for the next push.

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

**Two-row icon nav** (restructured 2026-05-25). Row 1 = "my stuff", Row 2 = "market intel". Home tab removed — the logo IS the home click target.

- **Row 1**: Collection · Cards · Decks
- **Row 2**: Screener · Price Graphing · Analytics · Help

Icons live in `NAV_ICONS` (Index.html) — hand-coded inline SVG (Tabler/Lucide-style line glyphs), `stroke="currentColor"` so they inherit theme color. To add/swap an icon: edit the `path` for that key in NAV_ICONS, no asset file needed.

- **Screener** = sortable financial-database table (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface. Has a prominent **Raw Prices / Graded mode toggle** (segmented buttons) above the preset chips — flips the table between TCGCSV raw + TCGPriceLookup graded data.
- **Price Graphing** = per-card history + multi-card Compare (handoff from Screener batch action).
- **Analytics** = umbrella for calculator-y tools (EV, Card Averages, Playset Cost, Heatmap, Sealed, Simulate).

### Mobile top-nav structure (do NOT regress)

- Scroll lives on `.tabs` (middle), NOT on the whole top-nav. Logo + right cluster stay anchored as flex peers.
- Right cluster on mobile is `flex-direction:column` with two rows:
  - **Row 1**: profile/sign-in pill (collapses to avatar-only on ≤640px) **+ install bubble** (📲, conditional on `!isStandalone && (isIOS || isAndroid)`)
  - **Row 2**: help bubble (?) + theme toggle bubble (🌙/☀)
- The install bubble lives in row 1 next to the profile because it **disappears** once the user installs the PWA (`isStandalone` flips true). Having it pair with the profile avatar means row 1 naturally collapses to just-the-avatar post-install, no layout shift. Putting install in row 2 (its old location) pushed row 2 to 3 bubbles wide (~116px) and tipped `ANALYTICS` off the right edge of the scrolling tabs container on phones ≤420px.
- **Help is a bubble in the right cluster's bubble row** (as of 2026-05-26), NOT a peer chip in tabs row 2. The previous "Help chip inside the tabs row" layout collided with the sign-in pill / profile chip on phones — the chip sat at the right edge of the scrolling tabs row and overlapped the anchored right cluster. Moving Help to `.top-nav-right-row--bubbles` puts it in the same flex container as install + theme, where it can't bump into the sign-in pill above it. Implemented as `<button class="theme-toggle theme-toggle--help">` (inherits bubble shape; `.active` paints accent when view=faq).
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

- **Catalog key**: `packsink:catalog:vN` (currently **v41**). Bump N whenever cached row shape changes — old entries silently ignored on version mismatch. 24h TTL with background refresh.
- **Freshness probe** (added 2026-05-24): every page load with a "still fresh by TTL" cache fires a single-row query against `card_prices_latest` for `max(price_date)`. If server > cache's stored `latestDate`, cache is invalidated and refreshed. Means daily visitors see today's prices within seconds of opening the site after the ETL, not 24h later. **When the probe detects an outdated catalog it also wipes every price-derived aux cache** (`packsink:*` except catalog/auth/install-prefs) — movers, sealed, history, setsMeta, colvalue all derive from price data and were going stale silently behind their 12h TTLs.
- **`AUX_CACHE_VERSION` sentinel** (Index.html top, added 2026-05-24): per-deploy stamp compared against `packsink:auxCacheVersion` on module load. Mismatch → one-shot wipe of every `packsink:*` key except catalog/auth/install-prefs. **Bump the string to force every existing user's next page load to refresh aux caches** — useful when an ETL/matview change makes those caches stale faster than their TTLs catch. Independent from `CACHE_KEY` (which only invalidates the catalog itself).
- **Visibility re-probe**: `visibilitychange` + `pageshow` listeners re-run `loadFromSupabase` when the tab/PWA becomes visible again (throttled 60s). Without this, PWA users who background the app would see stale data forever on resume — React tree never remounts.
- **`img_large` AND `text` are STRIPPED from catalog cache on write** (writeCache `slim = rows.map(r => { const {img_large, text, ...rest} = r; return rest; })`). Saves ~30% (img_large) + ~25% (text). Sites that prefer img_large (deck poster, hover preview, detail modal) fall back to `img_normal` gracefully. The text strip means body-text smart-search ("gets", "gains", etc.) works on the live session after cold-fetch — and on cache replay it gracefully degrades to name+type+classification matching (the matchesCardFilter haystack tolerates `row.text` being undefined). Don't add either back — initially I kept text in cache thinking 5MB had room, but it pushed sealed + movers aux caches into QuotaExceededError. The freshness probe wipes the catalog whenever the ETL has published, so most active users cold-fetch within hours of opening the site and get text-search back daily.
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

The prefs-sync effect in `App.jsx` (writes `{themeMode, theme, tipsEnabled, avatarCardId}`) omits `user` from deps and uses `prefsHydrated.current`. Symptoms of regression: catalog fetch takes minutes, "Loading price database…" forever, every tab switch cold-loads.

## Theme: 3-way mode (light / dark / system)

Two pieces of state:
- **`themeMode`** = the user's pick: `"light" | "dark" | "system"`. Persisted at `localStorage["packsink:themeMode"]` and synced to Supabase auth user_metadata.
- **`resolvedTheme`** (aliased as `theme` for back-compat) = the effective value applied to `<html data-theme>`. When mode is `"system"`, listens to `prefers-color-scheme` media query and re-resolves on change — this is how "sunset darkmode" works (OS night-shift schedule drives the pref).
- **Migration**: on first load, reads old `packsink:theme` (light|dark) if `themeMode` key absent. Both keys get written so older code paths reading `packsink:theme` still see the effective value.
- **`toggleTheme`** (top-bar bubble) flips between explicit light/dark — if currently in `"system"` mode, switches to the OPPOSITE of whatever the OS resolved to (does NOT return to system; that's an explicit pick in the settings popover).
- **`showTopBarTheme`** pref (`packsink:showTopBarTheme`): toggle to hide the quick theme bubble in the top-nav right cluster. Default ON.

Settings popover (gear/profile dropdown) has a Theme segmented control (Light / Dark / Match system) — that's the only place to choose System mode.

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
- **Classification soft match** — card qualifies if EITHER classifications include the word OR product name includes the word. Without this, "elsa spirit" zeroes out (Elsa - Spirit of Winter has no Spirit subtype). Other dimensions stay hard.
- **Partial-rarity prefix matching** via `resolveRarityPrefix(token)` (Index.html ~line 2232). Any ≥3-char unambiguous prefix of a canonical rarity resolves: `ench`/`enchant`/`enchante` → Enchanted, `leg`/`lege`/`legen` → Legendary, `epi`/`epic`, `ico`/`icon`/`iconi`, `pro`/`prom`/`promo`, `rar`/`rare`, `com`/`comm`/`common`, `unc`/`unco`/`uncom`. **Super Rare is intentionally excluded** — `sup` collides with the `super` classification subtype (Big Hero 6 Super characters). Use `sr` / `super rare` / `superrare` for that one explicitly.
- **Card body text in the haystack** — `buildRow` carries `text` from `cards.text` onto every row. `matchesCardFilter`'s name-fallback haystack includes `(row.text||"").toLowerCase()` so "gets" / "gains" / "draws" / "banish" / etc surface every card whose printed ability text says that word. Text is stripped on cache write (see "Client cache rules") so an older cached catalog silently degrades to name+type+classification matching without crashing.
- **Enter key does NOT auto-apply the first suggestion.** `suggestIdx` starts at -1; only arrow keys / hover arm a suggestion. Pressing Enter on free text just commits the typed query (fuzzy matching). Prevents accidental "contains" chip conversion.
- **`SET_NICKNAMES` deliberately does NOT include single-token character names** ("ursula", "jafar") even though the sets are "Ursula's Return" and "Reign of Jafar". Those tokens are character names too — typing `ursula` in the deck builder should search for the *card*, not promote to the whole set. The longer/unambiguous forms still work (`ursulas`, `ursulas return`, `reign`, `reign of jafar`). Set suggestion dropdown still surfaces the set via prefix match, so users can click through if they meant the set.
- Catalog must have `cards.strength / willpower / lore / move_cost` columns (migration 43). Cold load probes for `lore`; silently omits all four from `CARDS_COLS` if missing.

### Single canonical matcher: `matchesCardFilter(row, f, parsed)`

Every card-search surface in the app **must** route through `matchesCardFilter` (defined at the top of Index.html, ~line 2691). It's the only function that knows about the classification soft-match, the haystack fallback for name search, and the union of every filter dimension. Inline custom matchers will drift from the canonical behavior and produce subtle UX bugs (the "elsa spirit" / "Woody Enchanted" zero-result class of issue).

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

Drawer-only: Strength / Willpower / Lore (numeric buckets), Type, Set, Keywords, Classifications, Artist.

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

- **`graded_prices_daily` PK** (mig 49): `(tcgplayer_product_id, printing, grader, grade, date)`. The `printing` value comes from TCGPriceLookup's `variant` field on each card record — values are `"Normal"`, `"Cold Foil"`, `"Holofoil"`. Split-printing cards (TFC Cold Foil rares, LCP C1 Holofoils) appear as multiple TCGPriceLookup records sharing one `tcgplayer_id`; the ETL captures each variant as its own row instead of silently overwriting on upsert (pre-49 behavior caused foil/non-foil prices to conflate randomly).
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

`graded_collection_items.custom_value numeric(12,2)` (nullable, added migration 51). When set, the user's owned slot uses this value instead of the TCGPriceLookup eBay average — covers two cases: (a) low-volume cards with NO graded market data at all (the GradedPricesTab early-returns "No graded sales recorded" but the user still owns the slot), (b) any card where the user disagrees with the algorithmic price.

- **Surface**: `CardDetailModal` → graded focus → "Your Graded Copies" panel (gold box above the Price History / Graded tabs). For every owned slot, an inline `<CostDateInputs showCustomValue=${true}/>` renders three always-visible fields: **Paid** / **Acquired** / **Value**. The whole panel sits ABOVE the tab content, so it works even when GradedPricesTab early-returns on empty market data.
- **Plumbing**: `updateItemMeta({card_id, printing, grader, grade}, {custom_value: N|null})` writes through. Fetch path includes `custom_value` in the SELECT with a schema-tolerant fallback for pre-mig-51 environments. `get_shared_collection_graded` RPC was recreated (drop+create) to return `custom_value` too.
- **Read path**: any value computation should prefer `it.custom_value ?? lookupGradedPx(...)`. Search for `custom_value` in Index.html for the existing call sites (header totals, value chart, slot pills).
- **UI affordance**: when `custom_value` is set, the slot's price pill flips from green API price to gold `✎ $N` so the user can see at a glance which copies are overridden.
- **`CostDateInputs` props**: `currentPaid`, `currentDate`, `currentCustomValue`, `showCustomValue`, `onCommit(patch)`. The component is shared between sealed (no custom value) and graded (with). Don't pass `showCustomValue` for sealed.

## Manual graded price overrides

`scripts/graded_overrides.json` is hand-curated graded price entries the daily ETL merges AFTER pulling TCGPriceLookup (overrides win on PK collision). Use when TCGPriceLookup conflates printings (e.g. LCP C1 Baymax — pid 595439 — has only a "Normal" TCGPriceLookup record but its CGC 8/8.5 sales clearly reflect Holofoil pricing).

Two arrays:
- `overrides[]` — full row inserts. PK fields required; `date: "today"` resolves at ETL time. `source: "manual_override"` is the default tag.
- `delete[]` — `{pid, printing, grader, grade}` keys to drop from today's snapshot AFTER the upsert (so the TCGPriceLookup row we're suppressing doesn't outrank our override on read).

`notes` field on each entry is freeform and ignored. Don't blow up the schema; if you need bulk corrections, write a one-off `scripts/cleanup_*.py` instead.

## Graded ops scripts

- **`scripts/probe_graded_printings.py [pids...]`** — audit utility. Walks the TCGPriceLookup catalog and reports any `tcgplayer_id`s with multiple records (= split-printing cards). Use to verify whether new cards have foil/non-foil records BEFORE adding them to `SPLIT_BY_PRINTING_SETS_GLOBAL`.
- **`scripts/cleanup_stale_graded_printings.py [--commit]`** — purges `graded_prices_daily` rows whose `(pid, printing)` combo doesn't exist in TCGPriceLookup's catalog (e.g. pre-migration-49 "Normal" rows for Holofoil-only cards). Run after any printing-related schema/ETL change. Default is dry-run; `--commit` actually deletes.
- **`scripts/backfill_graded_history.py [--pids 510153,...]`** — pulls a year of `/history` per card. Now captures `printing` from each record's `variant` field. Re-run after a schema migration to backfill correct printing labels.

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

## Graded display: avg_1d primary, avg_30d secondary

`graded_prices_latest` exposes three eBay-windowed averages: `ebay_avg_1d`, `ebay_avg_7d`, `ebay_avg_30d`. **The display contract changed 2026-05-26: `avg_1d` is primary, `avg_30d` is secondary, `avg_7d` is the last-resort fallback.** Previously `avg_7d` was preferred which was the "weird average" user complaint — for low-volume cards (chase rarities especially) the 7d window collapses a single sale and several stale days into one number that doesn't reflect anything users want.

- The 8 inline fallback chains throughout Index.html (~lines 1687, 1696, 8432, 9893, 9965, 10257, 10294, 10538) all switched from `ebay_avg_7d ?? ebay_avg_1d ?? ebay_avg_30d` → `ebay_avg_1d ?? ebay_avg_30d ?? ebay_avg_7d`.
- The GradedPricesTab detail table renders all three columns explicitly (header reads "Latest avg · 7d avg · 30d avg") so users can inspect the windowed history — only the SINGLE-PRICE displays elsewhere on the site swapped.
- "Last Sale + Avg of last 5" was the user's literal request. Not implementable today because TCGPriceLookup only exposes daily aggregates, not individual sale records. See memory `project_future_graded_db.md` for the eventual own-database plan.

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

## Cost & date tracking (sealed + graded collection)

Migration 48 added optional `amount_paid numeric(12,2)` + `acquired_date date` to both `sealed_collection_items` and `graded_collection_items`. Both nullable. Shared-collection RPCs (`get_shared_collection_sealed` / `_graded`) recreated with the new columns in their RETURNS TABLE.

- **UI**: per-section "Track cost & date" toggle (`packsink:sealedColl:trackCosts` / `packsink:graded:trackCosts` localStorage). Off by default. When on, a `CostDateInputs` component renders below each owned row/slot. Both fields stay optional even when the toggle is on; clearing them writes NULL.
- **Shared component**: `CostDateInputs` (Index.html, just above `SealedCollectionView`) — `$ paid` + date inputs, commit on blur or Enter. Used by sealed (per-row, keyed by pid) and graded (per-slot, keyed by card_id + grader + grade).
- **State plumbing**:
  - Sealed: parallel `sealedMeta = {[pid]: {amount_paid, acquired_date}}` map at App level. `updateSealedMeta(pid, patch)` callback. Flows through `CollectionView` → `SealedCollectionView` AND through `HomeView` → `CollectionPanel` (the chart needs it).
  - Graded: rows already include `amount_paid` / `acquired_date` (no parallel state needed). `updateItemMeta({card_id, grader, grade}, patch)` callback.
- **Schema-tolerant fetches**: both fetch paths probe with the new columns, retry without on 42703 (column missing) so the frontend still works pre-migration. Safe to deploy code before applying the migration.
- **Chart gating** (`computeCollectionValueHistory` + `computeGradedValueHistory`): per-key acquired_date map. A slot contributes $0 to dates strictly before its acquired_date so historical value reflects only what the user actually owned at the time. Slots without acquired_date keep the existing earliest-snapshot behavior.
- **Graded chart backward-fill (two places)**: TCGPriceLookup graded `/history` is extremely sparse (avg 10 rows/slot/year, median slot's first row is months into a 1y window). **(1) Per-section:** `computeGradedValueHistory` seeds each slot's `prev` with its first known price so a slot is always represented once we have ANY data for it. Without this, plain forward-fill produced an artificial ramp ($100 → $2500) as more slots came online with their first data point. **(2) Combined-chart sum:** the combined-line builder in `CollectionPanel`'s `chartSeries` memo seeds each section's cursor with `s.sorted[0]?.value` so dates BEFORE a section's earliest data point still receive that section's earliest value. Without this, the combined line dropped to (cards + sealed only) on early dates and then jumped up when graded's first datapoint hit — even though the individual graded line in split mode was flat across the entire range. The two backward-fills compose: per-slot inside graded's own series, then per-section across the sum. Acquired_date gating still wins on the per-slot side.

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

## Artist Alley poster

`window.open` opens a self-contained poster in a new tab. Plain `<img>` tags + same-origin `/img-proxy/*` for Lorcast art (canvas exports work cleanly).

- **`.brand-footer`** at bottom with Packs.Ink logo (110px) + "packs.ink" wordmark. Stays visible in screen + print + html2canvas capture.
- **Copy as Image**: html2canvas → single tall PNG → clipboard.
- **Save JPG**: html2canvas → adaptive scale + q=0.85 → recompress (q=0.78 → 0.55) until under 9.5MB (Discord cap).
- **Print PDF path** preserves dark poster via `print-color-adjust: exact`. `break-inside: avoid` on figures. Pinned to 6 cols via `!important` in `@media print`.

## PWA install nudge

Auto-opens `InstallHelpModal` on visits 2 and 3 (counter at `localStorage["packsink:installVisits"]`). Skipped on visit 1 (no ambush), and entirely when already standalone, on desktop, or after the user clicked "Don't show this again" (`packsink:installDismissed`).

Modal accepts `onDismissForever`; only passed on visit ≥3 so the dismiss link appears the second time the modal pops.

## First-time sign-in onboarding

Two prompts fire in sequence on a fresh sign-in:

1. **Display name prompt** (`showNamePrompt` state in App): opens whenever `profiles.display_name` is empty for the signed-in user. Triggers via the `useEffect` that hydrates the profile row. Closes via `saveDisplayName` (which writes the name and flips the flag).
2. **Avatar picker** (`AvatarPicker` component): auto-opens 200ms after the user finishes step 1, gated by `localStorage["packsink:avatarPromptShown"]` and `!avatarCardId`. Picks ANY card from the catalog as the user's profile picture (writes `avatarCardId` to user_metadata + localStorage). The 200ms defer keeps the name-prompt unmount animation from fighting the picker mount.

The avatar gate is one-shot — closing the picker once flips `packsink:avatarPromptShown` so returning users without an avatar aren't pestered on every visit. Settings-popover edits to display name DON'T trigger the avatar prompt (the trigger is gated on `wasFirstTime = showNamePrompt` at save time).

## Home page surface

- **No "Lorcana Market" h1 or "Click a card for details" subtitle** — both removed 2026-05-26. The search bar sits directly under the top nav. The logo IS the home click target (the title was redundant).
- **Your Top Movers tiles show a printing badge** when the moving row is the foil printing — class `.panel-movers-foil-tag`, accent-color chip with text "Foil" / "Cold Foil" / "Holo" (Holofoil shortens to "Holo" to fit the tight column). Logic: `row.tcg_printing && row.tcg_printing !== "Normal" && row.tcg_printing !== "Non-Foil"` → render. Lets users tell foil-vs-non-foil movers of the same card apart.

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

- **`sw.js CACHE_VERSION`** (current `packsink-v103`): bump on ANY meaningful Index.html / styles.css / logo.js change. Activate handler purges old caches. Pre-cache uses `cache.add().catch(null)` per asset. HTML requests are **network-first**, so users get fresh Index.html every visit when online.
- **Catalog cache version**: `packsink:catalog:vN` (current **v42**). Bump when row shape changes (v42 added `text` field for body-text search), OR when forcing all users to cold-fetch.
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

## Brand assets

- `Logos/` ships at runtime.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons.
- `Logos/rarity/{common,uncommon,...}.svg` — 9 rarity icons (added 2026-05-23).
- `Logos/packs-ink-logo.png` — site wordmark (top bar @ 60px height, footer @ 48px).
- `Logos/Logo on Black.png` — Ink & Lore footer logo (base64-embedded as `LOGO_B64`).
- `Logos/PacksInk.ai` + `Logos/PacksInk.pdf` — source files for the commissioned wordmark (not used in deploy).
- Custom SVG glyphs: `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` (shared `<HexFrame/>`).

## Pending / roadmap

**iPhone bugs to verify after the 2026-05-26 deploy lands** (may already be resolved by the tap-target / safe-area / sticky-overlap fixes — retest before doing more work):

- **Recent Set EV panel off-center on home (Photo 2)** — deferred pending safe-area retest. Likely resolves incidentally.
- **Profile pill click "spawns a duplicate username" on iPhone (Photo 4)** — was probably a half-tap registering twice on a 28×28 hit area; now 36×36. If it persists, dig into the profile-pill click handler / settings-popover mount logic.
- **Tournament Results panel rendering twice on mobile** — attributed to stale service-worker cache serving an older Index.html. Force-quit PWA twice (let v68 take over). If it persists, real component-mount bug.

**Top of the list:**

- **Domain transfer Netlify → Name.com → (optional) Cloudflare** for WAF + Bot Fight Mode in front of Netlify. Blocked until **2026-06-08** (ICANN lock). Netlify only transfers to Name.com per their partnership.
- **Card scanner (phone)** — vision-based identification. Scan → identify → price + history.

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
- Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6 in `etl.yml`.
- **Rotate the cron-job.org GitHub PAT every ~80 days** (90-day expiry, give yourself a buffer). Token lives in each of the 5 cron-job.org jobs' `Authorization: Bearer <token>` header. Issued 2026-05-24 → first rotation due ~2026-08-12. cron-job.org will start emailing failure alerts when the token dies; rotating before expiry prevents data gaps.
- 5 `.bak` PNG icon files at repo root (`apple-touch-icon.png.bak` etc.) — rollback safety net from the 2026-05-26 icon rebake. Delete once the dark-blue icons are confirmed correct on iPhone home screen.
