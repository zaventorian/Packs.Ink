# Tournaments

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

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
- **Home Tournament Results banner.** Top 8 decks for each of the 4 most-recent non-empty events, newest first. **ONE mount site as of 2026-08-04** — it's a configurable home panel (`tournaments`, default column `left`) like every other, so there is no breakpoint-dependent mount and no `useMaxWidth` / `isNarrow` gate any more. Always rendered `collapsible`, so the `home-feed-collapse-btn` chevron works on desktop too; state persists in `packsink:home:tourneyCollapsed`. List caps at `max-height:560px`, dropping to 340px at ≤1100px where the panel is half a column wide.
  - The dead `.home-tourney-col` / `.home-tourney-col--desktop` wrapper classes and the `chaseStyleTitle` mobile styling are gone; the modifier class is now `.home-feed--tourney` (was `--tourney-mobile`, which stopped being true once the desktop mount used it too).
  - **Two earlier side-by-side attempts were ripped out** (`ChaseRowWithTourney`, pairing it with Rare–Legendary in a 2-col mobile grid height-locked via `position:absolute;inset:0`). The current pairing is NOT that: it's a plain `grid-template-columns:repeat(2,minmax(0,1fr))` with `align-items:start` on `.home-left-col` at ≤1100px, so Following and Tournament Results sit at their natural heights with nothing absolutely positioned. Falls back to one panel per row at ≤360px. If you touch it, keep it height-lock-free — that's what broke both predecessors.
