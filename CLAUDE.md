# Packs.Ink

Lorcana TCG market + collection app. Affiliate revenue via TCGPlayer (Impact, 3.5%, granted 2026-05-11).

## Stack

- **Frontend**: single `Index.html`, React via `htm` template literals, no build step. Served by `python -m http.server 8765`.
- **DB**: Supabase (Postgres + PostgREST).
  - Tables: `cards`, `sets`, `prices_daily`, `collection_items`, `decks`, `deck_cards`.
  - Materialized views (refreshed nightly by the ETL): `card_prices_latest`, `rarity_avg_daily`, `price_movers`.
- **ETL**: `scripts/etl_tcgcsv_daily.py` pulls TCGCSV, upserts `prices_daily`, then refreshes all three matviews via SECURITY DEFINER RPCs (`refresh_card_prices_latest`, `refresh_rarity_avg_daily`, `refresh_price_movers`).
- **Card metadata**: Lorcast (`scripts/load_lorcast.py`).
- **Local dev preview**: launch config lives in `../Sayumi.Ink/.claude/launch.json` under the `packs-ink` entry (MCP preview reads from session CWD).

## Data flow (non-negotiable)

ETL → Supabase → client fetches once → localStorage cache → render. **Never** API-per-request from the browser to TCGCSV / Lorcast. The cache is the hot path.

## Client cache rules

- Key: `packsink:catalog:vN`. **Bump N whenever the cached row shape changes** — old cache entries are silently ignored on version mismatch. Currently `v18`.
- Quota is ~5MB. Keep slim: don't cache `text`, `flavor_text`, `image_large`, mid/high prices. Modal fetches those on demand by `card_id`.
- Min rows: 4000. Max age: 1 hour.

## PostgREST gotchas

- `sbFetchAll` parallel range pagination **requires an explicit `order=` param** — without it, ranges overlap and rows duplicate. Always pass a stable sort (e.g. `tcgplayer_product_id.asc,printing.asc` for prices, `id.asc` for cards).
- Anything previously a "regular view" that hits `prices_daily` should be a **materialized view**. Statement timeout is 10s; raw views over the ~3M-row `prices_daily` will hit it. `card_prices_latest`, `rarity_avg_daily`, and `price_movers` are all matviews now.
- Matviews need a unique index for `REFRESH CONCURRENTLY`. All three have one; refresh functions fall back to non-concurrent on first run.
- **PostgREST default page size is 1000.** `sbClient.from().select()` silently truncates beyond that. Always paginate `.range()` for tables that could exceed it (collection fetch in App does this).
- **Upserts return `{error}`, they don't throw.** Always check `.error`. For bulk upserts, also add `.select("any_col")` and compare returned count vs sent count — RLS / triggers can silently drop rows otherwise.
- **`ON CONFLICT DO UPDATE` rejects batches with duplicate conflict-target rows.** Dedupe by the conflict key before sending (CSV import learned this the hard way).
- **`sbFetchWithRetry` wraps every fetch** with 3 retries on 5xx — Supabase's 57014 (statement timeout) is intermittent under load.

## Catalog merging — `transformSupabaseData` rules

This is where catalog correctness lives. Three structural cleanups beyond the basic cards+prices merge:

1. **Holofoil mislabel rule** — TCGCSV sometimes publishes a card's in-pack foil under `printing=Holofoil` instead of `Cold Foil` (late-2024+ sets, confirmed via live TCGPlayer listings). When a non-chase, non-extras card has a Holofoil row, that's the canonical foil and any separate Cold Foil/Foil row is suppressed as stale.
2. **`EXTRAS_MAP`** — curated map of `tcgplayer_product_id` → variant info for cards that get promoted to the "Extras & Oddities" bucket. Currently 17 entries:
   - 12 starter-deck-exclusive foils (4 each in Wilds Unknown, Fabled, Whispers in the Well — flagged as Holofoil in TCGCSV).
   - 5 Illumineer's Quest: Deep Trouble cards (Half Hexwell Crown, Mickey Mouse Playful Sorcerer, Yen Sid, Mulan Elite Archer, Piglet Pooh Pirate Captain).
   - `excludeFromBaseSet: true` cards are suppressed from their origin set (Deep Trouble + Half Hexwell Crown).
   - `standalone: {...}` lets us include cards Lorcast doesn't index (Piglet has this).
3. **`CONNECTING_FOILS`** — map of `base_product_id` → `foil_product_id` for cards whose foil version TCGPlayer lists as a separate SKU (connecting-art / extended-art foils). 24 entries across Winterspell, Wilds Unknown, and Reign of Jafar. The foil row is emitted under the base card's `card_id` so the collection slot stays grouped. The companion product is suppressed from the main loop to avoid duplicate rows.

