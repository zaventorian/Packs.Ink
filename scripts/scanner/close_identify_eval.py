"""
Full identify() pipeline on the close set, OLD vs NEW scanner settings:
  OLD = name top-4  + current cn ROI
  NEW = name top-6  + cn sweep (the two worker fixes this session)
Mirrors scanner.js identify() (name-primary; cn+name lock; cn soft-orders).
Prints the predicted card for each, flags where they differ.

  python scripts/scanner/close_identify_eval.py [--real]
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import descriptors as D
from real_eval2 import detect, rectify
from ocr_match_validate import prep_card, rankNames_py
from qa_cn_test import name_read, cn_current, cn_sweep

REPO = HERE.parent.parent; SCAN = REPO / "scanner"

cards = json.loads((SCAN / "text.json").read_text(encoding="utf-8"))
for c in cards: prep_card(c)
byid = {c["id"]: c for c in cards}
cnLoose = {}
for c in cards:
    if c.get("cn"):
        num = re.sub(r"\D", "", str(c["cn"]))
        if num: cnLoose.setdefault(num, []).append(c["id"])
man = json.loads((SCAN / "index.json").read_text(encoding="utf-8"))
N = man["count"]
colour = np.frombuffer((SCAN / "color.bin").read_bytes(), np.int8).astype(np.float32).reshape(N, 432)
cid_at = [m["id"] for m in man["cards"]]


def colour_rank(rim, k=12):
    qv = D.color_sig(rim); s = colour @ qv; return [cid_at[i] for i in np.argsort(-s)[:k]]


def disp(cid):
    c = byid.get(cid); return ((c.get("n") or "") + (" - " + c["v"] if c.get("v") else "")) if c else str(cid)


def identify(lines, cnNum, colRanked):
    nm = rankNames_py(lines, cards, 6)
    nameIds = [t["id"] for t in nm["top"]]
    numIds = cnLoose.get(re.sub(r"\D", "", cnNum), []) if cnNum else []
    numSet = set(numIds)
    if numIds:
        for nid in nameIds:
            if nid in numSet: return nid, "cn+name"
    if nm["conf"] == "high" and nameIds: return nameIds[0], "name"
    if numIds:
        namepos = {t["id"]: i for i, t in enumerate(nm["top"])}
        colpos = {c: i for i, c in enumerate(colRanked)}
        numIds = sorted(numIds, key=lambda x: (namepos.get(x, 99), colpos.get(x, 999)))
        return numIds[0], "cn"
    return (nameIds[0] if nameIds else (colRanked[0] if colRanked else None)), "fallback"


def main():
    folder = "real" if "--real" in sys.argv else "close"
    files = sorted(glob.glob(str(HERE / "data" / folder / "*.jpg")))
    print(f"{len(files)} photos in data/{folder}\n")
    print(f"{'file':10} {'OLD (top4 + cnCur)':32} {'NEW (top6 + sweep)':32}")
    print("-" * 78)
    ndiff = 0
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"{Path(f).stem[:8]:10} NODET"); continue
        rim = rectify(rgb, q)
        rimg = Image.fromarray(rim)
        if rimg.width != 1200:
            rimg = rimg.resize((1200, int(1200 * rimg.height / rimg.width)), Image.LANCZOS)
            rim = np.asarray(rimg)
        Hd, Wd = rim.shape[:2]
        col = colour_rank(rimg)
        n4 = name_read(rim, Hd, Wd, 0.74, 4)
        n6 = name_read(rim, Hd, Wd, 0.74, 6)
        cc, _ = cn_current(rim, Hd, Wd)
        cs, _ = cn_sweep(rim, Hd, Wd)
        old_id, old_src = identify(n4, cc, col)
        new_id, new_src = identify(n6, cs, col)
        flag = "" if old_id == new_id else "  <-- differs"
        if old_id != new_id: ndiff += 1
        print(f"{Path(f).stem[:8]:10} {(disp(old_id)+' ['+old_src+']')[:32]:32} {(disp(new_id)+' ['+new_src+']')[:32]:32}{flag}")
    print("-" * 78)
    print(f"predictions changed OLD->NEW: {ndiff}/{len(files)}")


if __name__ == "__main__":
    main()
