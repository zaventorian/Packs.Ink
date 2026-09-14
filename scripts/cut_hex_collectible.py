"""
cut_hex_collectible.py — cut a lore counter out of a photo that has NO plain
background, by finding the dial's own hexagon.

`cut_collectible_bg.py` is the right tool whenever the subject sits on a studio
sweep: it flood-fills inward from the frame edge and keeps whatever is
near-white AND connected to the border. That predicate is the whole design, and
it has no answer at all for a counter photographed on set art, on a game mat, or
screenshotted out of a carousel — there is no background colour to fill.

A lore counter is a REGULAR HEXAGON, which is a much stronger thing to know than
"the background is white". So this script does not look for background; it looks
for the subject, fits a hexagon to it, and masks to that. Everything outside the
hexagon goes, whatever colour it was.

    python scripts/cut_hex_collectible.py --in src --out out --contact sheet.png
    python scripts/cut_hex_collectible.py --in src --out out \
        --hex ctr-25=157,157,135,0,1.19   # cx,cy,r,deg[,aspect] — skip the fit

⚠ ALWAYS look at --contact, and look at --debug too when a fit is doubtful. The
failure here is not a hole or a fringe (the mask is a clean polygon by
construction) — it is a hexagon in the WRONG PLACE, which crops the dial and
keeps a wedge of background, and at thumbnail size that reads as a real photo.

⚠ A counter shot at an angle is a hexagon in PERSPECTIVE, not a regular one. The
fit allows an aspect and a rotation, which covers a mild tilt; a hard 3/4 angle
is not recoverable and the honest answer there is a better source photo.
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PAD_FRAC = 0.02
FEATHER = 0.8
# A hexagon fills 3*sqrt(3)/8 = 0.6495 of its bounding box. A fit whose mask
# covers far less than that has locked onto something smaller than the dial;
# far more and it is not a hexagon at all.
FILL_LO, FILL_HI = 0.52, 0.78


def hex_points(cx: float, cy: float, r: float, deg: float, aspect: float = 1.0):
    """Pointy-top hexagon, the orientation every Lorcana dial is printed in."""
    out = []
    for i in range(6):
        a = math.radians(deg - 90 + 60 * i)
        out.append((cx + r * aspect * math.cos(a), cy + r * math.sin(a)))
    return out


def subject_mask(bgr: np.ndarray) -> np.ndarray:
    """Rough 'this pixel is part of the thing in the middle' mask.

    GrabCut, seeded with a generous central rectangle. It beats edge-finding
    here because a dial's own art is high-contrast and full of edges, so Canny
    plus a polygon approximation locks onto a shape INSIDE the counter as
    readily as onto its rim."""
    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    rect = (int(w * 0.06), int(h * 0.06), int(w * 0.88), int(h * 0.88))
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    try:
        cv2.grabCut(bgr, mask, rect, bgd, fgd, 5, cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return np.ones((h, w), np.uint8)
    m = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype(np.uint8)
    # keep the component touching the centre; a carousel arrow or a neighbouring
    # dial in the same frame is foreground too, and it must not drag the fit
    n, lab = cv2.connectedComponents(m)
    if n > 1:
        mid = lab[h // 2, w // 2]
        if mid == 0:                       # centre landed on background
            sizes = [(lab == i).sum() for i in range(1, n)]
            mid = 1 + int(np.argmax(sizes))
        m = (lab == mid).astype(np.uint8)
    return m


def convex_hull_mask(m: np.ndarray) -> np.ndarray:
    """The subject mask's convex hull.

    ⚠ Fit against THIS, not the raw mask. A hexagon is convex by construction,
    but the GrabCut mask is not: wherever the dial's own art goes dark at the
    rim it merges with the background and a bite is taken out of the silhouette.
    Fitting to the bitten shape drags the hexagon inward and twists it to
    cover the damage — on the first real photo that was IoU 0.76 with two
    corners of the counter sliced off, against 0.94 fitting to the hull."""
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return m
    hull = cv2.convexHull(max(cnts, key=cv2.contourArea))
    out = np.zeros_like(m)
    cv2.fillPoly(out, [hull], 1)
    return out


def fit_hex(m: np.ndarray):
    """Search cx, cy, r, rotation (and a mild aspect) for the best-covering hexagon."""
    m = convex_hull_mask(m)
    ys, xs = np.nonzero(m)
    if len(xs) < 50:
        return None
    cx0, cy0 = float(xs.mean()), float(ys.mean())
    r0 = math.sqrt(m.sum() / (1.5 * math.sqrt(3)))       # area of a regular hexagon

    def score(cx, cy, r, deg, asp):
        poly = np.array(hex_points(cx, cy, r, deg, asp), np.int32)
        cand = np.zeros_like(m)
        cv2.fillPoly(cand, [poly], 1)
        union = int(np.logical_or(cand, m).sum())
        return (int(np.logical_and(cand, m).sum()) / union) if union else 0.0

    # Aspect ranges wide because a dial shot even slightly off-square is a
    # hexagon in perspective and comes out WIDER THAN TALL — the Attack of the
    # Vine promo measures ~1.19 against the 1.0 of a face-on dial.
    #
    # ⚠ But a wide aspect does NOT rescue a DROP SHADOW, and that is the failure
    # to watch for. GrabCut takes a counter's shadow for part of the counter, the
    # hull inherits it, and the best-covering hexagon of THAT shape is a taller
    # one sitting low — which crops the dial's top and lets a wedge of background
    # in at both bottom corners. It scored IoU 0.95 doing it, so the number says
    # nothing; only --debug does. A shadowed source is what `--hex` is for.
    #
    # Coarse then fine, because the full grid at a useful step is ~10^5 fills.
    ASPECTS = (0.86, 0.92, 0.98, 1.04, 1.10, 1.16, 1.22)
    best = None
    for deg in range(0, 60, 4):                          # 6-fold symmetric
        for asp in ASPECTS:
            for rs in (0.86, 0.92, 1.0, 1.08, 1.16):
                for dx in (-6, 0, 6):
                    for dy in (-6, 0, 6):
                        s = score(cx0 + dx, cy0 + dy, r0 * rs, deg, asp)
                        if best is None or s > best[0]:
                            best = (s, cx0 + dx, cy0 + dy, r0 * rs, deg, asp)
    _, bx, by, br, bdeg, basp = best
    for ddeg in (-3, -2, -1, 0, 1, 2, 3):
        for dasp in (-0.04, -0.02, 0, 0.02, 0.04):
            for drs in (0.96, 0.98, 1.0, 1.02, 1.04):
                for dx in (-4, -2, 0, 2, 4):
                    for dy in (-4, -2, 0, 2, 4):
                        cand = (bx + dx, by + dy, br * drs, bdeg + ddeg, basp + dasp)
                        s = score(*cand)
                        if s > best[0]:
                            best = (s,) + cand
    return best


def cut(path: str, size: int, override=None, debug_dir=None, poly_override=None):
    src = Image.open(path).convert("RGB")
    bgr = cv2.cvtColor(np.array(src), cv2.COLOR_RGB2BGR)
    w, h = src.size

    if poly_override:
        pts = [tuple(p) for p in poly_override]
        iou, how = float("nan"), "poly"
        cx = sum(p[0] for p in pts) / 6.0
        cy = sum(p[1] for p in pts) / 6.0
        r = deg = 0.0
        asp = 1.0
    elif override:
        cx, cy, r, deg = override[:4]
        asp = override[4] if len(override) > 4 else 1.0
        iou, how = float("nan"), "manual"
        pts = hex_points(cx, cy, r, deg, asp)
    else:
        m = subject_mask(bgr)
        fit = fit_hex(m)
        if not fit:
            raise ValueError("no subject found")
        iou, cx, cy, r, deg, asp = fit
        how = "auto"
        pts = hex_points(cx, cy, r, deg, asp)
        if debug_dir:
            d = np.array(src).copy()
            d[m.astype(bool)] = (0.5 * d[m.astype(bool)] + np.array([0, 128, 0])).astype(np.uint8)
            im = Image.fromarray(d)
            ImageDraw.Draw(im).polygon(hex_points(cx, cy, r, deg, asp), outline=(255, 0, 0))
            im.save(os.path.join(debug_dir, os.path.basename(path) + ".debug.png"))

    alpha = Image.new("L", (w, h), 0)
    ImageDraw.Draw(alpha).polygon(pts, fill=255)
    # Fill is measured against the POLYGON's own bounding box, never the frame's:
    # a hexagon is 3*sqrt(3)/8 of its bbox wherever it sits, but it can occupy
    # any fraction of the photograph it was cropped from.
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bw, bh = max(xs) - min(xs), max(ys) - min(ys)
    poly_area = float(np.array(alpha).astype(bool).sum())
    bbox_fill = poly_area / (bw * bh) if bw > 0 and bh > 0 else 0.0

    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(FEATHER))
    out = src.convert("RGBA")
    out.putalpha(alpha)

    box = out.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if box:
        pad = int(max(out.size) * PAD_FRAC)
        x0, y0, x1, y1 = box
        out = out.crop((max(0, x0 - pad), max(0, y0 - pad),
                        min(out.width, x1 + pad), min(out.height, y1 + pad)))
    if max(out.size) > size:
        s = size / max(out.size)
        out = out.resize((max(1, round(out.width * s)), max(1, round(out.height * s))), Image.LANCZOS)

    note = ""
    if how == "auto":
        if iou < 0.88:
            note = "  <-- LOW IoU %.2f, check --debug" % iou
        elif not (FILL_LO <= bbox_fill <= FILL_HI):
            note = "  <-- fill %.2f outside hexagon range, check --debug" % bbox_fill
    out.info["note"] = note
    out.info["fit"] = ("poly (6 hand-placed vertices)" if how == "poly" else
                       "%s cx=%.0f cy=%.0f r=%.0f deg=%.0f asp=%.2f iou=%.2f"
                       % (how, cx, cy, r, deg, asp, iou))
    return out


def contact_sheet(items, path, cell=200, cols=6):
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 16)), (245, 245, 247))
    d = ImageDraw.Draw(sheet)
    for i, (name, im) in enumerate(items):
        cx, cy = (i % cols) * cell, (i // cols) * (cell + 16)
        d.rectangle([cx + cell // 2, cy, cx + cell, cy + cell], fill=(24, 10, 34))
        th = im.copy()
        th.thumbnail((cell - 12, cell - 12), Image.LANCZOS)
        sheet.paste(th, (cx + (cell - th.width) // 2, cy + (cell - th.height) // 2), th)
        d.text((cx + 4, cy + cell + 3), name[:28], fill=(40, 40, 44))
    sheet.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--size", type=int, default=400)
    ap.add_argument("--hex", action="append", default=[],
                    help="stem=cx,cy,r,deg[,aspect] — skip the fit for this one image. "
                         "aspect>1 is wider than tall, which is what a tilted dial is.")
    ap.add_argument("--poly", action="append", default=[],
                    help="stem=x1,y1,...,x6,y6 — six explicit vertices, clockwise from "
                         "the top. The escape hatch for a dial shot in PERSPECTIVE, whose "
                         "outline is a general hexagon that no scaled regular one fits.")
    ap.add_argument("--contact")
    ap.add_argument("--debug", help="directory for fit overlays")
    args = ap.parse_args()

    overrides = {}
    for o in args.hex:
        stem, _, nums = o.partition("=")
        overrides[stem] = tuple(float(v) for v in nums.split(","))
    polys = {}
    for o in args.poly:
        stem, _, nums = o.partition("=")
        v = [float(x) for x in nums.split(",")]
        if len(v) != 12:
            ap.error("--poly %s needs 12 numbers (six x,y pairs), got %d" % (stem, len(v)))
        polys[stem] = [(v[i], v[i + 1]) for i in range(0, 12, 2)]

    os.makedirs(args.dst, exist_ok=True)
    if args.debug:
        os.makedirs(args.debug, exist_ok=True)
    made = []
    for f in sorted(os.listdir(args.src), key=lambda f: (len(f), f)):
        p = os.path.join(args.src, f)
        if not os.path.isfile(p):
            continue
        stem = os.path.splitext(f)[0]
        try:
            im = cut(p, args.size, overrides.get(stem), args.debug, polys.get(stem))
        except Exception as e:                                   # noqa: BLE001
            print("SKIP %-18s %s" % (f, e))
            continue
        im.quantize(colors=255, method=Image.FASTOCTREE,
                    dither=Image.FLOYDSTEINBERG).save(os.path.join(args.dst, stem + ".png"),
                                                      "PNG", optimize=True)
        made.append((stem, im))
        print("%-18s %4dx%-4d %-46s%s"
              % (stem, im.width, im.height, im.info["fit"], im.info["note"]))

    if args.contact and made:
        contact_sheet(made, args.contact)
        print("\ncontact sheet -> %s  (%d images)" % (args.contact, len(made)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
