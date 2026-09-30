"""Bake the "blank art" proxy template: Logos/proxy-blank.png.

The proxy dialog's "No art" face prints the REAL card with its art window
painted white. That needs to know, pixel for pixel, which part of a card is
art and which is frame. Nobody publishes that, but it can be measured: the
frame (black border, the brush blob behind the cost, the inkwell ring, the
stat shields) is the same pixels on every card of a layout, and the art is
different on every card. So for each layout we stack ~90 real Lorcast
renders and call a pixel FRAME when most cards agree on its colour, and ART
when they don't.

Output is one RGBA sprite of six 674x940 tiles, one per layout, laid out left
to right in TILES order (the same order as PROXY_BLANK_TILES in Index.html):

  white, alpha = the art window   -> drawn over a card, blanks the art
  frame colour, opaque            -> a band of border around the window,
                                     which paints over art that breaks out
                                     of the frame, and which the client also
                                     reads to decide whether a card is on the
                                     standard frame at all
  transparent                     -> everything else, left exactly as printed

Needs .env (SUPABASE_URL + key), network to cards.lorcast.io, numpy, scipy and
a Pillow that reads AVIF (12+). Re-run it if Ravensburger ever changes the
card frame; --contact writes a sheet of held-out cards with the template
applied. LOOK AT IT: a mask that is off by a few pixels fails silently, as a
coloured sliver along the border or a nick out of the frame.

  python scripts/bake_proxy_blank_mask.py --contact proxy_blank_check.png
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import random
import sys
import tempfile
import urllib.request

import numpy as np
from dotenv import load_dotenv
from PIL import Image
from scipy import ndimage as ndi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from supabase_client import Supabase  # noqa: E402

W, H = 674, 940
TILES = ["char_ink", "char_unk", "other_ink", "other_unk", "loc_ink", "loc_unk"]
BASE_RARITIES = "Common,Uncommon,Rare,Super Rare,Legendary"
FULL_ART = "Enchanted,Iconic,Epic"
# Not under Logos/lorcana/: that directory is bake_brand_assets.py's manifest
# output, and test_brand_art.mjs holds it to exactly that.
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Logos", "proxy-blank.png")

# A pixel is frame when at least this share of cards sit within FRAME_DIST of
# the layout's per-pixel median colour.
FRAME_AGREE = 0.55
FRAME_DIST = 40.0
# The border band painted in frame colour: frame pixels this close to the art.
REPAIR_BAND = 30
# The cost hex and its digit are frame but not black; the band stays out of it.
COST_CENTRE, COST_R = (66, 72), 58
# Where each layout's plate is sampled to find its top (portrait) or left
# (location) edge: a patch of plate that never carries text.
PORTRAIT_PLATE_REF = (575, 590, 20, 110)   # y0, y1, x0, x1
LOCATION_PLATE_REF = (150, 260, 334, 346)


def tile_of(r):
    t = r.get("card_type") or ""
    lay = "loc" if t == "Location" else "char" if t == "Character" else "other"
    return lay + ("_ink" if r.get("inkable") else "_unk")


def fetch(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (packs.ink proxy template bake)"})
    with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def load(path):
    im = Image.open(path)
    rgba = im.convert("RGBA")
    if rgba.size != (W, H):
        rgba = rgba.resize((W, H), Image.LANCZOS)
    a = np.asarray(rgba)
    return a[..., :3], a[..., 3]


def per_pixel_stats(rgbs, alphas):
    """Median colour, median alpha and colour agreement, in row strips so a
    90-card stack never has to exist as one float array."""
    med = np.zeros((H, W, 3), np.float32)
    agree = np.zeros((H, W), np.float32)
    amed = np.zeros((H, W), np.float32)
    for y0 in range(0, H, 80):
        y1 = min(H, y0 + 80)
        A = np.stack([x[y0:y1] for x in rgbs]).astype(np.float32)
        m = np.median(A, axis=0)
        med[y0:y1] = m
        agree[y0:y1] = (np.linalg.norm(A - m, axis=3) < FRAME_DIST).mean(0)
        amed[y0:y1] = np.median(np.stack([x[y0:y1] for x in alphas]).astype(np.float32), axis=0)
    return med, agree, amed


def plate_edge(rgbs, ref, scan, vertical):
    """Per column (portrait) or row (location): where the plate starts, found
    by voting which pixels match each card's own plate colour."""
    y0, y1, x0, x1 = ref
    votes = np.zeros((H, W), np.float32)
    for a in rgbs:
        a = a.astype(np.float32)
        patch = a[y0:y1, x0:x1].reshape(-1, 3)
        m = np.median(patch, axis=0)
        spread = np.percentile(np.linalg.norm(patch - m, axis=1), 90)
        votes += np.linalg.norm(a - m, axis=2) < max(spread * 1.3, 25)
    votes /= len(rgbs)
    lo, hi = scan
    n = H if vertical else W
    edge = np.full(n, np.nan)
    for i in range(n):
        line = votes[i, lo:hi] if vertical else votes[lo:hi, i]
        hit = np.where(line > 0.35)[0]
        if len(hit):
            edge[i] = lo + hit[0]
    fill = np.nanmedian(edge)
    edge = np.where(np.isnan(edge), fill, edge)
    return ndi.median_filter(edge, size=31 if vertical else 21, mode="nearest")


