# Handoff — 2026-05-14

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-13 → 2026-05-14)

Massive session. The 6+ months of WIP that had been documented in handoff.md but never committed is now in git (commit `8bbc3b5`, pushed to `origin/main`). Major themes:

1. **Audited every layer** — found and fixed a daily ETL bug that had been silently breaking matview refreshes for the entire life of the project.
2. **Reorganized navigation** — Market sub-tab umbrella consolidates the v1 analytics sprawl; Decks gains Favorites / Following / Discover sub-tabs.
3. **Deck sharing shipped** end-to-end — three visibility states, share tokens with auto-rotation, read-only viewer, favorites of unlisted decks, creator profile pages, view counts, favorite counts.
4. **Sealed-product surface** built from scratch — TCGCSV catalog loader, sealed_products + sealed_prices_latest, Market → Sealed sub-tab, Collection → Sealed section, Price Trends sealed mode, EV-vs-Box-price column.
5. **Display name / avatar / user-facing identity** is now user-controlled, not Google-derived.
6. **Ops** — Sentry + UptimeRobot live; ETL stale-data footer pill caught the silent-failure bug above.

## What landed (in rough order)

### ETL hardening (Tier 1)

1. **`scripts/supabase_client.py` `upsert()` dedupes by `on_conflict` keys** before chunking — fixes the silent "cannot affect row a second time" failure mode.
2. **`scripts/etl_tcgcsv_daily.py` exits non-zero on any matview-refresh RPC failure.** Plus per-row try/except around the set-group update loop so one bad row doesn't abort the rest.
3. **Migration `25_refresh_function_timeouts.sql`** — pins `statement_timeout = '5min'` on every refresh function. The card_prices_latest / rarity_avg_daily / price_movers refreshes had grown past the role-level default timeout (~30s) and were silently dying in the GitHub Actions cron. Symptom: `prices_daily` current but matviews stuck on 2026-05-12.

### Nav reorganization (Option C)

4. **Top nav collapsed from 13 tabs to 6**: Home, Market, Price Trends (renamed from History), Cards, Collection, Decks. Plus `?` icon top-right for How It Works.
5. **Market umbrella** (`MarketView`) — sub-tab strip with Expected Value, Card Averages, Playset Cost, Heatmap, Sealed, Simulate. Persisted sub-tab + persisted Low/Market price toggle. EV-specific `nc` / `ne` toggles moved into the EV page header (out of the global strip).
6. **Renames**: "Set Values" → **Playset Cost**, "Pull Rates" → **Card Averages**, "Expected Value" replaced "Box EV". "Compare Sets" folded into Card Averages with chip-based multi-select; Diff column appears when exactly two sets are picked.

### Expected Value rebuild

7. **Card-style header with integrated toggle cards** ("Remove Bulk", "Exclude Enchanted/Iconic") replacing the toolbar checkboxes. Tooltips wired through `<Tip>`.
8. **Historical EV % change pills** for 1D / 1W / 1M / 3M / 6M / 1Y. Two-phase fetch: probe `rarity_avg_daily` for the latest date, then one batched call for the seven target dates. Pulls both `avg_low` and `avg_market` so the global Low/Market toggle flips the % derivation too.
9. **EV vs Box Price column** when sealed prices are loaded. Per-set Booster Box lookup excludes "Case" SKUs (12-box cases) and picks the cheapest non-case listing. Diff badge: green when `EV > box price` (cracking is +EV), red otherwise. Tooltip: "Cracking is +EV at current box price" / "Box price exceeds EV — buy singles." Box link routes through `tcgUrl()` (affiliate).
10. **Newest-first set ordering** in every Market sub-view via `setsNewest = sets.slice().reverse()`. Mainline simulators (Pack / Box Sim) inherit the same ordering in their set dropdowns.
11. **Clicking any set name jumps to Price Trends** focused on that set (cross-view nav via App-level `historyTarget` state with nonce so re-clicks re-fire).

### Sealed product (full surface)

