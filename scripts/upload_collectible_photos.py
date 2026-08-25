"""
upload_collectible_photos.py — publish the pin / lore-counter photos to the
public `card-art` Supabase Storage bucket.

The photos are Lorcana Player's, re-hosted here with their permission (granted
2026-08-24). Re-hosted rather than hotlinked for the usual two reasons — their
bandwidth isn't ours to spend, and a URL we don't control can move — plus one
specific to this job: what ships is not their file. `cut_collectible_bg.py`
takes the studio-white background off so a pin can sit on any of the seven
themes, which means the bytes have to live somewhere we control anyway.

Pins and lore counters are NOT rows in `sealed_products`. They're the static
LORCANA_PINS / LORCANA_LORE_COUNTERS consts in Index.html, rendered as
checklist tiles under synthetic pids; this script only handles their art. The
`n` in those consts is the STABLE id and is what names the object here, so
renumbering a const would orphan every uploaded photo.

Usage:
    python scripts/upload_collectible_photos.py --pins <dir> --counters <dir>
    # add --commit to actually upload (default is a dry run)

Input files are named pin-<n>.png / ctr-<n>.png, straight out of
cut_collectible_bg.py. Passing only the ones you're replacing is fine — the
missing-number warning is informational and the upload is an upsert.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

BUCKET = "card-art"
# Two prefixes rather than one flat folder: the two lists number from 1
# independently, so pin 12 and counter 12 would collide.
PREFIX_PINS = "collectibles/pins"
PREFIX_COUNTERS = "collectibles/counters"

EXPECTED_PINS = 41
EXPECTED_COUNTERS = 21
MAX_BYTES = 400 * 1024   # a tile photo past this means the cut script was skipped


def upload(sb, prefix: str, n: int, data: bytes) -> str:
    path = f"{prefix}/{n:02d}.png"
    r = requests.post(
        f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
        headers={
            "apikey": sb.key, "Authorization": f"Bearer {sb.key}",
            "Content-Type": "image/png", "x-upsert": "true",
            # These never change once uploaded; a new photo goes to a new `n`
            # or rides a cache-buster on the client side.
            "Cache-Control": "public, max-age=31536000, immutable",
        },
        data=data, timeout=60,
    )
    if not r.ok:
        raise RuntimeError(f"upload {path} failed ({r.status_code}): {r.text[:300]}")
    return f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"


def collect(folder: str, stem: str) -> dict:
    found = {}
    if not folder:
        return found
    for f in os.listdir(folder):
        m = re.match(rf"^{stem}-(\d{{1,3}})\.png$", f, re.I)
        if m:
            found[int(m.group(1))] = os.path.join(folder, f)
    return found


def run(sb, folder: str, stem: str, prefix: str, expected: int, commit: bool) -> int:
    found = collect(folder, stem)
    if not found:
        return 0
    missing = sorted(set(range(1, expected + 1)) - set(found))
    extra = sorted(k for k in found if k < 1 or k > expected)
    if missing:
        print(f"  WARNING missing numbers: {missing}")
    if extra:
        print(f"  WARNING unexpected numbers: {extra}")

    total = 0
    for n in sorted(found):
        data = open(found[n], "rb").read()
        total += len(data)
        flag = "  <-- LARGE, did you skip cut_collectible_bg.py?" if len(data) > MAX_BYTES else ""
        if commit:
            url = upload(sb, prefix, n, data)
            print(f"  #{n:02d} {len(data)//1024:>4}KB -> {url}{flag}")
        else:
            print(f"  #{n:02d} {len(data)//1024:>4}KB (dry run){flag}")
    print(f"  {len(found)} files, {total/1024/1024:.2f} MB")
    return len(found)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pins")
    ap.add_argument("--counters")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    if not args.pins and not args.counters:
        ap.error("give --pins and/or --counters")

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase() if args.commit else None

    n = 0
    if args.pins:
        print(f"pins -> {BUCKET}/{PREFIX_PINS}")
        n += run(sb, args.pins, "pin", PREFIX_PINS, EXPECTED_PINS, args.commit)
    if args.counters:
        print(f"lore counters -> {BUCKET}/{PREFIX_COUNTERS}")
        n += run(sb, args.counters, "ctr", PREFIX_COUNTERS, EXPECTED_COUNTERS, args.commit)

    if not args.commit:
        print(f"\nDRY RUN — {n} files would be uploaded. Re-run with --commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
