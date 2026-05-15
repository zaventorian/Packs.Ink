# Handoff — 2026-05-13

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-12 → 2026-05-13)

The site grew a Home page, a Collection-value tracker, a full Decks tab + builder, and a major catalog cleanup pass. We also fixed enough Supabase / cache / RLS edge cases that the data layer is now meaningfully more reliable. Cache version now `v18`.

## What landed (in rough order)

### Home page redesign
1. **Two scrolling movers banners** (Chase / Rare-Legendary) backed by the new `price_movers` matview. Time-window + gainers/droppers + pause toggle.
2. **Most Valuable banner** at the top of Home — top 20 main/chase cards from the newest mainline set with prices.
3. **Right-side Collection panel** (sticky) — current value, range-bucketed line chart (1M/3M/6M/1Y/All), in-panel "Your Top Movers" mini-table with its own window/direction controls.
4. **Collection-value chart caching** — `packsink:colvalue:{userId}:{productsHash}:{rangeKey}` in localStorage. Hydrates instantly on mount; background refreshes. No more "loading…" on tab return.

### Decks tab (new)
5. **`supabase/13_decks.sql`** — `decks` + `deck_cards` tables with RLS scoped to `user_id`.
6. **Decks list view** — grid of decks with name, cards/60, total $, owned %, rename / duplicate / delete actions.
7. **Deck editor** — left: shared `CardBrowser` (mainline-only) with +/- counter overlay on each tile; right: sticky panel with stat tiles + cost-curve / color / inkable / type pies + per-section card list.
8. **Auto-detected format badge** — Core Constructed (green) / Infinity (gold) / Invalid Deck (red), computed from `MAINLINE_RELEASE_ORDER` + the standard 60/4/2-ink rules. No user dropdown.
9. **Inline editable deck name**, duplicate-as-"Copy of X" with toast, import/export plain-text decklists, Save indicator (`Saved ✓` / `Saving…`).

### Catalog correctness (`transformSupabaseData`)
10. **`EXTRAS_SET_NAME`** (Extras & Oddities) added as a synthetic set bucket. 17 curated entries:
    - 12 starter-deck-exclusive foils (Wilds Unknown / Fabled / WitW — 4 each)
    - 5 Illumineer's Quest: Deep Trouble cards (Half Hexwell + 4 from Ursula's Return). Piglet uses `standalone` metadata since Lorcast doesn't index him.
11. **`CONNECTING_FOILS`** map — 24 cards whose foil is a separate TCGPlayer SKU (Winterspell connecting art + Wilds Unknown connecting art + Reign of Jafar extended-art `Nf`-numbered foils). Companion products are suppressed from the main loop; their image overrides the base card's foil-row image.
12. **Holofoil mislabel rule** — non-chase, non-extras cards with a Holofoil row treat that row as their canonical Cold Foil; any separate Cold Foil/Foil row is dropped as stale.
13. **Promo Set 1 / 2 / 3** added to `SET_ORDER` but not `MAINLINE_SETS`. EV / Sim / History / Set Values / Compare / Heatmap / Avg use mainline only; Collection grid + Cards browse include promo sets.
14. **`inkable` column fix** — `load_lorcast.py` was reading `c.get("inkable")` but Lorcast's field is `inkwell`. Backfilled all 2911 rows via `scripts/patch_inkable.py` (bulk PATCH'd by value, ~20 round-trips).

### Performance
15. **`card_prices_latest` → matview** (`supabase/12_card_prices_latest_matview.sql`). Hit Supabase's 10s timeout consistently as a regular view.
16. **CardTile is now `React.memo`** with two-stage memoization (`allGroups = useMemo(() => groupCards(raw))` outside filter pipeline, then filter the groups). Stable group refs + stable callbacks = filter clicks no longer freeze the grid. Ink-shield clicks feel instant.
17. **`sbFetchAll` retry wrapper** — 3 retries with exponential backoff on 5xx / network errors. The intermittent 57014 timeouts on `prices_daily` queries quietly resolve themselves now.

### Auth / persistence fixes
18. **Collection fetch paginates** — was silently truncating at 1000 rows. CSV imports of large collections kept "disappearing on refresh" because the read-back missed everything beyond row 1000.
19. **`bulkUpdateCollection` hardening** — dedupes by (card_id, printing) before upserting (was failing the `ON CONFLICT DO UPDATE` "cannot affect row a second time" rule). `.select()` + count-check on every chunk so RLS / trigger filters can't silently drop rows.
20. **`supabase/11_drop_collection_card_fk.sql`** — dropped the `collection_items.card_id` FK so synthetic card IDs (`extras:...`) can be saved without violating the constraint.
21. **`updateDeckCard` / `updateDeckMeta`** — optimistic local update + Supabase write + rollback on failure + in-flight counter wired into the `Saved ✓ / Saving…` badge.

### UI polish
22. **Custom tooltip system** — `<Tip text="...">` portal-rendered to body, escapes overflow:hidden ancestors. Replaced native `title=` (which had ~1s delay) everywhere it mattered.
23. **Combined profile/settings button** — top-bar avatar+name opens a popover with: profile-card chooser, tooltips toggle, sign in/out. Replaces the old separate gear + profile buttons.
24. **Card-as-avatar** — `avatarCardId` synced to localStorage + Supabase user_metadata. Falls back to Google avatar with `onError` so the broken-image icon doesn't show, then to a first-initial circle.
25. **Ink shield icons** in filter chips (96px PNGs from Ravensburger media kit, in `Logos/inks/`).
26. **Custom SVG hex glyphs** — `<HexFrame/>` + `<InkableHex/>` (six-petal gold filigree) + `<UninkableHex/>` (dim empty hex) + `<CostHex/>` (numbered). All inline SVG, no external assets, drawn from scratch.
27. **Card browser list view** — 3-column grid matching the Collection set-detail layout, with image thumbnail + name + meta + price chips + optional +/- counter. Toggle persisted to localStorage.
28. **Clear-filters button** in the toolbar when `activeCount > 0`. Cost row forced onto its own line below the ink row.
29. **Hover preview** in Collection set-detail rows — floats a 210px card image near the cursor, portaled to body.

