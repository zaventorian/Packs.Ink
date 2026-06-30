"""
Run the worker's EXACT name + collector-number OCR on the 18 already-rectified
QA-snap images (scripts/scanner/data/qa/qa_<id>.jpg) — the flywheel stores the
rectified `rect` the worker produced ON-DEVICE, so we do NOT detect/rectify again.

Three things per image:
  - NAME  : det upper 0.74, tallest boxes with a letter (mirrors scanner-ocr-worker.js handleOcr)
  - CN cur: the SHIPPED readNumber ROIs [[0,.90,.60,1,x5],[0,.85,.66,1,x6]]  (expect ~0)
  - CN wide: a tall lower-band search that finds the "N/M" pattern wherever the
             card's bottom actually sits (robust to the loose rectify we observed)

  python scripts/scanner/qa_cn_test.py
"""
from __future__ import annotations
import glob, re, sys
from pathlib import Path
import numpy as np, cv2
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import ppocr_web_sim as P            # reuse onnx sessions + det/rec plumbing

QA = HERE / "data" / "qa"

# Ground truth for the 18 debug ids (from DB truth_card_id where reviewed, else
# eyeballed from the rectified image). name only — version noted where it matters.
TRUTH = {
 82: "Plunger Crossbow", 83: "Super Relocation Program", 84: "Incrediboy",
 85: "Amazu's Inkcaster", 86: "Dangerous Plan", 87: "Escape Plan",
 88: "Omnidroid", 89: "Julieta's Arepas", 90: "Touch the Sky",
 91: "Monterey Jack", 92: "Monterey Jack", 93: "Minnie Mouse",
 94: "Omnidroid", 95: "Julieta's Arepas", 96: "Dangerous Plan",
 97: "Dangerous Plan", 98: "Escape Plan", 99: "Amazu's Inkcaster",
}


def parseCN2(txt):
    """mirror scanner-ocr-worker.js parseCN; returns (num, tot) or None."""
    t = re.sub(r"[Oo]", "0", txt)
    t = re.sub(r"[•·∙°]", " ", t)
    for pat in (r"(\d{1,3})\s*/\s*(\d{2,3})",
                r"(\d{1,3})\s*[1lI|]\s*(\d{2,3})",
                r"(\d{1,3})\s+(\d{2,3})(?!\d)"):
        m = re.search(pat, t)
        if m:
            return (m.group(1).lstrip("0") or "0", int(m.group(2)))
    return None


def parseCN(txt):
    r = parseCN2(txt)
    return r[0] if r else None


def det_boxes(strip):
    """full axis-aligned boxes (x0,y0,x1,y1,h) + rec'd text for a strip."""
    x, rh, rw = P.det_preproc(strip, "min", P.DET_SIDE)
    prob = P._det.run(None, {P._det_in: x})[0][0, 0]
    out = []
    for (bx0, by0, bx1, by1, bh) in P.cc_boxes(prob, rh, rw):
        crop = strip[int(by0):int(by1), int(bx0):int(bx1)]
        if crop.size == 0:
            continue
        txt = P.rec_one(crop)
        if txt.strip():
            out.append((bx0, by0, bx1, by1, txt))
    return out


