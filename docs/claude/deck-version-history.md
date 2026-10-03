# Deck version history (migration 125)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**A version is one EDITING SESSION, not one keystroke.** The editor already snapshots the deck when you enter edit mode (`editSnapshot`, which powers "Undo changes"); leaving edit mode writes that pre-edit state as the next version — but only if `deckCardsSignature` says something actually changed. Snapshot per card-tap and you get four hundred rows nobody can read as history.

Both exits are hooked: **Done** (`toggleDeckEditMode`) and **Back** (`onBack`). Miss the second and a whole session is absent from history purely because the user backed out instead of pressing Done. Both must read `editSnapshot` BEFORE flipping `editMode` — the effect that owns the snapshot clears it the instant the flag goes false.

- `deck_versions(deck_id, version, name, coconut_card, cards jsonb, created_at)`. Cards carry the **same obfuscation as `deck_cards`** (card_id deterministic-encrypted, quantity plain int) — an archive of decklists shouldn't be readable when the live table isn't. `decDeckVersionRows` decodes on read.
- Writes go through **`save_deck_version()`** only; there is no INSERT policy. It assigns `max(version)+1` and prunes past **30** under one lock, so the number can't be raced. Version numbers are never reused — "v4" always means the same snapshot even after v1 is pruned.
- `diffDeckVersions(from, to)` keys on **card_id + printing** (the `deck_cards` PK), so a Normal→Foil swap reads as one card out and one in — which is what happened to the deck. Guarded by `node scripts/test_deck_versions.mjs`; the signature is the dangerous half, since being too sensitive fills history with empty changelogs and being too lax loses real edits, and both are silent.
- **`decks.share_versions`, default FALSE.** Sharing a deck is one decision; sharing every draft it passed through is a bigger one, and it must never happen because somebody forgot a checkbox existed. `get_shared_deck_versions` requires all three of: not private, token matches, `share_versions` true. `get_shared_deck` reports the flag so a viewer's client knows whether to offer the History button.
- **The flag is read on demand in DeckEditor, NOT plumbed through the deck lists.** Adding `share_versions` to those hot selects would 400 every list query until the migration lands. Same reason every version call routes through `deckVersionsUnavailable(err)` (42P01 / 42703 / PGRST202): pre-migration the History modal says "isn't switched on for this site yet" instead of throwing.
