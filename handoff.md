# Handoff — 2026-05-16

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-14 → 2026-05-16)

Two-day sprint focused on three large surfaces:

1. **Deck view rebuild** — clicking a deck now opens a read-only view (stats / charts / list) with an ✎ Edit toggle to the card-browser editor. Three list layouts (compact list, image grid, stacked pile), Highlight-Missing toggle, Notes + YouTube embed, owner Shop-on-TCGPlayer CTA with affiliate mass-entry. The deck page is now a real-feeling consumer page, not just an editor.
2. **Dual-ink support** — schema, loader, backfill, and rendering. Dual-ink cards now form their own pie bucket with a neutral color + "dual" tag in the legend, render as a diagonal gradient block in the cost curve, and show a half/half circle next to the card name. Legality counts both colors toward the 2-ink cap.
3. **Screener** — entirely new top-level tab. Morningstar-style financial table of every tracked card with sortable columns, multi-select filters, preset views (Gainers / Losers with window picker, Buyouts, Crashing, Discount, Premium), signal chips, density toggle, pinned name column, saved views, sparklines, multi-card Compare handoff to Price Graphing.

Plus a critical ETL fix and several CSS / quality polish passes.

## What landed (rough order)

### Deck view rebuild

1. **Default-to-view-mode** when clicking your own deck. `DecksView` now uses `openDeckInMode(id, "view"|"edit")` everywhere instead of bare `setSelectedDeckId(id)`. New decks open in edit (empty view would be useless); duplicates open in view.
2. **✎ Edit / ✓ Done toggle** in the toolbar (own decks only). Hides the CardBrowser + inline-rename when in view mode.
3. **Two-column layout** (deck list left ~60%, stats sidebar right ~340px) in view mode. Fixes the previous stretched/fuzzy chart problem from when the panel went full-width.
4. **Three layouts** (View ▾ dropdown): compact list, image grid, stacked pile. Persisted to localStorage. Stacked-pile peeks are 22px tall with each successive layer 1% wider — reads as "physical stack" instead of "stacked JPEGs". Default layout = grid.
5. **Group by + Sort by** dropdowns in the View popover. Group: Type / Color / Set / Rarity / Inkwell / Cost. Sort: Cost ↑↓ / Name / Price ↑↓.
6. **Highlight Missing toggle** — dims owned rows, pops missing ones (red border on grid/stacked; subtle red bg on list). Pairs with an X/Y fraction badge ("1/4" → green when complete).
7. **Per-card ink swatch** next to each card name in the list view: solid circle for single-ink, half/half gradient with hard divider for dual-ink. 14px so the duals are unmistakable.
8. **Missing-tile becomes Shop CTA** — clickable green pill that opens a TCGPlayer mass-entry cart pre-filled with all missing cards (`?productline=Lorcana TCG&c=4 Name||4 Name`), routed through the Impact affiliate URL.
9. **Per-card price chips are affiliate links** — every $ chip in the deck list opens that exact product+printing on TCGPlayer.
10. **Hover preview** in list mode floats a full `img_large` card image near the cursor (portaled to body to escape overflow:hidden ancestors). Pinned to viewport so it never clips at the edges.
11. **Inkable indicator** (small gold/empty hex dot) next to each list-row card name.
12. **Updated timestamp** in the deck header. "Updated 2h ago" with absolute-local-time tooltip.
13. **Notes + YouTube embed** — optional fields in the deck. `📝 Notes` button opens a popover with a textarea + URL input; both commit on outside-click. View-mode renders them in a `.deck-notes-block` under the charts. `youtubeIdFromUrl` extracts video IDs from watch / youtu.be / embed / shorts URLs. Empty fields render nothing.

### Dual-ink card support

14. **Migration `27_card_inks_array.sql`** — adds `inks text[]` to `cards`. Legacy `ink` column kept and populated with `inks[0]` for back-compat.
15. **`scripts/load_lorcast.py`** — writes both `ink` and the full `inks` array.
16. **`scripts/patch_card_inks.py`** — one-shot backfill for rows loaded before the migration. Idempotent. 2911 rows updated across 15 dual-ink combinations on first run.
17. **`CARDS_COLS` includes `inks`**, with a defensive probe in `transformSupabaseData` that drops the column from the SELECT if the migration hasn't been applied — uses a direct `fetch()` to avoid the `sbFetchAll` + limit=1 pagination quirk that produced false-negative 416s.
18. **Cache version bumped to v19**, then **v20** when `image_large` was added.
19. **Dual-ink rendering convention** (durable in CLAUDE.md):
    - Pie: own bucket keyed by joined names ("Emerald/Sapphire"), neutral charcoal fill, "dual" tag in legend.
    - Cost curve: same bucket, but rendered as a 135° diagonal gradient block (large enough to read both colors).
    - Deck row ink swatch: half/half circle with hard divider.
    - Legality: both inks count toward the 2-ink cap.
