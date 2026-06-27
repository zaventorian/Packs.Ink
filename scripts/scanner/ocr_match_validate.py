"""
Port the synthesis matcher to Python, validate on the 60 real crops with a CORRECT
metric (right CHARACTER = name+version match; printing/version is colour's job).
OCRs once, caches reads to _ocr_cache.json, then the matcher runs instantly so the
thresholds can be tuned. This is the algorithm that ships in scanner.js.

  python scripts/scanner/ocr_match_validate.py
"""
from __future__ import annotations
import glob, json, re, sys, time
from pathlib import Path
import numpy as np
from PIL import Image
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
FLY = HERE / "data" / "flywheel"
CACHE = HERE / "data" / "_ocr_cache.json"

# ---- matcher (mirror of the JS we will ship) ----
def normName(s):
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace("'", "").replace("’", "").replace(".", "").replace("_", "")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()
def ocrCanon(s):
    return normName(s).replace("rn", "m").replace("vv", "w")
def trigrams(s):
    s = "  " + s.replace(" ", "") + "  "
    return set(s[i:i+3] for i in range(len(s)-2))
def toks(s):
    return set(w for w in normName(s).split() if len(w) >= 2)
def lev(a, b):
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b)+1))
    for i, ca in enumerate(a):
        cur = [i+1]
        for j, cb in enumerate(b):
            cur.append(min(prev[j+1]+1, cur[j]+1, prev[j]+(ca != cb)))
        prev = cur
    return prev[-1]
def levSim(a, b):
    if abs(len(a)-len(b)) > len(a)*0.5: return 0
    return 1 - lev(a, b)/(max(len(a), len(b)) or 1)
def dice(A, B):
    if not A or not B: return 0
    return 2*len(A & B)/(len(A)+len(B))

def prep_card(c):
    name = c.get("n") or ""; ver = c.get("v") or ""; full = (name + " " + ver).strip()
    c["_nName"] = ocrCanon(name); c["_nFull"] = ocrCanon(full)
    c["_nSq"] = c["_nName"].replace(" ", ""); c["_nFullSq"] = c["_nFull"].replace(" ", "")
    c["_tok"] = toks(name) | toks(ver)
    c["_tri"] = trigrams(ocrCanon(full))

def textScore(qn, qnSq, qtok, qtri, c):
    L = max(levSim(qn, c["_nName"]), levSim(qn, c["_nFull"]), levSim(qnSq, c["_nSq"]), levSim(qnSq, c["_nFullSq"]))
    inter = len(qtok & c["_tok"])
    union = len(qtok | c["_tok"]) or 1
    tok = 0.5*(inter/union) + 0.5*(inter/(min(len(qtok), len(c["_tok"])) or 1))
    return 0.42*L + 0.33*tok + 0.25*dice(qtri, c["_tri"])

def rankNames_py(lines, cards, k=3):
    """reusable: rank cards by OCR name candidate lines. mirrors scanner.js rankNames."""
    queries = []
    for ln in lines:
        qn = ocrCanon(ln)
        if len(qn) >= 3: queries.append((qn, qn.replace(" ", ""), toks(ln), trigrams(qn)))
    if not queries: return {"top": [], "conf": "low", "score": 0}
    best = []
    for c in cards:
        s = max((textScore(qn, qs, qt, qtr, c) for qn, qs, qt, qtr in queries), default=0)
        best.append((s, c))
    best.sort(key=lambda x: -x[0])
    top = [{"id": c["id"], "name": c.get("n") or "", "version": c.get("v") or "", "score": s} for s, c in best[:k]]
    s0 = top[0]["score"] if top else 0; s1 = top[1]["score"] if len(top) > 1 else 0
    conf = "high" if s0 >= 0.80 else "medium" if s0 >= 0.58 else "low"
    return {"top": top, "conf": conf, "score": s0, "margin": s0 - s1}

def main():
    cards = json.loads((REPO/"scanner"/"text.json").read_text(encoding="utf-8"))
    for c in cards: prep_card(c)
    files = [f for f in sorted(glob.glob(str(FLY/"*.jpg"))) if "_sheet" not in f]

    # --- OCR cache (slow once) ---
    if CACHE.exists():
        cache = json.loads(CACHE.read_text(encoding="utf-8"))
    else:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR(); cache = {}
        for f in files:
            im = Image.open(f).convert("RGB"); W, H = im.size
            # OCR a generous mid+upper region (covers character name band AND
            # action/song top title) at 4x; collect ALL text lines.
            reads = []
            for box in [(0.02, 0.04, 0.98, 0.20), (0.02, 0.50, 0.98, 0.71)]:
                crop = im.crop((int(W*box[0]), int(H*box[1]), int(W*box[2]), int(H*box[3])))
                crop = crop.resize((crop.width*4, crop.height*4), Image.LANCZOS)
                res, _ = ocr(np.asarray(crop))
                for bx, txt, sc in (res or []):
                    ys = [p[1] for p in bx]
                    reads.append({"t": txt, "h": float(max(ys)-min(ys))})
            cache[Path(f).name] = reads
            print("ocr", Path(f).name[:30])
        CACHE.write_text(json.dumps(cache), encoding="utf-8")

    # --- validate matcher on cached reads ---
    n = t1 = t3 = readok = 0
    for f in files:
        truth = re.search(r"truth-([^_]+)", Path(f).stem).group(1).replace("-", " ")
        ttok = set(w for w in normName(truth).split() if len(w) >= 2)
        reads = cache[Path(f).name]
        if not reads:
            n += 1; continue
        n += 1
        # candidate name lines: the tallest text boxes (name is biggest font)
        reads = sorted(reads, key=lambda r: -r["h"])[:3]
        rk = rankNames_py([r["t"] for r in reads], cards, 3)
        if not rk["top"]: continue
        byid = {c["id"]: c for c in cards}
        def ischar(it):
            cn = byid[it["id"]]["_tok"]; return ttok and ttok.issubset(cn)
        if ischar(rk["top"][0]): t1 += 1
        if any(ischar(it) for it in rk["top"]): t3 += 1
        # did SOME card name token from truth read?
        joined = normName(" ".join(r["t"] for r in reads))
        if any(t in joined for t in ttok if len(t) >= 4): readok += 1
    print(f"\n=== SYNTHESIS MATCHER on {n} REAL 400px crops (char-level) ===")
    print(f"  truth name read at all: {readok}/{n} ({100*readok/n:.0f}%)")
    print(f"  character top1: {t1}/{n} ({100*t1/n:.0f}%)   top3: {t3}/{n} ({100*t3/n:.0f}%)")
    print(f"  (colour-only baseline ~30%/40%; these are 400px downscales, app uses 1000px)")
    print(f"  of the cards whose name READ, char top1 = {t1}/{readok} ({100*t1/max(1,readok):.0f}%)")

if __name__ == "__main__":
    main()
