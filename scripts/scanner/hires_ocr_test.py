"""
The decisive test: rectify the HIGH-RES original phone photos at 1000x1400 (what
the app's OCR path actually uses) and OCR the name band at native res. This is the
real ceiling for OCR-name-primary (the 400px flywheel crops badly understate it).

  python scripts/scanner/hires_ocr_test.py
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parent))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from real_eval2 import detect, rectify
from ocr_match_validate import prep_card, rankNames_py, normName

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
REAL = HERE / "data" / "real"


def main():
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cards = json.loads((REPO / "scanner" / "text.json").read_text(encoding="utf-8"))
    for c in cards: prep_card(c)
    files = [f for f in sorted(glob.glob(str(REAL / "*.jpg"))) if "_contact" not in f]
    print(f"{len(files)} high-res originals\n")
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"  {Path(f).stem[:8]}  NODET"); continue
        # rectify big (1000x1400) — native high-res name text
        rim = Image.fromarray(rectify(rgb, q))
        if rim.width < 600:  # ensure big enough
            rim = rim.resize((1000, int(1000 * rim.height / rim.width)), Image.LANCZOS)
        W, H = rim.size
        # OCR the whole card (above the rules box) ONCE; the NAME is the
        # largest-font text on a Lorcana card, so take the tallest text lines —
        # layout-agnostic (works for characters mid-card AND songs/actions on top).
        lines = []
        crop = rim.crop((0, 0, W, int(H*0.74)))
        res, _ = ocr(np.asarray(crop))
        for bx, txt, sc in (res or []):
            ys = [p[1] for p in bx]; h = max(ys) - min(ys)
            wlen = max(p[0] for p in bx) - min(p[0] for p in bx)
            t = (txt or "").strip()
            # skip tiny text (cost/lore pips) + very long rules lines
            if len(t) >= 2 and h > 0: lines.append((h, t))
        lines.sort(key=lambda x: -x[0])
        cand = [t for _, t in lines[:3]]
        r = rankNames_py(cand, cards, 3)
        top = r["top"][0] if r["top"] else {"name": "—", "version": "", "score": 0}
        nm = (top["name"] + (" - " + top["version"] if top.get("version") else ""))
        print(f"  {Path(f).stem[:8]}  read:{str(cand[:1]):26} -> {nm[:30]:30} conf={r['conf']} ({top['score']:.2f})")


if __name__ == "__main__":
    main()