12. **Migration `15_sealed_products.sql`** — table for TCGCSV catalog entries that aren't cards (booster boxes, packs, troves, starter decks, gift sets, bundles, quests, promo singles). Loader `scripts/load_sealed_products.py` classifies by name heuristic; idempotent re-runnable.
13. **Migration `16_sealed_prices_latest.sql`** — matview joining sealed_products + prices_daily for latest price per SKU. Refreshed daily by the ETL alongside the card matviews.
14. **Market → Sealed sub-tab** (`SealedView`) — sections by display type (Booster Boxes → Booster Packs → Sleeved Booster Packs → Booster Pack Art Bundles → Troves → Prerelease Packs → Starter Decks → Gift Sets → Bundles → Quests → Sealed → Collector's Edition → Cases & Displays). Click set pill on any row → Price Trends. Per-product change windows mirroring EV.
15. **Migration `17_sealed_collection_items.sql`** + Collection → Sealed section. Per-user inventory of sealed product with +/- counters, summary stats (units, distinct SKUs, estimated value), "Show only owned" filter, owned-row tinting.
16. **Price Trends "By Sealed" mode** — picker grouped by display type, click-to-chart any sealed product's price history.
17. **Frontend reclassification overrides** — "Collection Starter Set" and "Starter Blister Bundle" SKUs display under Bundles instead of Starter Decks (they're sealed collectibles, not competitive starters). Pure render-time refinement; no loader re-run needed.

### Deck sharing (Phases A → C + token security)

18. **Migration `18_deck_sharing.sql`** — `decks.visibility` column (private/unlisted/public), broadened SELECT RLS, public `profiles` table mirroring auth.users metadata, `deck_follows` table (later renamed to `deck_favorites`).
19. **Migration `19_deck_sharing_v2.sql`** — renamed `deck_follows` → `deck_favorites`; added `user_follows` (creator-level follow distinct from deck-level favorite). Concept split:
    - **Favorite** = save a specific deck (`deck_favorites`, deck-scoped bookmark).
    - **Follow** = follow another creator (`user_follows`); their public decks appear in your Following feed.
20. **Migration `20_deck_favorite_counts.sql`** — SECURITY DEFINER RPC exposing aggregate counts without leaking who-favorited-what.
21. **Migration `22_deck_share_tokens.sql`** — per-deck `share_token` (~128-bit random base64). RLS tightened from `OR visibility != 'private'` (enumerable) to `OR visibility = 'public'`. Non-owner reads of unlisted go through `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` RPCs that require token. Trigger auto-rotates token on flip to Private. Owner-only `regenerate_deck_share_token(uuid)` RPC for explicit revocation. `deck_favorites.share_token` column captures the token used to access an unlisted deck so the Favorites list can re-fetch via the RPC.
22. **Migration `23_fix_share_token_search_path.sql`** — `gen_random_bytes()` is in `extensions` schema; SECURITY DEFINER functions need explicit `search_path = public, extensions, pg_catalog`. Hit once during the token rollout.
23. **Migration `24_deck_views.sql`** — `deck_views (user_id, deck_id, viewed_at)` unique-per-(user, deck), `deck_view_counts(uuid[])` aggregate RPC. Counted on URL deep-link AND card-click. Owner views of own decks gated client-side so they don't bump their own counter.
24. **Migration `21_profile_display_name.sql`** — 32-char length check on `profiles.display_name`. Plus the `notify pgrst` habit-builder.

**Frontend wiring for deck sharing:**

- URL deep links: `?deck=<uuid>[&token=<token>]` for decks, `?user=<uuid>` for creator profiles. Address bar auto-syncs with current view. Token only appended for Unlisted decks (Public stays clean).
- Read-only viewer with creator banner (avatar / display name / + Follow button) and Favorite + Duplicate actions. CardBrowser hidden in read-only mode.
- Share popover: visibility radios + share URL + Copy button + "↻ Regenerate share link" for Unlisted. Visibility change reads back the row post-update so trigger-rotated `share_token` syncs locally.
- Favorites / Following / Discover sub-tabs in Decks with chip-based ink filter + Your-Decks search + 6-way sort (Recently updated / Recently created / Highest value / Most favorited / Most owned / Name A→Z).
- Discover feed: paginated cursor-by-`updated_at`, excludes the current user's own decks. "Load more" button.
- Creator profile page with avatar / name / public deck list / Follow button. Reachable via clickable creator name in any read-only banner.

### Deck-list UX revamp

25. **Ink-tinted gradient backgrounds** on every deck card. 4-stop linear-gradient renders solid color A for 45% → blend zone → solid color B from 55%, so 2-ink decks read as a clear half-and-half split instead of a wash. Theme-aware via INK_TINT_LIGHT/DARK.
26. **Visibility badge** on Your Decks cards: 🌐 Public / 🔗 Unlisted / 🔒 Private pills with explanatory tooltips.
27. **Ink/uninkable counts as hex symbols** (using existing `<InkableHex/>` / `<UninkableHex/>`) instead of `12 / 3` text. Per-deck ink shield row in card meta.
28. **View count + favorite count** in card meta line (`★ N`, `👁 N`) and in the deck-editor toolbar.
29. **Updated …Xd ago timestamp** on every card with absolute-time tooltip in the viewer's local timezone (`relativeTime()` + `absoluteLocalTime()` helpers — 8am Tokyo update reads as Thursday 6pm Chicago automatically).

### Display name + avatar

30. **First-time display-name prompt modal** when a freshly-signed-in user has no `profiles.display_name`. Blocking — there's no close button. Required field, 32-char cap, helper text emphasizes "not your real name."
31. **Settings popover** has inline Display Name editor (Set / Change). 
32. **Avatars are card art only.** `AvatarPicker` writes the chosen card's image URL into `profiles.avatar_url`; Google's `avatar_url` is never synced. Existing users' Google-derived display names are left in place but they can edit through Settings.

### Ops & monitoring

33. **Sentry browser SDK** wired in via the loader script `<script>` tag in `<head>`. User attribution via `Sentry.setUser({id, username})` on auth state change (UUID + display name only — no email). Free tier; no card on file.
34. **UptimeRobot** monitors prod URL every 5 minutes; alerts after 2 consecutive failures.
35. **ETL stale-data footer pill** appears when `card_prices_latest`'s max(price_date) is > 36h old. Caught the matview-refresh silent failure the same day it was wired in.
36. **Sealed-prices localStorage cache** (`packsink:sealed:v1`, 1h max age, mirrors catalog cache pattern).

### Database hygiene

37. **Migration `14_drop_redundant_indexes.sql`** — dropped `collection_items_user_idx` and `deck_cards_deck_idx` (both leading columns already covered by their tables' PKs). Confirmed via the new `supabase/diagnostics/index_usage_audit.sql` diagnostic.
38. **Migration headers updated** on `04_card_view_v2.sql`, `05_view_perf.sql`, `09_price_movers.sql` to flag them as superseded by later migrations (still safe to run on a fresh deploy, just redundant).

### Cleanup

39. **`Art Assets/` folder (3.3 GB) deleted** from disk and gitignored. Source media-kit zips weren't being used at runtime; only the curated `Logos/` subset ships.
40. **Catchup commit pushed** (`8bbc3b5`): 43 files changed, +11,280 / -418. GitHub repo `zaventorian/Packs.Ink` now reflects the full state.

## Blocked / waiting on user

None at the moment. All migrations through `25_*.sql` have been run; ETL is healthy; site is live.

## Verified

- Cache v18 (no shape change this session); all sets rendering with correct counts.
- Deck sharing end-to-end across two accounts: create → flip Unlisted → copy share URL → load incognito → favorite → unfavorite → flip Private → URL stops working → flip Unlisted → token rotates → old URL stays dead → new URL works.
- ETL #6 ran green in 59s with all four `Refreshed via …` lines in the log. Matviews caught up to today's date.
- Sentry receives errors with user attribution (display name + UUID).
- Sealed product visible in Market → Sealed; collection sealed quantities persist across reload.

## Outstanding from previous handoffs

- **Tier 2 schema** (strength / willpower / lore columns + smart-search filters) — not started.
- **Buyout badge** — not started. Data path is wired (`price_movers` has `pct_1d` + `low_prev`); needs UI + threshold tuning.
- **Card scanner (phone)** — not started. Lowest priority.
- **Deck list cost-curve sparklines** — not started.

## Next up (priority order)

1. **Buyout badge** — highest-leverage user-facing feature still on the list, ladders into the north-star framing. ~1-2 hours including the home-page "Potential buyouts" banner.
2. **Tier 2 schema** + smart-search filters — Lorcast already exposes these; mostly loader + UI plumbing. ~2-3 hours.
3. **Sim a pack inline button** on each Playset Cost / Set Values row — Option C plan leftover. Folds Pack/Box Sim from destination → contextual action. ~45 minutes.
4. **Deck-list cost-curve sparklines** — small per-deck visualization on the Decks list page. ~45 minutes.
5. **EV-pill server-side fallback** — make `rarity_avg_daily` matview's row-level Low/Market fallback match `processData`'s frontend logic so the historical % change doesn't underreport for the newest set.
6. **Bump GitHub Actions to Node 24** — `actions/checkout@v4` → v5, `actions/setup-python@v5` → v6. Cosmetic warning clear; required before September 2026 anyway.

## Useful invariants when debugging

- **If "Prices may be stale" pill appears**: check the diagnostic query `select max(date) from prices_daily; select max(price_date) from card_prices_latest;`. If they diverge → matview refresh failed → check today's GitHub Actions ETL log for `Could not call refresh_*` lines. Fix is usually a statement_timeout regression — verify all refresh functions still have `set statement_timeout = '5min'`.
- **If shared deck loads as "no longer available"**: the share_token rotated or the deck flipped to private. Owner can regenerate the token from the Share popover or flip back to Unlisted; either generates a new URL.
- **If Your Decks shows decks you don't own**: regression of the post-18_*.sql user_id filter on `refreshDecks`. The SELECT must include `.eq("user_id", user.id)`.
- **If favorited unlisted decks vanish from your list**: creator rotated the token or flipped to private. The stored token in `deck_favorites.share_token` no longer matches; RPC returns empty.
- **If Collection counts go wrong**: first suspect cache version, then pagination ordering, then the `transformSupabaseData` mislabel/EXTRAS/CONNECTING_FOILS rules, then catalog-vs-prices merge direction.
- **If a filter feels laggy**: check that callbacks flowing into CardBrowser are wrapped in `useCallback` (busts `React.memo` otherwise). Two-stage memoization (`allGroups` then `grouped`) + `useDeferredValue(filter)` + `content-visibility: auto` must stay intact.
- **If a SECURITY DEFINER RPC says "function X does not exist"**: pgcrypto search_path. The function needs `set search_path = public, extensions, pg_catalog`.
- **If a matview refresh hits PG error 57014**: statement_timeout. Either bump the function's pinned `statement_timeout`, drop CONCURRENTLY (fallback path is faster but locks reads), or move the refresh out of the API path entirely with `pg_cron`.
- **If PostgREST 404s a freshly-renamed table or new RPC**: schema cache. Run `notify pgrst, 'reload schema';` in SQL editor.

## Files most recently touched

- `Index.html` (~9k lines) — Market sub-tab umbrella, EV rebuild, sealed surfaces, deck sharing UI, Decks list UX, display-name flow, Sentry init, ETL stale-pill.
- `CLAUDE.md`, `handoff.md` — full refresh today.
- `.gitignore` — added `Art Assets/`, dryrun outputs, audit CSVs.
- `scripts/etl_tcgcsv_daily.py` — refresh-failure exit code, set-group update error handling.
- `scripts/supabase_client.py` — upsert dedup by on_conflict keys.
- `scripts/load_sealed_products.py` (new) — TCGCSV product catalog loader.
- `supabase/14_drop_redundant_indexes.sql` through `supabase/25_refresh_function_timeouts.sql` — 12 new migrations.
- `supabase/diagnostics/index_usage_audit.sql`, `supabase/diagnostics/sealed_product_audit.sql` — reusable DB diagnostics.
- `.github/workflows/etl.yml` — unchanged; the silent matview bug was in the script, not the workflow.