20. **Inkable / Types pies refreshed** to use vibrant non-ink colors so they don't visually rhyme with the Colors pie.

### Screener (new top-level tab)

21. **Top nav reorg**: `Home · Screener · Price Graphing · Analytics · Cards · Collection · Decks`. "Market" renamed to "Analytics" since none of its sub-pages actually show the market — they analyze it. Internal view key stays `market` so old URLs / state don't break.
22. **`PriceDatabase` component** — sortable table backed by `price_movers`. Columns: image · name + meta · set · rarity · NM Low · NM Market · Δ% (3 windows centered on the selected window; "All windows" toggle to see all 6) · signals.
23. **Presets**: `All`, `Gainers`, `Losers`, `Buyouts`, `Crashing`, `Discount`, `Premium`. Gainers / Losers show a window-chip row (1D / 1W / 1M / 3M / 6M / 1Y). Default = abs(1D Δ) sort, persisted across reloads.
24. **Filters**: search by name, multi-select rarity (selectable button chips), set dropdown. Advanced drawer adds multi-select ink, price range (default min = $5), and Δ% range over any chosen window.
25. **Signals as compact text badges** (BUY / CRSH / DISC / PREM / TRND) — fixed-width, color-coded, generic plain-English tooltips via the existing `<Tip>` component. `priceDbSignals` is module-level so the filter useMemo can reference it without TDZ.
26. **Buyout rule** = any of: 1W ≥ +20%, 1M ≥ +35%, 3M ≥ +60%, 6M ≥ +100%, 1Y ≥ +200%, OR low_today ≥ 1.5× low_30d / 2× low_90d / 3× low_180d. Catches both fast sweeps and quiet supply-tightening runs. Old single-1D rule was missing real buyouts.
27. **Crashing** = 1W ≤ -20%. **Discount** = low ≤ 85% of market. **Premium** = low ≥ 110% of market. **Trending** = 1M ≥ +15% (signal-only, no preset).
28. **Collection-status pills** (All / Owned / Missing) — only shown when signed in. Filters against the existing `collection` map.
29. **Signal-presence chips** as a secondary filter — click BUY to show only cards tagged BUY.
30. **Per-row checkbox + batch actions**:
    - 🛒 Buy on TCGPlayer — affiliate mass-entry cart.
    - 📋 Copy as decklist — `1 Name` lines to clipboard.
    - 📊 Add to Price Graphing — pushes selected cards into the new Compare mode (see below).
31. **Click image or name** → opens the existing `CardDetailModal` with full price history. ↗ link beside the name opens TCGPlayer directly.
32. **Sort-source highlight** — the active sort column has an accent-colored header and accent-glow cell background.
33. **Sticky table header** + **pinned name column** (position:sticky on the Name td/th) so the header stays visible vertically and the name stays visible horizontally during wide table scrolls.
34. **Density toggle** (▤ Compact / ▥ Comfy), **saved filter views** (☆ Save view — captures every filter + preset + sort + density; chip strip at the top to apply/delete), **sparkline column** (toggle reveals an inline SVG line built from the 7 price snapshots already in price_movers — no extra DB fetch), **CSV export** of the current filtered/sorted view (download button).
35. **Multi-card price graphing** — Screener's `Add to Price Graphing` batch action wires `App.startCompareCards(cards)`, flips view to `history`, and `HistoryView` opens its new **Compare** mode. Compare mode fetches each card's history in parallel, renders one LineChart with one colored series per card, supports NM Low / NM Market y-axis toggle, removable card chips in the legend. Capped at 8 cards (chart legibility).

### ETL hardening + diagnostics