### Misc
30. **`supabase/10_price_movers_matview.sql`** — promoted price_movers to a matview after the regular view hit timeout. Includes 1d/7d/30d/90d/180d/365d snapshots + both low and market Δ%.
31. **`supabase/08_stale_price_fallback.sql`** — `card_prices_latest` surfaces the most recent non-null price even if the card was missing from today's snapshot. Adds `is_stale` flag.
32. **`scripts/audit_holofoils.py` + `audit_connecting_foils.py` + `audit_missing_foils.py`** — re-runnable audits for the EXTRAS_MAP / CONNECTING_FOILS curated lists.
33. **Brand asset unpack** — `Art Assets/unzipped/` extracted from the Ravensburger media kit (logos, ink shields, set posters, web banners, product photography for S10–S13).
34. **Minimal disclaimer** added to the bottom of the How It Works page (one paragraph identifying the site as unofficial).

## Blocked / waiting on user

- **Run `supabase/11_drop_collection_card_fk.sql`** — required so synthetic card IDs (Extras & Oddities, `extras:<pid>`) can be saved in `collection_items`. User confirmed this was run, but a fresh deployment would need it.
- **Run `supabase/12_card_prices_latest_matview.sql`** — promotes `card_prices_latest` to a matview. Required to avoid the 10s statement timeout on the home-page catalog fetch.
- **Run `supabase/13_decks.sql`** — required for the Decks tab to function. Site shows a "table not in schema cache" error without it.

## Verified

- Cache slim (v18), all sets rendering with the cleaned-up counts.
- Decks tab end-to-end: create / rename inline / add cards / duplicate / delete / import / export / format badge.
- Ink filter no longer freezes when toggled.
- Inkable column populated for all 2911 cards (2205 Inkable, 706 Uninkable).
- Reign of Jafar shows 204/204 foil (was 209 from the extended-art duplicates).
- Ursula's Return shows 204 normal/foil (was 207 from Deep Trouble cards leaking through).
- Wilds Unknown shows full foil prices on all 15 connecting-art cards.
- Fabled shows 205 normal cards (the cn=0 card is real Lorcast data, not a bug).

## Next up (priority order)

1. **Tier 2 schema** — `strength` / `willpower` / `lore` columns + matching smart-search filters.
2. **Buyout badge** on tiles when `low_price` jumps a large % day-over-day (prior_low ≥ $1 floor). Surfaces on Home banners + as a card-tile badge.
3. **Deck legality auto-fix suggestions** — "your deck is 57 cards, here are 3 candidates to add."
4. **Public deck sharing** — read-only deck URLs via a separate `public_decks` table or signed URL.
5. **Deck stats on list view** — small cost-curve sparkline per deck card on the Decks list page.
6. **More Extras & Oddities curation** — the audit scripts surface candidates; user has to triage case-by-case.

## Useful invariants when debugging

- If Collection counts go wrong: first suspect cache version, then pagination ordering, then the `transformSupabaseData` mislabel/EXTRAS/CONNECTING_FOILS rules, then catalog-vs-prices merge direction.
- If a filter feels laggy: check that callbacks flowing into CardBrowser are wrapped in `useCallback` (busts `React.memo` otherwise). Two-stage memoization (`allGroups` then `grouped`) must stay intact.
- If decks can't save: run `supabase/13_decks.sql`. If specific card IDs fail (synthetic), run `supabase/11_drop_collection_card_fk.sql`.
- If Supabase returns 500 / 57014 on home-page load: `card_prices_latest` matview probably stale (or doesn't exist). ETL refreshes it; or run `supabase/12_card_prices_latest_matview.sql`.
- If cache write throws `QuotaExceededError`: a heavy field snuck back into the cached row shape. Strip it and bump `CACHE_KEY`.
- If a card filter (e.g. Inkable) returns weirdly few results: suspect a column population issue. `scripts/patch_inkable.py` was the model for backfilling a single column without rerunning the full Lorcast load.

## Files most recently touched

- `Index.html` (~6000 lines) — Home page + Decks tab + EXTRAS_MAP + CONNECTING_FOILS + CardBrowser refactor + perf memoization + custom hex SVGs + ink-icon chips + clear-filters button + cost-row break
- `supabase/10_price_movers_matview.sql`, `11_drop_collection_card_fk.sql`, `12_card_prices_latest_matview.sql`, `13_decks.sql`
- `scripts/etl_tcgcsv_daily.py` — now refreshes all three matviews
- `scripts/load_lorcast.py` — `inkable` field bug fixed (was reading wrong key)
- `scripts/patch_inkable.py` (new), `audit_holofoils.py` (new), `audit_connecting_foils.py` (new), `audit_missing_foils.py` (new)
- `Logos/inks/{AMBER,AMETHYST,EMERALD,RUBY,SAPPHIRE,STEEL}.png` — official ink shields, 96px
- `Art Assets/unzipped/` — extracted Ravensburger media kit (originals untouched as zips)
