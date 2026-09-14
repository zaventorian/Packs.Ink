#!/usr/bin/env python3
"""
promo_kit.py — build promo/kit_final.html from kit_template.html.

The template carries the copy and `@@T:<asset>@@` placeholders; this inlines a
JPEG thumbnail of each as a data URI so the finished kit is ONE self-contained
file that survives being published as an artifact, mailed, or opened off a USB
stick. A kit that references `promo/images/*.png` by path is a kit that renders
as broken frames the moment it leaves this laptop.

    python scripts/promo_kit.py            # thumbs + build
    python scripts/promo_kit.py --check    # report placeholders, write nothing

Assets resolve from promo/images/ first, then promo/shots/ — the template refers
to both (`@@T:hero_announce@@`, `@@T:shot_d_home@@`).
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROMO = os.path.join(REPO, "promo")
IMAGES = os.path.join(PROMO, "images")
SHOTS = os.path.join(PROMO, "shots")
THUMBS = os.path.join(PROMO, "build", "thumbs")
TEMPLATE = os.path.join(PROMO, "kit_template.html")
FINAL = os.path.join(PROMO, "kit_final.html")

THUMB_W = 460
QUALITY = 72


def source_for(name: str) -> str | None:
    """`shot_d_home` -> promo/shots/d_home.png; `card_pins` -> promo/images/…"""
    if name.startswith("shot_"):
        p = os.path.join(SHOTS, name[5:] + ".png")
        return p if os.path.exists(p) else None
    for root in (IMAGES, SHOTS):
        p = os.path.join(root, name + ".png")
        if os.path.exists(p):
            return p
    return None


def thumb(name: str) -> str | None:
    """Return a data: URI for the asset, rebuilding the JPEG if it is stale."""
    src = source_for(name)
    if not src:
        return None
    from PIL import Image
    dst = os.path.join(THUMBS, name + ".jpg")
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
        im = Image.open(src).convert("RGB")
        h = max(1, round(im.height * THUMB_W / im.width))
        im = im.resize((THUMB_W, h), Image.LANCZOS)
        os.makedirs(THUMBS, exist_ok=True)
        im.save(dst, "JPEG", quality=QUALITY, optimize=True)
    with open(dst, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    src = open(TEMPLATE, encoding="utf8").read()
    names = re.findall(r"@@T:([A-Za-z0-9_]+)@@", src)
    uniq = sorted(set(names))
    missing = [n for n in uniq if not source_for(n)]

    print(f"{len(names)} placeholders, {len(uniq)} unique assets")
    if missing:
        print("MISSING SOURCE for: " + ", ".join(missing))
    if a.check:
        return 1 if missing else 0
    if missing:
        # A missing thumb renders as a broken frame in the gallery, which is
        # exactly the kind of thing nobody notices until it is published.
        print("refusing to build with missing assets — re-run the capture first")
        return 1

    out = src
    for n in uniq:
        out = out.replace(f"@@T:{n}@@", thumb(n))
    open(FINAL, "w", encoding="utf8").write(out)
    print(f"built {FINAL}  ({os.path.getsize(FINAL)/1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
