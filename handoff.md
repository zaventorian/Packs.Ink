# Handoff — 2026-05-21

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-18 → 2026-05-21)

Three-day stretch with three big themes:

1. **Collection sharing end-to-end** — schema + per-section visibility (raw/sealed/graded), unlisted-link RPCs, viewer mode with avatar + comparison stats, share UI moved from settings popover to a dropdown on the Collection tab.
2. **Tournament admin gets full deck-level control** — add/edit/delete individual decks; bulk-edit modal mirrors the Bulk Upload UI but pre-populates and diff-saves. Discover feed now renders tournament decks with a custom trophy tile instead of "by Anonymous".
3. **Catalog cleanup: Challenge Promo (C1), Palace Heist Extras, Golden Mickey, pid corrections, prerelease guard, image fallbacks.** A lot of long-tail catalog hygiene now codified into scripts/maps so future drops are mechanical.

Plus a couple of foundational refactors: CSS extracted into `styles.css`, base64 logo into `logo.js`, dev server hardened (no-store cache headers + correct launch.json wiring).

## What landed (rough order)

### Code-organization refactors

1. **CSS extracted to [styles.css](styles.css)** — the 2,450-line `<style>` block in Index.html became its own file. Linked via `<link rel="stylesheet">`. Same behavior, better browser caching across deploys, less editor friction.
2. **`LOGO_B64` extracted to [logo.js](logo.js)** — 16.5 KB base64 wordmark moved out of the main script. Loaded before the main `<script>` block so the global is in scope.
3. **`scripts/dev_server.py` now sends `Cache-Control: no-store`** on HTML/CSS/JS responses. Stops Chrome's disk cache from serving stale assets after edits.
4. **Project launch config at [.claude/launch.json](.claude/launch.json) points at `dev_server.py`** (was running `python -m http.server` which has no `/img-proxy/` route). The MCP preview reads from the active project's `.claude/launch.json`, NOT `Sayumi.Ink/.claude/launch.json` as the old CLAUDE.md comment implied. If image copy in deck poster export breaks locally, this is why.

### Collection sharing (Phase 1: schema + viewer)

5. **Migration `39_collection_sharing.sql`** — adds three visibility columns + `collection_share_token` to `profiles`. Trigger rotates the token when all three sections go private. RPCs: `get_collection_visibility(uuid, text)`, `get_shared_collection_raw/sealed/graded(uuid, text)`, owner-only `regenerate_collection_share_token()`.
6. **Three-axis visibility model** — raw / sealed / graded each get their own `private | unlisted | public` enum. The single `collection_share_token` covers all unlisted sections at once; public sections render with or without it. Mix freely: raw=public + sealed=unlisted + graded=private is a supported state.
7. **Read-only `CollectionView` mode** — when `?collection=<uuid>` is in the URL, App fetches via the visibility-gated RPCs and feeds the existing CollectionView component with a `viewerContext` prop. All edit affordances (+/- counters, CSV import, sharing dropdown) gate on `!readOnly`.
8. **`InlineCounter` now shows qty in read-only mode** — previously rendered as an empty div when `onChange` was null, which broke the set-detail grid alignment (no qty visible at all). Now displays a centered qty pill with no +/- buttons.
9. **Viewer banner**: avatar + clickable display name → owner's creator profile (`?user=<uuid>`). First-initial fallback when no avatar.
10. **Comparison stats strip** — when the viewer is signed in, shows `N they own · M we both have · K missing for you` for both Cards and Sealed rows. Color-coded (shared green, missing red). Computed from distinct (card_id, printing) slots.
11. **Comparison filter dropdown** in the viewer banner: `All cards` / `Missing for me` / `We both have` — passed through to `CollectionSetDetail` and applied per-card.
12. **`paginateRpc` helper** wraps the three `get_shared_collection_*` calls — PostgREST caps RPC table-returns at 1000 rows by default, so collections >1000 silently truncated. Now drains via `.range(from, to)` until a short page.

### Collection sharing (Phase 2: UI surfaces)

