"""
Product-scenario validation: synthesize RAW-card phone photos (no slab) —
perspective-warp a card, light/blur/glare it, composite on a background — then
run the SHIPPED pipeline (detect_quad -> rectify -> color match). This is the
honest proxy for "person points phone at a raw card on a table": single card,
contrasting background, no grader label/plastic. Saves a few composites to look at.

  python scripts/scanner/synth_raw_eval.py [--n 300] [--save 10]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).resolve().parent
DATA = HERE/"data"; IMG = DATA/"img"; OUT = DATA/"synth_out"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D
from detect_eval import detect_quad, rectify

def make_background(W, H, rng):
    kind = rng.integers(0, 3)
    if kind == 0:  # solid muted
        c = rng.integers(40, 200, 3); bg = np.ones((H, W, 3), np.uint8) * c.astype(np.uint8)
    elif kind == 1:  # gradient
        a = rng.integers(20, 230, 3).astype(float); b = rng.integers(20, 230, 3).astype(float)
        t = np.linspace(0, 1, H)[:, None, None]; bg = (a*(1-t) + b*t).astype(np.uint8) * np.ones((1, W, 1), np.uint8)
    else:  # noisy wood-ish
        base = rng.integers(60, 160, 3); bg = (np.ones((H, W, 3))*base).astype(np.uint8)
        bg = np.clip(bg + rng.normal(0, 18, (H, W, 3)), 0, 255).astype(np.uint8)
    return bg

def synth_photo(card_rgb, rng):
    ch, cw = card_rgb.shape[:2]
    W, H = 900, 1300
    fill = rng.uniform(0.55, 0.82)
    dst_h = int(H*fill); dst_w = int(dst_h * cw/ch)
    # destination quad with perspective jitter + rotation, centred
    cx, cy = W/2, H/2
    base = np.array([[-dst_w/2,-dst_h/2],[dst_w/2,-dst_h/2],[dst_w/2,dst_h/2],[-dst_w/2,dst_h/2]], np.float32)
    ang = np.radians(rng.uniform(-10, 10)); R = np.array([[np.cos(ang),-np.sin(ang)],[np.sin(ang),np.cos(ang)]])
    j = 0.10
    jit = rng.uniform(-j, j, (4, 2)) * np.array([dst_w, dst_h])
    dstq = (base @ R.T) + jit + np.array([cx, cy])
    srcq = np.array([[0,0],[cw,0],[cw,ch],[0,ch]], np.float32)
    M = cv2.getPerspectiveTransform(srcq, dstq.astype(np.float32))
    warped = cv2.warpPerspective(card_rgb, M, (W, H), borderValue=(0,0,0))
    mask = cv2.warpPerspective(np.ones((ch, cw), np.uint8)*255, M, (W, H))
    bg = make_background(W, H, rng)
    out = bg.copy(); out[mask > 127] = warped[mask > 127]
    pim = Image.fromarray(out)
    pim = ImageEnhance.Brightness(pim).enhance(rng.uniform(0.7, 1.2))
    pim = ImageEnhance.Color(pim).enhance(rng.uniform(0.85, 1.15))
    pim = pim.filter(ImageFilter.GaussianBlur(rng.uniform(0, 1.2)))
    a = np.asarray(pim, np.float32) + rng.normal(0, 5, (H, W, 3))
    return np.clip(a, 0, 255).astype(np.uint8)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=300); ap.add_argument("--save", type=int, default=10); ap.add_argument("--seed", type=int, default=11)
    a = ap.parse_args(); OUT.mkdir(exist_ok=True)
    idx = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8")); meta = idx["cards"]; art = np.array([c["art_key"] for c in meta])
    print("refs..."); ref = np.zeros((len(meta), 432), np.float32)
    for i, c in enumerate(meta):
        p = IMG/f"{c['id']}.avif"
        if p.exists(): ref[i] = D.color_sig(Image.open(p).convert("RGB"))
    rng = np.random.default_rng(a.seed)
    sel = rng.choice([i for i, c in enumerate(meta) if (IMG/f"{c['id']}.avif").exists()], size=a.n, replace=False)
    detHit = dT1 = dT3 = 0; n = 0
    t0 = time.time()
    for k, ci in enumerate(sel):
        card = np.asarray(Image.open(IMG/f"{meta[ci]['id']}.avif").convert("RGB"))
        photo = synth_photo(card, rng); n += 1
        quad = detect_quad(photo)
        if quad is not None:
            detHit += 1; qv = D.color_sig(Image.fromarray(rectify(photo, quad)))
        else:
            H, W = photo.shape[:2]; qv = D.color_sig(Image.fromarray(photo[int(H*0.18):int(H*0.82), int(W*0.18):int(W*0.82)]))
        s = ref @ qv; order = np.argsort(-s)[:3]
        if art[order[0]] == art[ci]: dT1 += 1
        if any(art[o] == art[ci] for o in order): dT3 += 1
        if k < a.save:
            vis = photo.copy()
            if quad is not None: cv2.polylines(vis, [quad.astype(np.int32)], True, (0,255,0), 5)
            Image.fromarray(vis).resize((220, 318)).save(OUT/f"{k:02d}_{'OK' if art[order[0]]==art[ci] else 'XX'}.png")
        if (k+1) % 50 == 0: print(f"{k+1}/{a.n} detHit={100*detHit/(k+1):.0f}% t1={100*dT1/(k+1):.0f} t3={100*dT3/(k+1):.0f}  ({time.time()-t0:.0f}s)")
    print(f"\n=== SYNTHETIC RAW-CARD pipeline (n={n}) ===")
    print(f"detection rate: {100*detHit/n:.1f}%")
    print(f"end-to-end:     top1={100*dT1/n:.1f}%  top3={100*dT3/n:.1f}%")

if __name__ == "__main__":
    main()
