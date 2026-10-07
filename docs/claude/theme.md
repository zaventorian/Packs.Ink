# Theme: 6 named palettes + 3-mode resolver (2026-06-05 rewrite)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

State is **three independent pieces**, each persisted independently to localStorage AND synced to Supabase user_metadata (cross-device):
- **`lightTheme`** (`packsink:lightTheme`) — which of the 4 light variants: `parchment` (default) | `sunrise` | `watercolor` | `daydream`.
- **`darkTheme`** (`packsink:darkTheme`) — which of the 3 dark variants: `velvet` (default) | `aurora` | `black`.
- **`themeMode`** (`packsink:themeMode`) — `"light" | "dark" | "system"`. Picks which family is currently active.

Resolution at render time:
- `themeMode === "light"` → `lightTheme`
- `themeMode === "dark"` → `darkTheme`
- `themeMode === "system"` → `osDark ? darkTheme : lightTheme` (matchMedia driven, re-resolves at OS night-shift / sunset).

The `resolvedTheme` (aliased `theme` for back-compat) is what gets written to `<html data-theme>`. The CSS file has one `html[data-theme="..."]` block per named theme — picking one swaps the entire palette atomically.

**Top-bar moon/sun toggle**: behavior depends on `themeMode`:
- Light or Dark mode: flips `themeMode` to the other side. The user's persistent `lightTheme` / `darkTheme` picks determine which exact variant renders.
- System mode: applies a **transient in-memory override** (`systemOverride` state, NOT persisted). The override clears on the next OS pref change (matchMedia listener) OR on page reload. Matches spec: "you can override it with the moon, but it will switch back next time system switches."

**Migration paths** (one-shot on first load after this rewrite):
- If localStorage `themeMode` held a specific theme name (e.g. `"velvet"`), the init infers the family and migrates: `themeMode → "dark"`, `darkTheme → "velvet"`.
- Old `packsink:lastDarkVariant` / `packsink:lastLightVariant` keys are read as fallback during init.
- Old `packsink:theme` key is also honored for the same family-inference.
- Supabase user_metadata hydration mirrors the same logic — old metadata with `themeMode === "aurora"` migrates the same way.

**Theme classification helpers** (`Index.html` ~line 22519):
- `LIGHT_VARIANTS = ["parchment","sunrise","watercolor","daydream"]`
- `DARK_VARIANTS  = ["velvet","aurora","black"]`
- `DARK_THEMES` Set includes the legacy `"dark"` alias; light membership is derived from `LIGHT_VARIANTS` (the `LIGHT_THEMES` Set was removed as unused — only `isDarkTheme`/`DARK_THEMES` are consumed).
- `isDarkTheme(t)` is checked at every site that branches on theme (e.g. `inkTint`, deck gradient builder). **Never check `theme === "dark"`** — that would miss `aurora` / `velvet` / `black`. Use `theme !== "light"` or `isDarkTheme(t)` or `DARK_THEMES_GLOBAL.has(t)` (the module-scope mirror used by `inkTint`).