13. **`CollectionSharingPanel`** component — three section dropdowns, copy-link buttons that only render when public/unlisted exists, "Regenerate unlisted link" (confirm-gated), "Make all private" (revokes everything in one click).
14. **Share dropdown on the Collection tab** — `.collection-share-wrap` next to the section tabs. Click "Share ▾" → panel pops out. Replaces the prior settings-popover placement (closer to where the user thinks about sharing).
15. **"View collection" link on creator profiles** — shows up next to the avatar when the profile owner has at least one visible section.

### Tournament admin: full deck-level editing

16. **Migration `40_tournament_deck_admin.sql`** — three new SECURITY DEFINER RPCs gated on `is_tournament_admin(auth.uid())`:
    - `admin_replace_tournament_deck_cards(result_id, inks, cards jsonb)` — wipes deck_cards for the linked deck and re-inserts; updates `decks.inks`.
    - `admin_add_tournament_deck(tid, place, place_rank, player, deck_name, inks, cards jsonb) returns uuid` — adds a single deck to an existing tournament. Mirrors the per-row portion of `bulk_upload_tournament`.
    - `admin_delete_tournament_deck(result_id)` — removes one deck + its `tournament_decks` row (cascades).
17. **`TournamentBulkEditModal`** — replaces the meta-only `TournamentEditModal`. Same layout as the Bulk Upload modal but with pre-populated rows (single batched `deck_cards` query for all linked decks → back-resolves card_ids to `"N Card Name"` lines). Header fields included. Diff-based save:
    - existing row + meta changed → `admin_update_tournament_deck`
    - existing row + cards changed → `admin_replace_tournament_deck_cards`
    - new row (no result_id) → `admin_add_tournament_deck`
    - removed result_id → `admin_delete_tournament_deck`
    - all unmatched lines surface in one prompt before save
18. **Per-row admin affordances** kept: ✎ Edit single deck, 🗑 Quick delete, + Add deck (one). The "Edit all" button on the header opens the bulk editor.
19. **Discover feed: tournament decks get a custom tile** — when `tournamentByDeckId[d.id]` exists, `renderExternalCard` swaps the byline from "by anonymous" to "by {player_name}" and adds a trophy line: `🏆 Ink Inc Open · 1st · 57p`. New `.deck-card-tourney` styles for the accent-tinted strip.
20. **Tournament detail row CSS bug fixed** — grid layout (`80px 180px 1fr auto`) was on the outer `.tournament-result-row` div, but the spans live inside the inner `.tournament-result-open` button. For non-admin (no admin sidecar div), the grid had nothing to lay out → player/deck text collapsed to invisible. Grid moved to `.tournament-result-open`.

### Catalog data: Challenge Promo (C1) + Palace Heist + Golden Mickey

