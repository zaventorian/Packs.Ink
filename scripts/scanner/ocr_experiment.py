"""
Does OCR actually solve the scanner? Test 3 OCR strategies on the 60 real
labelled flywheel crops (truth in the filename) and compare to the ~30% colour
baseline. Uses PP-OCR (rapidocr-onnxruntime) = the ship-able engine class.

  python scripts/scanner/ocr_experiment.py
"""
from __future__ import annotations
import glob, json, re, sys, time
from difflib import SequenceMatcher
from pathlib import Path
import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FLY = HERE / "data" / "flywheel"


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
def squash(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())
def toks(s):
    return [w for w in norm(s).split() if len(w) >= 2]


def main():
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cards = json.loads((REPO / "scanner" / "text.json").read_text(encoding="utf-8"))
    # display name + searchable forms
    for c in cards:
        c["_name"] = (c.get("n", "") + (" - " + c["v"] if c.get("v") else "")).strip()
        c["_nsq"] = squash(c.get("n", ""))            # name only, squashed
        c["_fsq"] = squash(c["_name"])                # full, squashed
    # IDF over the text blob (mirror of the app's textMatch)
    N = len(cards); df = {}
    for c in cards:
        for t in set(toks(c.get("b", ""))):
            df[t] = df.get(t, 0) + 1
    idf = {t: np.log(N / (v + 1)) for t, v in df.items()}
    # collector-number index: cn -> [cards]
    cn_idx = {}
    for c in cards:
        if c.get("cn"):
            cn_idx.setdefault(str(c["cn"]), []).append(c)

    def ocr_text(im_rgb):
        res, _ = ocr(np.asarray(im_rgb))
        return [(t, float(s)) for _, t, s in (res or [])]

    def best_name(ocr_str):
        """fuzzy-match an OCR'd name line to a card name. returns (card, score)."""
        q = squash(ocr_str)
        if len(q) < 3:
            return None, 0
        best, bs = None, 0
        for c in cards:
            # ratio against name-only and full; substring bonus
            r = max(SequenceMatcher(None, q, c["_nsq"]).ratio(),
                    SequenceMatcher(None, q, c["_fsq"]).ratio())
            if c["_nsq"] and (c["_nsq"] in q or q in c["_nsq"]):
                r = max(r, 0.9)
            if r > bs:
                bs, best = r, c
        return best, bs

    def idf_match(blob):
        qt = set(toks(blob))
        scores = []
        for c in cards:
            s = sum(idf.get(w, 0) for w in qt if w in set(toks(c.get("b", ""))))
            scores.append(s)
        order = np.argsort(scores)[::-1][:3]
        return [(cards[i], scores[i]) for i in order]

    files = [f for f in sorted(glob.glob(str(FLY / "*.jpg"))) if "_sheet" not in f]
    nameOK = fullOK = full3OK = cnOK = anyOK = n = 0
    tA = tB = tC = 0.0
    for f in files:
        mt = re.search(r"truth-([^_]+)", Path(f).stem)
        truth = mt.group(1).replace("-", " ") if mt else ""
        if not truth:
            continue
        n += 1
        tsq = squash(truth)
        im = Image.open(f).convert("RGB")
        W, H = im.size
        up = lambda box, k=3: im.crop(box).resize((int((box[2]-box[0])*k), int((box[3]-box[1])*k)), Image.LANCZOS)

        # A. NAME region (character layout: name banner ~y0.55-0.67, left ~75%)
        t0 = time.time()
        nameimg = up((int(W*0.03), int(H*0.53), int(W*0.80), int(H*0.69)), 4)
        ntxt = " ".join(t for t, s in ocr_text(nameimg) if s > 0.3)
        card, sc = best_name(ntxt)
        tA += time.time() - t0
        a_ok = card is not None and sc > 0.55 and squash(card["_name"]) and (tsq in squash(card["_name"]) or squash(card["_name"]) in tsq or squash(card.get("n","")) == squash(truth.split(" - ")[0]))

        # B. FULL lower-card text -> IDF (layout-agnostic, the app's approach)
        t0 = time.time()
        fullimg = up((int(W*0.02), int(H*0.40), int(W*0.98), int(H*0.99)), 2)
        ftxt = " ".join(t for t, s in ocr_text(fullimg) if s > 0.3)
        top3 = idf_match(ftxt)
        tB += time.time() - t0
        b_ok = top3 and squash(top3[0][0]["_name"]) and (tsq in squash(top3[0][0]["_name"]) or squash(top3[0][0]["_name"]) in tsq)
        b3_ok = any((tsq in squash(c["_name"]) or squash(c["_name"]) in tsq) for c, _ in top3)

        # C. COLLECTOR NUMBER (bottom-left ~y0.88-0.965)
        t0 = time.time()
        cnimg = up((int(W*0.02), int(H*0.87), int(W*0.42), int(H*0.97)), 4)
        ctxt = " ".join(t for t, s in ocr_text(cnimg))
        m = re.search(r"(\d{1,3})\s*[/i|]\s*(\d{2,3})", ctxt)
        c_ok = False
        if m:
            cand = cn_idx.get(m.group(1), [])
            c_ok = any((tsq in squash(c["_name"]) or squash(c["_name"]) in tsq) for c in cand)
        tC += time.time() - t0

        nameOK += a_ok; fullOK += b_ok; full3OK += b3_ok; cnOK += c_ok
        anyOK += (a_ok or b_ok or c_ok)
        if n <= 14:
            print(f"  {truth[:22]:22} | name:{'OK' if a_ok else '..'} '{ntxt[:24]}' | full:{'OK' if b_ok else '..'} | cn:{'OK' if c_ok else '..'} '{m.group(0) if m else ''}'")

    print(f"\n=== OCR strategies on {n} REAL labelled crops (400px, upscaled) ===")
    print(f"  A. name-region  -> fuzzy name : {nameOK}/{n} ({100*nameOK/n:.0f}%)   ~{1000*tA/n:.0f}ms/card")
    print(f"  B. full-text    -> IDF top1   : {fullOK}/{n} ({100*fullOK/n:.0f}%)  top3 {full3OK}/{n} ({100*full3OK/n:.0f}%)   ~{1000*tB/n:.0f}ms/card")
    print(f"  C. collector#   -> exact      : {cnOK}/{n} ({100*cnOK/n:.0f}%)   ~{1000*tC/n:.0f}ms/card")
    print(f"  ANY of A/B/C right            : {anyOK}/{n} ({100*anyOK/n:.0f}%)")
    print(f"  (colour-only baseline was ~30% top1 / 40% top3)")


if __name__ == "__main__":
    main()
