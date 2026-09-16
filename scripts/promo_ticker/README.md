# Stream-ticker promo videos

> **Not the same thing as `scripts/promo_*.py`.** That is the site tour kit —
> `promo_video.py` records segments of the real signed-in app and
> `promo/build/assemble.mjs` cuts them into `tour_main.mp4` / `tour_mobile.mp4`
> plus feature shorts. Its `SEGMENTS` list has never covered the stream ticker.
> This is a self-contained pair of ticker shorts that needs neither the demo
> account nor the assemble step, because the ticker is a standalone page with
> no app state to drive. If the ticker should instead become `seg_ticker` /
> `seg_m_ticker` in that pipeline, the copy and timing here port over directly.

Two cuts of the same 36-second script, both recorded from the **real**
`/ticker?bar=1` page running in an iframe sized like an OBS browser source:

| file | size | for |
|---|---|---|
| `promo/stream-ticker-desktop.mp4` | 1920×1080 | Twitter/X, YouTube, Discord, the site |
| `promo/stream-ticker-mobile.mp4` | 1080×1920 | TikTok, Reels, Shorts, Discord on a phone |

```
node scripts/promo_ticker/record_promo.mjs                 # both, into promo/
node scripts/promo_ticker/record_promo.mjs --only mobile   # one format
node scripts/promo_ticker/record_promo.mjs --stills 4,12,20,27   # PNG frames, no encode
```

Needs `playwright-core` (a devDependency — `npm install`), a Chromium and an
`ffmpeg` **with libx264**. Both are auto-detected; override with `PROMO_CHROME`
/ `PROMO_FFMPEG` / `PROMO_PYTHON`.

> ⚠ **Playwright's bundled ffmpeg cannot be used.** It is a stripped build —
> libvpx/webm only, no libx264 and no mp4 muxer — so it is deliberately absent
> from the search list. On Windows the detector looks for a real gyan.dev
> build; if none is found, install one and point `PROMO_FFMPEG` at it.

## The script

Five beats, identical in both formats so the two cuts say the same thing at the
same moment. `FEATURES` / `GRADED` / `CUSTOM` / `CTASTEPS` in
`promo_scene.html` hold the copy; `__seek` derives every fade and stagger from
`BEATS`, so re-timing needs nothing else touched.

| beat | what it says |
|---|---|
| head | what it is: a free scrolling overlay for OBS |
| reel | what is in it — windows, rarity groups, direction, price floor |
| graded | graded slabs: graders, grades, movers vs top sales |
| custom | the real page, panned through every setting it offers |
| cta | 1-2-3 to OBS, and `packs.ink/ticker` |

The three middle beats each show the **real configurator beside the copy**,
parked on the card that beat is describing — reel bullets next to "What's in
the reel", graded bullets next to "Graded slabs", and so on. The recorder
measures those card rectangles; the scene decides whether each one fits the
frame whole (centre it and hold) or has to be swept.

## ⚠ The cut is measured in BARS, not seconds

The backing track is **139.675 BPM**, measured off the file (an FFT
autocorrelation of its onset envelope), so a bar is 1.7184s. The video is 21
bars — one of lead-in, then four per block — which is why it is 36.09s and not
a round 36. Every block therefore appears on a downbeat.

`BPM` appears in **both** `promo_scene.html` and `record_promo.mjs` and the two
must agree: the scene derives the beat windows from it and the recorder derives
the total duration. `AUDIO_START` (32.388s) is also a downbeat, chosen because
it is where the chorus enters — energy jumps 0.34 → 0.77 there and the window
still ends strong. **Move it to another downbeat or every cut drifts off the
beat.**

Audio lives at `promo/audio/ticker-promo.mp3` (gitignored, like everything else
under `promo/`) and is muxed in the same ffmpeg pass that encodes the frames,
so the video is never re-encoded to add sound. If the file is missing the run
still works and just produces a silent cut.

> ⚠ **The track is a commercial recording.** It is deliberately not committed,
> and a Disney-owned song on a Disney-adjacent fan site's promo is the kind of
> thing that gets muted or pulled by automated rights matching on YouTube,
> Instagram and TikTok. Swap `--audio` for a licensed bed if that matters.