Audit scripts to regenerate these maps: `scripts/audit_holofoils.py`, `scripts/audit_connecting_foils.py`, `scripts/audit_missing_foils.py`.

## Set conventions

- **`MAINLINE_SETS`** = the 13 booster-pack sets (TFC → Attack of the Vines). Used by EV, Pack Sim, Box Sim, Set Values, History, Compare, Heatmap, Average Card Prices, and the Home page "newest set" walk.
- **`SET_ORDER`** = `[EXTRAS_SET_NAME, "Promo Set 1/2/3", ...MAINLINE_SETS]`. Drives the Cards browse, Collection grid, set-membership gates. `reverse()` in the renderer puts mainlines on top and Extras at the bottom.
- **`MAINLINE_RELEASE_ORDER`** = `MAINLINE_SETS` minus unreleased sets. Drives Core Constructed rotation math (`computeCoreSets`) — keeps the two most-recent complete 4-set groups + the in-progress group.
- Decks pick up format automatically (`checkDeckLegality`): structurally legal + all cards in Core legal sets → "Core Constructed"; structurally legal otherwise → "Infinity"; structurally broken → "Invalid Deck".

## TCGCSV / Lorcast notes

- categoryId 71 = Lorcana. Archive starts 2024-02-08.
- Daily snapshot lands ~20:00 UTC.
- Low price can be contaminated by foreign-language listings — prefer market when in doubt.
- Affiliate URL: `https://partner.tcgplayer.com/c/7285926/1780961/21018?u=<encoded TCGPlayer URL>`.
- **Lorcast's API key for "is this card inkable" is `inkwell`, not `inkable`.** Our column is named `inkable`; the ETL has to translate. Backfill script: `scripts/patch_inkable.py` (one-shot, idempotent).

## Conventions

- No comments unless the *why* is non-obvious. No multi-line docstrings.
- Don't add backwards-compat shims when you can just change the code.
- Set release dates: two flags per set — `LGS Release` and `Retail Release`. Source: Wikipedia.
- "<$1 → $0" toggle: cards under $1 count as 0 **before** averaging (mirrors `avg_low_nc` / `avg_market_nc`).
- Earliest price data: 2024-02-08. Sets released before that show a `*` asterisk note.

## Performance gotchas

- The Cards browse / deck-builder grid renders 1500+ tiles. Two-stage memoization (`allGroups = useMemo(groupCards(raw))` then filter the groups) keeps group references stable across filter changes. `CardTile` is wrapped in `React.memo` so unchanged tiles skip re-render. The callbacks flowing into `CardBrowser` (`onSelectGroup`, `deckQty`, `onDeckQtyChange`) must be stable (`useCallback`) — otherwise the memo busts.
- The Collection-value chart caches the *computed* series (not the raw rows) in `localStorage` under `packsink:colvalue:{userId}:{productsHash}:{rangeKey}`. Hydrates synchronously on mount so the chart paints immediately and refreshes in the background.

## Disclaimer

Lives only on the **How It Works** page. One paragraph: "Packs.Ink is an unofficial fan site. Disney Lorcana TCG is a trademark of Disney; the game is operated by Ravensburger. This site is not affiliated with, endorsed by, or sponsored by Disney or Ravensburger." The Affiliate Disclosure section (a few headings above) covers the monetization side.

## Brand assets

- Official Ravensburger media-kit assets live under `Art Assets/` (originals as zips) and `Art Assets/unzipped/` (extracted). The `Logos/` folder holds the curated subset we actually serve.
- `Logos/inks/{AMBER,...}.png` — 96px ink shield icons used in filter chips.
- `Logos/packs-ink-logo.png` — site wordmark (top bar).
- `Logos/Logo on Black.png` — Ink & Lore footer logo (base64-embedded as `LOGO_B64`).
- Custom-drawn SVG glyphs (NOT extracted from card art): `<InkableHex/>`, `<UninkableHex/>`, `<CostHex/>` in Index.html. Built from a shared `<HexFrame/>` so all three families render with identical geometry.

## Pending / roadmap

- **Tier 2 schema**: strength / willpower / lore columns + filters.
- **Buyout badge**: flag cards where **low_price** jumps a large % day-over-day. Threshold TBD (start with maybe +200% in 24h, prior_low ≥ $1 to filter noise). Surface as a badge on tiles and a dedicated "Potential buyouts" banner.
- **Public deck sharing** — read-only deck URLs.
- **Deck cost-curve / pies on the list view** — currently only in the editor.
- **Card scanner (phone)** — lowest priority, last-to-build. Vision: scan a card with the camera → identify → show current price + history.
- **North-star framing**: "the ultimate place to check what new cards cost and how the market is moving." Every feature decision should ladder up to that — surface prices and price movement, not deckbuilding theorycraft.
