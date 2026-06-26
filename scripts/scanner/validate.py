"""
Scanner validation harness. Builds the descriptor index over every cached card,
then synthesises camera-like query images (perspective warp + lighting + blur +
JPEG + noise + rotation + imperfect crop) and measures top-1/3/5 recall against
the FULL index. Recall is scored by `art_key` so a foil/non-foil printing that
shares identical art counts as correct.

Usage:
  python scripts/scanner/validate.py [--n 500] [--hard] [--seed 0]
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"
sys.path.insert(0, str(HERE))
import descriptors as D  # noqa: E402

# popcount lookup over a byte
_POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def load_index() -> tuple[list[dict], dict]:
    cards = json.loads((DATA / "cards.json").read_text(encoding="utf-8"))
    cards = [c for c in cards if (IMGDIR / f"{c['id']}.avif").exists()]
    dhash = np.zeros(len(cards), dtype=np.uint64)
    phash = np.zeros(len(cards), dtype=np.uint64)
    color = np.zeros((len(cards), D.COLOR_GRID * D.COLOR_GRID * 3), dtype=np.float32)
    gray = np.zeros((len(cards), D.GRAY_GRID * D.GRAY_GRID), dtype=np.float32)
    t0 = time.time()
    for i, c in enumerate(cards):
        im = Image.open(IMGDIR / f"{c['id']}.avif").convert("RGB")
        d = D.describe(im)
        dhash[i] = d["dhash"]
        phash[i] = d["phash"]
        color[i] = d["color"]
        gray[i] = d["gray"]
        if (i + 1) % 500 == 0:
            print(f"  indexed {i+1}/{len(cards)} ({time.time()-t0:.0f}s)")
    idx = {"dhash": dhash, "phash": phash, "color": color, "gray": gray}
    return cards, idx


def ham_vec(ref: np.ndarray, q: int) -> np.ndarray:
    xor = (ref ^ np.uint64(q)).view(np.uint8).reshape(-1, 8)
    return _POP[xor].sum(1).astype(np.float32)


def score_all(idx: dict, q: dict, w: tuple) -> np.ndarray:
    wd, wp, wc, wg = w
    s = np.zeros(len(idx["dhash"]), dtype=np.float32)
    if wd:
        s += wd * ham_vec(idx["dhash"], q["dhash"]) / 64.0
    if wp:
        s += wp * ham_vec(idx["phash"], q["phash"]) / 64.0
    if wc:
        s += wc * (1.0 - idx["color"] @ q["color"])
    if wg:
        s += wg * (1.0 - idx["gray"] @ q["gray"])
    return s


def warp(im: Image.Image, rng: np.random.Generator, hard: bool) -> Image.Image:
    w, h = im.size
    # perspective: jitter the 4 source corners
    j = (0.12 if hard else 0.06)
    def jit(v, m):
        return v + rng.uniform(-j, j) * m
    quad = (
        jit(0, w), jit(0, h),          # upper-left
        jit(0, w), jit(h, h),          # lower-left
        jit(w, w), jit(h, h),          # lower-right
        jit(w, w), jit(0, h),          # upper-right
    )
    im = im.transform((w, h), Image.QUAD, quad, Image.BILINEAR)
    # rotation
    im = im.rotate(rng.uniform(-6 if hard else -3, 6 if hard else 3),
                   resample=Image.BILINEAR, fillcolor=(20, 20, 20))
    # brightness / contrast
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.6 if hard else 0.8, 1.35))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.7, 1.3))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.8, 1.25))
    # blur
    im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0, 1.6 if hard else 0.9)))
    # imperfect crop: scale + translate so the card doesn't fill the frame exactly
    sc = rng.uniform(0.88, 1.0)
    nw, nh = int(w * sc), int(h * sc)
    ox = rng.integers(0, max(1, w - nw + 1))
    oy = rng.integers(0, max(1, h - nh + 1))
    im = im.crop((ox, oy, ox + nw, oy + nh)).resize((w, h), Image.BILINEAR)
    # gaussian noise
    a = np.asarray(im, dtype=np.float32)
    a += rng.normal(0, (10 if hard else 5), a.shape)
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    # jpeg round-trip
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=int(rng.integers(40 if hard else 60, 85)))
    return Image.open(buf).convert("RGB")


WEIGHT_SETS = {
    "dhash":      (1, 0, 0, 0),
    "phash":      (0, 1, 0, 0),
    "color":      (0, 0, 1, 0),
    "gray":       (0, 0, 0, 1),
    "d+p":        (1, 1, 0, 0),
    "hashes+gray":(1, 1, 0, 1.5),
    "all":        (1, 1, 1.5, 1.5),
    "all-colorhi":(1, 1, 2.5, 1.0),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--hard", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    print("building index ...")
    cards, idx = load_index()
    art = np.array([c["art_key"] for c in cards])
    print(f"index: {len(cards)} cards, {len(set(art))} distinct arts")

    rng = np.random.default_rng(args.seed)
    qsel = rng.choice(len(cards), size=min(args.n, len(cards)), replace=False)

    # precompute query descriptors once
    queries = []
    for qi in qsel:
        im = Image.open(IMGDIR / f"{cards[qi]['id']}.avif").convert("RGB")
        q = D.describe(warp(im, rng, args.hard))
        queries.append((qi, q))

    print(f"\nscoring {len(queries)} {'HARD' if args.hard else 'easy'} queries vs full index:\n")
    print(f"{'weights':<14} {'top1':>6} {'top3':>6} {'top5':>6}")
    for name, w in WEIGHT_SETS.items():
        t1 = t3 = t5 = 0
        for qi, q in queries:
            s = score_all(idx, q, w)
            order = np.argsort(s)[:5]
            truth = art[qi]
            ranks = [j for j, oi in enumerate(order) if art[oi] == truth]
            if ranks:
                r = ranks[0]
                t5 += 1
                if r < 3:
                    t3 += 1
                if r < 1:
                    t1 += 1
        n = len(queries)
        print(f"{name:<14} {t1/n:>6.1%} {t3/n:>6.1%} {t5/n:>6.1%}")


if __name__ == "__main__":
    main()
