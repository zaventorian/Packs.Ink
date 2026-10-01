# Graded view UX patterns

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

- **`.gc-caps-*` class family** (header chips): uppercase, letter-spaced 10px font matching `.gc-stat-lbl` so the whole header row reads as one chip set. Includes `.gc-caps-btn`, `.gc-caps-cta`, `.gc-caps-seg`, `.gc-caps-flag`, `.gc-caps-select`. New header controls should adopt these classes for visual consistency.
- **`.gc-caps-tip` tooltip**: custom popover on the ⓘ icon. More reliable than native `title=` (no delay, multi-line, mobile-friendly). On ≤700px switches to `position: fixed` + full-width-minus-margins so wrapping parents / `overflow:hidden` ancestors can't clip it. Use this pattern for any non-trivial tooltip in the graded view.
- **`.gc-add-fab` mobile FAB**: at ≤700px, the inline "+ Add graded card" chip is hidden via `.gc-add-cta-desktop` and replaced by a `position:fixed` bottom-right FAB. Standard pattern for high-frequency mobile actions when the header is too crowded.
- **Two-tap remove** (`armedRemove` state + `.gc-slot-armed` red pulse class): clicking an owned slot pill arms it for ~3s; second click within window confirms. Replaces `window.confirm()`. Reusable pattern — same state machine works for any destructive single-click action.
- **Quick-add on tracked tile** (`.gc-slot-quickadd` button): clicking the "+ PSA 10" pill on a tracked-only tile logs a PSA 10 instantly (one-tap goal progress). Shift-click opens the full Add modal for non-default grader/grade.
- **`grader_collection_items` does NOT have RLS for printing** — anyone with the owner's `share_token` can read all printings via the RPC. No additional gating needed; the RPC is already SECURITY DEFINER + token-checked.

### Persisted localStorage keys (graded view)

- `packsink:graded:collapsed` — array of set_ids that are collapsed
- `packsink:graded:display` — "grid" | "compact"
- `packsink:graded:trackCosts` — "1" | "0"
- `packsink:graded:removed` — array of `"cardId|printing"` composite keys (cards user removed from tracking). Replaces the old `packsink:graded:hidden` key (per-card hide feature was killed 2026-05-26 — see "Remove from tracking" section below).
- `packsink:graded:visFilter` — "all" | "owned" | "tracked"
- `packsink:graded:sectionSort` — "release" | "complete" | "value"
