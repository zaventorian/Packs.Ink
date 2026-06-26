"""
Verify the shipped int8 index: load scanner/color.bin exactly as the JS client
will, run hard+WB synthetic queries, confirm recall matches the float version.
Also dumps a few example top-3 confusions for manual sanity.

  python scripts/scanner/verify_index.py [--n 500] [--seed 3]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"
REPO = HERE.parent.parent
OUT = REPO / "scanner"
sys.path.insert(0, str(HERE))
import descriptors as D  # noqa: E402
from tune_color import warp  # reuse the hard+WB distortion  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=3)
    args = ap.parse_args()

    man = json.loads((OUT / "index.json").read_text(encoding="utf-8"))
    n, dims = man["count"], man["dims"]
    color = np.frombuffer((OUT / "color.bin").read_bytes(), dtype=np.int8).reshape(n, dims).astype(np.float32)
    meta = man["cards"]
    art = np.array([c["art_key"] for c in meta])
    print(f"loaded shipped index: {n} cards x {dims} dims (int8)")

    # map id -> row for query lookup
    id_to_row = {c["id"]: i for i, c in enumerate(meta)}
    rng = np.random.default_rng(args.seed)
    qsel = rng.choice(n, size=min(args.n, n), replace=False)

    t1 = t3 = t5 = 0
    examples = []
    for qi in qsel:
        cid = meta[qi]["id"]
        im = Image.open(IMGDIR / f"{cid}.avif").convert("RGB")
        qv = D.color_sig(warp(im, rng)).astype(np.float32)   # float query
        s = -(color @ qv)                                    # higher dot = closer
        order = np.argsort(s)[:5]
        ranks = [j for j, oi in enumerate(order) if art[oi] == art[qi]]
        if ranks:
            t5 += 1
            if ranks[0] < 3: t3 += 1
            if ranks[0] < 1: t1 += 1
        elif len(examples) < 8:
            def lbl(o):
                m = meta[o]
                return f"{m['name']}" + (f" - {m['version']}" if m['version'] else "")
            examples.append(f"  MISS  truth={lbl(qi):<38} got top3: " +
                            " | ".join(lbl(o) for o in order[:3]))
    m = len(qsel)
    print(f"\nint8 index recall (hard+WB, n={m}):  top1={t1/m:.1%}  top3={t3/m:.1%}  top5={t5/m:.1%}")
    if examples:
        print("\nsample misses (truth not in top-5):")
        print("\n".join(examples))


if __name__ == "__main__":
    main()
