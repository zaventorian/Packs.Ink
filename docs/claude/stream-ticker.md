# Stream ticker (`/ticker`) — OBS overlay, added 2026-08-21

*Moved out of CLAUDE.md on 2026-09-30; CLAUDE.md keeps the pointer and the rules that bite.*

Built for streamers (vVonderland's Discord ask): a scrolling bottom-of-stream bar of the top
%-movers. **Standalone `ticker.html`, NOT part of the SPA** — same reasoning as swiss.html, plus
an OBS Browser Source should not boot the whole app. `?bar=1` renders ONLY the bar (transparent
page, every size keyed off `--tkh` = bar height, so the streamer scales it purely by sizing the
OBS source); without it the page is a configurator with live preview + "Copy overlay URL".

- **Route: `/ticker` has NO worker route on purpose.** Workers Assets' pretty-URL handling serves
  `ticker.html` for it through the asset fall-through with the query intact. Do NOT add a worker
  route that fetches `/ticker.html` — the assets layer 307s that to `/ticker` and DROPS the query
  string, and `?bar=1&…` IS the overlay's configuration (this is the same 307 that moved swiss to
  `/swiss`). Dev route in `dev_server.py`; listed in `build_dist.mjs`. **Bare `/ticker` (no `bar` /
  `embed`) is now the SPA's Stream Ticker TAB** (the worker's `tickerIsSpa`), so it is in the
  sitemap and NOT robots-disallowed (2026-09-26) — `ticker.html` keeps its noindex meta, and a
  crawler must be allowed to fetch a page to see that, so blocking `/ticker` only hid the tab. No
  sw.js involvement — the overlay never registers it and OBS's browser profile never visits the SPA.