36. **Duplicate-snapshot guard in `etl_tcgcsv_daily.py`** — before upserting, the script compares each fetched row against yesterday's `prices_daily` row by (product, printing). If >95% are byte-identical, aborts with a clear message ("TCGCSV likely served a stale snapshot — re-run after 20:00 UTC, or pass --force to write anyway"). TCGCSV occasionally re-serves yesterday's file; without the guard we'd silently pollute prices_daily with a duplicate-day row that zeros out 1D movers downstream for the next 30 days.
37. **Migration `26_price_movers_fix_prev.sql`** — fixes the pct_1d-collapses-to-0 bug for sparse cards. Old definition was `low_prev = most recent non-null low WHERE date < global_max(date)`; for a card whose latest non-null low was 3 days ago, both `low_today` and `low_prev` resolved to the same older snapshot → pct_1d = 0. New definition uses a per-(product, printing) `latest_low_date` CTE and defines prev relative to *that* date.

### Migrations 28 / 29 / 30 — deck features

38. **`28_deck_cards_quantity_99.sql`** — relaxes `deck_cards.quantity <= 4` to `<= 99`. Required for Dalmatian Puppy Tail Wagger (99 cap) and Microbots (unlimited, UI-capped at 99). `SPECIAL_DECK_LIMITS` map in `Index.html` holds the per-card overrides; `checkDeckLegality` sums by Product Name across variants.
39. **`29_deck_youtube_url.sql`** — adds `decks.youtube_url text` for the optional embed.
40. **`30_shared_deck_youtube.sql`** — rebuilds the `get_shared_deck` RPC to include `youtube_url` in its RETURNS TABLE so shared-deck viewers see the embed. `CREATE OR REPLACE FUNCTION` can't change a TABLE signature; have to drop first, then create. Established as the template for "added a deck column, need it in the shared RPC."

### Visual polish

41. **Movers banner mask-image blur fix** — `.movers-wrap` had a CSS `mask-image: linear-gradient(...)` for the edge fade. CSS masks force a compositing layer that rasterizes children at the layer's pixel ratio, visibly softening AVIF card art. Replaced with absolutely-positioned gradient `::before` / `::after` overlays that achieve the same visual fade without compositing children. Captured the insight as `memory/project_css_mask_image_blur.md`.
42. **Banner tile sizing tuned to 138px** with tighter row layout — two banners fit on a typical viewport now. Removed a leftover `image-rendering: crisp-edges` that was making AVIF look blocky (pixel-art mode, wrong for photos).
43. **Image resolution upgrades** — Lorcast publishes `small`/`normal`/`large` (200/400/734w). `CARDS_COLS` now includes `image_large`; deck grid tiles + stacked top use `img_normal`; hover previews and detail modal use `img_large`. Cache bumped v19→v20.

### Memory entries

44. `project_low_price_sticky.md` — TCGCSV `low_price` is a sticker not a sale; use market_price for short-window detection.
45. `project_deck_limit_exceptions.md` — `SPECIAL_DECK_LIMITS` convention and how to add new exception cards.
46. `project_css_mask_image_blur.md` — mask-image / filter / transform on a container blurs child `<img>` via compositing.

## Blocked / waiting on user

None active. Migrations 26-30 should be confirmed run in production Supabase. Patch_card_inks.py should have been run against production once. If a fresh deploy starts from scratch, the sequence is: `27 → patch_card_inks → 28 → 29 → 30 → 26` (26 last so the matview rebuild happens after the column is populated).

## Verified

- Deck view opens by default; Edit toggle flips to builder; brand-new decks open in edit; Save indicator runs in edit only.
- Three deck-list layouts render correctly; +/- counters work in all three.
- Dual-ink card (Ink Geyser) renders: own pie bucket "Emerald/Sapphire" with dual tag; diagonal-gradient cost-curve block; half/half ink swatch on the row.
- Notes + YouTube fields hide when blank; both render in view mode + shared-deck mode after migration 30.
- Dalmatian Puppy / Microbots can go past 4 in the deck builder.
- Buyouts preset now populates (Black Cauldron Cold Foil, Snow White, Scuttle, Mickey Mouse Brave Little Tailor visible).
- Multi-card Compare mode: tick 3 rows in Screener → Add to Price Graphing → all 3 lines render on one chart with removable legend chips.
- Saved Screener views persist across reload; sparkline toggle adds a Trend column.
- CSV export downloads with TCGPlayer URLs.