**Gradient themes** (sunrise / watercolor / daydream / aurora) hold a CSS `linear-gradient(...)` or `radial-gradient(...)` as their `--bg` value (instead of a hex color). To make this work end-to-end:
- `body { background-color: var(--bg); }` (NOT `background:`). When `--bg` is a gradient value, `background-color` silently drops it (gradients aren't valid color values) — so the body stays transparent.
- `body::before { background: var(--bg); position: fixed; inset: 0; z-index: -2; }` — this fullscreen layer is the only thing that actually paints the gradient. Anchored to viewport, scrolls-fixed.
- The body is `max-width: 1300px`. If body's own `background` rendered a gradient, the 1300px column would seam visibly against the fullscreen `::before`. The `background-color` trick avoids that seam for gradient themes while still working for solid themes.

**Ink tints in dark/gradient modes** (`Index.html` ~line 2420, `INK_TINT_DARK`): values were retuned 2026-06-05 to land on the deep purple Velvet canvas (`#180a22`). Amber/Emerald previously muddied against purple at the old 16% opacity — now sit at 22% with brighter base hues. `INK_TINT_DARK` is also used for the gradient themes (any non-light theme).

**Settings popover layout** (gear/profile dropdown):
- **Mode**: 3-button segmented control `[Light] [Dark] [System]`
- **Light theme**: 4-button swatch grid (Parchment / Sunrise / Watercolor / Daydream)
- **Dark theme**: 3-button swatch grid (Velvet / Aurora / Black)
- The light-theme grid + dark-theme grid are ALWAYS visible regardless of current mode — picking one updates that family's pref and changes the toggle pair without changing mode.

**`showTopBarTheme`** pref (`packsink:showTopBarTheme`): toggle to hide the quick theme bubble in the top-nav right cluster. Default ON.

### Text on an accent fill is `--on-accent`, and muted text is sized to 4.5:1 (2026-09-26)

Measured across all seven themes with a pixel-sampling harness (the session's scratch
`agent_themes/`), two systemic readability gaps, both fixed at the TOKEN so every
instance moved together:

- **`--on-accent`** — the text colour on the site's one active-chip / primary-button
  treatment, `background:var(--accent)`. It was a literal `#fff` in ~75 rules, which reads
  on the light themes' dark gold (now #775e17, 6:1) and FAILS on the dark themes' bright gold
  (#c8a846 2.3:1, aurora's #e8c850 1.6:1 — "Sign in" among them). `:root` sets `#fff`;
  aurora / velvet / black override it with dark ink `#1a1022`. **New accent-filled UI takes
  `color:var(--on-accent)`, never `#fff`** — and never a new token for the same job.
- **`--text-muted` / `--text-dim` alphas were raised** so muted clears 4.5:1 on each theme's
  own backgrounds (parchment measured 2.8:1 — nav labels, table headers, chart axes, sub-
  lines). Parchment/light 0.40→0.55 (dim 0.58→0.68), sunrise/watercolor/daydream
  0.55→0.66 (dim 0.7→0.8), velvet 0.40→0.50 (dim 0.55→0.65), aurora 0.50→0.56 (dim
  0.65→0.7), black 0.45→0.50. Muted stays lighter than dim. **Stacking `opacity` on muted
  text undoes this** (the footer disclosure sat at 2.3:1 that way) — fade the element, not
  the text, or don't.
- Also from the same pass: placeholders follow the theme (`input::placeholder` →
  `--text-muted`, opacity 1 — the browser default #757575 measured 2.6–3.5:1); calendar
  kind chips keep the pure hue on the BORDER and darken the label toward black on light
  themes (`--chip-hue` + `color-mix`); the bright Elo top-rank gold becomes `--accent` on
  light themes; out-of-month / dense-calendar day numbers stay recessive but readable.
- **Guarded by `node scripts/test_theme_contrast.mjs`**, which parses the theme blocks out of
  styles.css and does the WCAG arithmetic: muted ≥ 4.5:1 on every theme's `--bg-solid`, dim
  at least as strong as muted, `--on-accent` ≥ 4.5:1 on `--accent`, and no rule pairing
  `background:var(--accent)` with a literal white. It fails 16 checks on the pre-fix sheet.
- **The light gold is dark enough to be TEXT (2026-10-06).** #8a6d1b measured 4.43:1 on
  Parchment's own background and 3.6:1 on a hovered panel, so every gold link, active nav label
  and active chip failed. It is `#775e17` now, `#715916` on Sunrise and Daydream (darker, purple-
  tinted panels); same hue, a few points darker, with the rgba tints following. Dark text on the
  gold FILL went to `var(--on-accent)` too (13 rules), because darker gold made dark-on-gold 3:1.
  The guard checks gold text on `--bg-solid` / `--bg-card` / `--bg-modal`, on a panel over a
  hovered row, and the active chip, and bans a literal dark colour on the fill.
- **An axe run in a GRADIENT theme reports false contrast failures**: it can't see `body::before`,
  so it measures against the wrong background. Force Parchment before trusting a contrast finding.
- **The harness has two known artifacts** worth recognising before "fixing" them: text over a
  modal that hadn't finished loading (backgrounds of #010101), and positions sampled from a
  different scroll offset than the screenshot (footer text "on" map tiles). Confirm a
  low reading with `getComputedStyle` before touching CSS.

### ⚠ `color-scheme` is declared at the DOCUMENT level — don't scope it off again (2026-09-13)

`<meta name="color-scheme" content="dark light">` in the head, plus
`html[data-mode="dark"]{color-scheme:dark}` / `[data-mode="light"]{…light}` in styles.css.
It is the **only** signal a browser has that this page already handles dark mode. Without
it, Chrome's "Darken websites", Samsung Internet's dark mode and Android WebView's
algorithmic darkening treat the app as un-themed and paint their **own** darkening filter
over our already-dark palette.

- **Reported from a freshly installed copy of the PWA**, sitting beside an older install of
  the same build that looked correct — so it reads as "the app changed", and nothing in the
  app had. Both were standalone, same theme, same commit.
- **How to tell this apart from a theme bug in one step: it darkens IMAGES.** The logo PNG
  and the profile avatar came back dimmed, and no stylesheet can do that. Measured on the
  two screenshots: layout pixel-identical, and the good one rendered Aurora's own gradient
  stop `#2a1450` to the byte while the bad one crushed it to `#0f0134`. Whites (the OS
  status bar, nav labels) were untouched — a shadow-crushing dark filter, not a dim setting.
- **It was scoped to form controls once before**, because Samsung Internet answered the dark
  signal by painting a tan/cream UA widget background on `<button>` (the profile button and
  its avatar tile). That is guarded at source now: the global `button` rule sets
  `appearance:none`, so no button can fall back to a UA-painted widget in any engine. Don't
  remove that `appearance:none` and don't re-scope `color-scheme` — fix the widget, not the
  signal.
- **Declare BOTH modes.** A light theme left undeclared is the case those filters treat most
  aggressively.
- The root declaration also covers what the old form-control-scoped rule was for: native
  `<select>` option panels, scrollbars and focus rings stay readable in dark themes.
- **⚠ Samsung Internet's forced dark mode CANNOT be opted out of from the page (2026-09-18).**
  Samsung (browser AND installed PWA) double-darkens the dark themes and greys the light
  ones, while Chrome's PWA is fine. Tell-tale: the black-translucent corner buttons on mover
  tiles render WHITE. v431 added `only dark` / `only light` (meta `dark light only`) and a
  `prefers-color-scheme: dark` block in styles.css on the theory that Samsung looks for one —
  **that theory was wrong**, verified on Zaven's phone the same night. Samsung's stable force-dark
  ignores color-scheme, `only` and the media query alike; only its experimental "Adaptive Force
  Dark" (`internet://flags`) respects the page. Both changes are kept: `only` is correct for
  Chromium's auto-dark and harmless elsewhere. The user-side fix is Samsung Internet →
  Settings → Labs → **Use website dark theme** (or turning off its dark mode for sites).
  Don't burn another round on CSS for this.
