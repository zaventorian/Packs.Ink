# Handoff — 2026-05-23

> Snapshot in time. Treat as stale once `git log` (or file mtimes) move past this date. Durable rules live in `CLAUDE.md`.

## Big picture since last handoff (2026-05-22 → 2026-05-23)

Picked off two items from the previous roadmap, killed one. Short day.

1. **Tier 2 stats landed** — `strength` / `willpower` / `lore` / `move_cost` columns on `cards`, smart-search filters wired up with comparison operators (`lore>=2`, `str<4`, `wil=5`).
2. **Screener saved views to Supabase** — new `screener_views` table replaces localStorage-only persistence. Local stays as cache + unauth fallback. First sign-in migrates local-only views up.
3. **Roadmap cleanup** — removed "Deck legality auto-fix suggestions" (won't pursue). Card scanner moved to remaining top-of-list along with the still-blocked domain transfer.

## What landed

### Tier 2 schema (migration 43)

1. **`supabase/43_card_tier2_stats.sql`** — adds nullable `strength`, `willpower`, `lore`, `move_cost` int columns + three single-column indexes (skipped one on `move_cost` since it's rarely filtered).
2. **`scripts/load_lorcast.py`** — `transform_card` now reads `strength` / `willpower` / `lore` / `move_cost` directly from Lorcast. Sunday cron picks up new cards automatically.
3. **`scripts/patch_card_tier2.py`** (new) — one-shot backfill for the ~2k existing rows. Per-row PATCH (no group-by-value win since each card's stats are unique). Idempotent.
4. **`Index.html`**:
   - Cold-load probe adds a third parallel fetch (`select=lore&limit=1`) alongside the existing inks / illustrators probes. If 42703, `CARDS_COLS` omits the four Tier 2 columns and the filters silently become no-ops — no crash on un-migrated DBs.
   - `buildRow` projects `strength` / `willpower` / `lore` / `move_cost` onto every row.
   - `parseSearchQuery` numeric-stat parser extended to support `>=`, `<=`, `>`, `<`, `=` with three input forms: `kw N`, `kwN` (no space), `kw>=N`. Operator stored at `filters[statKey + "Op"]`; numeric value still at `filters[statKey]` for back-compat with the chip-cost handoff.
   - `matchesCardFilter` + the Cards-browse `cardMatches` use a small `_cmp(rowVal, want, op)` helper for cost + the three new stats. Null row values fail any non-null filter.
   - Chip-summary line shows `Lore>=3` etc. instead of just `Lore 3`.
5. **`CACHE_KEY = "packsink:catalog:v39"`** (was v38) — row shape gained four fields. Existing browsers re-fetch on next visit.

### Screener saved views to Supabase (migration 44)

6. **`supabase/44_screener_views.sql`** — `screener_views(user_id, name text, payload jsonb, created_at, updated_at)`. PK `(user_id, name)`. Owner-only RLS (select/insert/update/delete via `auth.uid() = user_id`). `set_updated_at` trigger for ordering. Grants to `authenticated` + `service_role`.
7. **`Index.html`** `PriceDatabase`:
   - `savedViews` still hydrates synchronously from localStorage on mount (for first paint speed + unauth users).
   - New effect on `[user]`: fetch from `screener_views` ordered by `updated_at` desc. If remote is empty AND local has views → one-shot migration upsert. Otherwise replace state with remote. Gracefully skips on 42P01 (table not deployed yet) with a console hint.
   - `saveCurrentView` now async — sets state immediately, then upserts to Supabase when signed in. Payload excludes `name` (name is the row key); state row still carries `name` as a flat field for back-compat with the existing chip render.
   - `deleteView` now async — sets state immediately, then deletes the matching row when signed in.
   - localStorage write effect retained as the always-on mirror.

### Service worker

8. **`sw.js CACHE_VERSION = "packsink-v5"`** (was v4). Force shell refresh on next visit.

## Migrations applied to prod (run order)

35 → 36 → 37 → 38 → 39 → 40 → 41 → 42 → **43 → 44 (pending — apply via Supabase SQL editor)**

After applying 43, run `python scripts/patch_card_tier2.py` to backfill existing rows. 44 needs no backfill (per-user table starts empty; users' existing local views migrate up on first sign-in).

## Verified live (against dev server)

- Page loads with no JS errors after the changes.
- Probe correctly detects missing `lore` column on the current Supabase instance and logs the expected one-line warning. Catalog fetch otherwise unaffected.
- Screener renders 412 rows; Saved chip row hidden when no views (expected).
- Cards browse smart search: typing `lore>=3` produces a `Lore>=3` chip in the parsed-filters strip. Filter is currently a no-op because the column doesn't exist yet in this DB — will start filtering once 43 + the backfill run.

## Useful invariants when debugging

- **Tier 2 filter silently does nothing in prod?** Check that migration 43 ran and `scripts/patch_card_tier2.py` was executed. Then `select strength, willpower, lore from cards limit 5;` to confirm values are populated. Then bump `CACHE_KEY` if browsers are still on a pre-Tier-2 cache.
- **Screener views not persisting across devices?** Confirm migration 44 ran. If signed-in user logs an `42P01` warning on cold load, the table is missing. Local-only views still work fine — they just don't roam.
- **First sign-in didn't migrate local views?** The migration only runs when the remote table is empty. If the user already has even one saved view server-side (e.g. from another device), local-only views won't merge — would need an explicit "merge" affordance. Not built; rare enough to be acceptable.

## Files touched

- `Index.html` — CACHE_KEY bump, third column probe (lore), Tier 2 fields in buildRow, parser comparison operators, matchesCardFilter + cardMatches `_cmp` helper, screener saved views Supabase hydrate/save/delete.
- `sw.js` — `CACHE_VERSION = packsink-v5`.
- `scripts/load_lorcast.py` — transform_card emits strength/willpower/lore/move_cost.
- [scripts/patch_card_tier2.py](scripts/patch_card_tier2.py) (new) — one-shot backfill.
- [supabase/43_card_tier2_stats.sql](supabase/43_card_tier2_stats.sql) (new) — columns + indexes.
- [supabase/44_screener_views.sql](supabase/44_screener_views.sql) (new) — per-user table + RLS.
- `CLAUDE.md`, `handoff.md` — refresh (this commit). Roadmap: removed deck legality auto-fix entry (decided against), removed Tier 2 + Screener-views (landed).

## Blocked / waiting on user

- **Apply migration 43** in Supabase SQL editor, then `python scripts/patch_card_tier2.py`.
- **Apply migration 44** in Supabase SQL editor. No backfill.
- **Google OAuth consent screen verification** — unchanged from prior handoff.
- **Domain transfer** still blocked until 2026-06-08.

## Next up (priority order)

1. **Domain transfer to Cloudflare** after 2026-06-08 — gates the WAF / Bot Fight Mode rollout.
2. **Card scanner (phone)** — vision-based identification. Biggest scope on the list.
3. Nice-to-haves from the long list: pack-sim inline button, deck-list cost sparklines, Screener floor-coverage indicator, stale-row indicator.
