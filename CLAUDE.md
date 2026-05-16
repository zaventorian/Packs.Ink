# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## Stack

- **Frontend**: single `Index.html`, React via `htm` template literals, no build step. Served by `python -m http.server 8765` for dev; **Netlify free tier** for prod (Cloudflare Pages is the natural upgrade if bandwidth hits 100GB/mo).
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog tables**: `cards`, `sets`, `prices_daily`, `sealed_products`.
  - **User tables**: `profiles`, `collection_items`, `sealed_collection_items`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`.
  - **Materialized views** (refreshed daily by the ETL): `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`.
- **ETL**: `scripts/etl_tcgcsv_daily.py` pulls TCGCSV, upserts `prices_daily`, then refreshes all four matviews via SECURITY DEFINER RPCs (`refresh_card_prices_latest`, `refresh_rarity_avg_daily`, `refresh_price_movers`, `refresh_sealed_prices_latest`). Runs via GitHub Actions cron at 21:00 UTC daily (`.github/workflows/etl.yml`). **Aborts when today's fetched snapshot is >95% byte-identical to yesterday's** — TCGCSV publishes ~20:00 UTC and the ETL guard catches the "ran before file dropped" case so we don't pollute prices_daily with a duplicate-day row that zeros out 1D movers downstream.
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed-product catalog**: `scripts/load_sealed_products.py` — pulls every product TCGCSV exposes for category 71, classifies by name, upserts into `sealed_products`.
- **Local dev preview**: launch config lives in `../Sayumi.Ink/.claude/launch.json` under the `packs-ink` entry (MCP preview reads from session CWD).

## Top-level nav

`Home · Screener · Price Graphing · Analytics · Cards · Collection · Decks`

- **Screener** = sortable financial-database-style table of every tracked card (price_movers + filters + signals). Top-level since cards-as-instruments is the north-star surface.
- **Price Graphing** = per-card history charts and a multi-card Compare mode (handoff from Screener's batch action).
- **Analytics** = umbrella for the calculator-y tools (Expected Value, Card Averages, Playset Cost, Heatmap, Sealed, Simulate). Was called "Market"; renamed because none of those sub-pages actually show market data, they analyze it.

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from the browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- Catalog key: `packsink:catalog:vN`. **Bump N whenever the cached row shape changes** — old cache entries are silently ignored on version mismatch. Currently `v20`.
- Sealed-price key: `packsink:sealed:v1`. Bump independently when sealed_prices_latest's SELECT columns change.
- Quota is ~5MB. Keep slim: don't cache `text`, `flavor_text`, mid/high prices. `img_large` IS cached (~730w URLs) since the hover preview / detail modal benefits.
- Min rows: 4000. Max age: 1 hour.

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

## price_movers matview gotcha

The matview computes Δ% across 6 windows (1D / 1W / 1M / 3M / 6M / 1Y) for both low and market. **`low_prev` is "most recent non-null low BEFORE low_today's own date"**, not "before the global max date in prices_daily" — migration 26 fixes this. The old definition collapsed pct_1d to 0 for every card that wasn't priced today, which is most sparse-listing chase cards. If 1D movers ever look broken again, check that the per-card `latest_low_date` CTE is still in place.

## Catalog merging — `transformSupabaseData` rules

This is where catalog correctness lives. Structural cleanups beyond the basic cards+prices merge:

1. **Holofoil mislabel rule** — TCGCSV sometimes publishes a card's in-pack foil under `printing=Holofoil` instead of `Cold Foil` (late-2024+ sets, confirmed via live TCGPlayer listings). When a non-chase, non-extras card has a Holofoil row, that's the canonical foil and any separate Cold Foil/Foil row is suppressed as stale.
2. **`EXTRAS_MAP`** — curated map of `tcgplayer_product_id` → variant info for cards that get promoted to the "Extras & Oddities" bucket. Currently 17 entries:
   - 12 starter-deck-exclusive foils (4 each in Wilds Unknown, Fabled, Whispers in the Well — flagged as Holofoil in TCGCSV).
   - 5 Illumineer's Quest: Deep Trouble cards (Half Hexwell Crown, Mickey Mouse Playful Sorcerer, Yen Sid, Mulan Elite Archer, Piglet Pooh Pirate Captain).
   - `excludeFromBaseSet: true` cards are suppressed from their origin set (Deep Trouble + Half Hexwell Crown).
   - `standalone: {...}` lets us include cards Lorcast doesn't index (Piglet has this).
3. **`CONNECTING_FOILS`** — map of `base_product_id` → `foil_product_id` for cards whose foil version TCGPlayer lists as a separate SKU (connecting-art / extended-art foils). 24 entries across Winterspell, Wilds Unknown, and Reign of Jafar. The foil row is emitted under the base card's `card_id` so the collection slot stays grouped. The companion product is suppressed from the main loop to avoid duplicate rows.
4. **Low ↔ Market fallback in `processData`** — collects samples from both `low_price` and `market_price` columns. When a card has one but not the other (typical for sparse/newest-set rows), the missing side falls back to the present side so it still contributes to rarity averages. The Analytics views' `priceMode` toggle then picks the preferred field per render.

Audit scripts to regenerate these maps: `scripts/audit_holofoils.py`, `scripts/audit_connecting_foils.py`, `scripts/audit_missing_foils.py`. Sealed orphan / catalog audits: `supabase/diagnostics/sealed_product_audit.sql`. Index usage walks: `supabase/diagnostics/index_usage_audit.sql`.

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
- **Image sizes**: Lorcast publishes `small` (200w), `normal` (400w), `large` (734w). All three are stored in `cards`. Use `img_normal` for tiles ≤200px wide; `img_large` for hover previews and detail modals; `img_small` only for thumbnails ≤80px.

## CSS pitfalls

- **`mask-image` on a container softens its child `<img>` elements.** The mask forces an offscreen compositing layer that rasterizes children at the layer's pixel ratio, visibly blurring AVIF / hi-res photos. Use absolutely-positioned gradient pseudo-elements (`::before` / `::after`) for edge-fade effects instead. Same caution applies to `will-change: transform`, `filter: blur(0)`, `transform: translateZ(0)`, `opacity: 0.99` — all known compositing-layer triggers.
- **`image-rendering: crisp-edges`** is for pixel-art sprites. It disables smooth bilinear interpolation and makes downsampled card art look blocky/jagged. Default `image-rendering: auto` is correct for photos.

## Conventions

- No comments unless the *why* is non-obvious. No multi-line docstrings.
- Don't add backwards-compat shims when you can just change the code.
- Set release dates: two flags per set — `LGS Release` and `Retail Release`. Source: Wikipedia.
- "<$1 → $0" toggle: cards under $1 count as 0 **before** averaging (mirrors `avg_low_nc` / `avg_market_nc`).
- Earliest price data: 2024-02-08. Sets released before that show a `*` asterisk note.
- Time display: `relativeTime(iso)` for compact ("2d ago"), `absoluteLocalTime(iso)` for the hover tooltip. Both use the browser's local time zone — `timestamptz` carries the offset, `new Date(iso).toLocaleString()` handles the conversion.

## Performance gotchas

- The Cards browse / deck-builder grid renders 1500+ tiles. **Three layers** make this fast:
  1. Two-stage memoization (`allGroups = useMemo(groupCards(raw))` then filter the groups) keeps group references stable across filter changes.
  2. `CardTile` is wrapped in `React.memo` so unchanged tiles skip re-render. The callbacks flowing into `CardBrowser` (`onSelectGroup`, `deckQty`, `onDeckQtyChange`) must be stable (`useCallback`) — otherwise the memo busts.
  3. CSS `content-visibility: auto` + `contain-intrinsic-size` on `.card-tile` / `.card-row` lets the browser skip layout/paint for off-screen tiles. Combined with `useDeferredValue(filter)`, ink-filter toggling stays responsive even when going from 250 visible back to 1500.
- The Collection-value chart caches the *computed* series (not the raw rows) in `localStorage` under `packsink:colvalue:{userId}:{productsHash}:{rangeKey}`. Hydrates synchronously on mount so the chart paints immediately and refreshes in the background.
- The Screener table caps rendering at 1,000 rows; users tighten filters to see beyond. Could promote to virtualized scrolling if catalog grows past ~10k tracked cards.

## Ops

- **GitHub Actions cron** (`.github/workflows/etl.yml`): daily at 21:00 UTC for prices, Sundays at 22:00 UTC for Lorcast metadata refresh. **Heads-up: GitHub auto-disables scheduled workflows after 60 days of repo inactivity** — push at least monthly or you'll lose the cron silently.
- **Sentry browser SDK** loaded via CDN in `<head>` of `Index.html` (loader script, lazy init on first error). User attribution via `Sentry.setUser({id, username})` on auth state change.
- **UptimeRobot** pings the prod URL every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest`'s max(price_date) on App load and flashes ⚠ if > 36h behind.
- **Duplicate-snapshot guard in `etl_tcgcsv_daily.py`** — refuses to write a snapshot that's >95% byte-identical to yesterday's. Pass `--force` to override. TCGCSV occasionally re-serves yesterday's file when its daily cron hasn't fired yet; the guard prevents polluting prices_daily.

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