def build_tile(rgbs, alphas, zone, seed):
    med, agree, amed = per_pixel_stats(rgbs, alphas)
    cand = (agree < FRAME_AGREE) & zone
    cand = ndi.binary_opening(cand, iterations=1)
    lab, _ = ndi.label(cand)
    art = ndi.binary_fill_holes(lab == lab[seed[1], seed[0]])
    grown = ndi.binary_dilation(art, iterations=1)
    alpha = np.clip(ndi.gaussian_filter(grown.astype(np.float32), 0.7) * 1.15, 0, 1)

    yy, xx = np.mgrid[0:H, 0:W]
    dist = ndi.distance_transform_edt(~grown)
    lum = med.mean(axis=2)
    cost = (xx - COST_CENTRE[0]) ** 2 + (yy - COST_CENTRE[1]) ** 2 < COST_R ** 2
    band = (dist > 0) & (dist <= REPAIR_BAND) & zone & ~cost & (lum < 60) & (amed > 250) & (agree >= 0.8)

    tile = np.zeros((H, W, 4), np.uint8)
    tile[..., :3] = 255
    tile[..., 3] = np.round(alpha * 255).astype(np.uint8)
    tile[band, :3] = np.round(med[band]).astype(np.uint8)
    tile[band, 3] = 255
    return tile


def frame_score(tile, rgb):
    """The client's standard-frame test, on one card: the share of the band's
    pixels that are dark on this card. Kept in step with proxyFrameScore."""
    band = (tile[..., 3] == 255) & (tile[..., :3].mean(axis=2) < 60)
    return float((rgb[band].mean(axis=1) < 70).mean()) if band.any() else 0.0