def cn_current(rim, Hd, Wd):
    """the SHIPPED readNumber: bottom-strip ROIs, upscale, det+rec, parseCN."""
    for (x0f, y0f, x1f, y1f, up) in [(0.0, 0.90, 0.60, 1.0, 5), (0.0, 0.85, 0.66, 1.0, 6)]:
        rx, ry = int(Wd * x0f), int(Hd * y0f)
        rw, rh = int(Wd * x1f) - rx, int(Hd * y1f) - ry
        if rw < 4 or rh < 2:
            continue
        strip = cv2.resize(rim[ry:ry + rh, rx:rx + rw], (rw * up, rh * up), interpolation=cv2.INTER_CUBIC)
        boxes = det_boxes(strip)
        # per-box, then full L-to-R line join
        for (bx0, by0, bx1, by1, txt) in sorted(boxes, key=lambda b: b[0]):
            c = parseCN(txt)
            if c: return c, f"cur[{y0f}-{y1f}]"
        joined = " ".join(t for *_r, t in sorted(boxes, key=lambda b: b[1] // 30 * 1000 + b[0]))
        c = parseCN(joined)
        if c: return c, f"cur-join[{y0f}-{y1f}]"
    return None, None


def cn_sweep(rim, Hd, Wd):
    """The FIX: keep the thin-ROI high-upscale read (what makes cn legible), but
    sweep thin bands bottom-up so one lands on the collector-number line wherever
    the card's bottom actually sits (handles a loose rectify where background fills
    below the card). Band 1+2 == the SHIPPED ROIs, so the sweep is a strict SUPERSET
    of the current read (can't regress); the higher rescue bands only ADD reads, and
    require a plausible set-total denominator (>=60) to reject rules-text/stat false
    positives like '2/3'. Bottom-up so a real low cn wins before we reach rules text.

    bands: (y0, y1, width, upscale, min_tot)."""
    bands = [
        (0.90, 1.00, 0.60, 5, 0),     # == shipped ROI #1
        (0.85, 1.00, 0.66, 6, 0),     # == shipped ROI #2
        (0.80, 0.92, 0.55, 5, 150),   # mild-loose rescue, just above card bottom;
        (0.74, 0.86, 0.55, 5, 150),   # tight set-total guard (Lorcana totals ~165-224)
    ]
    for (y0f, y1f, x1f, up, min_tot) in bands:
        ry, ry1 = int(Hd * y0f), int(Hd * y1f)
        strip = rim[ry:ry1, 0:int(Wd * x1f)]
        if strip.size == 0:
            continue
        strip = cv2.resize(strip, (strip.shape[1] * up, strip.shape[0] * up), interpolation=cv2.INTER_CUBIC)
        boxes = det_boxes(strip)
        cands = sorted(boxes, key=lambda b: b[0])
        joined = " ".join(t for *_r, t in sorted(boxes, key=lambda b: (b[1] // 40, b[0])))
        for txt in [t for *_r, t in cands] + [joined]:
            r = parseCN2(txt)
            if r and r[1] >= min_tot:
                return r[0], f"sweep[{y0f:.2f}]"
    return None, None


def cn_wide(rim, Hd, Wd):
    """Robust to the loose rectify: scan a TALL lower band (the card's bottom can
    be anywhere from ~0.55 to ~0.97 of the frame). Upscale x3, det, then look for
    the 'N/M' pattern per detected line (boxes bucketed by y, joined L-to-R)."""
    for (y0f, y1f, x1f, up) in [(0.45, 1.0, 0.62, 3), (0.45, 1.0, 1.0, 3)]:
        ry, ry1 = int(Hd * y0f), int(Hd * y1f)
        rx1 = int(Wd * x1f)
        strip = rim[ry:ry1, 0:rx1]
        if strip.size == 0:
            continue
        strip = cv2.resize(strip, (strip.shape[1] * up, strip.shape[0] * up), interpolation=cv2.INTER_CUBIC)
        boxes = det_boxes(strip)
        if not boxes:
            continue
        # per-box first (the common "171/204" single-box read)
        for (bx0, by0, bx1, by1, txt) in boxes:
            c = parseCN(txt)
            if c: return c, f"wide[{y0f}-{y1f} x{x1f}]", txt
        # then bucket into lines by y and join L-to-R
        boxes.sort(key=lambda b: (b[1], b[0]))
        lines, cur, cy = [], [], None
        for b in boxes:
            h = b[3] - b[1]
            if cy is None or abs(b[1] - cy) < 0.6 * h:
                cur.append(b); cy = b[1] if cy is None else cy
            else:
                lines.append(cur); cur = [b]; cy = b[1]
        if cur: lines.append(cur)
        for ln in lines:
            joined = " ".join(t for *_r, t in sorted(ln, key=lambda b: b[0]))
            c = parseCN(joined)
            if c: return c, f"wide-join[{y0f}-{y1f}]", joined
    return None, None, None


def name_read(rim, Hd, Wd, frac=0.74, topn=4):
    """mirror handleOcr NAME: det upper `frac`, tallest `topn` boxes with a letter."""
    upper = rim[0:int(Hd * frac), 0:Wd]
    boxes = det_boxes(upper)
    cand = [(t, (by1 - by0)) for (bx0, by0, bx1, by1, t) in boxes
            if len(t.strip()) >= 2 and re.search(r"[A-Za-z]", t)]
    cand.sort(key=lambda r: -r[1])
    return [t for t, _h in cand[:topn]]


def main():
    files = sorted(glob.glob(str(QA / "qa_*.jpg")))
    ncur = nwide = nname_ok = 0
    print(f"{len(files)} QA images (already-rectified on-device output)\n")
    print(f"{'id':>3} {'truth':22} {'name_read':22} {'cn_cur':>6} {'cn_wide':>7}  where")
    print("-" * 86)
    for f in files:
        cid = int(Path(f).stem.split("_")[1])
        rim = np.asarray(Image.open(f).convert("RGB"))
        Hd, Wd = rim.shape[:2]
        names = name_read(rim, Hd, Wd)
        n0 = names[0] if names else ""
        cur, _cw = cn_current(rim, Hd, Wd)
        wide, wwhere, wtxt = cn_wide(rim, Hd, Wd)
        truth = TRUTH.get(cid, "?")
        name_ok = truth.lower()[:8] in (n0.lower().replace(" ", "")) or n0.lower()[:5] in truth.lower().replace(" ", "")
        if cur: ncur += 1
        if wide: nwide += 1
        if name_ok: nname_ok += 1
        print(f"{cid:>3} {truth[:22]:22} {n0[:22]:22} {(cur or '-'):>6} {(wide or '-'):>7}  {wwhere or ''}")
    n = len(files)
    print("-" * 86)
    print(f"cn CURRENT (shipped) : {ncur}/{n} ({100*ncur//max(1,n)}%)")
    print(f"cn WIDE   (proposed) : {nwide}/{n} ({100*nwide//max(1,n)}%)")
    print(f"name top-1 contains  : {nname_ok}/{n} ({100*nname_ok//max(1,n)}%)")


if __name__ == "__main__":
    main()
