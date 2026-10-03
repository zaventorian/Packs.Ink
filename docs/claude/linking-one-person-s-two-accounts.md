# Linking one person's two accounts (2026-09-08)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

`suggest_aliases.py` proposes exact/normalized matches and fuzzy pairs at **ratio >= 0.85**, so
two handles that differ by more than that are never suggested and never will be — `heyzeusvee` on
melee against `heyzeus` on RPH is the shape. Somebody has to say so, and
**`scripts/elo/manual_merges.csv`** is where they say it: one row per ruling, with a `why`.

- **⚠ It is applied on EVERY refresh, from a committed file, and that is the point.** The
  canonical SQLite is downloaded from Supabase Storage at the top of `refresh_elo.py` and uploaded
  at the bottom, so a merge applied anywhere else is silently overwritten by the next refresh —
  the same trap as the one-off event ingest. The merge does persist in the DB once applied;
  re-applying every run is what makes it survive a rebuild too, at one lookup per row.
- **Keyed on `(platform, display_name)`** — the players table's own UNIQUE constraint, so the key
  survives a rebuild. `player_id` would NOT: it is a bare autoincrement rowid, so a rebuilt DB
  renumbers it and every row would quietly point at a different person. (Same reasoning as
  `draw_overrides.py`, and the reason the older `aliases_manual_*.csv` files — which are
  id-keyed — are history rather than the place to add a row.)
- **Names resolve case-insensitively, and against `external_username` as well as `display_name`.**
  Someone reporting their own handle types it how they say it, not how the platform stored it.
- **A row that resolves to nobody FAILS the refresh**, and the failure prints the nearest names on
  that platform — so one failed run is also the lookup you needed. Two accounts silently coming
  apart is the exact complaint this exists to fix, so a warning in a green run is no good. The
  step runs before the upload, so a failure leaves the stored DB untouched and is re-runnable.
- **A source already merged somewhere else fails rather than repointing** — silently moving an
  account's whole history to a different person is worse than stopping.
- Merges are **melee -> rph** by convention (RPH is canonical), but the columns name both
  platforms, so an RPH alt merging into an RPH primary is expressible.
- Guarded by `python scripts/elo/test_manual_merges.py`.
