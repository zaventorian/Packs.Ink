"""
Experiment: measure detection rate + speed + top-3 colour match on the real phone
photos, comparing the CURRENT detector vs a SAFE two-pass detector (pass 2 only
runs when pass 1 finds no quad — so it can't regress a card that already works).

  python scripts/scanner/real_eval2.py
"""
from __future__ import annotations
import glob, json, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE/"data"; IMG = DATA/"img"; REAL = DATA/"real"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))
import descriptors as D


def order_quad(pts):
    s = pts.sum(1); d = pts[:, 1] - pts[:, 0]
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def _pt_in_quad(p, q, tol=4.0):
    """point inside a convex quad (sign-consistent cross test, tol px slack)."""
    sign = 0
    for i in range(4):
        a = q[i]; b = q[(i+1) % 4]
        ex, ey = b[0]-a[0], b[1]-a[1]
        ln = (ex*ex+ey*ey) ** 0.5 or 1.0
        d = (ex*(p[1]-a[1]) - ey*(p[0]-a[0])) / ln
        if d > tol:
            if sign < 0: return False
            sign = 1
        elif d < -tol:
            if sign > 0: return False
            sign = -1
    return True


def _scan(edges, sc, procW, procH, gates, containment=True):
    """find best quad on an edge map; gates = (rect_min, fill_min, ar_tol, area_min).
    containment=True adds the ART-BOX-TRAP fix: a card's inner art frame (~4:3
    landscape ~= an inverted 5:7) passes every gate and can outscore the true card
    boundary (centre bias) -> landscape-squashed rectifies of portrait cards. If a
    bigger gate-passing quad fully CONTAINS the winner, take the outer one."""
    rect_min, fill_min, ar_tol, area_min = gates
    cnts, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    cands = []; area_img = procW * procH
    cx, cy = procW / 2, procH / 2; halfd = (cx**2 + cy**2) ** 0.5

    def consider(q, ca, clean):
        w1 = np.linalg.norm(q[0]-q[1]); w2 = np.linalg.norm(q[3]-q[2])
        h1 = np.linalg.norm(q[0]-q[3]); h2 = np.linalg.norm(q[1]-q[2])
        wq = (w1+w2)/2; hq = (h1+h2)/2
        if min(wq, hq) < 20: return
        rect = (min(w1, w2)/max(w1, w2))*(min(h1, h2)/max(h1, h2))
        if rect < rect_min: return
        ar = min(wq, hq)/max(wq, hq)
        arsc = 1 - min(1, abs(ar - 5/7)/ar_tol)
        if arsc <= 0: return
        qa = wq*hq; fill = min(1, ca/(qa+1e-6))
        if fill < fill_min: return
        qx = (q[0][0]+q[1][0]+q[2][0]+q[3][0])/4; qy = (q[0][1]+q[1][1]+q[2][1]+q[3][1])/4
        ctr = 1 - min(1, ((qx-cx)**2+(qy-cy)**2)**0.5/halfd)
        score = arsc*0.3 + rect*0.22 + fill*0.16 + min(1, qa/area_img)*0.1 + ctr*0.22
        if not clean: score *= 0.92
        cands.append((q, score, qa))
    for c in cnts:
        a = cv2.contourArea(c)
        if a < area_img*area_min: continue
        peri = cv2.arcLength(c, True)
        for ep in (0.02, 0.035, 0.05, 0.07):
            ap = cv2.approxPolyDP(c, ep*peri, True)
            if len(ap) == 4 and cv2.isContourConvex(ap):
                consider(order_quad(ap.reshape(4, 2).astype(np.float32)), a, True); break
        box = cv2.boxPoints(cv2.minAreaRect(c))
        consider(order_quad(box.astype(np.float32)), a, False)
    if not cands: return None, 0
    best = max(cands, key=lambda t: t[1])
    chosen = best
    if containment:
        # container must be fully INTERIOR to the frame — the image-border contour
        # (Canny artifacts at the frame edge) passes every gate and contains
        # everything, so without this it hijacks every detection. A real card
        # boundary that lost to its own art box is interior (card fully in view).
        # threshold 1.9x: art-box -> full card is ~2.2-3.1x (fires), a stack
        # outline around the top card is ~1.2-1.6x (doesn't — validated on the
        # close+real sets: 0 changes at 1.9, six stack over-grabs at 1.3).
        m = 0.03 * min(procW, procH)
        for q, s, qa in cands:
            if qa <= best[2] * 1.9 or qa <= chosen[2]: continue
            if not all(m < p[0] < procW - m and m < p[1] < procH - m for p in q): continue
            if all(_pt_in_quad(p, q) for p in best[0]):
                chosen = (q, s, qa)
    return chosen[0]/sc, chosen[1]


