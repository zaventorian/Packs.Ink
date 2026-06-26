"""
Descriptor x crop bake-off against the REAL slab-photo benchmark (data/ebay/),
in Python (fast — all images local). Measures which (descriptor, query-crop)
combo best identifies a card from a real photograph. Reference descriptors are
always computed on the full Lorcast art; query descriptors on the cropped slab.

  python scripts/scanner/bakeoff.py [--n 700]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"
EBAY = DATA / "ebay"
REPO = HERE.parent.parent


def grid_rgb(im, g):
    a = np.asarray(im.convert("RGB").resize((g, g), Image.BILINEAR), dtype=np.float32).reshape(-1)
    a -= a.mean(); n = np.linalg.norm(a); return a / n if n > 1e-6 else a

def grid_gray(im, g):
    a = np.asarray(im.convert("L").resize((g, g), Image.BILINEAR), dtype=np.float32).reshape(-1)
    a -= a.mean(); n = np.linalg.norm(a); return a / n if n > 1e-6 else a

def grid_grad(im, g):
    a = np.asarray(im.convert("L").resize((g + 1, g + 1), Image.BILINEAR), dtype=np.float32)
    dx = (a[:-1, 1:] - a[:-1, :-1]).reshape(-1)
    dy = (a[1:, :-1] - a[:-1, :-1]).reshape(-1)
    v = np.concatenate([dx, dy]); v -= v.mean(); n = np.linalg.norm(v); return v / n if n > 1e-6 else v

def cat(*vs):
    v = np.concatenate(vs); v -= v.mean(); n = np.linalg.norm(v); return v / n if n > 1e-6 else v

DESCS = {
    "color12": lambda im: grid_rgb(im, 12),
    "color16": lambda im: grid_rgb(im, 16),
    "color24": lambda im: grid_rgb(im, 24),
    "gray16":  lambda im: grid_gray(im, 16),
    "grad16":  lambda im: grid_grad(im, 16),
    "c16grad16": lambda im: cat(grid_rgb(im, 16), grid_grad(im, 16)),
    "c12g16grad12": lambda im: cat(grid_rgb(im, 12), grid_gray(im, 16), grid_grad(im, 12)),
}

# query crops on the slab (fractional box) — reference always uses the full card
CROPS = {
    "whole":    (0.00, 0.00, 1.00, 1.00),
    "slabcard": (0.06, 0.26, 0.94, 0.96),   # skip grader label + plastic frame
    "slabtight":(0.10, 0.30, 0.90, 0.93),
    "center":   (0.20, 0.20, 0.80, 0.80),
}


def crop(im, box):
    W, H = im.size
    l, t, r, b = box
    return im.crop((int(W * l), int(H * t), int(W * r), int(H * b)))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=700); args = ap.parse_args()
    idx = json.loads((REPO / "scanner" / "index.json").read_text(encoding="utf-8"))
    meta = idx["cards"]
    art = np.array([c["art_key"] for c in meta])

    names = list(DESCS)
    print(f"building ref descriptors for {len(meta)} cards ...")
    t0 = time.time()
    refs = {n: [] for n in names}
    for i, c in enumerate(meta):
        p = IMGDIR / f"{c['id']}.avif"
        if not p.exists():
            for n in names: refs[n].append(None)
            continue
        im = Image.open(p).convert("RGB")
        for n in names: refs[n].append(DESCS[n](im))
        if (i + 1) % 800 == 0: print(f"  {i+1}/{len(meta)} ({time.time()-t0:.0f}s)")
    refmat = {}
    for n in names:
        dim = next(v for v in refs[n] if v is not None).shape[0]
        M = np.zeros((len(meta), dim), dtype=np.float32)
        for i, v in enumerate(refs[n]):
            if v is not None: M[i] = v
        refmat[n] = M
    print(f"refs built ({time.time()-t0:.0f}s)")

    ts = json.loads((DATA / "test_set.json").read_text(encoding="utf-8"))[: args.n]
    ts = [r for r in ts if (EBAY / r["file"]).exists()]
    print(f"loading {len(ts)} slab photos + computing query descriptors ...")
    # precompute query descriptors: {(desc,crop): [vecs]}, and truth art_keys
    qvecs = {(dn, cn): [] for dn in names for cn in CROPS}
    truth = []
    for j, r in enumerate(ts):
        im = Image.open(EBAY / r["file"]).convert("RGB")
        truth.append(r["art_key"])
        for cn, box in CROPS.items():
            cim = crop(im, box)
            for dn in names:
                qvecs[(dn, cn)].append(DESCS[dn](cim))
        if (j + 1) % 150 == 0: print(f"  {j+1}/{len(ts)}")
    truth = np.array(truth)

    print(f"\n{'descriptor x crop':<26} {'top1':>7} {'top3':>7} {'top5':>7}")
    rows = []
    for dn in names:
        M = refmat[dn]
        for cn in CROPS:
            Q = np.stack(qvecs[(dn, cn)]).astype(np.float32)   # (nq, dim)
            S = Q @ M.T                                         # (nq, ncards) cosine
            order = np.argsort(-S, axis=1)[:, :5]
            t1 = t3 = t5 = 0
            for j in range(len(truth)):
                ranks = [k for k, oi in enumerate(order[j]) if art[oi] == truth[j]]
                if ranks:
                    t5 += 1
                    if ranks[0] < 3: t3 += 1
                    if ranks[0] < 1: t1 += 1
            nq = len(truth)
            rows.append((f"{dn} x {cn}", t1/nq, t3/nq, t5/nq))
    rows.sort(key=lambda r: -r[2])
    for name, a, b, c in rows:
        print(f"{name:<26} {a:>6.1%} {b:>6.1%} {c:>6.1%}")


if __name__ == "__main__":
    main()
