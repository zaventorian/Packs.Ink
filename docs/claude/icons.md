# Icons — there are no emoji in the UI (2026-08-24)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

**`uiIcon(key, size)`** (Index.html, right below `NAV_ICONS`) is the one accessor for every
pictograph on the site. Paths live in `UI_ICON_PATHS`, drawn in the same Tabler/Lucide line
vocabulary as the nav: 24x24 box, `fill=none`, `stroke=currentColor`, round caps. Default size 14
(inline with button text); 16-20 for a standalone bubble.

The sweep that removed the last 218 emoji is not cosmetic bikeshedding — emoji failed three ways
at once: **every platform draws them differently** (the same button was a flat glyph on desktop
and a glossy colour sticker on Android, which is how Zaven noticed), they **carry their own
palette** so they never matched the accent or the theme, and their **metrics are unrelated to the
text beside them**, which is why icon+label buttons never sat straight.

- **Add a glyph by adding a path to `UI_ICON_PATHS`.** Don't inline a one-off `<svg>` at a call
  site and don't reach for an emoji "just this once" — the point is that the set is closed.
- **`svg[focusable="false"]{vertical-align:-0.18em;flex:0 0 auto}`** (styles.css, above `.chip`) is
  the single global rule that makes inline glyphs sit on the cap height and never shrink in a
  tight button. Every icon in the set carries `focusable="false"`; nothing else does. It is inert
  inside flex/grid parents, so `NAV_ICONS` and the deck-action rows are unaffected.
- **Typographic marks stay**: `✓ ✕ ★ ☆ ✦ ≡ ⚑ → ↴ ▸ ▾`. Those read as type, not as
  pictures, and none of them is emoji-CAPABLE, which is the real test (next bullet).
- **⚠ "No emoji" means no emoji-CAPABLE code point, not just the ones that look like one**
  (2026-09-27). `↗` (the arrow after every outbound link), `↩`, `▶`, `⏱`, `⤴` and `⚠` all read
  as plain type in the source, but Unicode marks them emoji-capable and the page font (Nunito Sans,
  latin subset) carries none of them. So the browser falls back to another font, and on an iPhone
  that font is Apple Color Emoji: "Buy on TCGplayer" ended in a blue sticker tile, 52 times across
  the site, while every desktop drew a clean arrow. Reported off a Discord screenshot of the
  Playmats modal.
  - **`extIcon()`** draws the outbound-link arrow: the `ext` glyph at `1em`, so it takes the size of
    whatever small type it trails (8px on a price badge, 14px on a printing row), and
    `svg.ico-ext` lifts it to sit where the character did. The rest went to `undo` / `play` /
    `clock` / `warn`, and the Playset Cost row toggle to `▸` / `▾`.
  - **The Coconut badge's `⚠` is gone too.** It used to be the one documented exception here,
    and it was an emoji tile on every iPhone.
  - Guarded by `node scripts/test_no_emoji.mjs`: any Emoji / Extended_Pictographic code point outside
    a comment in a served file fails it, except `© ® ™`, which ARE in the font. **It strips
    comments in ONE left-to-right pass**: stripping block comments first read the `/*` inside a line
    comment (`// proxied to /img-proxy/*`) as an opener and hid 1,900 lines of Index.html, two real
    emoji included. It checks itself against planted samples, so a broken stripper goes red.
  - Player names and other DATA keep whatever a person typed. This is about the site's own chrome.
- **Two documents can't reach `uiIcon`** and hold literal SVG instead: the Artist Alley poster
  (`window.open`) and the `/swiss` + `/ticker` standalone pages. `/picks` has its own `ICONS` map
  and `glyph()` builder, and its arrow comes from there. In the poster the icon is a
  sibling of a `<span>` label, and the mid-render `textContent` swaps target the span — setting
  `btn.textContent` would wipe the glyph.
- **Comments and CLAUDE.md still use emoji freely.** They are documentation, not UI.