## Useful invariants when debugging

- **If "Prices may be stale" pill appears**: check `select max(date) from prices_daily; select max(price_date) from card_prices_latest;`. If they diverge, matview refresh failed — check today's GitHub Actions ETL log for `Could not call refresh_*` lines.
- **If 1D movers banner is empty**: it's probably real. TCGCSV's `low_price` rarely moves day-to-day for high-value cards (sticker, not sale). Switch to 1W on the banner toolbar.
- **If today's prices_daily looks identical to yesterday's**: TCGCSV served a stale snapshot. The new ETL guard aborts on this; if it slipped through somehow, re-run after 20:00 UTC.
- **If the Screener Buyouts preset shows nothing**: likely the matview is stale (run `select public.refresh_price_movers();`). The rule itself fires across all six windows + baseline-lift comparisons; if it still shows nothing after a fresh refresh, lower the thresholds in `priceDbSignals` and the buyouts filter in `Index.html`.
- **If `Cannot access 'sigOf' before initialization` in the Screener**: a hooked function got referenced from a useMemo body before its `const` declaration. Move it to module-level (à la `priceDbSignals`).
- **If a shared deck loads as "no longer available"**: share_token rotated or deck flipped private. Owner can regenerate via the Share popover.
- **If the deck Notes save but the video doesn't show for other viewers**: the `get_shared_deck` RPC's RETURNS TABLE is missing `youtube_url`. PostgREST drops fields not declared. Drop + recreate the RPC.
- **If a SECURITY DEFINER RPC says "function X does not exist"**: pgcrypto search_path. Needs `set search_path = public, extensions, pg_catalog`.
- **If a matview refresh hits PG error 57014**: statement_timeout. Either bump the function's pinned `statement_timeout`, drop CONCURRENTLY, or move out of the API path.
- **If PostgREST 404s a freshly-renamed table or new RPC**: schema cache. Run `notify pgrst, 'reload schema';` in SQL editor.
- **If new columns / matview-recreates lose service_role access**: re-grant. `grant select on price_movers to anon, authenticated, service_role` after a `drop materialized view ... cascade`.
- **If banner / Screener images look fuzzy on a particular card**: check for `mask-image`, `filter`, `will-change`, `transform: translateZ(0)`, or `opacity: 0.99` on any ancestor. All trigger compositing-layer rasterization that softens AVIF.

## Next up (priority order)

1. **Tier 2 schema** — `strength` / `willpower` / `lore` columns + smart-search filters (e.g. `lore>=3`). Lorcast exposes the data; mostly a loader update + UI. ~2-3 hours. Unlocks much more useful Cards-tab filtering and a richer Screener.
2. **Deck-list cost-curve sparklines** on the Decks tab list page (already have inline sparklines on Screener — same pattern, fewer data points).
3. **Save Screener views to Supabase** instead of localStorage so they roam.
4. **Stale-data warning per row** on Screener — flag rows whose latest non-null low_today is more than 3 days old.
5. **Floor-coverage indicator** — distinguishes "1 lonely listing" from "10 sellers at the floor". Needs TCGCSV's `/products` endpoint, not just `/prices`.

## Files most recently touched

- `Index.html` (~11k lines) — deck view rebuild, dual-ink rendering, Screener / Price Database, multi-card Compare mode in HistoryView, batch actions, signal badges, density/saved-views/sparklines, nav rename, mask-image fix.
- `supabase/26_price_movers_fix_prev.sql` (new) — fixes per-card prev/today collapse bug.
- `supabase/27_card_inks_array.sql` (new) — adds `inks text[]` column.
- `supabase/28_deck_cards_quantity_99.sql` (new) — relax quantity constraint.
- `supabase/29_deck_youtube_url.sql` (new) — adds `decks.youtube_url`.
- `supabase/30_shared_deck_youtube.sql` (new) — RPC signature update.
- `scripts/etl_tcgcsv_daily.py` — duplicate-snapshot guard + `--force` flag.
- `scripts/load_lorcast.py` — writes `inks` array.
- `scripts/patch_card_inks.py` (new) — one-shot backfill for `inks`.
- `CLAUDE.md`, `handoff.md` — full refresh (this commit).
- `~/.claude/projects/.../memory/` — three new memory entries on TCGCSV semantics, deck-limit exceptions, and CSS mask blur.
