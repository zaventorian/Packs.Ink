"""
Validate card DETECTION + RECTIFICATION + match on the real slab benchmark.
Mirrors scanner-cv.js. Saves annotated originals + rectified crops to
data/detect_out/ so the detection quality can be eyeballed, and reports
top-1/3 with detection vs the fixed-crop baseline.

  python scripts/scanner/detect_eval.py [--n 300] [--save 16]
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import numpy as np
import cv2
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; IMG = DATA / "img"; EBAY = DATA / "ebay"; OUT = DATA / "detect_out"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D

def pil_rgb(p): return np.asarray(Image.open(p).convert("RGB"))

def order_quad(pts):
    s = pts.sum(1); d = (pts[:,1] - pts[:,0])
    tl = pts[np.argmin(s)]; br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]; bl = pts[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)

def detect_quad(rgb, min_area_frac=0.10):
    h, w = rgb.shape[:2]
    procW = 480; scale = procW / w; procH = int(h * scale)
    small = cv2.resize(rgb, (procW, procH))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 60, 180)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8))
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    best = None; best_score = 0; img_area = procW * procH
    for c in cnts:
        area = cv2.contourArea(c)
        if area < img_area * min_area_frac: continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            q = order_quad(approx.reshape(4, 2).astype(np.float32))
            wT = np.linalg.norm(q[0]-q[1]); wB = np.linalg.norm(q[3]-q[2])
            hL = np.linalg.norm(q[0]-q[3]); hR = np.linalg.norm(q[1]-q[2])
            ww = (wT+wB)/2; hh = (hL+hR)/2
            ar = min(ww,hh)/max(ww,hh)
            ar_score = 1 - min(1, abs(ar - 5/7)/0.22)
            score = ar_score*0.6 + min(1, area/img_area)*0.4
            if ar_score > 0 and score > best_score:
                best_score = score; best = q/scale
    return best

def rectify(rgb, quad):
    wT = np.linalg.norm(quad[0]-quad[1]); wB = np.linalg.norm(quad[3]-quad[2])
    hL = np.linalg.norm(quad[0]-quad[3]); hR = np.linalg.norm(quad[1]-quad[2])
    ww = (wT+wB)/2; hh = (hL+hR)/2
    if ww > hh: outW, outH = 560, 400
    else:       outW, outH = 400, 560
    dst = np.array([[0,0],[outW,0],[outW,outH],[0,outH]], dtype=np.float32)
    M = cv2.getPerspectiveTransform(quad.astype(np.float32), dst)
    warp = cv2.warpPerspective(rgb, M, (outW, outH))
    return warp

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--n", type=int, default=300); ap.add_argument("--save", type=int, default=16)
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    idx = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8"))
    meta = idx["cards"]; art = np.array([c["art_key"] for c in meta])

    print("building color refs ...")
    t0=time.time(); ref = np.zeros((len(meta), 432), dtype=np.float32)
    for i,c in enumerate(meta):
        p = IMG/f"{c['id']}.avif"
        if p.exists(): ref[i] = D.color_sig(Image.open(p).convert("RGB"))
    print(f"refs {time.time()-t0:.0f}s")

    ts = json.loads((DATA/"test_set.json").read_text(encoding="utf-8"))[:args.n]
    ts = [r for r in ts if (EBAY/r["file"]).exists()]
    detHit=0; dT1=dT3=0; bT1=bT3=0; n=0
    for j,r in enumerate(ts):
        rgb = pil_rgb(EBAY/r["file"]); n+=1; a=r["art_key"]
        quad = detect_quad(rgb)
        if quad is not None:
            detHit+=1; warp = rectify(rgb, quad)
            qv = D.color_sig(Image.fromarray(warp))
        else:
            H,W = rgb.shape[:2]
            cr = rgb[int(H*0.30):int(H*0.93), int(W*0.10):int(W*0.90)]
            qv = D.color_sig(Image.fromarray(cr))
        s = ref @ qv; order = np.argsort(-s)[:3]
        if art[order[0]]==a: dT1+=1
        if any(art[o]==a for o in order): dT3+=1
        # baseline fixed crop
        H,W = rgb.shape[:2]; cr = rgb[int(H*0.30):int(H*0.93), int(W*0.10):int(W*0.90)]
        bv = D.color_sig(Image.fromarray(cr)); bs = ref @ bv; bo = np.argsort(-bs)[:3]
        if art[bo[0]]==a: bT1+=1
        if any(art[o]==a for o in bo): bT3+=1
        # save a few for inspection
        if j < args.save:
            vis = rgb.copy()
            if quad is not None:
                cv2.polylines(vis, [quad.astype(np.int32)], True, (0,255,0), 6)
                Image.fromarray(rectify(rgb, quad)).save(OUT/f"{j:02d}_rect_{'OK' if art[order[0]]==a else 'XX'}.png")
            Image.fromarray(vis).resize((240, int(240*vis.shape[0]/vis.shape[1]))).save(OUT/f"{j:02d}_orig.png")
        if (j+1)%50==0:
            print(f"{j+1}/{len(ts)} detHit={100*detHit/(j+1):.0f}% det:t1={100*dT1/(j+1):.0f} t3={100*dT3/(j+1):.0f} | base:t1={100*bT1/(j+1):.0f} t3={100*bT3/(j+1):.0f}")
    print(f"\n=== DETECT+RECTIFY vs FIXED-CROP (n={n}) ===")
    print(f"detection found a quad: {100*detHit/n:.1f}%")
    print(f"detect+rectify: top1={100*dT1/n:.1f}%  top3={100*dT3/n:.1f}%")
    print(f"fixed-crop    : top1={100*bT1/n:.1f}%  top3={100*bT3/n:.1f}%")
    print(f"saved {args.save} examples to {OUT}")

if __name__ == "__main__":
    main()
