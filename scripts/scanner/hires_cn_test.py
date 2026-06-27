"""
Can we read the COLLECTOR NUMBER at high res? It's a near-unique key (N/M = the
Nth card of an M-card set), so a reliable read = near-100% top-1 identity,
domain-gap-immune. Rectify the originals at 1000x1400 and OCR the bottom strip.

  python scripts/scanner/hires_cn_test.py
"""
from __future__ import annotations
import glob, re, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from real_eval2 import detect, rectify

HERE = Path(__file__).resolve().parent
REAL = HERE / "data" / "real"


def main():
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    files = [f for f in sorted(glob.glob(str(REAL / "*.jpg"))) if "_contact" not in f]
    print(f"{len(files)} high-res originals — reading the collector-number strip\n")
    hits = 0
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"  {Path(f).stem[:8]}  NODET"); continue
        rim = Image.fromarray(rectify(rgb, q))
        if rim.width < 700:
            rim = rim.resize((1000, int(1000*rim.height/rim.width)), Image.LANCZOS)
        W, H = rim.size
        # the collector line ("1/204 EN 1") sits in the bottom-left; try a couple
        # of bands, upscaled, and pull any N/M.
        found = None; raw = []
        for box in [(0.02, 0.935, 0.42, 0.99), (0.02, 0.95, 0.55, 1.0), (0.0, 0.92, 0.40, 0.985)]:
            crop = rim.crop((int(W*box[0]), int(H*box[1]), int(W*box[2]), int(H*box[3])))
            crop = crop.resize((crop.width*4, crop.height*4), Image.LANCZOS)
            res, _ = ocr(np.asarray(crop))
            txt = " ".join(t for _, t, _ in (res or []))
            raw.append(txt)
            m = re.search(r"(\d{1,3})\s*[/I|l]\s*(\d{2,3})", txt)
            if m: found = m.group(1) + "/" + m.group(2); break
        if found: hits += 1
        print(f"  {Path(f).stem[:8]}  {'N/M=' + found if found else 'no N/M':14}  raw: {raw[0][:40]!r}")
    n = len(files)
    print(f"\ncollector-number read N/M on {hits}/{n} ({100*hits//n}%) of these FAR/stacked originals")
    print("(close-framed single cards — the target workflow — should read much higher)")


if __name__ == "__main__":
    main()
