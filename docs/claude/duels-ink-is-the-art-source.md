# duels.ink is the art source for stand-ins (2026-09-30)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

A stand-in built from a pasted screenshot (`import_pasted_cards.py`) is the weakest art we carry:
tilted, still in the reveal photo's yellow backdrop, cut off at an edge, or 125px wide (RPH #1/#2/#3/#5
were). duels.ink's public card API (`duels.ink/api/cards?limit=200&offset=N`, plain `requests` works)
publishes every card as a flat, upright 1101x1536 render, and **`imageSource` says what it is**:

- **`reveal`** — a clean full-card render of the real print. Use it.
- **`generated`** — a gold "duels.ink preview" placeholder with NO art. **Never import one**; it is
  worse than any crop. 21 Hyperia City cards were still placeholders on 2026-09-30.
- **null** — the official gallery's image, which `import_official_set.py` already owns.

`python scripts/import_duels_art.py --setnum 14 --tag set14 [--add-missing] [--commit]` (dry run by
default, guarded by `python scripts/test_import_duels_art.py`) upgrades only rows that are ALREADY
`crd_prestage_*` and not exactly 734x1024, so it cannot sit on top of Lorcast or the gallery.
- **It writes image columns only.** duels' names for a Japan-only reveal are its own translations
  (see the set-14 provenance memory), so a stand-in's data is never overwritten from there.
- **The stored URL gains `?v=<hash>`** — `packsink-img-v1` survives deploys and keys on the URL, so an
  in-place overwrite alone would keep serving the old crop. `scanner` `art_key` strips the query.
- `--add-missing` adds PROMOS duels lists and we lack (Hyperia City: PD1 #11/#12/#14, RPH #6/#7);
  mainline numbers are never added this way. Illustrators are not in the API — pass `--illustrators`.
- **Language check before trusting a render**: the print line reads `N/204 • EN|JA|DE|FR • 14`.
  Héctor Rivera - Gone to Pieces (#121) is a Japanese print on our site and duels has only a
  placeholder for it.
- **A scanner-index rebuild follows an art change** (`fetch_cards.py` → `build_index.py` →
  `build_text_index.py`, then bump `IDXV`/`TXTV` and `test_scanner_asset_cache.mjs --update`).
