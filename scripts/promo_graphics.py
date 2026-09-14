#!/usr/bin/env python3
"""
promo_graphics.py — render the designed promo graphics from their HTML sources.

Every graphic in `promo/images/` is an HTML page in `promo/graphics_src/`
screenshotted at its declared body size. That indirection is the point: the
graphics embed the UI screenshots by path, so re-shooting with
`promo_capture.py` and re-rendering here refreshes every card, banner and square
without anyone opening an image editor.

    python scripts/promo_graphics.py --list
    python scripts/promo_graphics.py                  # render all
    python scripts/promo_graphics.py --only card_calendar sq_hero

Sources reference their assets RELATIVELY (`../shots/...`, `../../Logos/...`) so
the tree can move machines. A template that hardcodes a file:/// path renders
once, on one laptop, and silently renders blank frames anywhere else.
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "promo", "graphics_src")
OUT = os.path.join(REPO, "promo", "images")
OVERLAYS = os.path.join(REPO, "promo", "video", "overlays")

# Overlay plates are drawn at video size and composited by assemble.mjs; the
# rest are social graphics. Size comes from the page's own body rule, so a
# template is free to declare whatever it needs.
FALLBACK = (1600, 900)

# Render scale. Output stays at the declared CSS size; see render().
SS = 2


def is_overlay(name: str) -> bool:
    """ov_* / ovv_* are caption plates ffmpeg lays OVER the footage."""
    return name.startswith("ov_") or name.startswith("ovv_")


def dest_dir(name: str) -> str:
    return OVERLAYS if is_overlay(name) else OUT


def render(page, name: str) -> tuple[int, int]:
    path = os.path.join(SRC, name + ".html")
    page.goto("file:///" + path.replace("\\", "/"), wait_until="load", timeout=60000)
    try:
        page.wait_for_function("document.fonts && document.fonts.status === 'loaded'",
                               timeout=8000)
    except Exception:
        pass
    # Give embedded screenshots a beat to decode — a half-decoded <img> renders
    # as an empty frame and the failure is invisible until someone posts it.
    page.wait_for_timeout(900)
    size = page.evaluate(
        "() => {const b=document.body;const r=b.getBoundingClientRect();"
        "return [Math.round(r.width)||0, Math.round(r.height)||0];}")
    w, h = (size or FALLBACK)
    if not w or not h:
        w, h = FALLBACK
    page.set_viewport_size({"width": w, "height": h})
    page.wait_for_timeout(350)
    out = dest_dir(name)
    os.makedirs(out, exist_ok=True)
    # ⚠ A plate rendered without omit_background comes out as an opaque
    # 1920x1080 rectangle, and ffmpeg then covers the entire video with it —
    # the footage disappears and only the finished MP4 shows it.
    dest = os.path.join(out, name + ".png")
    page.screenshot(path=dest, omit_background=is_overlay(name))
    # SUPERSAMPLE: render at SS x device scale, resample back down here.
    # Measured on banner_x, the honest result is +9% edge acutance overall, and
    # it is NOT evenly spread: the headline is indistinguishable (large glyphs
    # were already well antialiased at 1x) and the whole gain is in the EMBEDDED
    # SCREENSHOT, which now goes 1920 -> 1484 in the browser then 1484 -> 742 by
    # Lanczos, instead of 1920 -> 742 in one browser pass. So this earns its
    # keep on cards that embed a UI shot and does close to nothing elsewhere.
    if SS != 1:
        from PIL import Image
        im = Image.open(dest)
        im.resize((w, h), Image.LANCZOS).save(dest)
    return w, h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    names = sorted(os.path.splitext(os.path.basename(p))[0]
                   for p in glob.glob(os.path.join(SRC, "*.html")))
    if a.list:
        for n in names:
            print(n)
        return 0
    if a.only:
        missing = [n for n in a.only if n not in names]
        if missing:
            print("no such source:", ", ".join(missing))
            return 1
        names = [n for n in names if n in a.only]

    os.makedirs(OUT, exist_ok=True)
    from playwright.sync_api import sync_playwright
    ok = fail = 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1600, "height": 900},
                          device_scale_factor=SS)
        for n in names:
            try:
                w, h = render(page, n)
                print(f"  ok   {n}  {w}x{h}")
                ok += 1
            except Exception as e:
                print(f"  FAIL {n}: {str(e)[:140]}")
                fail += 1
        b.close()
    print(f"\n{ok} rendered, {fail} failed -> {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
