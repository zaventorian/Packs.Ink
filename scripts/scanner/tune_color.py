"""
Tune the color-signature descriptor: grid resolution, normalisation strategy,
and multi-scale concat. Adds a white-balance shift to the hard distortion so we
don't over-credit a descriptor that isn't colour-temperature robust.

  python scripts/scanner/tune_color.py [--n 500] [--seed 2]
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


def color_variant(im: Image.Image, grid, norm: str) -> np.ndarray:
    """grid: int or list[int] (multiscale). norm: 'global'|'chan'|'chanz'."""
    grids = grid if isinstance(grid, (list, tuple)) else [grid]
    parts = []
    for g in grids:
        a = np.asarray(im.convert("RGB").resize((g, g), Image.BILINEAR),
                       dtype=np.float32).reshape(-1, 3)  # (g*g, 3)
        if norm == "global":
            a = a - a.mean()
        elif norm == "chan":
            a = a - a.mean(0, keepdims=True)
        elif norm == "chanz":
            a = a - a.mean(0, keepdims=True)
            a = a / (a.std(0, keepdims=True) + 1e-3)
        parts.append(a.reshape(-1))
    v = np.concatenate(parts)
    v = v - v.mean()
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else v


def warp(im, rng, white_balance=True):
    w, h = im.size
    j = 0.12
    def jit(v, m): return v + rng.uniform(-j, j) * m
    quad = (jit(0, w), jit(0, h), jit(0, w), jit(h, h),
            jit(w, w), jit(h, h), jit(w, w), jit(0, h))
    im = im.transform((w, h), Image.QUAD, quad, Image.BILINEAR)
    im = im.rotate(rng.uniform(-6, 6), resample=Image.BILINEAR, fillcolor=(20, 20, 20))
    im = ImageEnhance.Brightness(im).enhance(rng.uniform(0.6, 1.35))
    im = ImageEnhance.Contrast(im).enhance(rng.uniform(0.7, 1.3))
    im = ImageEnhance.Color(im).enhance(rng.uniform(0.8, 1.25))
    if white_balance:
        a = np.asarray(im, dtype=np.float32)
        gains = rng.uniform(0.82, 1.18, 3)            # per-channel WB shift
        a = np.clip(a * gains, 0, 255)
        im = Image.fromarray(a.astype(np.uint8))
    im = im.filter(ImageFilter.GaussianBlur(rng.uniform(0, 1.6)))
    sc = rng.uniform(0.86, 1.0)
    nw, nh = int(w * sc), int(h * sc)
    ox = int(rng.integers(0, max(1, w - nw + 1)))
    oy = int(rng.integers(0, max(1, h - nh + 1)))
    im = im.crop((ox, oy, ox + nw, oy + nh)).resize((w, h), Image.BILINEAR)
    a = np.asarray(im, dtype=np.float32) + rng.normal(0, 9, (h, w, 3))
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=int(rng.integers(40, 85)))
    return Image.open(buf).convert("RGB")


VARIANTS = {
    "g12 global":   (12, "global"),
    "g16 global":   (16, "global"),
    "g20 global":   (20, "global"),
    "g16 chan":     (16, "chan"),
    "g16 chanz":    (16, "chanz"),
    "g20 chan":     (20, "chan"),
    "ms[8,16] chan": ([8, 16], "chan"),
    "ms[8,20] chan": ([8, 20], "chan"),
    "ms[10,24] chan":([10, 24], "chan"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=2)
    args = ap.parse_args()

    cards = json.loads((DATA / "cards.json").read_text(encoding="utf-8"))
    cards = [c for c in cards if (IMGDIR / f"{c['id']}.avif").exists()]
    art = np.array([c["art_key"] for c in cards])
    imgs = [None] * len(cards)
    print(f"loading {len(cards)} images ...")
    for i, c in enumerate(cards):
        imgs[i] = Image.open(IMGDIR / f"{c['id']}.avif").convert("RGB")

    rng = np.random.default_rng(args.seed)
    qsel = rng.choice(len(cards), size=min(args.n, len(cards)), replace=False)
    queries = [(qi, warp(imgs[qi], rng)) for qi in qsel]

    print(f"\n{len(queries)} hard+WB queries vs full index\n")
    print(f"{'variant':<16} {'dims':>6} {'top1':>6} {'top3':>6} {'top5':>6} {'idx_s':>6}")
    for name, (grid, norm) in VARIANTS.items():
        t0 = time.time()
        ref = np.stack([color_variant(im, grid, norm) for im in imgs]).astype(np.float32)
        dims = ref.shape[1]
        idx_s = time.time() - t0
        t1 = t3 = t5 = 0
        for qi, qim in queries:
            qv = color_variant(qim, grid, norm)
            s = 1.0 - ref @ qv
            order = np.argsort(s)[:5]
            ranks = [j for j, oi in enumerate(order) if art[oi] == art[qi]]
            if ranks:
                t5 += 1
                if ranks[0] < 3: t3 += 1
                if ranks[0] < 1: t1 += 1
        n = len(queries)
        print(f"{name:<16} {dims:>6} {t1/n:>6.1%} {t3/n:>6.1%} {t5/n:>6.1%} {idx_s:>5.0f}s")


if __name__ == "__main__":
    main()