def apply(tile, rgb):
    a = tile[..., 3:4].astype(np.float32) / 255
    return (rgb.astype(np.float32) * (1 - a) + tile[..., :3].astype(np.float32) * a).astype(np.uint8)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--per-tile", type=int, default=90, help="cards stacked per layout (default 90)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--cache", default=os.path.join(tempfile.gettempdir(), "packsink-proxy-blank"))
    ap.add_argument("--contact", help="write a sheet of held-out cards with the template applied")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()
    cols = "id,card_type,rarity,inkable,image_large"
    base = sb.select("cards", columns=cols, filters={
        "rarity": f"in.({BASE_RARITIES})", "image_large": "like.*cards.lorcast.io*"})
    chase = sb.select("cards", columns=cols, filters={
        "rarity": f"in.({FULL_ART})", "image_large": "like.*cards.lorcast.io*"})
    print(f"catalog: {len(base)} base-rarity cards, {len(chase)} full-art")

    os.makedirs(args.cache, exist_ok=True)
    rng = random.Random(args.seed)
    by_tile = {t: [] for t in TILES}
    for r in base:
        if r.get("inkable") is not None:
            by_tile[tile_of(r)].append(r)
    train, held = {}, []
    for t in TILES:
        rows = sorted(by_tile[t], key=lambda r: r["id"])
        rng.shuffle(rows)
        held += rows[:3]
        train[t] = rows[3: 3 + args.per_tile]
    held_chase = rng.sample(sorted(chase, key=lambda r: r["id"]), min(12, len(chase)))

    want = [r for t in TILES for r in train[t]] + held + held_chase
    with cf.ThreadPoolExecutor(8) as ex:
        paths = dict(zip([r["id"] for r in want], ex.map(
            lambda r: fetch(r["image_large"], os.path.join(args.cache, r["id"] + ".avif")), want)))

    imgs = {rid: load(p) for rid, p in paths.items()}
    yy, xx = np.mgrid[0:H, 0:W]

    portrait_plates = [imgs[r["id"]][0] for t in ("other_ink", "other_unk") for r in train[t]]
    top = plate_edge(portrait_plates, PORTRAIT_PLATE_REF, (430, 560), vertical=False)
    loc_plates = [imgs[r["id"]][0] for t in ("loc_ink", "loc_unk") for r in train[t]]
    left = np.minimum(plate_edge(loc_plates, LOCATION_PLATE_REF, (250, 420), vertical=True), 335)
    print(f"portrait plate top y={int(top.min())}..{int(top.max())}, location plate left x={int(left.min())}..{int(left.max())}")
    zones = {"portrait": yy < top[None, :], "loc": xx < left[:, None]}

    tiles = {}
    for t in TILES:
        rows = train[t]
        if len(rows) < 12:
            sys.exit(f"{t}: only {len(rows)} cards - too few to tell frame from art")
        loc = t.startswith("loc")
        tiles[t] = build_tile([imgs[r["id"]][0] for r in rows], [imgs[r["id"]][1] for r in rows],
                              zones["loc" if loc else "portrait"], (170, 470) if loc else (337, 250))
        art = (tiles[t][..., 3] > 127) & (tiles[t][..., :3].min(axis=2) == 255)
        print(f"{t:10s} {len(rows):3d} cards  art {int(art.sum()):>7d} px")

    sprite = np.concatenate([tiles[t] for t in TILES], axis=1)
    Image.fromarray(sprite, "RGBA").save(OUT, optimize=True)
    print(f"wrote {os.path.relpath(OUT)} ({os.path.getsize(OUT) // 1024} KB)")

    # Every base card should clear the client's PROXY_FRAME_MIN, and full-art
    # printings mostly shouldn't (the client swaps those for a base printing
    # before it ever asks).
    base_scores = sorted((frame_score(tiles[tile_of(r)], imgs[r["id"]][0]), r["id"])
                         for t in TILES for r in train[t] + [h for h in held if tile_of(h) == t])
    chase_scores = sorted((frame_score(tiles[tile_of(r)], imgs[r["id"]][0]), r["id"], r["rarity"]) for r in held_chase)
    print("standard-frame score, lowest base cards:", " ".join(f"{s:.2f}" for s, _ in base_scores[:8]),
          f"(of {len(base_scores)})")
    print("standard-frame score, full-art cards:   ", " ".join(f"{s:.2f}{r[0]}" for s, _, r in chase_scores))

    if args.contact:
        cells = [apply(tiles[tile_of(r)], imgs[r["id"]][0]) for r in held]
        tw, th = W // 2, H // 2
        cols_n = 6
        sheet = Image.new("RGB", (cols_n * (tw + 6), ((len(cells) + cols_n - 1) // cols_n) * (th + 6)), "#777")
        for i, c in enumerate(cells):
            sheet.paste(Image.fromarray(c).resize((tw, th), Image.LANCZOS), ((i % cols_n) * (tw + 6), (i // cols_n) * (th + 6)))
        sheet.save(args.contact)
        print(f"wrote {args.contact}")


if __name__ == "__main__":
    main()
