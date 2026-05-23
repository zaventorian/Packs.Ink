# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## Stack

- **Frontend**: `Index.html` + `styles.css` + `logo.js`, React via `htm` template literals, no build step. Served by `python scripts/dev_server.py` (port 8766 — AnkiConnect squats 8765) for dev; **Netlify free tier** for prod (Cloudflare Pages is the natural upgrade if bandwidth hits 100GB/mo). Domain currently registered through Netlify; transfer to Cloudflare blocked until 2026-06-08 (ICANN 60-day post-registration lock). The CSS extraction is a deliberate split for browser caching + editor sanity; do NOT inline CSS back into Index.html.
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog tables**: `cards`, `sets`, `prices_daily`, `sealed_products`, `graded_prices_daily`.
  - **User tables**: `profiles` (now also carries collection-sharing visibility + share_token columns), `collection_items`, `sealed_collection_items`, `graded_collection_items`, `graded_collection_goals`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`, `screener_views`.
  - **Tournament tables**: `tournaments`, `tournament_decks`, `tournament_admins`, view `tournament_results_v` (security_invoker on).
  - **Materialized views** (refreshed daily by the ETL): `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`, `graded_prices_latest`.
- **ETL**: two daily pulls run sequentially in **one** GitHub Actions workflow at 21:00 UTC daily (`.github/workflows/etl.yml`):
  1. `scripts/etl_tcgcsv_daily.py` — TCGCSV → `prices_daily`, then refreshes the four raw-price matviews. **Aborts when today's fetched snapshot is >95% byte-identical to yesterday's** (`--force` to override). Pass-through guard against TCGCSV re-serving yesterday's file before its ~20:00 UTC daily cron fires.
  2. `scripts/etl_tcgpricelookup_daily.py` — TCGPriceLookup Trader tier → `graded_prices_daily`, then refreshes `graded_prices_latest`. Pinned `graded` after `prices` via `needs:` so a single 21:00 trigger covers both. GitHub free-tier scheduler silently drops one of two close-together schedules under load — that's why we consolidated.
  - Weekly Lorcast metadata refresh stays on its own Sundays 22:00 UTC cron.
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed-product catalog**: `scripts/load_sealed_products.py` — pulls every product TCGCSV exposes for category 71, classifies by name, upserts into `sealed_products`.
- **Local dev preview**: launch config lives in `./.claude/launch.json` under the `packs-ink` entry. **The MCP preview reads from the active project's `.claude/launch.json`, NOT the Sayumi.Ink workspace's.** Must point at `scripts/dev_server.py` (not `python -m http.server`) so `/img-proxy/*` works for the deck-poster export. There's also a stale-looking entry in `../Sayumi.Ink/.claude/launch.json` — it's not the active one.

## Top-level nav

`Home · Screener · Price Graphing · Analytics · Cards · Collection · Decks`

- **Screener** = sortable financial-database-style table of every tracked card (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface.
- **Price Graphing** = per-card history charts and a multi-card Compare mode (handoff from Screener's batch action).
- **Analytics** = umbrella for the calculator-y tools (Expected Value, Card Averages, Playset Cost, Heatmap, Sealed, Simulate). Was called "Market"; renamed because none of those sub-pages actually show market data, they analyze it.

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from the browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- **Catalog key**: `packsink:catalog:vN`. **Bump N whenever the cached row shape changes** — old cache entries are silently ignored on version mismatch. Currently `v37`. 24h TTL with background refresh.
- **`img_large` is STRIPPED from the catalog cache on write** (writeCache `slim = rows.map(({img_large, ...rest}) => rest)`). Saves ~30% of catalog size. The few places that prefer img_large (deck poster, hover preview, detail modal) all gracefully fall back to `img_normal`. Don't add img_large back — the 5MB quota is tight.
- **writeCache does three-pass eviction**: (1) `removeItem(CACHE_KEY)` before `setItem` since some browsers count old+new against quota during overwrite; (2) on failure, evict every other `packsink:*` key except auth/tiny prefs; (3) retry. Final fallback warns and lets the next visit retry.
- Per-view banner caches use generic `readJsonCache(key, ttlMs)` + `writeJsonCache(key, data)` helpers:
  - `packsink:movers:v1` — home movers (12h).
  - `packsink:screener-movers:v1` — Screener's separate price_movers fetch (12h).
  - `packsink:following:v1:{uid8}` — home Following feed (30min).
  - `packsink:home:tourneys:v1` — home Tournament Results banner (2h).
  - `packsink:hist:v1:{productId}:{printing}` — per-card price history (12h).
  - `packsink:sealed:v1` — sealed-price catalog. Bump independently.
  - `packsink:setsMeta:v1` — `sets` table snapshot (id + name + released_at). Fetched on EVERY page load via an independent `useEffect` (not bundled with the catalog Promise.all) because `loadFromSupabase` returns early on a fresh catalog cache, which would otherwise leave `setsMeta` empty and break (a) the home box-price set_id matching, and (b) the collection-value prerelease guard.
  - `packsink:colvalue:v2:{uid8}:{productsHash}:{rangeKey}` — collection value chart series. Bumped to v2 when the prerelease guard landed so stale unguarded entries get invalidated automatically.
- **`writeJsonCache` has its own QuotaExceededError eviction** that drops `packsink:hist:` first (cheapest to rebuild), then home banners, then sealed. Catalog is NOT in this eviction list (most expensive to rebuild). Catalog's own writeCache evicts everything else if it has to.
- Quota is ~5MB. Min rows for catalog: 4000.
- **Symptom of quota exhaustion**: cache writes fail silently, every visit becomes a cold fetch, per-view banners "unload" on tab switch. Diagnostic: `Object.entries(localStorage).reduce((s,[k,v])=>s+v.length,0)/1024/1024` in console.

## PostgREST gotchas

- `sbFetchAll` parallel range pagination **requires an explicit `order=` param** — without it, ranges overlap and rows duplicate. Always pass a stable sort (e.g. `tcgplayer_product_id.asc,printing.asc` for prices, `id.asc` for cards).
- `sbFetchAll` with `limit=N` confuses its own pagination — first request uses `Prefer: count=exact` which returns the FULL table count, so subsequent pages try to fetch beyond the limit and 416. **For "does this column exist" probes, use a direct `fetch()`, not sbFetchAll.**
- Anything previously a "regular view" that hits `prices_daily` should be a **materialized view**. Statement timeout is 10s; raw views over the ~3M-row `prices_daily` will hit it. `card_prices_latest`, `rarity_avg_daily`, `price_movers`, and `sealed_prices_latest` are all matviews now.
- Matviews need a unique index for `REFRESH CONCURRENTLY`. All four have one; refresh functions fall back to non-concurrent on first run.
- **PostgREST default page size is 1000.** `sbClient.from().select()` silently truncates beyond that. Always paginate `.range()` for tables that could exceed it (collection fetch in App does this).
- **Upserts return `{error}`, they don't throw.** Always check `.error`. For bulk upserts, also add `.select("any_col")` and compare returned count vs sent count — RLS / triggers can silently drop rows otherwise.
- **`ON CONFLICT DO UPDATE` rejects batches with duplicate conflict-target rows.** Dedupe by the conflict key before sending — `Supabase.upsert()` now does this automatically.
- **`sbFetchWithRetry` wraps every fetch** with 3 retries on 5xx — Supabase's 57014 (statement timeout) is intermittent under load.
- **`CREATE OR REPLACE FUNCTION` can't change a RETURNS TABLE signature.** Postgres errors with 42P13 / "cannot change return type". Drop first, then create. Hit when adding `youtube_url` to `get_shared_deck`.
- **RLS broadening trap.** When a SELECT policy includes `OR <some condition non-owner can satisfy>`, an unfiltered `select` returns every visible row, not just yours. Explicitly `.eq("user_id", user.id)` for "my own" reads.
- **`NOTIFY pgrst, 'reload schema';` at the end of every migration.** PostgREST caches the schema; renaming a table or adding a function means the API doesn't know about it until the cache reloads. Habit, not tooling.
- **`SECURITY DEFINER` functions must pin `search_path` to include `extensions`** if they use anything from pgcrypto (`gen_random_bytes`, `gen_random_uuid`, etc.). Supabase puts pgcrypto in the `extensions` schema, off the default search path.
- **Long-running RPCs need explicit statement_timeout.** Default role-level cap kills concurrent matview refreshes once the matview grows past ~30s. Every refresh function pins `set statement_timeout = '5min'`.
- **When recreating a matview, re-grant SELECT to every role that needs it.** `grant select on price_movers to anon, authenticated` is mandatory; service_role doesn't inherit unless you grant explicitly. Migration 26 missed service_role and broke offline diagnostics until we used the anon key.
- **Views authored as the dashboard user are SECURITY DEFINER by default** — triggers Supabase's `0010_security_definer_view` linter alert. Always create with `with (security_invoker = on)` so the view runs as the querying user. See `supabase/38_tournament_view_invoker.sql` for the retroactive `ALTER VIEW ... SET (security_invoker = on)` template.

## Auth state gotcha (do NOT regress)

**`sbClient.auth.updateUser()` fires an auth-state-change event after every successful call**, creating a new `user` object reference. If a `useEffect` syncs user_metadata back via `updateUser()` and has `user` in its deps, you get an infinite loop throttled only by debounce. Supabase rate-limits `/auth/v1/user` quickly (429); the auth lock then serializes and stalls every other Supabase query behind it.

The prefs-sync effect in `App.jsx` (writes `{theme, tipsEnabled, avatarCardId}` to `user_metadata`) deliberately omits `user` from its deps and uses `prefsHydrated.current` ref to wait for first hydration. Symptoms of regression: catalog fetch takes minutes, "Loading price database…" forever, every tab switch acts like a cold load.

## price_movers matview gotcha

The matview computes Δ% across 6 windows (1D / 1W / 1M / 3M / 6M / 1Y) for both low and market. **`low_prev` is "most recent non-null low BEFORE low_today's own date"**, not "before the global max date in prices_daily" — migration 26 fixes this. The old definition collapsed pct_1d to 0 for every card that wasn't priced today, which is most sparse-listing chase cards. If 1D movers ever look broken again, check that the per-card `latest_low_date` CTE is still in place.

## Catalog merging — `transformSupabaseData` rules

This is where catalog correctness lives. Structural cleanups beyond the basic cards+prices merge:

1. **Holofoil mislabel rule** — TCGCSV sometimes publishes a card's in-pack foil under `printing=Holofoil` instead of `Cold Foil` (late-2024+ sets, confirmed via live TCGPlayer listings). When a non-chase, non-extras card has a Holofoil row, that's the canonical foil and any separate Cold Foil/Foil row is suppressed as stale.
2. **`EXTRAS_MAP`** — curated map of `tcgplayer_product_id` → variant info for cards that get promoted to the "Extras & Oddities" bucket. 21 entries:
   - 12 starter-deck-exclusive foils (4 each in Wilds Unknown, Fabled, Whispers in the Well — flagged as Holofoil in TCGCSV).
   - 5 Illumineer's Quest: Deep Trouble cards (Half Hexwell Crown, Mickey Mouse Playful Sorcerer, Yen Sid, Mulan Elite Archer, Piglet Pooh Pirate Captain).
   - 4 Illumineer's Quest: Palace Heist cards (Bolt Superdog, Goofy Groundbreaking Chef, Pinocchio Strings Attached, Elsa Ice Maker).
   - `excludeFromBaseSet: true` cards are suppressed from their origin set (Deep Trouble + Half Hexwell Crown + all 4 Palace Heist).
   - `standalone: {...}` lets us include cards Lorcast doesn't index. Palace Heist + Piglet use this; their actual `cards` table rows come from `scripts/patch_pid_overrides.py` (see below).
3. **`CONNECTING_FOILS`** — map of `base_product_id` → `foil_product_id` for cards whose foil version TCGPlayer lists as a separate SKU (connecting-art / extended-art foils). 24 entries across Winterspell, Wilds Unknown, and Reign of Jafar. The foil row is emitted under the base card's `card_id` so the collection slot stays grouped. The companion product is suppressed from the main loop to avoid duplicate rows.
4. **`CUSTOM_VARIANTS`** — for cards Lorcast doesn't index that live INSIDE a mainline set (not in Extras). Genie - On the Job (Two Swords Variant) + Peter Pan - Pirate's Bane (Text Error). Each entry clones its base card's row with a distinct `card_id` (`<base>::variant::<slug>`), `Number` suffix `Error`, `variant_label`, null prices. `baseRarity` defaults to `Enchanted` — case-insensitive name match + rarity filter handles cases where the same name has multiple printings in the same set (e.g. Peter Pan's #120 base vs #215 Enchanted).
5. **`CUSTOM_CARDS`** — placeholder array for cards Lorcast doesn't index. Currently empty; Golden Mickey + Palace Heist all migrated to real `cards` rows via `patch_pid_overrides.py`. Kept as infrastructure for future one-off injections.
6. **`SET_DISPLAY_NAMES`** — `{Lorcast set name → UI display name}`. Currently `{"Challenge Promo": "Lorcana Challenge Promo (C1)", "Lorcana Challenge Year 3": "Lorcana Challenge Promo (C2)"}`. Applied in `transformSupabaseData`'s setName resolution so every downstream surface (tiles, drill-in, deck banner) uses the friendly name. **All in-code set comparisons use the DISPLAY name, not the Lorcast name** — this is the post-rename string.
7. **`COLLECTOR_NUMBER_OVERRIDES`** — keyed by `<set_id>|<lorcast_collector_number>`. Applied in `buildRow`. Currently renumbers Challenge Promo's Lorcast #25/41/42/43 → community-canonical #1/2/3/4. Use this when Lorcast's numbering doesn't match the print's printed number.
8. **`UNIFIED_TILE_SETS`** — a Set of set names whose Collection tile collapses Normal/Foil/Enchanted into one `Promos X/Y` row instead of three near-empty rows. Currently Promo Set 1/2/3, D23 Collection, EPCOT Festival of the Arts. Lorcana Challenge Promo (C1) and (C2) are intentionally NOT in this set — both have a real Non-Foil / Foil split. C1 shares one tcgplayer_product_id across both printings (Prize Wall non-foils + foil prizes); C2 prints each printing with a DIFFERENT collector number so they're already distinct cards in Lorcast.
9. **`CHINA_ONLY_NONFOIL`** — `{<name>|<cn>: <local image path>}` for cards whose Non-Foil printing exists only in the Chinese market. Currently Dragon Fire #25, Let It Go #41. Non-foil row gets `variant_label: "Chinese Exclusive"`, null prices, null `tcgplayer_product_id`, and the local image. Backfill emits a synthetic Normal row if TCGCSV only had foil entries.
10. **`TCG_PID_OVERRIDES` is authoritative** — was originally a fill-in-null mechanism but now overrides Lorcast even when Lorcast has a (wrong) value. Used to correct the Hiro Hamada #24/24B pid swap. **Entries are applied client-side in `transformSupabaseData` AND server-side via `scripts/patch_pid_overrides.py`** — the latter writes them into the `cards` table so the `card_prices_latest` matview JOIN picks them up. Client-only overrides don't help the matview.
11. **Image fallback chain in `buildRow`** — `img_normal` falls back to `img_large || img_small`, etc. Lorcast occasionally populates only `image_large` (Lorcana Challenge Promo (C1) Dragon Fire / Let It Go / Cinderella / Rapunzel are this way — small + normal are empty strings). Without the fallback, tiles render broken-image placeholders. **Downstream surfaces that read `price_movers` directly (home banners, Screener) DO NOT see the buildRow fallback** — and `img_large` is stripped from the localStorage catalog cache to save space. To enrich those rows, look up `raw[i].img_normal` (which already contains the large URL via buildRow's fallback) and inject as `image_normal` on the matview row. See `fallbackImgByCardId` in HomeView's movers and PriceDatabase's fetch handler.
12. **Low ↔ Market fallback in `processData`** — collects samples from both `low_price` and `market_price` columns. When a card has one but not the other (typical for sparse/newest-set rows), the missing side falls back to the present side so it still contributes to rarity averages. The Analytics views' `priceMode` toggle then picks the preferred field per render.
13. **`PROMO_RARITY_SETS`** — every card in the 7 promo-only sets (Promo Set 1/2/3, Lorcana Challenge Promo (C1), Lorcana Challenge Promo (C2), D23 Collection, EPCOT Festival of the Arts) gets its rarity overridden to `"Promo"` in `buildRow`. Lorcast publishes these with their printed rarities (e.g. Stitch - Rock Star = Rare, Anna Braving the Story = Super Rare), but the screener/banner/filter UX treats Promo as a single tier.
14. **`YEAR3_PRINTING_BY_NUMBER`** — Lorcana Challenge Promo (C2) cards each exist as exactly ONE printing per collector number (1–4 are foil prizes, 5–10 / 15–18 are non-foil prize wall). TCGCSV emits prices for both Normal and Cold Foil under every pid, producing ghost rows that would show the same card in both sections of the collection set-detail view. This map tells `transformSupabaseData` which printing is canonical per number so the bogus one is suppressed. Numbers not in the map fall through (defensive for future drops where the printing isn't known yet).
15. **`SPLIT_BY_PRINTING_SETS`** (in `groupCards`) — sets where Normal and Foil are economically distinct products and should render as separate tiles in the Cards grid. Currently `{Lorcana Challenge Promo (C1)}` — the Prize Wall non-foil and the Prize Foil prize share one tcgplayer_product_id but have wildly different prices. Group key suffix-appends `::Normal` / `::Foil` so each becomes its own tile + detail modal with a PRIZE WALL or PRIZE FOIL badge. `card_id` stays untouched so existing collection rows remain backward-compatible. (C2 is NOT here — its printings already have distinct card_ids from Lorcast.)
16. **`SECTION_SPLIT_SETS`** (in `CollectionSetDetail`) — sets that get a Non-Foil / Foil section split in the set-detail view (top stack = non-foil rows, bottom stack = foil rows). Currently `{Lorcana Challenge Promo (C1), Lorcana Challenge Promo (C2)}`.

**Rarity normalization invariant** — `cards.rarity` MUST be canonical: `Common, Uncommon, Rare, Super Rare, Legendary, Enchanted, Epic, Iconic, Promo`. Lorcast publishes Super Rare as `"Super_rare"` (snake_case); `scripts/load_lorcast.py` now normalizes on insert. Migration `42_normalize_cards_rarity.sql` retroactively fixed stored values. Both `price_movers` fetches (home + Screener) also normalize on read via `normalizeRarity()` as a defensive guard. Without this, `RARELEG_RARS.has("Super_rare")` returns false and the rare-leg movers banner silently drops every Super Rare card.

Audit scripts to regenerate these maps: `scripts/audit_holofoils.py`, `scripts/audit_connecting_foils.py`, `scripts/audit_missing_foils.py`. Sealed orphan / catalog audits: `supabase/diagnostics/sealed_product_audit.sql`. Index usage walks: `supabase/diagnostics/index_usage_audit.sql`.

**`scripts/patch_pid_overrides.py`** — the bridge between client-side maps and the DB. Run after editing `TCG_PID_OVERRIDES` in Index.html or after declaring new Extras-style standalone cards. It (a) writes the override pids into the `cards` table so the matview JOIN picks them up, (b) upserts synthetic `cards` rows for Lorcast-missing products (Golden Mickey pid 554628, Palace Heist 4: 634262/63/64/65 — all under Ursula's Return's `set_id` as the Deep Trouble convention), and (c) calls `refresh_card_prices_latest()` at the end. Idempotent; safe to re-run.

**Why client-side overrides aren't enough for prices.** `card_prices_latest` is `cards INNER JOIN prices_daily ON tcgplayer_product_id`. If `cards.tcgplayer_product_id` is null or wrong, no matview row → no price flowing through the catalog fetch into `pricesByProduct`. The client-side `TCG_PID_OVERRIDES` only fixes the display row's `tcgplayer_product_id` field, not the upstream join. Running the patch script is required for prices to appear.

## Graded data: `date` vs `price_date`

**Trap.** `graded_prices_daily.date` is the column name. The `graded_prices_latest` matview projects it as `price_date` to be consistent with `card_prices_latest`. If you query `graded_prices_daily` with `select("...price_date...")` or filter `price_date: "gte.YYYY-MM-DD"`, you'll get a 42703 "column does not exist" error. Easy to mix up since graded_prices_latest uses the renamed column. The Graded portfolio value chart in CollectionView learned this the hard way.

## Set conventions

- **`MAINLINE_SETS`** = the booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Playset Cost, Price Graphing, Card Averages, Heatmap, and the Home page "newest set" walk.
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. Drives the Cards browse, Collection grid, set-membership gates. `reverse()` in the renderer puts mainlines on top and Extras at the bottom.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased sets. Drives Core Constructed rotation math (`computeCoreSets`) — keeps the two most-recent complete 4-set groups + the in-progress group.
- **Newest-first inside Analytics.** Every Analytics sub-view lists sets newest-first via a `setsNewest = sets.slice().reverse()` derived once in `MarketView`. Simulators inherit the same ordering.
- Decks pick up format automatically (`checkDeckLegality`): structurally legal + all cards in Core legal sets → "Core Constructed"; structurally legal otherwise → "Infinity"; structurally broken → "Invalid Deck".

## Inks & dual-ink cards

Lorcana has six single inks (Amber, Amethyst, Emerald, Ruby, Sapphire, Steel) and dual-ink cards introduced in late 2025. Lorcast exposes duals as `inks: ["Emerald","Sapphire"]` with `ink: null`. **Always read `meta.inks` first, fall back to `[meta.ink]`** — the legacy `ink` column is populated with `inks[0]` for back-compat but doesn't capture the second color.

- Migration `27_card_inks_array.sql` adds the `inks text[]` column.
- `scripts/load_lorcast.py` writes both `ink` (= inks[0]) and `inks` (the full array).
- `scripts/patch_card_inks.py` is the one-shot backfill for rows loaded before the migration. Idempotent.

**Rendering convention for dual-ink:**
- **Deck stats Colors pie**: dual-ink cards form their OWN bucket keyed by joined ink names ("Emerald/Sapphire"). The bucket gets the full card quantity (not split). Slice rendered as a flat neutral charcoal (DUAL_INK_PIE_COLOR = slate-600) with a "dual" pill tag in the legend — gradient slices are unreadable at small angles.
- **Cost curve bar chart**: same bucketing as the pie, but the rendered block uses a 135° diagonal gradient (Emerald top-left → Sapphire bottom-right) since bar segments are large enough to read both colors.
- **Deck row ink swatch**: a 14px circle with a hard mid-line divider — half-color-A, half-color-B. Single inks use a solid circle.
- **Legality (`checkDeckLegality`)**: dual-ink cards contribute BOTH colors to the deck's ink set. An Emerald/Sapphire dual + an Amber single = 3 inks → over the 2-ink cap. Same logic for `inkColorsInDeck` header label.

## Deck-build limit exceptions

Lorcana's default is 4-of-any-card. A handful bypass it via card text — keep `SPECIAL_DECK_LIMITS` in `Index.html` updated when new exception cards are printed. Currently:

- `"Dalmatian Puppy - Tail Wagger"` → 99 (Puppy Power; variants share the total)
- `"Microbots"` → Infinity (UI caps at 99 for sanity)

`getDeckLimit(productName)` returns the cap (4 default). `getDeckLimitForUI(productName)` clamps Infinity to 99 for +/- buttons. `checkDeckLegality` sums by Product Name across variants before comparing — so variants of Tail Wagger correctly accumulate toward the 99 cap, not 99 each. DB constraint relaxed to `quantity <= 99` in migration `28_deck_cards_quantity_99.sql`.

## Deck sharing model

Three visibility states, each backed by a per-deck `share_token` (22-char URL-safe base64, ~128 bits of entropy):

| Visibility | Direct read RLS | URL behavior | Discovery feed |
|---|---|---|---|
| **Private** | owner only | none (link doesn't work for non-owners) | excluded |
| **Unlisted** | owner only | `?deck=<id>&token=<x>` works for anyone | excluded |
| **Public** | owner OR anyone | `?deck=<id>` works for anyone | included |

Key invariants:

- **Non-owner reads of unlisted decks go through the SECURITY DEFINER `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` RPCs.** These bypass RLS but require the token to match. **`get_shared_deck`'s RETURNS TABLE must include every column the client reads.** When a new deck column is added (e.g. `youtube_url`), the RPC needs to drop-and-recreate to include it — migration `30_shared_deck_youtube.sql` is the template for this kind of update.
- **Flipping a deck TO Private auto-rotates the share token** via the `rotate_share_token_on_private` trigger. Every in-the-wild share URL stops working instantly. Going back to Unlisted later generates a fresh token.
- **Owner-only `regenerate_deck_share_token(uuid)` RPC** lets users revoke a leaked URL without going through Private.
- **Favorites of unlisted decks** capture the share_token at favorite-time (`deck_favorites.share_token`). The Favorites list fetches via the RPC using stored tokens; rotation/revocation gracefully drops the favorite from the list.

Discovery surfaces:

- **Favorites** — per-user saved bookmarks of specific decks (`deck_favorites`).
- **Following** — per-user follow of creators (`user_follows`); feed shows recent public decks from followed creators.
- **Discover** — flat newest-first feed of all public decks, paginated by `updated_at` cursor.
- **Creator profile** — `?user=<uuid>` lists that creator's public decks. Reachable by clicking the creator name in any read-only deck banner.

Aggregate metrics (favorite count, view count) are exposed via SECURITY DEFINER RPCs (`deck_favorite_counts(uuid[])`, `deck_view_counts(uuid[])`) that return only totals, never the underlying `(user_id, deck_id)` rows. Privacy preserved.

## Collection sharing

Mirrors the Deck sharing pattern but with three independent visibility axes (raw / sealed / graded), each `private | unlisted | public`. Backed by `profiles.collection_raw_visibility` + `collection_sealed_visibility` + `collection_graded_visibility` + a shared `profiles.collection_share_token`.

| Visibility | Direct read (table API) | URL behavior | Profile listing |
|---|---|---|---|
| **Private** | owner only | none | excluded |
| **Unlisted** | owner only | `?collection=<uuid>&token=<x>` works | excluded |
| **Public** | n/a (RPCs only) | `?collection=<uuid>` works | included |

Key invariants (migration 39):

- **Non-owner reads always go through SECURITY DEFINER RPCs.** Direct `collection_items`/`sealed_collection_items`/`graded_collection_items` reads stay owner-only via RLS. The three `get_shared_collection_raw/sealed/graded(uuid, text)` RPCs are the only public-reachable path; they accept the token and gate per section visibility.
- **`get_collection_visibility(uuid, text)` returns** the three per-section booleans the client uses to decide which section tabs + sections to render.
- **One token for all three sections.** Public sections render with or without it; unlisted sections require it. Trigger rotates the token when all three sections go to `private` simultaneously (so revoking everything kills the URL).
- **Owner-only `regenerate_collection_share_token()` RPC** rotates the token without flipping visibility. Same pattern as decks.
- **Viewer mode** = `?collection=<uuid>` in the URL. App fetches via the visibility-gated RPCs and feeds `CollectionView` with a `viewerContext` prop (sets `readOnly`, hides edit affordances, gates section tabs by visibility).
- **`paginateRpc` is required** for the three `get_shared_collection_*` calls — PostgREST caps RPC table-returns at 1000 rows by default. The helper drains via `.range(from, to)` until a short page. Without it, collections >1000 silently truncate.
- **InlineCounter in read-only mode** renders the qty without +/- buttons. Previously it returned an empty div, breaking the set-detail grid alignment.
- **Comparison stats** in viewer mode require the viewer to be signed in (we need their `collection` + `sealedCollection` to compute overlap).

## Tournaments

Admin-gated bulk-upload of tournament results. Each tournament has N player rows; each row creates a public deck linked to the tournament. Tournament decks have **`user_id = null`** (ownerless) so they don't pollute the uploader's My Decks / Following feed.

- **Schema** (migrations 35 + 37): `tournaments`, `tournament_decks`, `tournament_admins`, view `tournament_results_v` (security_invoker=on). RLS: public SELECT, admin-only INSERT/UPDATE/DELETE. Manage admin rows manually via dashboard.
- **Admin gate**: `is_tournament_admin(uuid)` SECURITY DEFINER helper. Client calls `sbClient.rpc("is_tournament_admin", {p_user: user.id})` on auth to gate UI.
- **Bulk upload RPC**: `bulk_upload_tournament(p_name, p_event_date, p_format, p_num_players, p_rows jsonb) returns uuid`. One transactional round-trip — either everything lands or nothing. Replaces an older client loop that did 4 sequential round-trips per deck (took 5+ min on slow Supabase nights).
- **Admin ops RPCs**: `admin_delete_tournament(uuid)`, `admin_update_tournament_meta(uuid, name, date, format, num_players)`, `admin_update_tournament_deck(uuid, place, place_rank, player_name, deck_name)`, and (migration 40) `admin_replace_tournament_deck_cards(result_id, inks, cards jsonb)` + `admin_add_tournament_deck(...)` + `admin_delete_tournament_deck(result_id)`. All SECURITY DEFINER, gated on `is_tournament_admin(auth.uid())`.
- **`TournamentBulkEditModal`** is the canonical editor — replaces the meta-only `TournamentEditModal`. Same layout as Bulk Upload but pre-populates from existing rows (single batched `deck_cards` query for all linked decks) and diffs on save. Add/remove/edit multiple decks in one pass.
- **Discover tile for tournament decks** — `renderExternalCard` checks `tournamentByDeckId[d.id]`. If present, swaps the byline from "by Creator" to "by Player Name" and prepends a trophy strip: `🏆 Tournament Name · 1st · 57p`. Don't render the "Unfollow {creator}" button for ownerless decks (`d.user_id` is null).
- **CSS gotcha**: the tournament-result row's grid layout MUST live on `.tournament-result-open` (the inner button containing the spans), NOT `.tournament-result-row` (the outer wrapper). Admin mode's `.has-admin` flips to flex; non-admin mode would otherwise have a grid container with no laid-out children.
- **`decks.user_id` is nullable** (migration 37). Tournament decks set it null; any "my decks" / "following feed" / creator-profile queries filter on `user_id = X` and naturally exclude them. Discover feed (public decks) still shows them.
- **Per-row deck name fallback chain** (client-side, before sending to RPC): explicit deck name → joined inks (`Amber/Emerald`) → `${player_name}'s deck` → `Untitled deck`.
- **Per-row inks** computed client-side from `parseDeckText` entries + catalog meta, sent in the row payload. RPC writes to `decks.inks`. Avoids a server-side `cards` lookup per insert.
- **Deck detail page tournament badge**: `DeckEditor` accepts `tournamentContext` + `onOpenTournament` props. When set, the readonly banner replaces "by Creator" with `🏆 Tournament Name · 1st · 57 players` + "by Player Name". Build the lookup once in `DecksView` from `tournamentResults`: `tournamentByDeckId = useMemo(() => { ... }, [tournamentResults])`.
- **Image export poster** mirrors the badge — `DeckPosterModal` accepts `tournamentContext`, renders the trophy line under the deck title, uses `player_name` instead of `creatorName` for the "by" credit.
- **Home Tournament Results banner** below Following in `.home-left-col`. Top 4 decks per tournament, newest first, capped at 16 total. Row shape: `<place> Player Name: Deck Name 🛡️🛡️`. Deck click → `openDeckById`; tournament name click → `openTournamentById` (App-level cross-view nav, mirrors `openDeckById`).

## Deck view / edit modes

Clicking your own deck defaults to **view mode** (no card browser, no inline-rename); the toolbar has an **✎ Edit** toggle that flips to edit mode. Brand-new decks open straight into edit since the view is empty.

- `DecksView` uses `openDeckInMode(id, "view"|"edit")` instead of bare `setSelectedDeckId(id)`. Click → "view"; createDeck → "edit"; duplicate → "view".
- Owner controls (Share, Duplicate, Delete, Export) gate on `isOwnDeck`. Import + inline rename + Saved indicator + CardBrowser gate on `!readOnly`.
- The "Viewing shared deck" banner only renders when `readOnly && !isOwnDeck`.
- Three list layouts (View ▾ dropdown): compact list, image grid, stacked pile. Persisted to localStorage. The stacked pile uses peek strips of the same `img_small` for each extra copy — give each peek 22px height, +1% width per layer for a nested-cards-getting-larger effect, and let object-fit:cover clip to the card-top.

## TCGCSV / Lorcast notes

- categoryId 71 = Lorcana. Archive starts 2024-02-08.
- Daily snapshot lands ~20:00 UTC. ETL cron at 21:00 UTC = 1 hour after.
- **TCGCSV's `low_price` is a sticker, not a sale.** For high-value cards the lowest active listing often sits unchanged for weeks. ~98% of 1D `low_today == low_prev` is normal. **Use `market_price` / `mkt_pct_*` for short-window (≤7d) movement detection**; reserve `low_price` for medium-to-long windows where the buy-it-now floor matters more than transaction noise.
- Low price can also be contaminated by foreign-language listings — prefer Market when in doubt, but for set-level averages the `processData` fallback means Low is more inclusive.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded TCGPlayer URL>`. The `tcgUrl()` helper wraps every TCGPlayer link site-wide — never link directly to `tcgplayer.com/product/...`. Mass-entry carts use `https://www.tcgplayer.com/massentry?productline=Lorcana TCG&c=4 Name||4 Name` routed through the same affiliate wrapper.
- **Lorcast's API key for "is this card inkable" is `inkwell`, not `inkable`.** Our column is named `inkable`; the ETL has to translate. Backfill: `scripts/patch_inkable.py`. Same pattern: `inks` array uses `inks` directly.
- **Image sizes**: Lorcast publishes `small` (200w), `normal` (400w), `large` (734w). All three are stored in `cards`. Use `img_normal` for tiles ≤200px wide; `img_large` for hover previews / detail modals / poster export; `img_small` only for thumbnails ≤80px. **`img_large` is NOT in the catalog localStorage cache** (stripped on write to save ~30% size); fetch sites that prefer it fall back to `img_normal` gracefully — verify on existing call sites before adding new ones.

## CSS pitfalls

- **`mask-image` on a container softens its child `<img>` elements.** The mask forces an offscreen compositing layer that rasterizes children at the layer's pixel ratio, visibly blurring AVIF / hi-res photos. Use absolutely-positioned gradient pseudo-elements (`::before` / `::after`) for edge-fade effects instead. Same caution applies to `will-change: transform`, `filter: blur(0)`, `transform: translateZ(0)`, `opacity: 0.99` — all known compositing-layer triggers.
- **`image-rendering: crisp-edges`** is for pixel-art sprites. It disables smooth bilinear interpolation and makes downsampled card art look blocky/jagged. Default `image-rendering: auto` is correct for photos.
- **`--bg-card` is translucent in dark mode** (`rgba(255,255,255,0.06)`). Don't use it for modal/popup backgrounds — they'll be unreadable in dark mode. Use **`--bg-modal`** (opaque in both themes) for the `.modal` and `.name-prompt` containers. Tooltips/popovers intentionally use translucent surfaces over the page bg and render fine.
- **Conditional grid cells break grid-template-columns alignment.** If a grid-row JSX renders `${condition && html\`<img class="cell"/>\`}` for one of its columns, the cell vanishes when condition is falsy → all subsequent cells shift left. Always render a wrapper element for the slot, conditionally render the content inside it. The set-detail row's rarity icon slot uses `<span class="sd-row-rarity-slot">${RARITY_ICONS[r] && html\`<img.../>\`}</span>` for exactly this reason.

## Conventions

- No comments unless the *why* is non-obvious. No multi-line docstrings.
- Don't add backwards-compat shims when you can just change the code.
- Set release dates: two flags per set — `LGS Release` and `Retail Release`. Source: Wikipedia.
- "<$1 → $0" toggle: cards under $1 count as 0 **before** averaging (mirrors `avg_low_nc` / `avg_market_nc`).
- Earliest price data: 2024-02-08. Sets released before that show a `*` asterisk note.
- Time display: `relativeTime(iso)` for compact ("2d ago"), `absoluteLocalTime(iso)` for the hover tooltip. Both use the browser's local time zone — `timestamptz` carries the offset, `new Date(iso).toLocaleString()` handles the conversion.

## Browser back/history pattern

Sub-pages within a top-level view (deck detail inside Decks, set detail inside Collection, tournament detail inside Decks, viewer-mode collection) push their own history entries so browser back returns to the parent grid instead of jumping to the previously-active top-level view.

- **Entering a sub-page**: `window.history.pushState({...}, "", url-with-param)` BEFORE the state update. Query param convention: `?deck=<id>`, `?set=<name>`, `?tourney=<id>`, `?user=<uuid>`, `?collection=<uuid>` (+ optional `&token=<x>` for unlisted decks/collections).
- **Popstate listener inside the view**: reads the URL param and syncs `selectedDeckId` / `selectedSet` / `selectedTournamentId` state. Always present per-view (`CollectionView`, `DecksView`) so back/forward works within that view's sub-pages.
- **Existing wrappers**: `openDeckInMode(id, mode)` and `openTournament(tid)` in `DecksView`; the `useEffect` watching `selectedSet` in `CollectionView`. Add new sub-page navigation through one of these patterns or you'll regress the back button.
- **Top-nav clicks strip view-specific deep-link params.** When `view` changes via the top nav, the App-level URL sync effect removes `?deck`, `?token`, `?user`, `?collection`, `?set`, `?tourney` from the URL before pushing the new pathname. Otherwise navigating Collection viewer → Home would leave a stale `?collection=…` hanging. Each sub-view's own URL-sync effect re-adds the right param on entry.

## SQL editor syntax

Postgres functions are invoked from a `SELECT`, not as bare statements. Calling `refresh_card_prices_latest()` directly in the Supabase SQL editor errors with `42601 syntax error`. Use:

```sql
SELECT public.refresh_card_prices_latest();
SELECT public.refresh_rarity_avg_daily();
SELECT public.refresh_price_movers();
SELECT public.refresh_sealed_prices_latest();
SELECT public.refresh_graded_prices_latest();
```

## Smart-search numeric stat operators

`parseSearchQuery` accepts equality + comparison for `cost`, `strength`, `willpower`, `lore`. The numeric value lives at `filters[statKey]` (back-compat with the old equality-only contract); the operator lives at `filters[statKey + "Op"]` (`=`, `>`, `>=`, `<`, `<=`, defaults to `=`). Forms accepted: `lore 3` / `3 lore` (equality), `lore>=2`, `lore >= 2`, `lore2` (no space). Matchers in `matchesCardFilter` and the Cards-browse `cardMatches` use a small `_cmp(rowVal, want, op)` helper. Rows with the stat as null fail any non-null filter (a card with no lore stat can't satisfy `lore>=2`).

Catalog requirement: `cards.strength / willpower / lore / move_cost` columns must exist (migration 43). The catalog fetch probes the `lore` column on cold load and silently omits all four from `CARDS_COLS` if the migration hasn't been applied — filters then become no-ops rather than throwing.

## Screener saved views

`screener_views(user_id, name, payload jsonb)` — owner-only RLS. Hydrated on sign-in (newest-first); local-only views are migrated up on first sign-in if the remote table is empty. `saveCurrentView` / `deleteView` write to Supabase when `user` is present and mirror to localStorage unconditionally for the unauth fallback. If migration 44 isn't deployed (PostgREST returns 42P01), the client logs a one-time warning and stays on the localStorage-only path.

## parseDeckText scoring

The "paste a decklist" parser (used by Bulk Upload + import deck text + tournament rows) resolves a card NAME to a `card_id` via a per-name lookup. Multiple printings can share a Product Name once Challenge Promo / D23 / Lorcana Challenge Promo (C2) enter the catalog AND chase rarities (Enchanted #200ish) share the name with their base.

Scoring rules in `parseDeckText`:

- `+100` if `Set ∈ MAINLINE_SETS`
- `-80` if `Rarity ∈ {Enchanted, Iconic, Epic}` (chase printings share the base name; demote so the base wins inside one set)
- `-60` if `isCustomVariant` (Genie / Peter Pan error variants)
- `-40` if `isCustomCard` (legacy stub flag)
- `-20` if any `variant_label` is present

Highest-scoring candidate wins. Tiebreaker is iteration order. Verified: Cinderella - Stouthearted resolves to Rise of the Floodborn #177 (Super Rare) instead of Challenge Promo #42 or the Enchanted at #200ish.

## Collection value chart: prerelease guard

TCGPlayer pre-release prices for new sets are wildly inflated — often 10-20× the post-release floor. `computeCollectionValueHistory` accepts an optional `productEarliestDate` map (`tcgplayer_product_id → "YYYY-MM-DD"`); any prices_daily row with `date < earliest[pid]` is dropped before the rollup. `CollectionPanel` builds the map from `setsMeta.released_at + 1 day`, filtered to MAINLINE_SETS only (promos/D23/Challenge stay unfiltered — they don't have a "spike" pattern). Cache key bumped to `packsink:colvalue:v2:` so stale unguarded series get invalidated.

## Performance gotchas

- The Cards browse / deck-builder grid renders 1500+ tiles. **Three layers** make this fast:
  1. Two-stage memoization (`allGroups = useMemo(groupCards(raw))` then filter the groups) keeps group references stable across filter changes.
  2. `CardTile` is wrapped in `React.memo` so unchanged tiles skip re-render. The callbacks flowing into `CardBrowser` (`onSelectGroup`, `deckQty`, `onDeckQtyChange`) must be stable (`useCallback`) — otherwise the memo busts.
  3. CSS `content-visibility: auto` + `contain-intrinsic-size` on `.card-tile` / `.card-row` lets the browser skip layout/paint for off-screen tiles. Combined with `useDeferredValue(filter)`, ink-filter toggling stays responsive even when going from 250 visible back to 1500.
- The Collection-value chart caches the *computed* series (not the raw rows) in `localStorage` under `packsink:colvalue:{userId}:{productsHash}:{rangeKey}`. Hydrates synchronously on mount so the chart paints immediately and refreshes in the background.
- The Screener table caps rendering at 1,000 rows; users tighten filters to see beyond. Could promote to virtualized scrolling if catalog grows past ~10k tracked cards.
- **Per-view banners (movers / Following / tournaments / screener-movers) cache to localStorage** with their own TTLs so tab switches don't refire heavy queries. See "Client cache rules" for the keys. Each banner's effect hydrates from cache instantly and only background-refreshes when stale.
- **Per-card price history caches to localStorage** (`packsink:hist:v1:{productId}:{printing}`, 12h TTL) inside `fetchCardHistory`. The original anon `prices_daily` history fetch was 89% of total Supabase query time per the query-performance report; the cache collapses repeat views.
- **Top-of-cold-load parallelization**: the `cards.inks` and `cards.illustrators` schema probes run via `Promise.all` (were sequential). `FollowingFeed`'s initial `user_follows` + `deck_favorites` queries also parallel. `FollowingFeed`'s effect depends on `[user]` only (not `raw`) so it kicks off in parallel with the catalog fetch — saves 2-3s on cold loads.

## Ops

- **GitHub Actions cron** (`.github/workflows/etl.yml`): one consolidated daily trigger at 21:00 UTC. The `prices` job runs first; `graded` (`needs: prices`) runs sequentially after. Sundays 22:00 UTC fires the Lorcast metadata refresh separately. **Heads-up: GitHub auto-disables scheduled workflows after 60 days of repo inactivity** — push at least monthly or you'll lose the cron silently. Also: two close-together schedules silently drop one on the free tier — keep both daily jobs on the same 21:00 trigger.
- **Matview self-heal cron** (`.github/workflows/etl.yml` `selfheal` job, schedule `15 * * * *`): every hour at :15, runs `scripts/matview_self_heal.py` which compares `card_prices_latest.max(price_date)` to `prices_daily.max(date)`. No-op when matview is already current; calls the four `refresh_*` RPCs when behind. Catches the failure mode where the main ETL successfully upserts `prices_daily` but its inline matview refresh silently fails (the entire site then serves yesterday's prices for up to 24h). Footer also flashes a pill when the client detects the mismatch.
- **Dev server cache header**: `scripts/dev_server.py` sends `Cache-Control: no-store` on HTML/CSS/JS responses. Chrome's disk cache otherwise serves stale assets even after the file changes — this stops that in dev. Production uses normal Netlify cache rules.
- **`scripts/patch_pid_overrides.py`** is the bridge between client-side `TCG_PID_OVERRIDES` and the `cards` table. Re-run after editing the map in Index.html or after adding new synthetic Lorcast-missing cards. Idempotent.
- **Sentry browser SDK** loaded via CDN in `<head>` of `Index.html` (loader script, lazy init on first error). User attribution via `Sentry.setUser({id, username})` on auth state change.
- **UptimeRobot** pings the prod URL every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest`'s max(price_date) on App load and flashes ⚠ if > 36h behind.
- **Duplicate-snapshot guard in `etl_tcgcsv_daily.py`** — refuses to write a snapshot that's >95% byte-identical to yesterday's. Pass `--force` to override. TCGCSV occasionally re-serves yesterday's file when its daily cron hasn't fired yet; the guard prevents polluting prices_daily.
- **Required GitHub Actions secrets**: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `TCGPRICELOOKUP_API_KEY`. Missing the third makes the consolidated workflow's graded job fail with "api_key required".
- **PWA / service worker** (`sw.js`, registered from `<head>` of Index.html, scope `/`): caches the app shell (Index.html, styles.css, logo.js, manifest, icons) and Lorcast card images. Data APIs (Supabase, TCGCSV, Lorcast metadata, qrserver) are explicitly bypassed so they always hit network. **Bump `CACHE_VERSION` in sw.js any time Index.html / styles.css / logo.js changes meaningfully** — without the bump, installed clients serve the old cached shell until the SW happens to update on its own (up to 24h). Current version: `packsink-v5`. The activate handler purges any cache key that doesn't match the current version. Pre-cache uses `cache.add().catch(null)` per asset so a missing file (e.g. renamed icon) doesn't abort install. `manifest.json` and the `/icon-*.png` / `/favicon-*.png` / `apple-touch-icon.png` files all live at the repo root and must NOT be moved (the manifest references absolute paths).
- **Catalog cache version**: `packsink:catalog:vN` in localStorage. Bump N (in `Index.html`'s `CACHE_KEY` const) whenever cached row shape OR the meaning of cached rows changes (e.g. promo rarity override added → existing cache shows old rarities for ~24h until TTL). Current version: `v39`. CLAUDE.md's "Client cache rules" section above has the longer rationale.
- **Privacy policy page** — standalone `privacy.html` at repo root. Served as-is by Netlify (real file beats the SPA fallback). Pretty URL `/privacy → /privacy.html` via both `_redirects` and `dev_server.py`. Static HTML payload is required because Google's OAuth consent verification crawler doesn't execute JavaScript — the React footer's `<a href="/privacy">` is invisible to it. There's also a `<noscript>` block + visually-hidden `<a>` in `Index.html`'s body so the home page's static HTML contains a privacy link. FAQ's "Privacy policy" section mirrors the same content for in-app readers. Linked URL to put in Google Branding form: `https://packs.ink/privacy`.

## Disclaimer

Lives only on the **How It Works** page. One paragraph: "Packs.Ink is an unofficial fan site. Disney Lorcana TCG is a trademark of Disney; the game is operated by Ravensburger. This site is not affiliated with, endorsed by, or sponsored by Disney or Ravensburger." The Affiliate Disclosure section (a few headings above) covers the monetization side.

## Brand assets

- `Logos/` ships at runtime — that's the only image folder that's part of the deploy.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons used in filter chips + deck-list cards.
- `Logos/packs-ink-logo.png` — site wordmark (top bar).
- `Logos/Logo on Black.png` — Ink & Lore footer logo (base64-embedded as `LOGO_B64`).
- Custom-drawn SVG glyphs (NOT extracted from card art): `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` in Index.html. Built from a shared `<HexFrame/>` so all three families render with identical geometry.
- The original Ravensburger media kit (3.3 GB of source zips + extracted assets) is **not** in the repo. Re-download from Ravensburger's brand portal if needed.

## Pending / roadmap

**Top of the list:**

- **Domain transfer Netlify → Name.com → (optional) Cloudflare** to enable Cloudflare WAF + Bot Fight Mode in front of Netlify. Blocked until **2026-06-08** (ICANN 60-day post-registration lock). Netlify only transfers to Name.com per their partnership; from Name.com we'd flip nameservers to Cloudflare.
- **Card scanner (phone)** — vision-based identification. Scan a card → identify → show current price + history.

**Nice to have:**

- **Sim a pack inline button** on each row in Playset Cost / Set Values — folds Pack/Box Sim from a destination into a contextual action.
- **Deck-list cost-curve sparklines** on the Decks tab list (currently only in the editor).
- **More Extras & Oddities curation** — re-run the audit scripts periodically; user has to triage case-by-case.
- **Floor-coverage indicator** on Screener — distinguishes "1 lonely listing" from "10 sellers all at the floor". Needs a different upstream (TCGCSV's `/products` endpoint, not just /prices).
- **Stale-data warning per row** on Screener — flag rows whose `low_today` is more than 3 days old. `is_stale` exists on `card_prices_latest` but not on `price_movers` yet.

**Quality / operational:**

- **Re-run the index usage audit** ([supabase/diagnostics/index_usage_audit.sql](supabase/diagnostics/index_usage_audit.sql)) once stats age past ~13 days, drop anything confirmed unused.
- **EV % change pills can underreport for the newest set.** `evFromBucket` reads `rarity_avg_daily` directly with no Low↔Market fallback (the fallback only lives in client-side `processData`). Fix would be either a server-side fallback in the matview definition or a two-pass client-side fetch.
- **Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6** in `etl.yml` to clear the Node.js 20 deprecation warning.

**North-star framing**: "the ultimate place to check what new cards cost and how the market is moving." Every feature decision should ladder up to that — surface prices and price movement, not deckbuilding theorycraft.
