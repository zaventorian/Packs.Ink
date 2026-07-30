"""
upload_coconut_art.py — publish the [Format Coconut] beta leader-card renders to
the public `card-art` Supabase Storage bucket.

Coconut cards are deliberately NOT rows in `cards`. They aren't ownable,
priceable, or collectable — inserting them would pollute Cards browse, the
Screener, set-completion math and the catalog cache with 18 phantom entries.
They live as the static COCONUT_CARDS const in Index.html; this script only
handles their art.

The renders are official Ravensburger beta assets (grayscale + "FOR BETA TEST
ONLY" watermark). Ravensburger has not published them to Lorcast or the official
gallery, so they're sourced from a community mirror and re-hosted here rather
than hotlinked. When Lorcast eventually indexes the set, swap COCONUT_CARDS'
img fields to the Lorcast URLs and this script becomes dead weight.

Usage:
    python scripts/upload_coconut_art.py --folder <dir-of-NNN-images>
    # add --commit to actually upload (default is a dry run)

Input files are named by Coconut collector number: 001.webp … 018.webp
(they're served with a .webp extension but are actually JPEG).
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys

import requests
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

BUCKET = "card-art"
PREFIX = "coconut"
IMG_WIDTH = 734  # matches Lorcast 'large'; tiles/posters downscale via CSS

# Coconut collector number -> slug, from the official beta card list PDF
# (files.disneylorcana.com/FormatCoconut_BetaCoconutCards.pdf). Used only to
# name the uploaded objects readably; the app keys off these same numbers.
COCONUT_SLUGS = {
    1:  "scar-finally-king",
    2:  "ariel-spectacular-singer",
    3:  "winnie-the-pooh-hunny-wizard",
    4:  "stitch-rock-star",
    5:  "ursula-deceiver-of-all",
    6:  "mickey-mouse-brave-little-tailor",
    7:  "mufasa-ruler-of-pride-rock",
    8:  "nick-wilde-wily-fox",
    9:  "snow-white-merry-as-the-morning",
    10: "donald-duck-fred-honeywell",
    11: "mr-incredible-super-strong",
    12: "moana-curious-explorer",
    13: "john-silver-greedy-treasure-seeker",
    14: "robin-hood-sneaky-sleuth",
    15: "tinker-bell-giant-fairy",
    16: "sisu-emboldened-warrior",
    17: "pocahontas-peacekeeper",
    18: "dumbo-ninth-wonder-of-the-universe",
}


def optimize(path):
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    if im.width > IMG_WIDTH:
        h = round(im.height * IMG_WIDTH / im.width)
        im = im.resize((IMG_WIDTH, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue(), im.size


def upload(sb, cn, data):
    path = f"{PREFIX}/{cn:03d}.jpg"
    r = requests.post(
        f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
        headers={
            "apikey": sb.key, "Authorization": f"Bearer {sb.key}",
            "Content-Type": "image/jpeg", "x-upsert": "true",
        },
        data=data, timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"upload {path} failed ({r.status_code}): {r.text[:300]}")
    return f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase() if args.commit else None

    found = {}
    for f in os.listdir(args.folder):
        m = re.match(r"^(\d{1,3})\.(webp|jpg|jpeg|png)$", f, re.I)
        if m:
            found[int(m.group(1))] = os.path.join(args.folder, f)

    missing = sorted(set(COCONUT_SLUGS) - set(found))
    extra = sorted(set(found) - set(COCONUT_SLUGS))
    if missing:
        print(f"WARNING missing collector numbers: {missing}")
    if extra:
        print(f"WARNING unexpected files for: {extra}")

    total = 0
    for cn in sorted(found):
        data, size = optimize(found[cn])
        total += len(data)
        slug = COCONUT_SLUGS.get(cn, "?")
        if args.commit:
            url = upload(sb, cn, data)
            print(f"  #{cn:03d} {slug:<38} {size[0]}x{size[1]} {len(data)//1024:>4}KB -> {url}")
        else:
            print(f"  #{cn:03d} {slug:<38} {size[0]}x{size[1]} {len(data)//1024:>4}KB (dry run)")

    print(f"\n{len(found)} images, {total//1024}KB total"
          f"{'' if args.commit else ' — dry run, pass --commit to upload'}")


if __name__ == "__main__":
    main()
