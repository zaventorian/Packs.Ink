# Fonts — ask for a RANGE, or the site has no bold (2026-09-14)

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Two families, two files: **Cinzel** (`h1,h2,h3,.title-font`, the display face) and
**Nunito Sans** (everything else). Both are requested as a weight **range**
(`Cinzel:wght@400..700&family=Nunito+Sans:wght@300..800`), which makes Google serve
**one variable woff2 per family**.

**⚠ That is not a size optimisation, it is the only reason `font-weight:700` does
anything.** The request used to be a LIST — `Nunito+Sans:wght@300;400;500;600` — while
the stylesheet declares 700 or 800 in **~450 places**. CSS font matching resolves a
missing 700 down to the nearest loaded face, which was 600, and Chrome only synthesises
bold when the matched face is *below* 600 — so it did not synthesise either. Every
"bold" on the site rendered as **SemiBold**, identical to the 600 beside it, and nothing
anywhere errored. Found chasing *"font isn't cool"* on the calendar's timeline, where the
label title (800) and its date (600) were supposed to be two tiers and were the same
pixels.

- **Measured on the latin subset: 7 files / 202 KB → 2 files / 57 KB**, and every weight
  300–800 becomes real. The range form is smaller AND more correct; there is no tradeoff
  to weigh here.
- **⚠ Narrowing either family back to a `;`-list silently flattens bold again**, and the
  symptom is "the type looks a bit flat", not an error. The families must also stay in
  alphabetical order — css2 rejects the request otherwise.
- **Real 700 is ~1.6% wider than the 600 it used to fall back to** (800, ~3.3%). Cleared
  against the documented tight spots on the day: no horizontal overflow at 360/375/412/1400
  on home, /calendar, /screener, /cards, /analytics, and `.home-toolbar .seg-grp` still
  holds one row from 375px up (it wraps at 360px, which is its documented contract).
- **All four HTML entry points ask for the same two files** — `Index.html`, `swiss.html`,
  `picks.html`, `ticker.html`. They had drifted into three different requests, so moving
  between pages pulled a second set of statics instead of reusing the cache.
- **A canvas export must `document.fonts.load` every (weight, size) it paints**, because a
  canvas falls back to the generic family silently when a face is not loaded at the exact
  weight asked for. `buildCalendarTimelineBlob` loads Cinzel 700/600 and Nunito Sans
  500/600/700 up front, all best-effort — a blocked font network degrades to the fallback
  stack rather than failing the export.
- Verifying any of this needs the fonts actually loaded, and **`fonts.googleapis.com` is
  egress-blocked from the agent browser** (`document.fonts` comes back empty, so every
  weight collapses and the probe lies). Route `fonts.googleapis.com/**` and
  `fonts.gstatic.com/**` in Playwright and fulfil them from a shell `curl`, which does have
  egress.
