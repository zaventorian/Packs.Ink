# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## Stack

- **Frontend**: single `Index.html`, React via `htm` template literals, no build step. Served by `python -m http.server 8765` for dev; **Netlify free tier** for prod (Cloudflare Pages is the natural upgrade if bandwidth hits 100GB/mo).
- **DB**: Supabase (Postgres + PostgREST).
  - **Catalog tables**: `cards`, `sets`, `prices_daily`, `sealed_products`.
  - **User tables**: `profiles`, `collection_items`, `sealed_collection_items`, `decks`, `deck_cards`, `deck_favorites`, `user_follows`, `deck_views`.
  - **Materialized views** (refreshed daily by the ETL): `card_prices_latest`, `rarity_avg_daily`, `price_movers`, `sealed_prices_latest`.
- **ETL**: `scripts/etl_tcgcsv_daily.py` pulls TCGCSV, upserts `prices_daily`, then refreshes all four matviews via SECURITY DEFINER RPCs (`refresh_card_prices_latest`, `refresh_rarity_avg_daily`, `refresh_price_movers`, `refresh_sealed_prices_latest`). Runs via GitHub Actions cron at 21:00 UTC daily (`.github/workflows/etl.yml`).
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Sealed-product catalog**: `scripts/load_sealed_products.py` — pulls every product TCGCSV exposes for category 71, classifies by name, upserts into `sealed_products`.
- **Local dev preview**: launch config lives in `../Sayumi.Ink/.claude/launch.json` under the `packs-ink` entry (MCP preview reads from session CWD).

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from the browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- Catalog key: `packsink:catalog:vN`. **Bump N whenever the cached row shape changes** — old cache entries are silently ignored on version mismatch. Currently `v18`.
- Sealed-price key: `packsink:sealed:v1`. Bump independently when sealed_prices_latest's SELECT columns change.
- Quota is ~5MB. Keep slim: don't cache `text`, `flavor_text`, `image_large`, mid/high prices. Modal fetches those on demand by `card_id`.
- Min rows: 4000. Max age: 1 hour.

## PostgREST gotchas

- `sbFetchAll` parallel range pagination **requires an explicit `order=` param** — without it, ranges overlap and rows duplicate. Always pass a stable sort (e.g. `tcgplayer_product_id.asc,printing.asc` for prices, `id.asc` for cards).
- Anything previously a "regular view" that hits `prices_daily` should be a **materialized view**. Statement timeout is 10s; raw views over the ~3M-row `prices_daily` will hit it. `card_prices_latest`, `rarity_avg_daily`, `price_movers`, and `sealed_prices_latest` are all matviews now.
- Matviews need a unique index for `REFRESH CONCURRENTLY`. All four have one; refresh functions fall back to non-concurrent on first run.
- **PostgREST default page size is 1000.** `sbClient.from().select()` silently truncates beyond that. Always paginate `.range()` for tables that could exceed it (collection fetch in App does this).
- **Upserts return `{error}`, they don't throw.** Always check `.error`. For bulk upserts, also add `.select("any_col")` and compare returned count vs sent count — RLS / triggers can silently drop rows otherwise.
- **`ON CONFLICT DO UPDATE` rejects batches with duplicate conflict-target rows.** Dedupe by the conflict key before sending — `Supabase.upsert()` now does this automatically.
- **`sbFetchWithRetry` wraps every fetch** with 3 retries on 5xx — Supabase's 57014 (statement timeout) is intermittent under load.
- **RLS broadening trap.** When a SELECT policy includes `OR <some condition non-owner can satisfy>`, an unfiltered `select` returns every visible row, not just yours. Explicitly `.eq("user_id", user.id)` for "my own" reads. (Hit this twice: once when `decks` opened up to public sharing, once with deck visibility leaks via `?visibility=eq.unlisted`.)
- **`NOTIFY pgrst, 'reload schema';` at the end of every migration.** PostgREST caches the schema; renaming a table or adding a function means the API doesn't know about it until the cache reloads. Habit, not tooling.
- **`SECURITY DEFINER` functions must pin `search_path` to include `extensions`** if they use anything from pgcrypto (`gen_random_bytes`, `gen_random_uuid`, etc.). Supabase puts pgcrypto in the `extensions` schema, off the default search path.
- **Long-running RPCs need explicit statement_timeout.** Default role-level cap kills concurrent matview refreshes once the matview grows past ~30s. Every refresh function pins `set statement_timeout = '5min'`.

