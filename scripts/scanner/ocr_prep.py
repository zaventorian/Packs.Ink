"""
High-res rectifications of the real photos for the OCR experiment. Reuses the
shipped detection/rectify (real_eval) but outputs at a big size so the small
stylised text has enough pixels for OCR. Saves data/ocr_rect/<name>.png.
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"; REAL = DATA / "real"; OUT = DATA / "ocr_rect"
sys.path.insert(0, str(HERE))
from real_eval import detect_quad, rectify  # noqa: E402

def main():
    OUT.mkdir(exist_ok=True)
    files = [f for f in sorted(glob.glob(str(REAL / "*.jpg"))) if "_contact" not in f]
    n = 0
    for f in files:
        name = Path(f).stem[:8]
        rgb = np.asarray(Image.open(f).convert("RGB"))
        quad = detect_quad(rgb)
        if quad is None:
            H, W = rgb.shape[:2]; gh = int(H * 0.82); gw = int(gh * 5 / 7)
            crop = rgb[max(0, (H - gh) // 2):(H + gh) // 2, max(0, (W - gw) // 2):(W + gw) // 2]
            img = Image.fromarray(crop).resize((1000, 1400))
        else:
            # rectify, then upscale to a big canonical size for OCR
            r = rectify(rgb, quad, normalize=False)
            img = Image.fromarray(r).resize((1000, 1400), Image.LANCZOS)
        img.save(OUT / f"{name}.png")
        n += 1
    print(f"wrote {n} hi-res rectifications to {OUT}")

if __name__ == "__main__":
    main()
