#!/usr/bin/env python3
"""Write CCQ across the Lorcana hex mark.

    python scripts/derive_ccq_mark.py [--check] [--contact]

Why this exists
---------------
A Challenge Championship Qualifier is drawn with Ravensburger's Lorcana hex; a
Disney Lorcana Challenge with their Challenge badge. The badge SAYS "LORCANA
CHALLENGE" in its own artwork, so it identifies itself — the hex says nothing,
and at the 17-24px a calendar chip gives it, "a hexagon" is all a reader gets.
Zaven's call (2026-09-20): the mark is licensed for this use, put CCQ on it.

⚠ It DERIVES from the baked mark, it does not replace it. `lorcana-hex.png`
stays exactly as `bake_brand_assets.py` produced it, because it is also the
mark a plain qualifier-less surface would want, and because a derived file that
overwrites its own source cannot be regenerated after the first run.

⚠ Re-run this after any `bake_brand_assets.py` run — a fresh bundle rewrites
lorcana-hex.png and this output would then be a label on last season's art.
`--check` says whether the output is stale without writing anything, and the
bake script's own README line points here.

How it is drawn
---------------
The hex is a dark field with a gold swirl through its middle, so gold text laid
straight over it disappears into the swirl. The band is what makes it legible:
a dark plate across the waist, then the word in the mark's own gold. At 4x with
a LANCZOS downsample the letters stay clean down to ~16px, below which nothing
would have helped.
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "Logos", "lorcana", "marks", "lorcana-hex.png")
OUT = os.path.join(ROOT, "Logos", "lorcana", "marks", "lorcana-hex-ccq.png")

WORD = "CCQ"
SS = 6                      # supersample factor; the source is only 111x128
BAND_H = 0.30               # share of the mark's height the plate covers
BAND_PAD = 0.03             # inset from the left/right extremes at the waist
# Read off the artwork rather than guessed: the swirl's gold and the field's
# navy. `--check` reprints them so a re-baked mark that changed palette shows up.
GOLD = (214, 193, 150, 255)
PLATE = (17, 24, 48, 236)

# Windows, then the usual Linux/CI locations. Bold only — the word is 3 letters
# at 20px and a regular weight reads as a smudge.
FONTS = [
    r"C:\Windows\Fonts\arialbd.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]


def pick_font(px):
    for f in FONTS:
        if os.path.exists(f):
            return ImageFont.truetype(f, px)
    raise SystemExit("no bold font found; add one to FONTS")


def sample_palette(im):
    """The mark's own gold and navy, for --check."""
    px = im.convert("RGBA").load()
    w, h = im.size
    golds, navies = [], []
    for y in range(h // 3, 2 * h // 3):
        for x in range(w // 4, 3 * w // 4):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            (golds if r > 150 and g > 130 and b < 200 and r >= b else navies).append((r, g, b))
    def mean(rows):
        if not rows:
            return None
        n = len(rows)
        return tuple(sum(c[i] for c in rows) // n for i in range(3))
    return mean(golds), mean(navies)


def build():
    base = Image.open(SRC).convert("RGBA")
    w, h = base.size
    big = base.resize((w * SS, h * SS), Image.LANCZOS)
    W, H = big.size

    # The plate spans the mark's widest row — its waist — so it never sticks out
    # past the silhouette. Measured from the alpha, not assumed, because a
    # re-baked mark may be trimmed differently.
    alpha = big.getchannel("A")
    mid = H // 2
    row = [x for x in range(W) if alpha.getpixel((x, mid)) > 16]
    x0, x1 = (row[0], row[-1]) if row else (0, W - 1)
    inset = int((x1 - x0) * BAND_PAD)
    x0, x1 = x0 + inset, x1 - inset

    bh = int(H * BAND_H)
    y0, y1 = mid - bh // 2, mid + bh // 2

    plate = Image.new("RGBA", big.size, (0, 0, 0, 0))
    ImageDraw.Draw(plate).rounded_rectangle(
        [x0, y0, x1, y1], radius=bh // 4, fill=PLATE)
    # ⚠ Clip the plate to the mark's OWN alpha, or its corners square off the
    # hexagon's points where the band meets the waist and the silhouette stops
    # being a hexagon.
    plate = Image.composite(plate, Image.new("RGBA", big.size, (0, 0, 0, 0)),
                            alpha.point(lambda v: 255 if v > 16 else 0))
    out = Image.alpha_composite(big, plate)

    # Fit the word to the plate rather than picking a size: the mark's
    # proportions are not ours to rely on.
    target_w = (x1 - x0) * 0.86
    size = bh
    for _ in range(40):
        f = pick_font(size)
        bb = ImageDraw.Draw(out).textbbox((0, 0), WORD, font=f)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        if tw <= target_w and th <= bh * 0.72:
            break
        size = int(size * 0.94)
    d = ImageDraw.Draw(out)
    bb = d.textbbox((0, 0), WORD, font=f)
    d.text(((x0 + x1) / 2 - (bb[2] + bb[0]) / 2, mid - (bb[3] + bb[1]) / 2),
           WORD, font=f, fill=GOLD)

    return out.resize((w, h), Image.LANCZOS), base


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report whether the output is missing or older than the mark")
    ap.add_argument("--contact", action="store_true",
                    help="also write a light/dark sheet at real sizes to look at")
    a = ap.parse_args()

    if not os.path.exists(SRC):
        sys.exit(f"missing {SRC} — run bake_brand_assets.py first")

    if a.check:
        gold, navy = sample_palette(Image.open(SRC))
        print(f"source palette: gold={gold} navy={navy}  (constants: {GOLD[:3]} {PLATE[:3]})")
        if not os.path.exists(OUT):
            sys.exit("STALE: lorcana-hex-ccq.png does not exist — run without --check")
        if os.path.getmtime(OUT) < os.path.getmtime(SRC):
            sys.exit("STALE: the mark was re-baked after this was derived — re-run")
        print("OK: lorcana-hex-ccq.png is newer than the mark it derives from")
        return

    out, base = build()
    out.save(OUT, optimize=True)
    print(f"wrote {os.path.relpath(OUT, ROOT)}  {out.size}  {os.path.getsize(OUT)} bytes")

    if a.contact:
        # ⚠ Look at it. This is a label on a logo at 17px; "it encoded without an
        # error" is not the same as "a person can read it".
        sizes = [13, 17, 24, 34, 64]
        pad, gap = 10, 12
        cw = sum(sizes) + gap * len(sizes) + pad * 2
        sheet = Image.new("RGBA", (cw, 64 * 2 + pad * 3 + 16), (255, 255, 255, 255))
        d = ImageDraw.Draw(sheet)
        d.rectangle([0, sheet.height // 2, cw, sheet.height], fill=(30, 14, 44, 255))
        for row, y in ((base, pad), (out, sheet.height // 2 + pad)):
            x = pad
            for s in sizes:
                sheet.alpha_composite(row.resize((max(1, int(s * row.width / row.height)), s),
                                                 Image.LANCZOS), (x, y + (64 - s) // 2))
                x += s + gap
        # ⚠ NOT into Logos/. build_dist.mjs ships that whole tree, so a debug
        # sheet left there would go out with the site. The repo root is an
        # explicit include-list, so nothing new there can ship by accident.
        p = os.path.join(ROOT, "_ccq_contact.png")
        sheet.save(p)
        print(f"contact sheet: {os.path.relpath(p, ROOT)}  (top = plain mark, bottom = CCQ)")


if __name__ == "__main__":
    main()