## Catalog merging — `transformSupabaseData` rules

This is where catalog correctness lives. Four structural cleanups beyond the basic cards+prices merge:

1. **Holofoil mislabel rule** — TCGCSV sometimes publishes a card's in-pack foil under `printing=Holofoil` instead of `Cold Foil` (late-2024+ sets, confirmed via live TCGPlayer listings). When a non-chase, non-extras card has a Holofoil row, that's the canonical foil and any separate Cold Foil/Foil row is suppressed as stale.
2. **`EXTRAS_MAP`** — curated map of `tcgplayer_product_id` → variant info for cards that get promoted to the "Extras & Oddities" bucket. Currently 17 entries:
   - 12 starter-deck-exclusive foils (4 each in Wilds Unknown, Fabled, Whispers in the Well — flagged as Holofoil in TCGCSV).
   - 5 Illumineer's Quest: Deep Trouble cards (Half Hexwell Crown, Mickey Mouse Playful Sorcerer, Yen Sid, Mulan Elite Archer, Piglet Pooh Pirate Captain).
   - `excludeFromBaseSet: true` cards are suppressed from their origin set (Deep Trouble + Half Hexwell Crown).
   - `standalone: {...}` lets us include cards Lorcast doesn't index (Piglet has this).
3. **`CONNECTING_FOILS`** — map of `base_product_id` → `foil_product_id` for cards whose foil version TCGPlayer lists as a separate SKU (connecting-art / extended-art foils). 24 entries across Winterspell, Wilds Unknown, and Reign of Jafar. The foil row is emitted under the base card's `card_id` so the collection slot stays grouped. The companion product is suppressed from the main loop to avoid duplicate rows.
4. **Low ↔ Market fallback in `processData`** — collects samples from both `low_price` and `market_price` columns. When a card has one but not the other (typical for sparse/newest-set rows), the missing side falls back to the present side so it still contributes to rarity averages. The Market analytics views' `priceMode` toggle then picks the preferred field per render.

Audit scripts to regenerate these maps: `scripts/audit_holofoils.py`, `scripts/audit_connecting_foils.py`, `scripts/audit_missing_foils.py`. Sealed orphan / catalog audits: `supabase/diagnostics/sealed_product_audit.sql`. Index usage walks: `supabase/diagnostics/index_usage_audit.sql`.

## Set conventions

- **`MAINLINE_SETS`** = the 13 booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Playset Cost, Price Trends, Card Averages, Heatmap, and the Home page "newest set" walk.
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. Drives the Cards browse, Collection grid, set-membership gates. `reverse()` in the renderer puts mainlines on top and Extras at the bottom.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased sets. Drives Core Constructed rotation math (`computeCoreSets`) — keeps the two most-recent complete 4-set groups + the in-progress group.
- **Newest-first inside Market.** Every Market sub-view (EV, Card Averages, Playset Cost, Heatmap, Sealed) lists sets newest-first via a `setsNewest = sets.slice().reverse()` derived once in `MarketView`. Simulators inherit the same ordering — newest-first reads better in their dropdowns too.
- Decks pick up format automatically (`checkDeckLegality`): structurally legal + all cards in Core legal sets → "Core Constructed"; structurally legal otherwise → "Infinity"; structurally broken → "Invalid Deck".

## Deck sharing model

Three visibility states, each backed by a per-deck `share_token` (22-char URL-safe base64, ~128 bits of entropy):