## The bar in the video is the shipping bar

`promo_scene.html` is only a backdrop, some copy and an `<iframe>`. The ticker
inside it is `ticker.html` served by `scripts/dev_server.py` — same CSS, same
marquee, same `tickerRarityLine` rule that decides which cards say "· Foil". A
re-mocked bar would drift from the product the first time the product changed;
this one cannot.

## Every frame is a seek, not a capture

There is not one CSS transition or `@keyframes` in `promo_scene.html`.
`__seek(t)` positions every element as a pure function of `t`, and the recorder
steps `t` frame by frame, screenshotting each one. So the output is
deterministic, drops no frames, and does not care how fast the machine is —
unlike a real-time screen capture. The one thing that IS a CSS animation, the
ticker's own marquee, is driven through the Web Animations API (`pause()` then
`currentTime`), re-queried every frame because `layoutStrip()` tears the
animation down and rebuilds it whenever the bar re-measures.

## ⚠ Each beat cues the marquee to its own part of the reel

The reel is a marquee. The advertised config is nine sections long, and at
60 px/s that loop runs **over nine minutes** — so a 36-second video plays about
5% of it and would never reach a second section header. Each beat therefore
starts at its own offset into the *same* reel, chosen so the section that beat
is talking about is on screen. Within a beat the bar advances 1:1 with real
time, at exactly its configured speed; only the cut between beats moves it.

- Sections are picked **by what they say**, never by index — the section list
  is a product of the ticker's own config (windows × rarity groups, then
  graded), so an index would quietly point at a different section the moment
  that config changed.
- The cue position is **derived from the cap width plus one beat's travel**,
  not a fraction of the frame. The bar has a fixed packs.ink cap on its left,
  and a header that drifts under it is sliced in half for a couple of seconds —
  which reads as a rendering fault rather than as a marquee.

## ⚠ `/ticker` is two pages behind one path

With `?bar=` or `?embed=` it is the raw overlay page (`ticker.html`). **Bare, it
is the SPA's Analytics » Stream Ticker tab** — which is what someone told to
"go to packs.ink/ticker" actually lands on, and therefore what the "make it
yours" beat shoots.

That page shot is taken at **900 CSS px wide on purpose**: the configurator's
own layout goes single-column under 900px, which makes every settings card
~824px wide and genuinely readable when panned inside a frame. At desktop width
the same cards are a 340px column and the labels turn to mush on video.

The pan's end point is computed in the *scene*, not here: only the scene knows
the frame's height and scale, so only it can land the last card on the bottom
edge instead of sailing past it into the footer.

## ⚠ `--sample` is for a machine with no network

By default the run hits the **real Supabase feed and shows real card art**.
That is the version worth publishing, and it is the default.

`--sample` intercepts the Supabase query and answers it from `sample_data.mjs`,
and turns thumbnails off. The card names, versions and rarities are real (read
out of `scanner/index.json`, which already ships in this repo) but **the prices
and percentages are invented**. It exists for a sandbox with no egress to
`supabase.co` or the card-art CDN; use it to check layout, never to publish.

`--fonts <dir>` is the other no-network flag: it serves Google Fonts from a
local cache (`sh scripts/promo_ticker/fetch_fonts.sh <dir>`) for a browser that
cannot reach `fonts.googleapis.com`. Without the real Cinzel and Nunito Sans
every weight collapses to a fallback face and the bar measures itself against
type it will never ship with. On an ordinary machine, omit it.

## Before publishing

`--live` takes whatever that day's movers happen to be, so **look at the
result**. A slow news day makes a thinner reel; a graded section needs a long
enough window to have sales in it at all (1D and 1W are far thinner than 1M).
`--stills` is seconds rather than minutes and is the fast way to check.

The advertised config uses **NM Market** rather than the page's default Low
basis. Over a 1D/1W window Low is a published aggregate that can sit frozen and
throws multi-thousand-percent phantoms — real, derived, and indistinguishable
from a bug on screen. Every setting in the config is one the page offers, so
the bar in the video is a bar a viewer can actually build.
