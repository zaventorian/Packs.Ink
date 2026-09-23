# Lorcana Calendar promo video (desktop 16:9)

A ~77s cut recorded from the **real app** (this working tree, via the local dev
server) and edited onto a stage. Built around the user's workflow, with "Go
local" (find nearby Set Champs / prereleases / locals, follow a store) as the
centrepiece.

```
python scripts/dev_server.py 8850                          # in another shell
node scripts/promo_calendar/capture.mjs                    # raw clips + marks -> promo/calendar/clips/
node scripts/promo_calendar/compose.mjs                    # -> promo/calendar/lorcana-calendar-desktop.mp4
node scripts/promo_calendar/compose.mjs --stills 6,23,51   # PNG frames, no encode
node scripts/promo_calendar/compose.mjs --audio track.mp3  # mux music (none by default)
node scripts/promo_calendar/marksheet.mjs c_local out.png  # one labelled frame per mark
```

`promo/` is gitignored — outputs are regenerated, never committed.

## Pieces

- **`capture.mjs`** drives the app with Playwright, recording each clip from the
  CDP screencast at true 2x. Every action is a **mark** (`h.mark(name, sel)` or
  `{mark}` on a click): `<clip>.marks.json` records when it happened and where
  it was on screen. `c_local` runs first and follows a store, and its storage
  state carries into every later clip.
- **`plan.mjs`** is the edit, written against the marks: each shot is a list of
  `[clipFrom, clipTo, speed]` segments (a speed ramp — waits fast, payoffs near
  1x), a camera keyed to mark boxes, spotlight callouts on mark boxes, and a
  caption. `PACE` scales the whole cut.
- **`scene.html`** is the stage: window, camera, callouts, lower-third
  captions, chapter rail, hook/CTA cards. `__seek(t)` is a pure function of time.
- **`compose.mjs`** steps the scene frame by frame and pipes JPEGs to ffmpeg.

## ⚠ Things that were learned the hard way

- **Playwright's DPR emulation does NOT reach the screencast.** A 2x context
  still hands over 1440×900 frames. What works is `viewport: null` plus the
  `--force-device-scale-factor=2` Chrome flag, with the CSS viewport pinned by
  `Emulation.setDeviceMetricsOverride({deviceScaleFactor: 0})` — 0 means "keep
  the real 2x". Chrome won't size a window below ~500px, which is why the phone
  clips need the override rather than `--window-size`.
- **Filter prefs leak between clips** unless cleared: a region picked in one
  clip was still set in the next five. `BOOT` wipes `packsink:cal:*` and the
  finder's `packsink:sc*` keys per clip; `packsink:calSubs` (follows) is kept
  on purpose so the store followed in `d_finder` appears in every later clip.
  That is also why `c_local` is recorded first.
- **The finder's title button CLOSES the finder** when it is open — don't use
  it to dismiss a popover.
- On a phone, **"Follow a store" lives inside the Filters drawer**.
- The data is live: re-run capture on a different day and the month, the map
  pins and the finder results change. Look at the stills before publishing.

- **A capture can record the app FAILING** — one `c_views` take recorded
  "Can't reach the card database" after a transient Supabase error, and nothing
  errors. Look at the marksheet before composing.
- **The finder's ✕ sits over the "Just revealed" card strip**, so moving the
  cursor off it pops a card preview for a second; the edit starts after it.
