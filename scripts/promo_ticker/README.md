# Stream-ticker promo videos

> **Not the same thing as `scripts/promo_*.py`.** That is the site tour kit —
> `promo_video.py` records segments of the real signed-in app and
> `promo/build/assemble.mjs` cuts them into `tour_main.mp4` / `tour_mobile.mp4`
> plus feature shorts. Its `SEGMENTS` list has never covered the stream ticker.
> This is a self-contained pair of ticker shorts that needs neither the demo
> account nor the assemble step, because the ticker is a standalone page with
> no app state to drive. If the ticker should instead become `seg_ticker` /
> `seg_m_ticker` in that pipeline, the copy and timing here port over directly.

Two cuts of the same 30-second script, both recorded from the **real**
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

Needs `playwright-core` (a devDependency — `npm install`), a Chromium, and an
`ffmpeg` with libx264 on `PATH`. Override either with `PROMO_CHROME` /
`PROMO_FFMPEG`.

## The bar in the video is the shipping bar

`promo_scene.html` is only a backdrop, some copy and an `<iframe>`. The ticker
inside it is `ticker.html` served by `scripts/dev_server.py` — same CSS, same
marquee, same `tickerRarityLine` rule that decides which cards say "· Foil". A
re-mocked bar would drift from the product the first time the product changed;
this one cannot. The configurator screenshots in the "three steps" beat are
likewise real: `locator.screenshot()` over the live `/ticker` page.

## Every frame is a seek, not a capture

There is not one CSS transition or `@keyframes` in `promo_scene.html`.
`__seek(t)` positions every element as a pure function of `t`, and the recorder
steps `t` frame by frame, screenshotting each one. So the output is
deterministic, drops no frames, and does not care how fast the machine is —
unlike a real-time screen capture. The one thing that IS a CSS animation, the
ticker's own marquee, is driven through the Web Animations API (`pause()` then
`currentTime`), re-queried every frame because `layoutStrip()` tears the
animation down and rebuilds it whenever the bar re-measures.

## ⚠ `--live` vs the sample rows

By default the run **intercepts the Supabase query and answers it from
`sample_data.mjs`**, and turns card-art thumbnails off.

That is not the preferred output — it is the only possible one from an agent
sandbox, which has no egress to `supabase.co` or to the card-art CDN. The card
names, versions and rarities are real (read out of `scanner/index.json`, which
already ships in this repo) but **the prices and percentages are invented**, so
the bar renders real shapes without the video claiming a market day it cannot
know. Nothing on screen dates the numbers. Thumbnails are off rather than
faked, because inventing card art would misrepresent what the product shows.

**From a machine with normal network access, run `--live`** — real prices, real
art, no interception at all:

```
node scripts/promo_ticker/record_promo.mjs --live
```

That is the version worth publishing. Check the result before posting: `--live`
takes whatever that day's movers happen to be, and a slow news day makes a
thinner reel than the sample set does.

`--fonts <dir>` is the other sandbox-only flag: it serves Google Fonts from a
local cache (`sh scripts/promo_ticker/fetch_fonts.sh <dir>`) for a browser that cannot
reach `fonts.googleapis.com`. Without the real Cinzel and Nunito Sans every
weight collapses to a fallback face and the bar measures itself against type it
will never ship with. On an ordinary machine, omit it.

## Editing the script

`BEATS` in `promo_scene.html` holds the four beat windows in seconds; `FEATURES`
and `STEPS` hold the copy. Changing a beat's timing needs nothing else touched —
`__seek` derives every fade and stagger from those numbers. Re-render with
`--stills` first; it is seconds rather than minutes.
