"""
A/B the colour descriptor: current GLOBAL 12x12 vs ART-REGION-focused variants.
Measures top-1/top-3 on (a) the synthetic raw-card set (full ground truth) and
(b) the real phone photos (rectified with the two-pass detector). Ship a variant
ONLY if it beats the global on BOTH.

  python scripts/scanner/descriptor_ab.py [--n 250]
"""
from __future__ import annotations
import argparse, glob, json, sys, time
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE/"data"; IMG = DATA/"img"; REAL = DATA/"real"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D
from synth_raw_eval import synth_photo
from real_eval2 import detect, rectify  # two-pass detect


def _grid(img, box, g, gray=False):
    w, h = img.size
    x0, y0, x1, y1 = int(box[0]*w), int(box[1]*h), int(box[2]*w), int(box[3]*h)
    c = img.crop((x0, y0, x1, y1))
    c = c.convert("L" if gray else "RGB").resize((g, g), Image.BILINEAR)
    a = np.asarray(c, np.float32).reshape(-1)
    a -= a.mean(); n = np.linalg.norm(a)
    return a/n if n > 1e-6 else a


ART = (0.06, 0.07, 0.94, 0.57)      # character art window (portrait)
BANNER = (0.06, 0.56, 0.94, 0.66)   # name banner


def sig_global(img):   # v1 — current shipped
    return D.color_sig(img)

def sig_art12(img):    # art region only, 12x12 RGB
    return _grid(img, ART, 12)

def sig_art16(img):    # art region only, 16x16 RGB (finer)
    return _grid(img, ART, 16)

def sig_multi(img):    # art(10 rgb) + banner(4 rgb) + bottom(6 gray), weighted
    art = _grid(img, ART, 10)*1.0
    ban = _grid(img, BANNER, 4)*0.6
    fr = _grid(img, (0.0, 0.66, 1.0, 1.0), 6, gray=True)*0.4
    v = np.concatenate([art, ban, fr]); n = np.linalg.norm(v)
    return v/n if n > 1e-6 else v

VARIANTS = {"global12": sig_global, "art12": sig_art12, "art16": sig_art16, "multi": sig_multi}


def build_refs(meta):
    refs = {k: [] for k in VARIANTS}
    keep = []
    for i, c in enumerate(meta):
        p = IMG/f"{c['id']}.avif"
        if not p.exists(): continue
        im = Image.open(p).convert("RGB"); keep.append(i)
        for k, fn in VARIANTS.items(): refs[k].append(fn(im))
    for k in refs: refs[k] = np.array(refs[k], np.float32)
    return refs, np.array(keep)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=250); ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args()
    idx = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8")); meta = idx["cards"]
    art_key = np.array([c["art_key"] for c in meta])
    name = lambda i: meta[i]["name"] + (" - "+meta[i]["version"] if meta[i].get("version") else "")
    print("building refs (4 variants)...")
    refs, keep = build_refs(meta)
    art_keep = art_key[keep]

    # ---- synthetic (full ground truth) ----
    rng = np.random.default_rng(a.seed)
    sel = rng.choice(keep, size=a.n, replace=False)
    res = {k: [0, 0] for k in VARIANTS}  # [t1, t3]
    t0 = time.time()
    for k_i, ci in enumerate(sel):
        card = np.asarray(Image.open(IMG/f"{meta[ci]['id']}.avif").convert("RGB"))
        photo = synth_photo(card, rng)
        quad, _, _ = detect(photo, True)
        if quad is not None:
            rim = Image.fromarray(rectify(photo, quad))
        else:
            H, W = photo.shape[:2]; rim = Image.fromarray(photo[int(H*0.18):int(H*0.82), int(W*0.18):int(W*0.82)])
        for k, fn in VARIANTS.items():
            s = refs[k] @ fn(rim); order = np.argsort(-s)[:3]
            if art_keep[order[0]] == art_key[ci]: res[k][0] += 1
            if any(art_keep[o] == art_key[ci] for o in order): res[k][1] += 1
        if (k_i+1) % 50 == 0: print(f"  synth {k_i+1}/{a.n} ({time.time()-t0:.0f}s)")
    print(f"\n=== SYNTHETIC (n={a.n}) ===")
    for k in VARIANTS:
        print(f"  {k:9s} top1={100*res[k][0]/a.n:5.1f}%  top3={100*res[k][1]/a.n:5.1f}%")

    # ---- real photos (top-1 guess per variant; eyeball vs known labels) ----
    print("\n=== REAL PHOTOS (two-pass detect; top-1 per variant) ===")
    files = sorted(f for f in glob.glob(str(REAL/"*.jpg")) if "_contact" not in f)
    for f in files:
        nm = Path(f).stem[:8]
        rgb = np.asarray(Image.open(f).convert("RGB"))
        quad, _, _ = detect(rgb, True)
        if quad is None: print(f"  {nm}  NODET"); continue
        rim = Image.fromarray(rectify(rgb, quad))
        guesses = []
        for k, fn in VARIANTS.items():
            s = refs[k] @ fn(rim); guesses.append(f"{k}:{name(keep[np.argmax(s)])[:22]}")
        print(f"  {nm}  " + " | ".join(guesses))


if __name__ == "__main__":
    main()
