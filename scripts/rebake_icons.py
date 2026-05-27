#!/usr/bin/env python3
"""Rebake the PWA / favicon set from Logos/packs-ink-logo.png.

Reasoning: the live PWA icon (and Android/iOS save-to-home-screen tile)
shows just the gold "packs.ink" wordmark on a dark-blue square because
the previous icon batch was a stripped-down render. The canonical brand
logo (Logos/packs-ink-logo.png) is the full booster-pack artwork —
sparkles + ribbon + crescent moon + wordmark. This script bakes that
full art onto the same #0f0d20 background so installed PWAs show the
right thing on home screens once the cache buster bumps.

Output files (overwritten in repo root):
  apple-touch-icon.png  180x180
  favicon-16.png         16x16  (kept for older browsers, currently unused
                                 in Index.html but referenced by some
                                 RSS-style readers)
  favicon-32.png         32x32
  favicon-64.png         64x64
  icon-192.png          192x192
  icon-512.png          512x512

Each output:
  - solid #0f0d20 background (matches manifest.json background_color)
  - source logo resized with aspect-ratio preserved, centered, with a
    ~12% margin inset so the artwork doesn't crowd the rounded-square
    masks Android / iOS apply on top of the icon.

Run from repo root:
  python scripts/rebake_icons.py
"""
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "Logos" / "packs-ink-logo.png"
BG = (0x0F, 0x0D, 0x20, 255)  # #0f0d20 — matches manifest theme + body bg

TARGETS = [
    ("apple-touch-icon.png", 180),
    ("favicon-16.png", 16),
    ("favicon-32.png", 32),
    ("favicon-64.png", 64),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
]

# Inset percentage — leaves padding so iOS/Android squircle masks don't
# clip artwork edges. 12% on each side = artwork occupies 76% of the icon
# width. Tweak if the wordmark looks too small or crowded.
INSET = 0.12


def rebake_one(source: Image.Image, out_path: Path, size: int) -> None:
    canvas = Image.new("RGBA", (size, size), BG)
    inset_px = int(size * INSET)
    content_size = size - 2 * inset_px
    # Resize the source so its longest edge equals content_size, preserving
    # aspect ratio. Logo is portraitish (1200x1244) — height drives the
    # scaling, leaving some horizontal slack inside the square.
    src = source.copy()
    src.thumbnail((content_size, content_size), Image.Resampling.LANCZOS)
    # Center the resized art in the canvas.
    x = (size - src.width) // 2
    y = (size - src.height) // 2
    canvas.paste(src, (x, y), src if src.mode == "RGBA" else None)
    canvas.save(out_path, "PNG", optimize=True)
    print(f"  wrote {out_path.name}  {size}x{size}  ({out_path.stat().st_size:,} bytes)")


def main() -> int:
    if not SOURCE.exists():
        print(f"ERROR: source logo not found at {SOURCE}", file=sys.stderr)
        return 1
    print(f"Source: {SOURCE.relative_to(REPO_ROOT)}")
    src = Image.open(SOURCE).convert("RGBA")
    print(f"  {src.width}x{src.height}, mode={src.mode}")
    print(f"Background: #{BG[0]:02x}{BG[1]:02x}{BG[2]:02x}")
    print(f"Inset: {INSET*100:.0f}% on each side")
    print(f"Outputs:")
    for name, size in TARGETS:
        rebake_one(src, REPO_ROOT / name, size)
    print()
    print("Done. Next steps:")
    print("  1. Bump ?v=N on every icon <link> in Index.html + manifest.json")
    print("  2. Bump CACHE_VERSION in sw.js")
    print("  3. Tell PWA users to delete + reinstall (iOS especially) — the")
    print("     home-screen icon is captured at install time and won't refresh")
    print("     even when manifest icons change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
