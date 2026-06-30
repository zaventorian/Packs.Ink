"""
Where does the OCR time go? Profiles the name det + the number-read configs on the
full-res close set so we can cut latency without losing the cn/name read-rate.
onnxruntime-CPU absolute ms != phone WASM, but the RELATIVE cost (which scales with
det input pixels) transfers — so the ranking + speedups are the signal.

  python scripts/scanner/ocr_latency_profile.py [--n 12]
"""
from __future__ import annotations
import glob, re, sys, time
from pathlib import Path
import numpy as np, cv2
from PIL import Image
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import ppocr_web_sim as P
from real_eval2 import detect, rectify
from qa_cn_test import parseCN2, det_boxes

N = 12
if "--n" in sys.argv: N = int(sys.argv[sys.argv.index("--n") + 1])


def det_only(strip, side, limit="min"):
    """time just the det forward pass (the dominant cost) on a strip."""
    x, rh, rw = P.det_preproc(strip, limit, side)
    px = x.shape[2] * x.shape[3]
    t = time.perf_counter()
    P._det.run(None, {P._det_in: x})
    return (time.perf_counter() - t) * 1000, px


def number_read(rim, Hd, Wd, bands, side, rec_cap=99):
    """det+rec sweep; rec only the leftmost `rec_cap` boxes (cn is bottom-left).
    return (cn, total_ms, n_det_passes)."""
    t0 = time.perf_counter(); npass = 0
    cn = None
    for (y0f, y1f, x1f, up, min_tot) in bands:
        ry, ry1 = int(Hd * y0f), int(Hd * y1f)
        strip = rim[ry:ry1, 0:int(Wd * x1f)]
        if strip.size == 0:
            continue
        strip = cv2.resize(strip, (strip.shape[1] * up, strip.shape[0] * up), interpolation=cv2.INTER_CUBIC)
        x, rh, rw = P.det_preproc(strip, "min", side); npass += 1
        prob = P._det.run(None, {P._det_in: x})[0][0, 0]
        bx = sorted(P.cc_boxes(prob, rh, rw), key=lambda b: b[0])[:rec_cap]  # leftmost N only
        boxes = []
        for (bx0, by0, bx1, by1, bh) in bx:
            crop = strip[int(by0):int(by1), int(bx0):int(bx1)]
            if crop.size:
                txt = P.rec_one(crop)
                if txt.strip(): boxes.append((bx0, txt))
        texts = [t for _x, t in boxes] + [" ".join(t for _x, t in boxes)]
        hit = None
        for txt in texts:
            r = parseCN2(txt)
            if r and r[1] >= min_tot: hit = r[0]; break
        if hit: cn = hit; break
    return cn, (time.perf_counter() - t0) * 1000, npass


CUR   = [(0.90, 1.00, 0.60, 5, 0), (0.85, 1.00, 0.66, 6, 0)]
SWP4  = [(0.90, 1.00, 0.60, 5, 0), (0.85, 1.00, 0.66, 6, 0), (0.80, 0.92, 0.55, 5, 150), (0.74, 0.86, 0.55, 5, 150)]
# CHEAP: lower upscale (smaller strips), one combined bottom band + one mild-margin
# rescue, rec only the leftmost 4 boxes (cn is bottom-left), DET_SIDE 512.
CHEAP = [(0.88, 1.00, 0.58, 3, 0), (0.80, 0.93, 0.55, 3, 150)]


def main():
    files = sorted(glob.glob(str(HERE / "data" / "close" / "*.jpg")))[:N]
    name_ms = []
    cur = {"ms": [], "hit": 0}; swp = {"ms": [], "hit": 0}; chp = {"ms": [], "hit": 0}
    print(f"profiling {len(files)} close photos  (onnxruntime CPU ms — relative cost is the signal)\n")
    print(f"{'file':9} {'nameDet':>8} {'#cur(2)':>9} {'#swp(4)':>9} {'#cheap':>9}")
    print("-" * 52)
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None: continue
        rim = rectify(rgb, q); rimg = Image.fromarray(rim)
        if rimg.width != 1200:
            rimg = rimg.resize((1200, int(1200 * rimg.height / rimg.width)), Image.LANCZOS); rim = np.asarray(rimg)
        Hd, Wd = rim.shape[:2]
        nd_ms, npx = det_only(rim[0:int(Hd * 0.74), 0:Wd], 736); name_ms.append(nd_ms)
        c1, m1, _ = number_read(rim, Hd, Wd, CUR, 736);              cur["ms"].append(m1); cur["hit"] += bool(c1)
        c2, m2, _ = number_read(rim, Hd, Wd, CUR, 736, rec_cap=5);   swp["ms"].append(m2); swp["hit"] += bool(c2)
        c3, m3, _ = number_read(rim, Hd, Wd, CUR, 512, rec_cap=5);   chp["ms"].append(m3); chp["hit"] += bool(c3)
        print(f"{Path(f).stem[:8]:9} {nd_ms:7.0f}m {m1:8.0f}m {m2:8.0f}m {m3:8.0f}m")
    n = max(1, len(name_ms))
    avg = lambda a: sum(a) / max(1, len(a))
    print("-" * 52)
    print(f"name det avg: {avg(name_ms):.0f}ms")
    print(f"number CUR     (x5/6, side736, rec ALL): {avg(cur['ms']):.0f}ms avg   reads {cur['hit']}/{n}")
    print(f"number CAP5    (x5/6, side736, rec L5 ): {avg(swp['ms']):.0f}ms avg   reads {swp['hit']}/{n}")
    print(f"number CAP5+512(x5/6, side512, rec L5 ): {avg(chp['ms']):.0f}ms avg   reads {chp['hit']}/{n}")


if __name__ == "__main__":
    main()
