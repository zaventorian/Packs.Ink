"""
cut_collectible_bg.py — turn photographed pin / lore-counter shots into
transparent PNGs the collectibles checklist can drop onto any theme.

The source photos are pins on a white studio background. A naive "every white
pixel becomes transparent" punches holes straight through the white parts of
the pin itself (Baymax, most of the logo pins, every ink symbol's highlight),
so the background is found by FLOOD FILL from the border instead: a pixel is
background only if it is near-white AND connected to the edge of the frame.

The second half of the job is the halo. A JPEG of a dark object on white has an
edge ring of pixels that are genuinely half-white — they were never part of the
pin — and leaving them opaque puts a bright fringe around every pin on a dark
theme, which is exactly where these tiles live. Eroding the alpha by a pixel
before feathering removes the ring; losing one pixel off a 600px render is
invisible, a white outline is not.

Usage:
    python scripts/cut_collectible_bg.py --in <src-dir> --out <dst-dir>
    python scripts/cut_collectible_bg.py --in src --out out --contact contact.png

Input files may be any Pillow-readable format with any extension (the CDN
serves .jpg URLs that are sometimes PNG); output is always PNG with alpha,
trimmed to content and scaled so the long side is --size px.

--contact writes one sheet of every result over a split light/dark ground. Look
at it. Background removal fails quietly and per-image — a pin photographed on a
slightly grey card, or one whose own body is white to the frame edge, comes out
either uncut or eaten, and only your eyes catch that.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

# Near-white test, as a LADDER from loose to strict. WHITE_MIN is the floor for
# the darkest channel; SAT_MAX keeps a coloured-but-bright pixel (a pale gold
# rim, a lit enamel face) out of the background set.
#
# One fixed setting cannot do this job. A loose threshold cuts a JPEG-noisy
# background cleanly but leaks straight through a pale subject into its middle:
# the Winterspell counter is Stitch in SNOW, photographed on white, and a loose
# cut ate a hole through the snowdrift. A strict threshold protects that but
# leaves a grey rim around everything else. So each image walks the ladder and
# keeps the LOOSEST setting that does not punch a hole in the subject, which is
# a thing you can measure (see hole_fraction) rather than a thing you have to
# notice on a contact sheet.
LADDER = [(226, 22), (238, 14), (246, 8), (251, 4)]
# Leak detector. RAGGEDNESS is the cut's perimeter over the perimeter a circle
# of the same area would have, so 1.0 is a disc and a hexagonal pin lands near
# 1.3. A leak shreds the outline, and the separation is not subtle: across all
# 62 real photos every clean cut measured <= 1.65 and the one leak measured
# 4.40. 1.8 sits in the empty middle. Re-measure before moving it — the numbers
# are what justify it, not the round figure.
MAX_RAGGEDNESS = 1.8
MAX_HOLE_FRAC = 0.004   # walled-in transparency; a different way to leak
BG = 128          # sentinel written into the mask by the flood fill
PAD_FRAC = 0.02   # breathing room around the trimmed subject


def near_white_mask(rgb: Image.Image, white_min: int, sat_max: int) -> Image.Image:
    """L-mode mask, 255 where the pixel could be studio background."""
    r, g, b = rgb.split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    lightest = ImageChops.lighter(ImageChops.lighter(r, g), b)
    sat = ImageChops.subtract(lightest, darkest)
    bright = darkest.point(lambda v: 255 if v >= white_min else 0)
    grey = sat.point(lambda v: 255 if v <= sat_max else 0)
    # Both conditions: multiply of two 0/255 masks is a logical AND.
    return ImageChops.multiply(bright, grey)


def flood_from_border(mask: Image.Image) -> Image.Image:
    """Mark every candidate-background pixel reachable from the frame edge."""
    w, h = mask.size
    px = mask.load()
    for s in border_seeds(w, h):
        if px[s] == 255:
            ImageDraw.floodfill(mask, s, BG, thresh=0)
    return mask


def raggedness(solid: Image.Image) -> float:
    """Perimeter of the opaque region / perimeter of an equal-area circle.

    This is the measure that actually catches a leak. The obvious one --
    transparency walled in by the subject -- misses the common case, because a
    fill that escapes through a low-contrast seam usually stays CONNECTED to
    the outside; it eats a bay into the subject rather than an island inside
    it. What it always does is make the outline enormously longer."""
    area = sum(solid.histogram()[200:])
    if not area:
        return 999.0
    inner = solid.filter(ImageFilter.MinFilter(3))
    perim = area - sum(inner.histogram()[200:])
    return perim / (2.0 * math.sqrt(math.pi * area))


def hole_fraction(solid: Image.Image) -> float:
    """Fraction of the frame that is transparent but WALLED IN by the subject.

    A leak shows up as exactly this: the fill escapes through a low-contrast
    seam, spreads inside the subject, and leaves islands of transparency with
    opaque pixels all around them. Genuine enclosed background (the gap inside
    a ring pin) is rare and small; a leak is neither."""
    w, h = solid.size
    # Flood the TRANSPARENT region inward from the edge; whatever transparency
    # the flood cannot reach is enclosed.
    probe = solid.point(lambda v: 255 if v < 128 else 0)   # 255 = transparent
    probe = flood_from_border(probe)
    enclosed = probe.point(lambda v: 255 if v == 255 else 0)
    return sum(enclosed.histogram()[200:]) / float(w * h)


def border_seeds(w: int, h: int):
    """Every 4th pixel around the frame. A background split by an object that
    touches two edges (a lanyard, a long logo pin) needs more than the four
    corners, and the flood fill returns instantly on an already-filled seed."""
    step = 4
    for x in range(0, w, step):
        yield (x, 0)
        yield (x, h - 1)
    for y in range(0, h, step):
        yield (0, y)
        yield (w - 1, y)


def has_real_alpha(im: Image.Image) -> bool:
    """True if the source already carries transparency worth keeping."""
    if im.mode not in ("RGBA", "LA", "P"):
        return False
    a = im.convert("RGBA").getchannel("A")
    lo, hi = a.getextrema()
    return lo < 250   # something in there is not fully opaque


def cut(path: str, size: int) -> Image.Image:
    src = Image.open(path)
    src.load()

    note = ""
    if has_real_alpha(src):
        out = src.convert("RGBA")
    else:
        rgb = src.convert("RGB")
        chosen = None
        for i, (wmin, smax) in enumerate(LADDER):
            mask = flood_from_border(near_white_mask(rgb, wmin, smax))
            solid = mask.point(lambda v: 0 if v == BG else 255)
            rag = raggedness(solid)
            holes = hole_fraction(solid)
            ok = rag <= MAX_RAGGEDNESS and holes <= MAX_HOLE_FRAC
            chosen = (solid, wmin, smax, rag, holes, i)
            if ok:
                break
        solid, wmin, smax, rag, holes, step = chosen
        if step:
            note = "  [step %d/%d wmin=%d sat=%d]" % (step + 1, len(LADDER), wmin, smax)
        if rag > MAX_RAGGEDNESS or holes > MAX_HOLE_FRAC:
            note = "  <-- LEAKED even at the strictest step (ragged %.2f)" % rag
        # Erode one pixel to drop the half-white JPEG ring, then feather so the
        # edge doesn't read as a cut-out.
        alpha = solid.filter(ImageFilter.MinFilter(3))
        alpha = alpha.filter(ImageFilter.GaussianBlur(0.7))
        out = rgb.convert("RGBA")
        out.putalpha(alpha)
    out.info["note"] = note

    box = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        pad = int(max(out.size) * PAD_FRAC)
        x0, y0, x1, y1 = box
        box = (max(0, x0 - pad), max(0, y0 - pad),
               min(out.width, x1 + pad), min(out.height, y1 + pad))
        out = out.crop(box)

    if max(out.size) > size:
        scale = size / max(out.size)
        out = out.resize((max(1, round(out.width * scale)),
                          max(1, round(out.height * scale))), Image.LANCZOS)
    return out


def coverage(im: Image.Image) -> float:
    """Fraction of the frame that survived as opaque — the number that tells
    you at a glance whether a cut ate the subject (near 0) or did nothing
    (near 1)."""
    a = im.getchannel("A")
    hist = a.histogram()
    solid = sum(hist[200:])
    return solid / float(im.width * im.height)


def contact_sheet(items, path, cell=170, cols=8):
    """One sheet, each cell split light/dark, so a white fringe or a hole in
    the subject is obvious in a single look."""
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 16)), (245, 245, 247))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(items):
        cx, cy = (i % cols) * cell, (i // cols) * (cell + 16)
        d.rectangle([cx + cell // 2, cy, cx + cell, cy + cell], fill=(24, 10, 34))
        th = im.copy()
        th.thumbnail((cell - 12, cell - 12), Image.LANCZOS)
        sheet.paste(th, (cx + (cell - th.width) // 2, cy + (cell - th.height) // 2), th)
        d.text((cx + 4, cy + cell + 3), name[:26], fill=(40, 40, 44))
    sheet.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--size", type=int, default=400,
                    help="longest side, px. 400 is 2x a checklist tile.")
    ap.add_argument("--no-quantize", action="store_true",
                    help="keep 24-bit colour (roughly 8x the bytes)")
    ap.add_argument("--contact")
    args = ap.parse_args()

    os.makedirs(args.dst, exist_ok=True)
    names = sorted(os.listdir(args.src),
                   key=lambda f: (len(f), f))   # pin-2 before pin-10
    made = []
    for f in names:
        p = os.path.join(args.src, f)
        if not os.path.isfile(p):
            continue
        try:
            im = cut(p, args.size)
        except Exception as e:                      # noqa: BLE001
            print("SKIP %-22s %s" % (f, e))
            continue
        stem = os.path.splitext(f)[0]
        out = os.path.join(args.dst, stem + ".png")
        # A photographed pin at tile size has nowhere near 16M colours in it;
        # a 255-colour palette is visually identical here and about an eighth
        # of the bytes, which matters when the checklist loads 62 of them.
        # FASTOCTREE is the one Pillow quantizer that keeps the alpha channel.
        keep = im
        if not args.no_quantize:
            keep = im.quantize(colors=255, method=Image.FASTOCTREE,
                               dither=Image.FLOYDSTEINBERG)
        keep.save(out, "PNG", optimize=True)
        cov = coverage(im)
        flag = im.info.get("note", "")
        if not flag and (cov > 0.93 or cov < 0.06):
            flag = "  <-- CHECK"
        print("%-16s %4dx%-4d  opaque %5.1f%%  %6.1f KB%s"
              % (stem, im.width, im.height, cov * 100,
                 os.path.getsize(out) / 1024, flag))
        made.append((stem, im))

    if args.contact and made:
        contact_sheet(made, args.contact)
        print("\ncontact sheet -> %s  (%d images)" % (args.contact, len(made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