def detect(rgb, two_pass):
    h, w = rgb.shape[:2]; procW = 480; sc = procW/w; procH = int(h*sc)
    small = cv2.resize(rgb, (procW, procH))
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.createCLAHE(3.0, (8, 8)).apply(gray)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    # pass 1: current behaviour (fixed Canny, standard gates)
    e1 = cv2.dilate(cv2.Canny(blur, 40, 120), np.ones((7, 7), np.uint8))
    best, score = _scan(e1, sc, procW, procH, (0.6, 0.7, 0.26, 0.05))
    if best is not None or not two_pass:
        return best, score, 1
    # pass 2 (only if pass 1 failed): adaptive low Canny from the image median +
    # a bigger dilate to bridge gaps on stacks/dim cards + relaxed gates.
    med = float(np.median(blur))
    lo = int(max(0, 0.55*med)); hi = int(max(lo+20, 1.1*med))
    e2 = cv2.dilate(cv2.Canny(blur, lo, hi), np.ones((9, 9), np.uint8), iterations=2)
    best, score = _scan(e2, sc, procW, procH, (0.5, 0.55, 0.30, 0.04))
    return best, score, (2 if best is not None else 0)


def rectify(rgb, quad):
    wq = (np.linalg.norm(quad[0]-quad[1])+np.linalg.norm(quad[3]-quad[2]))/2
    hq = (np.linalg.norm(quad[0]-quad[3])+np.linalg.norm(quad[1]-quad[2]))/2
    outW, outH = (560, 400) if wq > hq else (360, 504)
    M = cv2.getPerspectiveTransform(quad.astype(np.float32),
        np.array([[0, 0], [outW, 0], [outW, outH], [0, outH]], np.float32))
    return cv2.warpPerspective(rgb, M, (outW, outH))


def main():
    idx = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8")); meta = idx["cards"]
    ref = np.zeros((len(meta), 432), np.float32)
    for i, c in enumerate(meta):
        p = IMG/f"{c['id']}.avif"
        if p.exists(): ref[i] = D.color_sig(Image.open(p).convert("RGB"))
    lbl = lambda m: m["name"] + (" - "+m["version"] if m.get("version") else "")

    def cmatch(rgbimg, k=3):
        t = time.perf_counter()
        qv = D.color_sig(Image.fromarray(rgbimg)); s = ref @ qv
        o = np.argsort(-s)[:k]
        return [lbl(meta[i]) for i in o], (time.perf_counter()-t)*1000

    files = sorted(f for f in glob.glob(str(REAL/"*.jpg")) if "_contact" not in f)
    # dump two-pass rectifications + a contact sheet so we can eyeball whether the
    # detector isolates the TOP card (good for OCR) or grabs a garbled region.
    from PIL import ImageDraw
    OUT2 = DATA/"real_out2"; OUT2.mkdir(exist_ok=True)
    rects = []
    for f in files:
        name = Path(f).stem[:8]
        rgb = np.asarray(Image.open(f).convert("RGB"))
        quad, score, used = detect(rgb, True)
        if quad is not None:
            rect = rectify(rgb, quad); top, _ = cmatch(rect)
            rects.append((name, used, rect, top[0]))
    cols = 4; rows = (len(rects)+cols-1)//cols; tw, th = 200, 300
    sheet = Image.new("RGB", (cols*tw, rows*th), (15, 15, 15)); dd = ImageDraw.Draw(sheet)
    for i, (name, used, rect, top) in enumerate(rects):
        im = Image.fromarray(rect); im.thumbnail((tw-8, th-40))
        x = (i % cols)*tw; y = (i//cols)*th; sheet.paste(im, (x+4, y+4))
        dd.text((x+6, y+th-34), name+(" P2" if used == 2 else " P1"), fill=(255, 180, 120) if used == 2 else (120, 255, 120))
        dd.text((x+6, y+th-20), top[:24], fill=(255, 255, 150))
    sheet.save(OUT2/"_twopass.jpg", quality=88)
    print("saved two-pass contact sheet:", OUT2/"_twopass.jpg")

    for label, two in (("CURRENT (1-pass)", False), ("TWO-PASS", True)):
        det = 0; p2 = 0; tdet = []; tmatch = []
        print(f"\n===== {label} =====")
        for f in files:
            name = Path(f).stem[:8]
            rgb = np.asarray(Image.open(f).convert("RGB"))
            t = time.perf_counter()
            quad, score, used = detect(rgb, two)
            tdet.append((time.perf_counter()-t)*1000)
            if quad is not None:
                det += 1
                if used == 2: p2 += 1
                rect = rectify(rgb, quad)
                top, mms = cmatch(rect); tmatch.append(mms)
                tag = "  [pass2]" if used == 2 else ""
                print(f"  {name} det conf={score:.2f}{tag}  -> {top[0]}")
            else:
                print(f"  {name} NODET")
        n = len(files)
        print(f"  detected {det}/{n} ({100*det//n}%)" + (f", {p2} via pass2" if two else ""))
        print(f"  detect: {np.mean(tdet):.0f}ms avg / {np.max(tdet):.0f}ms max (480px, desktop cv2)")
        if tmatch: print(f"  colour match: {np.mean(tmatch):.1f}ms avg")


if __name__ == "__main__":
    main()
