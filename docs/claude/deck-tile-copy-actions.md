# Deck-tile copy actions (🔗 / 📋 / 🖼)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Every deck-card tile in DecksView (owned, Discover, Favorites, Following, the per-tournament tile inside TournamentDetailView) carries three actions. They live inside `.deck-card-actions`, which got `flex-wrap: wrap` to handle the now ≥5-button row on ~260px tiles.

- **🔗 Copy link** — `copyDeckLinkToClipboard(d)` (owned + external) / `copyDeckLinkFromResult(r)` (tournament-detail). Uses `buildShareUrlFor(d)` for owned/external (`null` for private decks → "switch to Unlisted/Public" toast); tournament rows build inline from `r.deck_id` + `r.deck_share_token`. Public decks get a clean `?deck=<id>` (no token); unlisted + tournament decks get `?deck=<id>&token=<x>`.
- **📋 Copy list** — `copyDeckListToClipboard(d)` (cards already loaded) / `copyDeckListFromResult(r)` (async fetches via `fetchTournamentDeckForCopy` then formats with the existing `deckToText` helper).
- **🖼 Copy image** — see "Headless deck-poster autoCopy" below. Async lazy fetch on tournament tiles since the `tournament_results_v` feed carries metadata only.

**DeckEditor toolbar Copy-link button (non-owners).** When a non-owner opens a shared deck via deck-editor, the toolbar shows `🔗 Copy link` gated `${!isOwnDeck && shareUrl && ...}`. Reuses the existing `shareUrl` useMemo + `copyShareUrl` callback + `copied` state — flashes "🔗 Copied ✓" same as the owner's Share popover. Owners still see the full `↗ Share` popover (visibility radios + URL row + regenerate-token).

### Headless deck-poster autoCopy

`DeckPosterModal` has `autoCopy` + `onAutoCopyDone(success, blob|err)` props. The poster JSX was extracted into a `posterDom` const so both the visible modal-backdrop branch and the headless branch share the same DOM + the same `wrapRef`/`posterRef`. In autoCopy mode the outer wrap is:

```html
<div aria-hidden="true" style="position:fixed;left:-100000px;top:0;
  width:1200px;pointer-events:none;z-index:-1">
  ${posterDom}
</div>
```

useEffect waits for two animation frames (React commit + layout) → awaits every `<img>` inside `posterRef` to finish loading → calls `snapshot()` (the existing html2canvas chain) → `canvas.toBlob` → reports outcome via `onAutoCopyDone`.

**Caller pattern (mirrors mover-tile camera button — the user-activation rule):**

```js
flashToast("Copying image…", 12000);
let resolveBlob, rejectBlob;
const blobPromise = new Promise((res, rej) => { resolveBlob = res; rejectBlob = rej; });
navigator.clipboard.write([new ClipboardItem({"image/png": blobPromise})])
  .then(() => flashToast("Deck image copied to clipboard"))
  .catch(() => flashToast("Couldn't copy image — try the editor's Export button"));
setPosterAutoState({deck, creatorName, onDone: (ok, blobOrErr) => {
  setPosterAutoState(null);
  if(ok) resolveBlob(blobOrErr);
  else   rejectBlob(blobOrErr || new Error("snapshot failed"));
}});
```

The `clipboard.write` call is SYNCHRONOUS inside the user-gesture click, and the browser accepts the blob that resolves seconds later. Verified end-to-end: ~4.4s wall time, 2400×1970 canvas, ~5.5 MB PNG → clipboard. Without ClipboardItem support, `onDone` falls back to a `<a download>` save.

### TournamentDetailView is deck tiles, not a list

The old `tournament-result-row` list (`.tournament-result-open` button + 4-column grid) was replaced with `.deck-card.external.tournament` tiles in a `.deck-list` grid. Background gradient uses module-scope `INK_TINT_DARK` / `INK_TINT_LIGHT` + `DARK_THEMES_GLOBAL` so theme switching matches DecksView's tournament tiles. Place + player render in the trophy line; when `deck_name` is just an ink-only autofill ("Amber/Emerald") the player name promotes to the tile title (same dedupe as the home Tournament Results banner). Lazy deck-fetch uses `tournamentDeckCache = useRef(new Map())` keyed by deck_id so a 2nd copy-button click on the same tile is instant.

The orphaned `.tournament-result-*` and `.tr-*` rule clusters were already gone from styles.css (confirmed 2026-06-27 audit) — nothing left to clean up here.