- **The reel is SECTIONS, cycling (windows × rarity groups)** — reworked same day on Zaven's
  feedback. `buildTickerPlan(cfg)` emits one section per (time frame × group) in window-major
  canonical order, each introduced by an IN-REEL header ("1D Movers" over the group name) — the
  brand cap is the logo alone (2026-09-15; the "packs.ink" wordmark under it read as a second,
  smaller title beside the section headers). Groups mirror the home movers banners:
  Chase (Enchanted/Epic/Iconic) · Rare – Legendary · Promos · All Rarities.
  **Defaults (Zaven, 2026-09-15): 1D + 1W × Chase + Rare–Legendary, direction BOTH, LOW basis,
  20 cards/section**, **$5 floor** (user-settable; keeps 10-cent cards' +300% "moves" out —
  matches the Screener's default). **⚠ The floor is on the price the card STARTED the window at**
  (`low_prev` / `low_7d` … `market_365d`, one per `TK_WINDOWS.prior`), the home banners' rule — on
  TODAY's price a card that climbed from cents to $22 led a live 1Y bar at "549x" (2026-09-26). A
  gain past +1000% prints as the price MULTIPLE, `1 + p/100` (+1000% is 11x, not 10x).
  ⚠ **A default here is not a free choice: changing one RETARGETS every overlay already in the
  wild that took it.** `cfgToParams` writes only non-default params, so a streamer who accepted
  the defaults is running a bare `?bar=1` and picks up the new ones on their next load. Anyone who
  chose a value explicitly keeps it, because their URL names it. Measured at the $5 floor before
  the 2026-09-15 switch: Low has 70 risers / 107 fallers on 1D against NM Market's 113/97, and
  `both` needs only 10 a side — verified live afterwards, all four sections filled 20/20 (40
  risers, 40 fallers). The internal read on Low's stickiness is unchanged and lives in the TCGCSV
  notes; it is no longer said in USER-FACING copy (Zaven, 2026-09-15 — "remove the can sit frozen
  for weeks part"). `TIP_LOW` and the Help page were already clean; the ticker's own basis hint
  was the only place that carried it.
- **Data**: one PostgREST query per (section × direction) against `price_movers`, server-side
  `order={pct_col}.desc&limit=n` — never the full 5.8k-row matview on a stream machine. Params:
  `w`/`g` (csv, canonical-order sets), `foil=0`/`nf=0`, `m/dir/n/min/img/brand/speed/bg/fg` — the
  URL is the whole config, so a pasted OBS URL is set-and-forget. A failed query drops only its
  own section for the round and retries in 60s — an already-rendered strip is never blanked.
- **Refresh = once a day at 5:00 PM America/Chicago** (`nextTickerRefreshMs`, pure layer):
  prices change once daily (ETL 20:30 UTC ≈ 3:30 PM Chicago), and Zaven wants exactly one safe
  post-ETL check, not polling. Intl supplies Chicago's wall clock so DST is handled (CDT/CST both
  covered in the guard test); the initial page load still fetches immediately, and failed fetches
  retry in 60s. Don't turn it back into an interval.
- **The "powered by packs.ink" credit is REQUIRED** — it rides the SECTION HEADERS now (the
  header's third line, `.tk-sec-pow`), not a bottom strip: streamers cropped the strip away for
  height. `markTickerBrand` places it once per time frame and never more than
  `TK_BRAND_MAX_GAP` (2) sections apart. No param, no checkbox; the left cap is the optional one
  (`brand=0`). That attribution is the price of a free overlay riding our data — keep it.
  **⚠ The credit is placed on the PLAN, before any query runs, so it must be placed AGAIN after
  empty sections drop** (`tickerKeepFilled`) — dropping them took their credit along, and with
  `brand=0` a reel could carry no packs.ink anywhere (found 2026-09-26). Guarded.
- **A light Bar color swaps the accents** (`data-light`, set by `applyBarLook` from the bar
  colour's WCAG luminance, crossover 0.28): the gold/green/red/blue are tuned for a dark bar and
  read ~1.9:1 on white; the light set clears 5:1. A transparent bar keeps its dark scrim.
- **Double-clicking ticker.html from disk works** — that's how Zaven first tested it. Asset URLs
  are RELATIVE (file sits at site root, so they resolve the same at `/ticker` and on `file://`);
  on file:, card art hotlinks cards.lorcast.io directly (no /img-proxy route exists), the Copy URL
  is forced to `https://packs.ink/ticker` (a file:/// URL pasted into OBS breaks for anyone else),
  and `history.replaceState` is try/catch-guarded. Chip active-state styling carries hard token
  fallbacks + `!important` so toggles stay legible even with styles.css missing. No theme-toggle
  button (removed as confusing — the page follows the saved/system theme via the boot script).
- **Foil/Non-Foil toggles carry the Screener's chase bypass**: single-printing rarities
  (Enchanted/Epic/Iconic/Promo) ignore the printing filter — enforced server-side via
  `or=(printing.in.(…),rarity.in.(bypass))` on mixed groups, and by skipping the filter entirely on
  all-chase groups, else "non-foil only" silently empties every chase section. Verified live: the
  quoted in-lists inside `or=()` are valid PostgREST.
- **Marquee**: one `.tk-seq` duplicated until it spans ≥2 viewports, then `translateX` by exactly
  one sequence width, linear infinite — that equality is what makes the loop seamless. Duration =
  seqWidth / speed so `speed` is true px/s at any bar height. Thumbnails get explicit
  `aspect-ratio:5/7` + height so layout doesn't shift as images load (the measured width feeds the
  animation). Re-measures on resize and `document.fonts.ready`.
- Items render via `createElement` + `textContent` (card names are DB text — no innerHTML), as a
  3-line stack — name / version / rarity pill — with the price and its Δ%+arrow stacked to the
  right. **The rarity pill says "· Foil" ONLY for base-rarity foil variants** (`tickerRarityLine`
  owns the rule): chase rarities (Enchanted/Epic/Iconic/Promo) are inherently foil and never say
  it, and "Holofoil"/"Holo" never appear on this surface (TCGCSV's Holofoil label covers what are
  physically cold-foil printings — the holofoil-mislabel rule). `bg=transparent` keeps a
  translucent scrim on the brand cap and section headers so they stay readable over gameplay.
- **Guarded by `node scripts/test_ticker_query.mjs`** (extracts `parseTickerCfg` +
  `buildTickerPlan` + `tickerRarityLine` out of ticker.html, house pattern): section ordering +
  header text, window/metric → real matview column names, group rarity filters, foil-toggle
  bypass shapes, the rarity-line foil rule, both-mode split, min=0 not-null guard, clamps. Run it
  after touching the config layer.
- **It is an Analytics tab as of 2026-09-15** — at `/ticker` (its own path), embedding this page at
  `/ticker?embed=1`. See "Analytics tab" for the embed mechanism and the `_headers` carve-out it
  needs. `?bar=1` is still what goes into OBS.
- **⚠ The tab's settings live in the PAGE's address, not only the frame's (2026-09-26).**
  `TICKER_PARAM_KEYS` in Index.html is the one list of ticker params: the landing capture
  (`TICKER_EMBED_PARAMS`), the view-sync — which OWNS them at `/ticker` (so `?g=`/`?m=`, Price
  Graphing's and the Screener's letters everywhere else, survive there) and strips them anywhere
  else — and the mirror: the embedded configurator posts `packsink:embed-params` on every change
  and `AutoHeightFrame mirrorParamsAt="/ticker"` replaceStates them onto the page. Before, a
  refresh, a bookmark or Copy link reopened the default reel. Add a ticker param there too.
- **Switching Analytics tools across a PATH change (/ticker ↔ /analytics) is pushed by the
  view-sync, not the ?a= sync** (`marketPathPushed`). Replacing there rewrote the ticker's own
  history entry in place, so Back skipped the ticker — and ticker → Expected Value (no `?a=` on
  either side) got no entry at all.
- Not built: sealed products (client-computed in the SPA, no matview), per-card deep links from
  the bar, a home-Toolbox chip (deliberate — see the tab's note under "Analytics tab").

### Promo videos — 16:9 and 9:16 (2026-09-15)

`scripts/promo_ticker/` renders two 36-second cuts into `promo/` for social:
`stream-ticker-desktop.mp4` (1920x1080) and `stream-ticker-mobile.mp4` (1080x1920). Run
`node scripts/promo_ticker/record_promo.mjs`; see that folder's README. **Nothing here
ships** — `build_dist.mjs` is an include-list, so `promo/` and `scripts/` never reach the
Worker, and `promo/` is gitignored besides (it holds the tour kit's live demo password) — so
the two .mp4s are a REGENERATED artifact, never a committed one.

- **⚠ The cut is measured in BARS of the backing track, not in seconds.** The music is
  139.675 BPM — measured off the file by FFT-autocorrelating its onset envelope, not guessed —
  so a bar is 1.7184s and the video is 21 bars (one of lead-in, four per block), which is why
  it is 36.09s and not a round 36. **`BPM` appears in both `promo_scene.html` and
  `record_promo.mjs` and the two must agree**: the scene derives the beat windows, the recorder
  the duration. `AUDIO_START` (32.388s) is likewise a downbeat, picked because the chorus
  enters there (energy 0.34 → 0.77) and the window still ends strong — move it to another
  downbeat or every cut drifts off the beat. Audio is muxed in the SAME ffmpeg pass that
  encodes the frames, so the video is never re-encoded to add sound, and a missing file just
  yields a silent cut. **⚠ The track is a commercial Disney recording**: it lives in the
  gitignored `promo/audio/`, is never committed, and is the kind of thing automated rights
  matching mutes or pulls — swap `--audio` for a licensed bed before any paid push.
- **⚠ All three bullet beats show the configurator beside the copy**, each parked on the card
  that beat describes. The recorder measures those card rects; the SCENE decides whether a card
  fits the frame whole (centre and hold) or must be swept, because only it knows the frame
  height and scale. A card that already fits is deliberately NOT panned — motion for its own
  sake reads as drift at that size.
- **⚠ There is no "your camera" placeholder.** It sat top-left at 246px tall, exactly where the
  copy column starts (the bullet eyebrow is at 236px), so it ran into the text. The LIVE pill is
  top-RIGHT where nothing else goes and survives. On MOBILE the "your stream" watermark now
  stays up for the whole cut: the stream window is its own 16:9 box there and would otherwise be
  an empty black rectangle, which reads as a failed render rather than as "your content here".
- **Bullet headings are Cinzel uppercase** — the same face and treatment the ticker gives its own
  `.tk-sec-title`, so the copy beside the bar is set like the bar. Sub-lines stay sentence-case
  Nunito; a second line of tracked capitals at that size is a wall, not a clarification.

- **⚠ This is NOT `scripts/promo_*.py`, the site tour kit.** That one records segments of the
  real signed-in app (`promo_video.py`) and `promo/build/assemble.mjs` cuts them into
  `tour_main.mp4` / `tour_mobile.mp4`. **Its `SEGMENTS` list has never included the ticker**,
  and its whole non-script half lives under the gitignored `promo/`, so a fresh clone cannot
  run or extend it. Hence a standalone pair here.
- **⚠ The bar in both videos IS `ticker.html`, in an iframe sized like an OBS source** — same
  CSS, same marquee, same `tickerRarityLine`. A re-mocked bar drifts from the product the
  first time the product changes; this one can't.
- **⚠ Every frame is a SEEK, never a capture.** `promo_scene.html` holds no CSS transition and
  no `@keyframes`: `__seek(t)` is a pure function of time and the recorder steps it frame by
  frame, so output is deterministic whatever the machine's speed. The marquee — the one real
  CSS animation — rides the Web Animations API and is **re-queried every frame**, because
  `layoutStrip()` tears that animation down and rebuilds it whenever the bar re-measures.
- **⚠ Each beat cues the marquee to its OWN offset into the same reel.** The advertised config
  is nine sections, and at 60 px/s that loop runs over nine minutes — so a 36-second video
  plays ~5% of it and would otherwise never reach a second section header. Sections are picked
  **by what they say, never by index** (the list is a product of the ticker's own config), and
  the cue position is **the cap width plus one beat's travel**, not a fraction of the frame: a
  header that drifts under the fixed packs.ink cap is sliced in half for a couple of seconds,
  which reads as a rendering fault rather than as a marquee.
- **⚠ The "make it yours" beat shoots the SPA tab, because `/ticker` is two pages behind one
  path** — `?bar=`/`?embed=` is the raw overlay, bare is Analytics » Stream Ticker, and bare is
  what someone told to visit packs.ink/ticker lands on. It is captured at **900 CSS px wide on
  purpose**: the configurator goes single-column under 900px, which makes every settings card
  ~824px and readable when panned. At desktop width those cards are a 340px column and the
  labels turn to mush on video. The pan's end point is computed in the SCENE, since only it
  knows the frame height and scale needed to land the last card on the bottom edge.
- **⚠ LIVE is the default; `--sample` is the no-egress path** and its prices are invented, so
  it is for checking layout and never for publishing. The advertised config uses **NM Market**
  rather than the page's default Low basis: over 1D/1W, Low is a published aggregate that can
  sit frozen and throws multi-thousand-percent phantoms — real, derived, and indistinguishable
  from a bug on screen.
- **⚠ Playwright's bundled ffmpeg cannot encode these.** It is a stripped build (libvpx/webm
  only, no libx264, no mp4 muxer), so it is deliberately excluded from the binary search; the
  detector looks for a real gyan.dev build instead. Chromium, ffmpeg and python are all
  resolved rather than assumed (`PROMO_CHROME` / `PROMO_FFMPEG` / `PROMO_PYTHON`).
- **⚠ The dev server's stdio is DROPPED, not piped.** `dev_server.py` logs every request, and a
  piped stderr nobody drains fills its buffer and blocks the server mid-response — which
  surfaces as `ERR_EMPTY_RESPONSE` in the browser, not as an error in the recorder.