| Visibility | Direct read RLS | URL behavior | Discovery feed |
|---|---|---|---|
| **Private** | owner only | none (link doesn't work for non-owners) | excluded |
| **Unlisted** | owner only | `?deck=<id>&token=<x>` works for anyone | excluded |
| **Public** | owner OR anyone | `?deck=<id>` works for anyone | included |

Key invariants:

- **Non-owner reads of unlisted decks go through the SECURITY DEFINER `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` RPCs.** These bypass RLS but require the token to match. Defeats the `?visibility=eq.unlisted` enumeration that an `OR visibility != 'private'` policy would expose.
- **Flipping a deck TO Private auto-rotates the share token** via the `rotate_share_token_on_private` trigger. Every in-the-wild share URL stops working instantly. Going back to Unlisted later generates a fresh token.
- **Owner-only `regenerate_deck_share_token(uuid)` RPC** lets users revoke a leaked URL without going through Private.
- **Favorites of unlisted decks** capture the share_token at favorite-time (`deck_favorites.share_token`). The Favorites list fetches via the RPC using stored tokens; rotation/revocation gracefully drops the favorite from the list (it just stops loading).

Discovery surfaces:

- **Favorites** — per-user saved bookmarks of specific decks (`deck_favorites`).
- **Following** — per-user follow of creators (`user_follows`); feed shows recent public decks from followed creators.
- **Discover** — flat newest-first feed of all public decks, paginated by `updated_at` cursor.
- **Creator profile** — `?user=<uuid>` lists that creator's public decks. Reachable by clicking the creator name in any read-only deck banner.

Aggregate metrics (favorite count, view count) are exposed via SECURITY DEFINER RPCs (`deck_favorite_counts(uuid[])`, `deck_view_counts(uuid[])`) that return only totals, never the underlying `(user_id, deck_id)` rows. Privacy preserved.

## Profiles & display names

- Public `profiles` table mirrors the bits of `auth.users` metadata other users need to see ("made by …" on a shared deck).
- **Display name is user-chosen, not Google-derived.** First-time sign-in shows a blocking modal asking the user to pick one (your real name is never auto-applied). Edit later via Settings popover. 32-char check constraint.
- **Avatar is the user's chosen card art, never their Google profile photo.** `AvatarPicker` syncs the picked card's `image_small` URL into `profiles.avatar_url` so other viewers see the same art.

## TCGCSV / Lorcast notes

- categoryId 71 = Lorcana. Archive starts 2024-02-08.
- Daily snapshot lands ~20:00 UTC. ETL cron at 21:00 UTC = 1 hour after.
- Low price can be contaminated by foreign-language listings — prefer Market when in doubt, but for set-level averages the `processData` fallback (above) means Low is more inclusive.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded TCGPlayer URL>`. The `tcgUrl()` helper wraps every TCGPlayer link site-wide — never link directly to `tcgplayer.com/product/...`.
- **Lorcast's API key for "is this card inkable" is `inkwell`, not `inkable`.** Our column is named `inkable`; the ETL has to translate. Backfill script: `scripts/patch_inkable.py` (one-shot, idempotent).
- **Sealed product is product-agnostic.** The TCGCSV `/prices` endpoint returns booster boxes, packs, troves, starter decks alongside singles; the ETL upserts all of them. `sealed_products` catalogues the non-card subset. Loader is `scripts/load_sealed_products.py`, idempotent, classification refinable in the `classify()` helper.

## Conventions

- No comments unless the *why* is non-obvious. No multi-line docstrings.
- Don't add backwards-compat shims when you can just change the code.
- Set release dates: two flags per set — `LGS Release` and `Retail Release`. Source: Wikipedia.
- "<$1 → $0" toggle: cards under $1 count as 0 **before** averaging (mirrors `avg_low_nc` / `avg_market_nc`).
- Earliest price data: 2024-02-08. Sets released before that show a `*` asterisk note.
- Time display: `relativeTime(iso)` for compact ("2d ago"), `absoluteLocalTime(iso)` for the hover tooltip. Both use the browser's local time zone — `timestamptz` carries the offset, `new Date(iso).toLocaleString()` handles the conversion. Japan→Chicago time math is free.

## Performance gotchas

- The Cards browse / deck-builder grid renders 1500+ tiles. **Three layers** make this fast:
  1. Two-stage memoization (`allGroups = useMemo(groupCards(raw))` then filter the groups) keeps group references stable across filter changes.
  2. `CardTile` is wrapped in `React.memo` so unchanged tiles skip re-render. The callbacks flowing into `CardBrowser` (`onSelectGroup`, `deckQty`, `onDeckQtyChange`) must be stable (`useCallback`) — otherwise the memo busts.
  3. CSS `content-visibility: auto` + `contain-intrinsic-size` on `.card-tile` / `.card-row` lets the browser skip layout/paint for off-screen tiles. Combined with `useDeferredValue(filter)`, ink-filter toggling stays responsive even when going from 250 visible back to 1500.
- The Collection-value chart caches the *computed* series (not the raw rows) in `localStorage` under `packsink:colvalue:{userId}:{productsHash}:{rangeKey}`. Hydrates synchronously on mount so the chart paints immediately and refreshes in the background.

## Ops

- **GitHub Actions cron** (`.github/workflows/etl.yml`): daily at 21:00 UTC for prices, Sundays at 22:00 UTC for Lorcast metadata refresh. **Heads-up: GitHub auto-disables scheduled workflows after 60 days of repo inactivity** — push at least monthly or you'll lose the cron silently.
- **Sentry browser SDK** loaded via CDN in `<head>` of `Index.html` (loader script, lazy init on first error). User attribution wired in via `Sentry.setUser({id, username})` post-sign-in. Free tier; no card on file.
- **UptimeRobot** pings the prod URL every 5 minutes; alerts on 2 consecutive failures.
- **ETL stale-data footer pill** queries `card_prices_latest`'s max(price_date) on App load and flashes ⚠ if > 36h behind. Caught a 6-month-running silent bug on 2026-05-14 — the original ETL committed in the bootstrap didn't call the refresh RPCs, and only ran the refresh when invoked locally.

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
- **Buyout badge** — flag tiles where `low_price` jumps a large % day-over-day (suggested: +200% in 24h, prior_low ≥ $1 to filter noise). `price_movers` matview has the data. Surface as a card-tile badge + a "Potential buyouts" home banner. Highest-leverage feature still on deck.
- **Deck legality auto-fix suggestions** — "your deck is 57 cards; here are 3 candidates to add" based on cost curve / ink balance.

**Nice to have:**

- **Sim a pack inline button** on each row in Playset Cost / Set Values — folds Pack/Box Sim from a destination into a contextual action.
- **Deck-list cost-curve sparklines** on the Decks tab list (currently only in the editor).
- **Card scanner (phone)** — vision-based identification. Scan a card → identify → show current price + history. Lowest priority, last to build.
- **More Extras & Oddities curation** — re-run the audit scripts periodically; user has to triage case-by-case.

**Quality / operational:**

- **Re-run the index usage audit** ([supabase/diagnostics/index_usage_audit.sql](supabase/diagnostics/index_usage_audit.sql)) once stats age past ~13 days, drop anything confirmed unused (`sets_released_at_idx`, possibly `collection_items_card_idx`).
- **EV % change pills can underreport for the newest set.** `evFromBucket` reads `rarity_avg_daily` directly with no Low↔Market fallback (the fallback only lives in client-side `processData`). Fix would be either a server-side fallback in the matview definition or a two-pass client-side fetch.
- **Bump `actions/checkout@v4` → v5 and `actions/setup-python@v5` → v6** in `etl.yml` to clear the Node.js 20 deprecation warning. GitHub disables Node 20 actions in September 2026.

**North-star framing**: "the ultimate place to check what new cards cost and how the market is moving." Every feature decision should ladder up to that — surface prices and price movement, not deckbuilding theorycraft.
