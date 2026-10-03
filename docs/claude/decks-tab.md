# Decks tab — logged-out access (2026-06-05)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

The Decks tab is **usable without signing in**. The 5 sub-sections behave differently:

- **Discover** (public decks) — works fully without auth. Default landing section when signed out.
- **Tournaments** — works fully without auth.
- **Your Decks** / **Favorites** / **Following** — each section's body renders an inline sign-in CTA (a styled `.empty-state` block with a Sign-In-with-Google button + explanation) instead of crashing or loading empty. Section tabs ARE clickable when signed out (so the structure is discoverable).

Implementation:
- The unconditional `if(!user) return ...sign-in CTA...` at the top of `DecksView` was removed. The user-section CTAs live inside the per-section render branches.
- Initial `deckSection` defaults to `"discover"` for signed-out users (vs `"yours"` for signed-in). A separate `useEffect` watches the user prop and bumps signed-out users off any user-specific section onto Discover (without touching the saved-section pref, so signing back in restores their last pick).
- `decks` state is `null` until first fetch settles. References use `decks?.length || 0` to avoid the brief null-window crash for signed-out users.
- Per-deck action buttons (Follow / Favorite / Duplicate, in the external-deck banner): `onClick` now falls back to `onSignIn` when `!canAct` (i.e. no user). Previously the buttons rendered "Sign in to favorite" text but the onClick still pointed at the real action (silent no-op or crash). The external-deck `<DeckEditor>` renderer at line ~20089 already had `onToggleFavorite={user ? real : onSignIn}` wired — extended the same pattern to the in-banner buttons.

Public deck access paths (no auth needed):
- `externalDeck` flow — set via `openExternalDeckEntry()` when a Discover card is clicked. The SECURITY DEFINER RPCs `get_shared_deck(uuid, text)` / `get_shared_deck_cards(uuid, text)` handle the fetch without auth.
- Incoming URL deep-links (`?deck=<id>` or `?deck=<id>&token=<x>`) hit the same fetch path BEFORE the gate logic — already designed for logged-out shared-link visitors.