- **Tier 2 schema** — `strength` / `willpower` / `lore` columns in `cards` + smart-search filters in the Cards browse (`str>=3`, `lore>=2`, etc.). Lorcast exposes these already; mostly a loader update + UI work.
- **Deck legality auto-fix suggestions** — "your deck is 57 cards; here are 3 candidates to add" based on cost curve / ink balance.

**Nice to have:**

- **Sim a pack inline button** on each row in Playset Cost / Set Values — folds Pack/Box Sim from a destination into a contextual action.
- **Deck-list cost-curve sparklines** on the Decks tab list (currently only in the editor).
- **Card scanner (phone)** — vision-based identification. Scan a card → identify → show current price + history. Lowest priority, last to build.
- **More Extras & Oddities curation** — re-run the audit scripts periodically; user has to triage case-by-case.
- **Floor-coverage indicator** on Screener — distinguishes "1 lonely listing" from "10 sellers all at the floor". Needs a different upstream (TCGCSV's `/products` endpoint, not just /prices).
- **Stale-data warning per row** on Screener — flag rows whose `low_today` is more than 3 days old. `is_stale` exists on `card_prices_latest` but not on `price_movers` yet.
- **Save Screener views to Supabase** instead of localStorage so they roam across devices.

**Quality / operational:**

- **Re-run the index usage audit** ([supabase/diagnostics/index_usage_audit.sql](supabase/diagnostics/index_usage_audit.sql)) once stats age past ~13 days, drop anything confirmed unused.
- **EV % change pills can underreport for the newest set.** `evFromBucket` reads `rarity_avg_daily` directly with no Low↔Market fallback (the fallback only lives in client-side `processData`). Fix would be either a server-side fallback in the matview definition or a two-pass client-side fetch.
- **Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6** in `etl.yml` to clear the Node.js 20 deprecation warning.

**North-star framing**: "the ultimate place to check what new cards cost and how the market is moving." Every feature decision should ladder up to that — surface prices and price movement, not deckbuilding theorycraft.
