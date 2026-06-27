"""
OCR v2: the OCR reads names fine — fix the MATCHER + ROI. Pick the largest text
line in the name band (the name is the biggest text) and match by token-recall
(robust to junk + garbled chars). On the 60 labelled 400px crops.

  python scripts/scanner/ocr_experiment2.py
"""
from __future__ import annotations
import glob, json, re, sys, time
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np
from PIL import Image
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FLY = HERE / "data" / "flywheel"

def norm(s): return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
def toks(s): return [w for w in norm(s).split() if len(w) >= 2]
def squash(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def ratio(a, b): return SequenceMatcher(None, a, b).ratio()

def main():
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cards = json.loads((REPO / "scanner" / "text.json").read_text(encoding="utf-8"))
    for c in cards:
        c["_name"] = (c.get("n", "") + (" - " + c["v"] if c.get("v") else "")).strip()
        c["_ntok"] = toks(c.get("n", ""))            # name-only tokens
        c["_nsq"] = squash(c.get("n", ""))
    # token IDF over all card names (rare name-tokens are decisive)
    df = {}
    for c in cards:
        for t in set(c["_ntok"]): df[t] = df.get(t, 0) + 1
    Nn = len(cards)
    tidf = {t: np.log(Nn / (v + 1)) for t, v in df.items()}

    def name_match(ocr_line):
        """token-recall fuzzy match: how many of the card's name tokens appear
        (fuzzily) in the OCR line, IDF-weighted. Robust to junk + dropped chars."""
        q = squash(ocr_line)
        qt = toks(ocr_line)
        if len(q) < 3: return []
        scored = []
        for c in cards:
            nt = c["_ntok"]
            if not nt: continue
            got = wsum = 0.0
            for t in nt:
                w = tidf.get(t, 1.0)
                wsum += w
                # token present if any OCR token fuzzy-matches it, or it's a substring of the squashed line
                if any(ratio(t, u) >= 0.8 for u in qt) or (len(t) >= 4 and t in q):
                    got += w
            rec = got / wsum if wsum else 0
            # full-string similarity as a tiebreak / single-word-name help
            sim = ratio(q, c["_nsq"])
            score = rec * 0.8 + sim * 0.2
            scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:3]

    files = [f for f in sorted(glob.glob(str(FLY / "*.jpg"))) if "_sheet" not in f]
    n = t1 = t3 = read = 0
    tms = 0.0
    shown = 0
    for f in files:
        mt = re.search(r"truth-([^_]+)", Path(f).stem)
        truth = mt.group(1).replace("-", " ") if mt else ""
        if not truth: continue
        n += 1; tsq = squash(truth)
        im = Image.open(f).convert("RGB"); W, H = im.size
        # name band: y 0.50-0.71 (covers character name banner across most cards),
        # upscale 4x; take the TALLEST text box = the name line.
        t0 = time.time()
        band = im.crop((int(W*0.02), int(H*0.50), int(W*0.98), int(H*0.71)))
        band = band.resize((band.width*4, band.height*4), Image.LANCZOS)
        res, _ = ocr(np.asarray(band))
        lines = []
        for box, txt, sc in (res or []):
            ys = [p[1] for p in box]; h = max(ys) - min(ys)
            lines.append((h, txt, float(sc) if isinstance(sc, (int, float)) else 0.5))
        lines.sort(key=lambda x: -x[0])
        nameline = lines[0][1] if lines else ""
        top = name_match(nameline)
        tms += time.time() - t0
        # right CHARACTER = all of the truth's character-name tokens are in the
        # matched card's name (version/printing disambiguation is colour's job).
        truth_char_toks = [t for t in toks(truth.split(" - ")[0]) if len(t) >= 2]
        def hit(c):
            cn = set(toks(c.get("n", "")))
            return truth_char_toks and all(t in cn for t in truth_char_toks)
        if top and hit(top[0][1]): t1 += 1
        if any(hit(c) for _, c in top): t3 += 1
        # did the name read at all (any top-3 name-token overlap with truth)?
        if any(t in squash(nameline) for t in [w for w in toks(truth.split(' - ')[0]) if len(w) >= 4]): read += 1
        if shown < 16:
            shown += 1
            print(f"  {truth[:20]:20} | read:'{nameline[:22]:22}' | -> {top[0][1]['_name'][:24] if top else '—':24} | {'OK' if top and hit(top[0][1]) else '..'}")
    print(f"\n=== NAME-OCR v2 on {n} REAL 400px crops (tallest-line + token-recall) ===")
    print(f"  name read clearly (>=1 name-word): {read}/{n} ({100*read/n:.0f}%)")
    print(f"  match top1: {t1}/{n} ({100*t1/n:.0f}%)   top3: {t3}/{n} ({100*t3/n:.0f}%)   ~{1000*tms/n:.0f}ms/card")
    print(f"  (colour baseline ~30% top1; OCR v1 name 38%; these are 400px — app rectifies at 1000px)")

if __name__ == "__main__":
    main()
