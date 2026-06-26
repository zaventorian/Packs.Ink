"""
Hard-conditions eval mimicking the user's actual failure: a raw card held by
hand in a DIM room with DIRECTIONAL light (lamp on one side, shadow on the
other), tilted, slightly blurred. Compares three pipelines so we know exactly
how much each lever buys under those conditions:
  1. guide-crop  (the CURRENT shipped approach — no detection)
  2. detect+rectify
  3. detect+rectify + CLAHE lighting normalisation
Saves a few composites to data/hard_out/ to eyeball realism.

  python scripts/scanner/hard_eval.py [--n 300]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent
DATA = HERE/"data"; IMG = DATA/"img"; OUT = DATA/"hard_out"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D
from detect_eval import detect_quad, rectify

def directional_light(img, rng):
    """Multiply by a lamp gradient: one bright side, the rest dim. Mimics the
    user's lamp + dark-room photo."""
    H, W = img.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    cx = rng.uniform(0, W); cy = rng.uniform(0, H)             # lamp position
    d = np.sqrt((xx-cx)**2 + (yy-cy)**2); d /= d.max()
    overall = rng.uniform(0.35, 0.7)                           # dim room
    light = overall + (1.0 - overall) * (1 - d) ** rng.uniform(1.5, 3.0)
    out = img.astype(np.float32) * light[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)

def synth_hard(card_rgb, rng):
    ch, cw = card_rgb.shape[:2]
    W, H = 1000, 1400
    fill = rng.uniform(0.55, 0.85)
    dst_h = int(H*fill); dst_w = int(dst_h*cw/ch)
    cx, cy = W/2 + rng.uniform(-0.08,0.08)*W, H/2 + rng.uniform(-0.06,0.06)*H
    base = np.array([[-dst_w/2,-dst_h/2],[dst_w/2,-dst_h/2],[dst_w/2,dst_h/2],[-dst_w/2,dst_h/2]], np.float32)
    ang = np.radians(rng.uniform(-16, 16)); R = np.array([[np.cos(ang),-np.sin(ang)],[np.sin(ang),np.cos(ang)]])
    j = 0.15
    jit = rng.uniform(-j, j, (4,2)) * np.array([dst_w, dst_h])
    dstq = (base @ R.T) + jit + np.array([cx, cy])
    M = cv2.getPerspectiveTransform(np.array([[0,0],[cw,0],[cw,ch],[0,ch]], np.float32), dstq.astype(np.float32))
    warped = cv2.warpPerspective(card_rgb, M, (W, H), borderValue=(0,0,0))
    mask = cv2.warpPerspective(np.ones((ch,cw),np.uint8)*255, M, (W,H))
    # dim textured background (a wall/blanket)
    bg = (np.ones((H,W,3))*rng.integers(30,90,3)).astype(np.uint8)
    bg = np.clip(bg + rng.normal(0,12,(H,W,3)),0,255).astype(np.uint8)
    out = bg.copy(); out[mask>127] = warped[mask>127]
    out = directional_light(out, rng)
    pim = Image.fromarray(out).filter(ImageFilter.GaussianBlur(rng.uniform(0.4, 1.8)))
    a = np.asarray(pim, np.float32) + rng.normal(0, 7, (H,W,3))
    return np.clip(a,0,255).astype(np.uint8)

def clahe(rgb):
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
    l,a,b = cv2.split(lab)
    l = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8,8)).apply(l)
    return cv2.cvtColor(cv2.merge([l,a,b]), cv2.COLOR_LAB2RGB)

def sig(rgb): return D.color_sig(Image.fromarray(rgb))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=300); ap.add_argument("--save", type=int, default=8); ap.add_argument("--seed", type=int, default=21)
    a = ap.parse_args(); OUT.mkdir(exist_ok=True)
    idx = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8")); meta = idx["cards"]; art = np.array([c["art_key"] for c in meta])
    print("refs (color sig + CLAHE'd refs)...")
    ref = np.zeros((len(meta),432),np.float32); refC = np.zeros((len(meta),432),np.float32)
    for i,c in enumerate(meta):
        p = IMG/f"{c['id']}.avif"
        if p.exists():
            rgb = np.asarray(Image.open(p).convert("RGB")); ref[i]=sig(rgb); refC[i]=sig(clahe(rgb))
    rng = np.random.default_rng(a.seed)
    sel = rng.choice([i for i,c in enumerate(meta) if (IMG/f"{c['id']}.avif").exists()], size=a.n, replace=False)
    res = {"guidecrop":[0,0], "rectify":[0,0], "rectify+clahe":[0,0]}; n=0
    detHit=0; t0=time.time()
    for k,ci in enumerate(sel):
        card = np.asarray(Image.open(IMG/f"{meta[ci]['id']}.avif").convert("RGB"))
        photo = synth_hard(card, rng); n+=1; H,W = photo.shape[:2]; truth=art[ci]
        # 1. guide crop (current approach): centre 82% 5:7
        gh=int(H*0.82); gw=int(gh*5/7); gx=(W-gw)//2; gy=(H-gh)//2
        gc = photo[gy:gy+gh, gx:gx+gw]
        def score(qsig, refmat):
            s = refmat @ qsig; o = np.argsort(-s)[:3]; return art[o[0]]==truth, any(art[x]==truth for x in o)
        t1,t3 = score(sig(gc), ref);            res["guidecrop"][0]+=t1; res["guidecrop"][1]+=t3
        # 2 + 3. detect + rectify
        quad = detect_quad(photo)
        if quad is not None:
            detHit+=1; rect = rectify(photo, quad)
            t1,t3 = score(sig(rect), ref);       res["rectify"][0]+=t1; res["rectify"][1]+=t3
            rc = clahe(rect)
            t1,t3 = score(sig(rc), refC);         res["rectify+clahe"][0]+=t1; res["rectify+clahe"][1]+=t3
            if k < a.save:
                Image.fromarray(rc).save(OUT/f"{k:02d}_rectclahe.png")
        else:
            # rectify falls back to guide crop when no quad
            t1,t3 = score(sig(gc), ref);          res["rectify"][0]+=t1; res["rectify"][1]+=t3
            t1,t3 = score(sig(clahe(gc)), refC);  res["rectify+clahe"][0]+=t1; res["rectify+clahe"][1]+=t3
        if k < a.save:
            Image.fromarray(photo).resize((220,308)).save(OUT/f"{k:02d}_photo.png")
        if (k+1)%50==0: print(f"{k+1}/{a.n} detHit={100*detHit/(k+1):.0f}% ({time.time()-t0:.0f}s)")
    print(f"\n=== HARD conditions (dim+directional light, tilt) n={n}, detection rate {100*detHit/n:.0f}% ===")
    for name,(t1,t3) in res.items():
        print(f"{name:<16} top1={100*t1/n:5.1f}%  top3={100*t3/n:5.1f}%")

if __name__ == "__main__":
    main()
