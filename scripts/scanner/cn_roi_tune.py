"""
Lift the collector-number read rate. Try several bottom-strip ROIs + upscales on
the close photos, measure N/M read rate, and dump a strip contact sheet so we can
SEE where the number sits and why it misses.

  python scripts/scanner/cn_roi_tune.py "C:/Users/zaven/Downloads/card photos"
"""
from __future__ import annotations
import glob, re, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from real_eval2 import detect, rectify

OLD = {"167f2075","193f94de","1ce4898e","1dfccf3c","20b4d242","264fa11e","5567f7b2",
       "71f4188b","7221bd8c","9b4c6a02","9e6acc7c","a6ae22bf","aa32a7e1","bfb32821",
       "c2fc1c0f","d7721408","ea620437","f4e177ee","fc3a09fb"}

# candidate ROIs (x0,y0,x1,y1 fractions) + upscale
ROIS = {
    "cur 0-.55/.90-.99 x4": (0.0, 0.90, 0.55, 0.99, 4),
    "low .96-1.0 x5":       (0.0, 0.955, 0.50, 1.0, 5),
    "wide 0-.6/.93-1.0 x5": (0.0, 0.93, 0.60, 1.0, 5),
    "tall 0-.5/.90-1.0 x6": (0.0, 0.90, 0.50, 1.0, 6),
}


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else str(HERE/"data"/"real")
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    files = [f for f in sorted(glob.glob(str(Path(folder)/"*.jpg"))) if Path(f).stem[:8] not in OLD]
    print(f"{len(files)} close photos\n")
    counts = {k: 0 for k in ROIS}
    strips = []
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None: continue
        rim = Image.fromarray(rectify(rgb, q))
        if rim.width < 700: rim = rim.resize((1000, int(1000*rim.height/rim.width)), Image.LANCZOS)
        W, H = rim.size
        reads = {}
        for k, (x0, y0, x1, y1, up) in ROIS.items():
            crop = rim.crop((int(W*x0), int(H*y0), int(W*x1), int(H*y1)))
            crop = crop.resize((int(crop.width*up), int(crop.height*up)), Image.LANCZOS)
            res, _ = ocr(np.asarray(crop))
            txt = " ".join(t for _, t, _ in (res or []))
            m = re.search(r"(\d{1,3})\s*[/Il|]\s*(\d{2,3})", txt)
            reads[k] = (m.group(0) if m else None, txt[:30])
            if m: counts[k] += 1
        best = next((v[0] for v in reads.values() if v[0]), None)
        print(f"  {Path(f).stem[:8]}  " + " | ".join(f"{k.split()[0]}:{reads[k][0] or '-'}" for k in ROIS))
        # keep the wide strip for the sheet
        s = rim.crop((0, int(H*0.92), int(W*0.6), H)); strips.append((Path(f).stem[:8], s, best))
    n = len(files)
    print("\nread-rate per ROI:")
    for k in ROIS: print(f"  {k:24} {counts[k]}/{n} ({100*counts[k]//max(1,n)}%)")
    # strip sheet
    sw, sh = 360, 70; sheet = Image.new("RGB", (sw, sh*len(strips)+4), (10,10,10)); dd = ImageDraw.Draw(sheet)
    for i, (nm, s, best) in enumerate(strips):
        s2 = s.resize((sw-90, sh-8)); sheet.paste(s2, (2, i*sh+4))
        dd.text((sw-86, i*sh+24), nm+"\n"+(best or "no N/M"), fill=(120,255,120) if best else (255,140,140))
    sheet.save(HERE/"data"/"close_out"/"_cn_strips.jpg", quality=90)
    print("strip sheet ->", HERE/"data"/"close_out"/"_cn_strips.jpg")


if __name__ == "__main__":
    main()
