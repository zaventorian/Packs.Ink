# Shareable Screener + Price Graphing state (`?v=` / `?g=`)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Both views were unlinkable: a Screener query lived only in component state and `screener_views` (so it could be SAVED but never SENT), and an 18-card comparison died on refresh. `history` owned no params at all.

- **`?v=` carries the whole Screener screen.** `encodeScreenerState` / `decodeScreenerState` walk `SCREENER_STATE_FIELDS` — a `[payloadKey, urlKey, kind, default]` table — and write only non-defaults, so an ordinary two-chip screen is short and a bare `/screener` carries nothing. `decode` always returns a COMPLETE payload so a link can't leave a filter behind from the previous screen. `_scEsc` escapes only this codec's own `;:,~`; double-encoding would turn a shared `%20` into a literal.
  - **A field's default here must match the component's initialiser.** `minPrice` defaults to `"5"`, not `""` — with `""` an untouched Screener encoded `?v=p0:5` on every visit and the address bar was never clean.
- **`?g=` / `?hm=` / `?hr=` / `?hs=` carry Price Graphing** — compare list, mode, range, chart scale. `?g=` is IDENTITY ONLY (`c~<pid>~<printingCode>`, `s~<pid>`, `t~<setId>`, `g~<cardId>~<grader>~<grade>~<code>`); names, subtitles and art rebuild from the catalog on arrival, so the link stays short AND picks up corrected metadata rather than freezing the sender's copy. `~` separates fields, `,` separates items — both legal unescaped in a query string, and `~` specifically because a grade like `9.5` breaks a `.`-delimited encoding.
  - An unrecognised printing round-trips verbatim behind `_`. Collapsing it to Normal would graph a real line for the wrong SKU.
- **Register every new param in BOTH `dirtyParams` and `VIEW_OWNED`** — the standing rule. `screener` owns `m,v`; `history` owns `g,hm,hr,hs`.
- **`replaceState`, never push.** A filter is not a page; pushing would make Back walk backwards through every chip the user toggled. The Screener's writer is debounced 400ms because the search box writes per keystroke.
- **⚠ `showGraded` / `showSealed` come from `?v=` at INIT, not from a post-mount `applyView`.** The mode-flip effect keys on `prevShowGraded` and deliberately resets rarity, the price floor and the graded chips on a change — flipping the mode after mount fires it and wipes exactly the filters the link was carrying. Initialising means `prev === current` and it stays asleep.
- Guarded by `node scripts/test_screener_url.mjs`, which round-trips both codecs including search text containing every delimiter they own.
