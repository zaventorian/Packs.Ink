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

Each card uploads TWO objects — the full render at `coconut/NNN.jpg` and a
chip-sized square crop at `coconut/thumbs/NNN.jpg`. Both are required: every
chip-sized surface asks for the thumb and falls back to the full art only if it
404s, and a whole grayscale CARD shrunk to a 28px chip reads as a broken-image
glyph. Thumbs used to be produced outside this script, which is why cn 19
shipped with neither.

Usage:
    python scripts/upload_coconut_art.py --folder <dir-of-NNN-images>
    # add --commit to actually upload (default is a dry run)

Input files are named by Coconut collector number: 001.webp … 019.webp
(they're served with a .webp extension but are actually JPEG). Passing a folder
with only the numbers you're replacing is fine — the missing-number warning is
informational, and the upload is an upsert at the same path.

Ravensburger rebalances a leader by RE-RENDERING it in place: same collector
number, footer stamp goes "[Format Coconut] • Beta" -> "• Beta 1.1". After
re-uploading one, bump that cn in `COCONUT_ART_REV` (Index.html).

⚠ Two things that bump does NOT do, both easy to over-trust. It reaches the
THUMB only — coconutThumbUrl appends ?v=, coconutArtUrl does not — and it is
not the difference between fresh and stale-forever: sw.js serves IMG_CACHE
stale-while-revalidate, so an un-bumped URL costs one more stale paint and then
self-corrects. What the bump actually buys is an IMMEDIATE swap. So after a
re-render the full card keeps the old wording for one more load, and the
revalidation is a dangling promise rather than an event.waitUntil, so a service
worker killed early can stretch that to several.
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

# Chip-sized square crop of the art box, uploaded beside the full card.
#
# ⚠ THUMB_BOX is MEASURED, not guessed. It was recovered by template-matching
# the already-shipped thumbs back against their own full renders: the same box
# wins on every card tested, and reproduces all seven sampled thumbs at MSE
# < 0.5 — i.e. JPEG requantization noise, not a fit. Every beta render is the
# same 734x1024 card template, so the art box is a CONSTANT; there is no art
# detection to get wrong. Re-solve it only if Ravensburger changes the frame.
THUMB_PX = 160
THUMB_BOX = (144, 87, 589, 532)  # l, t, r, b in pixels of an IMG_WIDTH-wide render

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
    # Beta 2 wave. Not in that PDF — Ravensburger has published no Beta 2 list
    # and the renders print no collector number, so 19 is ours, continuing 1-18.
    # It must match the card's `cn` in Index.html: that is what names this object
    # AND what the site displays as the card's number.
    19: "the-vine-towering-stalk",
}


def normalize(path):
    """Open and scale to the IMG_WIDTH geometry every measurement assumes."""
    im = Image.open(path)
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    # ⚠ Scale in BOTH directions, not only down. THUMB_BOX is in pixels of a
    # 734-wide render, so a narrower source cropped by a box measured for a
    # wider one lands somewhere else entirely — and the result still looks like
    # a plausible thumbnail, so nothing would catch it.
    if im.width != IMG_WIDTH:
        h = round(im.height * IMG_WIDTH / im.width)
        im = im.resize((IMG_WIDTH, h), Image.LANCZOS)
    return im


def encode(im, quality=82):
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def make_thumb(im):
    l, t, r, b = THUMB_BOX
    # Clamp to the image, so an off-template source gives a wrong-but-valid crop
    # rather than a crash or a black band.
    r, b = min(r, im.width), min(b, im.height)
    l, t = min(l, r - 1), min(t, b - 1)
    return im.crop((l, t, r, b)).resize((THUMB_PX, THUMB_PX), Image.LANCZOS)


def upload(sb, path, data):
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
        im = normalize(found[cn])
        data = encode(im)
        thumb = encode(make_thumb(im))
        total += len(data) + len(thumb)
        slug = COCONUT_SLUGS.get(cn, "?")
        head = (f"  #{cn:03d} {slug:<38} {im.size[0]}x{im.size[1]} "
                f"{len(data)//1024:>4}KB + thumb {len(thumb)//1024}KB")
        if args.commit:
            url = upload(sb, f"{PREFIX}/{cn:03d}.jpg", data)
            upload(sb, f"{PREFIX}/thumbs/{cn:03d}.jpg", thumb)
            print(f"{head} -> {url}")
        else:
            print(f"{head} (dry run)")

    print(f"\n{len(found)} cards, {2*len(found)} objects, {total//1024}KB total"
          f"{'' if args.commit else ' — dry run, pass --commit to upload'}")


if __name__ == "__main__":
    main()