21. **`SET_DISPLAY_NAMES`** map — Lorcast's `"Challenge Promo"` → display name `"Challenge Promo (C1)"`. Applied in `transformSupabaseData`'s `setName` resolution. Trivial to extend.
22. **`COLLECTOR_NUMBER_OVERRIDES`** map — keyed by `set_id|collector_number`, renumbers Challenge Promo's Lorcast numbering (`#25/41/42/43`) to community numbering (`#1/2/3/4`) for Dragon Fire / Let It Go / Cinderella - Stouthearted / Rapunzel - Gifted with Healing. Applied in `buildRow`.
23. **`UNIFIED_TILE_SETS`** — Set of non-mainline sets whose Collection tile collapses Normal/Foil/Enchanted into a single `Promos X/Y` row. Currently: Promo Set 1/2/3, D23 Collection, Lorcana Challenge Year 3, EPCOT Festival of the Arts. **NOT** Challenge Promo (C1) — that set has a real Non-Foil + Foil split (Prize Wall vs Foil prizes).
24. **`CHINA_ONLY_NONFOIL`** map — `{"Dragon Fire|25": "Logos/cards/dragon-fire-chinese.png", "Let It Go|41": "Logos/cards/let-it-go-chinese.jpg"}`. Non-foil rows for these two cards get `variant_label: "Chinese Exclusive"`, null prices, null `tcgplayer_product_id`, and a locally-hosted image (Lorcast doesn't index the Chinese non-foil art). Backfill emits a synthetic Normal row if TCGCSV only had foil entries for that pid.
25. **Set detail: Foil/Non-Foil section split** for Challenge Promo (C1). `groupsByOrigin` yields two stacked buckets; `renderItems` accepts a `printingMode` override so each section's rows show ONE counter only. `projectForPrinting(g, printingMode)` hoists per-row subtitle + image fields up from `g.normal` / `g.foil` so Chinese-exclusive overrides + custom variant labels render correctly in their printing-specific section.
26. **`scripts/patch_pid_overrides.py`** — pushes the client-side `TCG_PID_OVERRIDES` map into the `cards` table AND upserts synthetic cards rows for products Lorcast doesn't index (Golden Mickey pid 554628, Palace Heist 4 cards: Bolt Superdog 634262, Goofy Groundbreaking Chef 634263, Pinocchio Strings Attached 634264, Elsa Ice Maker 634265). All synthetic cards use `set_id = Ursula's Return` (the Deep Trouble convention). Refreshes `card_prices_latest` matview at the end.
    - Why a script: client-side overrides don't help the matview. `card_prices_latest` is `cards INNER JOIN prices_daily ON tcgplayer_product_id` — if the pid isn't in the cards table, no matview row → no price flowing into the catalog fetch. The script fixes it permanently.
27. **EXTRAS_MAP additions** — 4 new entries for Palace Heist: `634262/63/64/65`, all `originSet: "Illumineer's Quest – Palace Heist"`, `excludeFromBaseSet: true`, with full `standalone` metadata sourced from TCGCSV's `extendedData` field.
28. **`TCG_PID_OVERRIDES` is now authoritative** — was previously a fill-in-null mechanism; now wins over Lorcast even when Lorcast has a (wrong) value. The motivating case was Hiro Hamada Armor Designer #24/24B: Lorcast bound 620276 to #24 but it's actually the Enchanted "Top 8" copy. Two override entries (#24 → 620277 participation, #24B → 620276 Enchanted) now correct the swap. **The override map's `cards` table writes happen via `patch_pid_overrides.py`** — re-run any time you add entries.

### Catalog data: custom variant cards in mainline sets

29. **`CUSTOM_VARIANTS`** const + injection loop in `transformSupabaseData` — for cards Lorcast doesn't index that live inside a mainline set. Each entry: `{baseProductName, baseSet, baseRarity: "Enchanted", variantLabel}`. Clones the base card's row with a distinct card_id (`<base>::variant::<slug>`), `Number` suffix `Error`, `variant_label` field for subtitle rendering, null prices. Currently two entries:
    - Genie - On the Job (Two Swords Variant) — Lorcast says "On the Job" with lowercase "the", case matters.
    - Peter Pan - Pirate's Bane (Text Error) — base = the #215 Enchanted, not the #120 base printing. Hence the rarity filter in the matcher.
30. **`variant_label` surfaces as the row subtitle** in `CollectionSetDetail` (both list + tile views). Extras view's `Rarity` subtitle still works — `g.variant_label || (isExtrasView ? g.Rarity : null)`.

### parseDeckText scoring

31. **Rewrote `parseDeckText`'s name → card lookup** ([Index.html:13105+](Index.html)) — was "first match wins" by Product Name. After loading Challenge Promo + D23 Collection, multiple printings of the same name existed, and iteration order picked the wrong card_id. Now collects ALL candidates per name and picks the highest-scoring one. Scoring:
    - `+100` if Set ∈ `MAINLINE_SETS`
    - `-80` if Rarity ∈ `{Enchanted, Iconic, Epic}` (chase printings within the same set share the Product Name with the base — demote them so the base wins)
    - `-60` if `isCustomVariant`
    - `-40` if `isCustomCard`
    - `-20` if any `variant_label` is present
32. **Verified** — pasting a deck list now resolves Cinderella - Stouthearted to Rise of the Floodborn #177 (mainline Super Rare) instead of Challenge Promo #42; Cinderella - Ballroom Sensation resolves to the Rare #3 instead of the Enchanted; etc.

### Image fallback chain

33. **`buildRow` now falls back across `image_large → image_normal → image_small`** when one is empty. Lorcast occasionally populates only `image_large` (Challenge Promo Dragon Fire / Let It Go / Cinderella / Rapunzel are this way — `small` and `normal` are empty strings). Without the fallback, tiles render with broken-image placeholders.

### Home page polish

34. **Section headers are now clickable nav links**:
    - `Recent set EV` → Analytics (defaults to EV sub-tab)
    - `Your Collection` → Collection tab
    - `Following` → Decks → Following section
    - `Tournament Results` → Decks → Tournaments list
    - Movers banner titles (`Chase Movers`, `Rare-Legendary Movers`, `{Set} · Most Valuable`) → Screener
35. **App-level callbacks** `openView(view)` and `openDecksSection(section)` plumbed through HomeView. The Decks-section variant uses the existing `incomingDeckSection` channel (same plumbing as `openTournamentsList`).
36. **`HomeEvStrip` box-price lookup hardened** — `boxForSet` now prefers `set_id` match against `setsMeta` and falls back to name substring. Picks the lowest matching box across multiple Booster Box SKUs per set. TCGPlayer affiliate link still flows through `tcgUrl()`.
37. **`setsMeta` state fetched independently of the catalog cache** — was previously bundled into the catalog `Promise.all`. But `loadFromSupabase` returns early on a fresh catalog cache hit, which left `setsMeta` empty → broke both the box-price set_id matching AND the new prerelease guard. New independent `useEffect` fetches `sets.id,name,released_at` on every mount, caches to `localStorage["packsink:setsMeta:v1"]` for instant hydration.

### Prerelease spike guard (collection value chart)

38. **`computeCollectionValueHistory(rows, owned, productEarliestDate)`** now accepts an optional 3rd argument: a map of `tcgplayer_product_id → "YYYY-MM-DD"` (release_at + 1 day). Any price_daily row with `date < earliest[pid]` is dropped before the rollup. Promos / non-mainline cards have no entry and aren't filtered. This kills the "20× the real price for two weeks before release" spike.
39. **`CollectionPanel` builds the map** from `setsMeta.released_at` + `raw.set_id`, filtered to `MAINLINE_SETS`-only Sets. Threaded into the `freshSeries` useMemo.
40. **Cache key bumped to `packsink:colvalue:v2:...`** so stale unguarded series get invalidated automatically on next compute.

### Screener tweaks

41. **Graded mode** — `Use Low / Use Market` toggle hidden when `showGraded`. Single header `Graded Price` (replacing `NM Low` + `NM Market` columns). Row click opens `CardDetailModal` with `initialTab="graded"` so the modal lands on the right tab.
42. **Rarity filter order** — most rare → least rare (`Promo / Iconic / Epic / Enchanted / Legendary / Super Rare / Rare / Uncommon / Common`). Was alphabetical.
43. **`▤ Compact / ▥ Comfy` density toggle removed** — kept the state + CSS class default ("comfy") so layout doesn't shift. Just removed the button.

### Graded view polish

44. **Set sections collapsible** — clickable section header toggles, `collapsedSets` persisted to localStorage as a Set of set_ids.
45. **Display mode toggle** — Grid (default, with images) vs Compact (3-column row layout, no images). Persisted to localStorage.
46. **PSA 10 reference price** shown on every tracked-but-not-owned card slot — looks up `<pid>|psa|10` in priceByKey and renders the ebay 7d-avg price next to the "Tracking" pill.
47. **Ink-tinted card tiles** — single-ink cards get a flat ink tint background; dual-ink cards get a 135° gradient across both colors.
48. **Raw price + Buy button** on each tile — `Raw $X.XX` plus a pill `Buy ↗` link that opens the TCGPlayer affiliate URL.
49. **Custom variant suppression** — Genie / Peter Pan error variants share their base's `tcgplayer_product_id`. Their graded reference prices would mislead, so for `isCustomVariant` cards: no price lookups (`priceByKey.get` skipped), no Buy link, variant label appended to the card name inline (`Genie - On the Job (Two Swords)`).
50. **Graded portfolio value chart** at the top of the Graded view — same shape as the Home page's collection value chart but pulls from `graded_prices_daily`. **Watch the column names**: `graded_prices_daily.date` (NOT `price_date`); the `graded_prices_latest` matview renames the column to `price_date` when projecting. The Graded chart's `fetchGradedHistoryFor` + `computeGradedValueHistory` use `date`. Easy gotcha — caused a 42703 error first time around.

### Deck poster export

51. **Cost curve now renders dual-ink cards as half/half gradient slices** — `costBuckets` keys by composite `"Ink1/Ink2"` (was splitting evenly across single-ink buckets, hiding the dual-ink-ness). Gradient defs (`<linearGradient>` in `<defs>` with a hard 50% stop) emitted once per unique dual key. Bar segments stack singles first (in INK_ORDER), then duals alphabetically.
52. **Image copy still depends on the `/img-proxy/*` rewrite** — Netlify's `_redirects` handles this in prod. Locally, it works only when `dev_server.py` is the active dev server (the launch.json fix at item #4).

### URL sync hardening

53. **Top-nav clicks now strip view-specific deep-link params** (`?deck`, `?token`, `?user`, `?collection`, `?set`, `?tourney`) so navigating from a deep-linked Collection viewer back to Home doesn't leave a stale `?collection=` hanging on the URL. Each sub-view's own URL-sync effect re-adds the right param when it owns the destination.

## Migrations applied to prod (run order)

35 → 36 → 37 → 38 → 39 → 40

After applying 40, also run `python scripts/patch_pid_overrides.py` once to upsert the Golden Mickey + Palace Heist 4 synthetic cards rows and patch the TCG_PID_OVERRIDES. Re-run any time `TCG_PID_OVERRIDES` changes in Index.html or new synthetic cards get added.

## Verified

- Collection sharing: per-section visibility persists, viewer mode renders for both anon and signed-in viewers, comparison stats reflect real overlap.
- Tournament bulk edit: editing a row's decklist replaces deck_cards correctly; adding 5 rows in one pass creates 5 new tournament_decks; removing a row cascade-deletes the deck.
- Discover tournament tile renders with trophy line for tournament-linked decks.
- parseDeckText scores correctly resolve Cinderella - Stouthearted to RotF #177 even after loading Challenge Promo. Verified via eval against live catalog.
- Golden Mickey and Palace Heist 4 cards all join through `card_prices_latest` after patch_pid_overrides.py.
- Box prices on Home (4 sets) all show with TCGPlayer affiliate links.
- Prerelease guard: Wilds Unknown (released 2026-05-08) cards now contribute $0 to the collection value chart before 2026-05-09; verified by eval-replaying the rollup with the guard map.
- Tournament detail row layout: non-admin sees player + deck columns correctly aligned.
- Graded chart fetches via `date` column (no more 42703).
- Cost curve dual-ink renders as diagonal half/half splits for both Amber/Emerald and Amber/Steel example decks.

## Useful invariants when debugging

- **If a card's price is missing for a pid that exists in prices_daily:** the matview JOIN didn't fire. Check that `cards.tcgplayer_product_id` matches. Client-side `TCG_PID_OVERRIDES` doesn't help — `card_prices_latest` is `cards INNER JOIN prices_daily`. Run `patch_pid_overrides.py`.
- **If the collection value chart shows pre-release-spike numbers:** `setsMeta` might not have loaded. Check `localStorage["packsink:setsMeta:v1"]` exists; if not, that fetch is broken. The guard only kicks in when both `setsMeta` AND `raw` are populated.
- **If image copy in deck poster export shows empty cards:** `/img-proxy/` is 404ing. In dev, you're running `python -m http.server` instead of `dev_server.py` — check `.claude/launch.json`. In prod, this should never happen (Netlify `_redirects` handles it).
- **If a graded-related query 400s with 42703:** you used `price_date` against `graded_prices_daily`. The raw daily table uses `date`; only the matview `graded_prices_latest` renames to `price_date`.
- **If parseDeckText is matching the wrong printing:** check the score map. Chase rarities (Enchanted/Iconic/Epic) get -80; this is what flips Cinderella - Stouthearted away from the Enchanted #200ish printing and onto the base.
- **If a sealed booster box price isn't showing on Home:** `setsMeta` not loaded OR the set has no Booster Box in the sealed_prices_latest matview yet (Attack of the Vines was unindexed for a while). `boxForSet` now does set_id match first, name substring fallback.
- **If a tournament detail row shows only place + ink shields (no player/deck):** that's the CSS grid bug — make sure the grid lives on `.tournament-result-open` (inner button), not `.tournament-result-row` (outer wrapper).

## Blocked / waiting on user

- Re-run `python scripts/load_lorcast.py` periodically — picks up Lorcana Challenge Year 3, EPCOT Festival of the Arts, and any future Lorcast additions automatically.
- Re-run `python scripts/patch_pid_overrides.py` after editing `TCG_PID_OVERRIDES` in Index.html or after adding synthetic cards. Idempotent; safe to re-run.
- Domain transfer still blocked until 2026-06-08.

## Next up (priority order)

1. **Tier 2 schema** — `strength` / `willpower` / `lore` columns. Lorcast exposes them; this is mostly a loader update + UI work in the Cards browse.
2. **Domain transfer to Cloudflare** after 2026-06-08 — gates the WAF / Bot Fight Mode rollout.
3. **Deck legality auto-fix suggestions** — "your deck is 57 cards; here are 3 candidates" based on cost curve + ink balance.
4. **Save Screener views to Supabase** so they roam.
5. **Card scanner (phone)** — vision-based identification. Lowest priority.

## Files most recently touched

- `Index.html` — collection sharing client surfaces, tournament admin bulk-edit modal, discover tournament tile, Challenge Promo (C1) handling (SET_DISPLAY_NAMES + COLLECTOR_NUMBER_OVERRIDES + UNIFIED_TILE_SETS + CHINA_ONLY_NONFOIL), set detail section split, CUSTOM_VARIANTS, EXTRAS_MAP Palace Heist additions, parseDeckText scoring rewrite, Home section header nav links, HomeEvStrip set_id box matching, setsMeta independent fetch, prerelease guard in computeCollectionValueHistory, Graded view polish (PSA 10 ref, compact 3-col, ink tints, variant suppression), Graded portfolio value chart, Screener graded-mode tweaks + rarity sort, density toggle removal, top-nav URL param cleanup, tournament row grid fix, deck poster dual-ink gradient cost curve.
- [styles.css](styles.css) (new, 2,650+ lines) — extracted from Index.html. Plus new rules for: home-title-link, collection-sharing controls, collection-viewer-banner, collection-compare-stats, deck-card-tourney, gc-set-grid compact, gc-card-raw, tournament-result-open grid.
- [logo.js](logo.js) (new) — base64 logo extracted from Index.html.
- [scripts/patch_pid_overrides.py](scripts/patch_pid_overrides.py) (new) — writes TCG_PID_OVERRIDES into cards table + upserts synthetic cards (Golden Mickey + Palace Heist 4) + refreshes matview.
- [scripts/dev_server.py](scripts/dev_server.py) — added Cache-Control: no-store for HTML/CSS/JS.
- [.claude/launch.json](.claude/launch.json) — pointed at dev_server.py instead of `python -m http.server`.
- [supabase/39_collection_sharing.sql](supabase/39_collection_sharing.sql) (new) — collection sharing schema + RPCs.
- [supabase/40_tournament_deck_admin.sql](supabase/40_tournament_deck_admin.sql) (new) — replace/add/delete tournament deck RPCs.
- [Logos/cards/dragon-fire-chinese.png](Logos/cards/dragon-fire-chinese.png), [Logos/cards/let-it-go-chinese.jpg](Logos/cards/let-it-go-chinese.jpg) (new) — local-hosted Chinese-only print art.
- `CLAUDE.md`, `handoff.md` — refresh (this commit).
