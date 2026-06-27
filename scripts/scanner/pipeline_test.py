"""
End-to-end test on the CLOSE-framed photos (the target workflow): detect ->
rectify 1000x1400 -> OCR name (tallest font) + collector number -> the parallel-
vote identify (collector-number backbone + name + colour). Ports scanner.js
identify(). Saves a contact sheet (rectified card + prediction) to eyeball.

  python scripts/scanner/pipeline_test.py "C:/Users/zaven/Downloads/card photos"
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import descriptors as D
from real_eval2 import detect, rectify
from ocr_match_validate import prep_card, rankNames_py, normName, ocrCanon

REPO = HERE.parent.parent
OLD = {"167f2075","193f94de","1ce4898e","1dfccf3c","20b4d242","264fa11e","5567f7b2",
       "71f4188b","7221bd8c","9b4c6a02","9e6acc7c","a6ae22bf","aa32a7e1","bfb32821",
       "c2fc1c0f","d7721408","ea620437","f4e177ee","fc3a09fb"}


def main():
    folder = sys.argv[1] if len(sys.argv) > 1 else str(HERE/"data"/"real")
    only_new = "--all" not in sys.argv
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    cards = json.loads((REPO/"scanner"/"text.json").read_text(encoding="utf-8"))
    for c in cards: prep_card(c)
    byid = {c["id"]: c for c in cards}
    cnLoose = {}
    for c in cards:
        if c.get("cn"):
            num = re.sub(r"\D", "", str(c["cn"]))
            if num: cnLoose.setdefault(num, []).append(c["id"])
    # colour ref (int8 shipped index)
    man = json.loads((REPO/"scanner"/"index.json").read_text(encoding="utf-8"))
    cmeta = man["cards"]; N = man["count"]
    colour = np.frombuffer((REPO/"scanner"/"color.bin").read_bytes(), np.int8).astype(np.float32).reshape(N, 432)
    cid_at = [m["id"] for m in cmeta]

    def colour_rank(rim, k=12):
        qv = D.color_sig(rim); s = colour @ qv; o = np.argsort(-s)[:k]
        return [cid_at[i] for i in o]

    def name_disp(cid):
        c = byid.get(cid); return (c.get("n") or "") + (" - " + c["v"] if c and c.get("v") else "") if c else cid

    def identify(lines, cnNum, colRanked):
        nm = rankNames_py(lines, cards, 6)
        nameIds = [t["id"] for t in nm["top"]]
        numIds = cnLoose.get(re.sub(r"\D","",cnNum), []) if cnNum else []
        numSet = set(numIds)
        # 1. number + name agree -> lock
        if numIds:
            for nid in nameIds:
                if nid in numSet:
                    return nid, "cn+name", "high", nm
        # 2. confident name
        if nm["conf"] == "high" and nameIds:
            return nameIds[0], "name", "high", nm
        # 3. number candidates ordered by name then colour
        if numIds:
            colpos = {c: i for i, c in enumerate(colRanked)}
            namepos = {t["id"]: i for i, t in enumerate(nm["top"])}
            numIds = sorted(numIds, key=lambda x: (namepos.get(x, 99), colpos.get(x, 999)))
            return numIds[0], "cn", ("medium" if len(numIds) <= 2 else "low"), nm
        # 4. name/colour
        return (nameIds[0] if nameIds else (colRanked[0] if colRanked else None)), "fallback", nm["conf"], nm

    files = sorted(glob.glob(str(Path(folder)/"*.jpg")))
    if only_new: files = [f for f in files if Path(f).stem[:8] not in OLD]
    print(f"{len(files)} photos\n")
    OUT = HERE/"data"/"close_out"; OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    nlock = ncn = 0
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"  {Path(f).stem[:8]}  NODET"); rows.append((Path(f).stem[:8], None, "NODET", "", "")); continue
        rim = Image.fromarray(rectify(rgb, q))
        if rim.width < 700: rim = rim.resize((1000, int(1000*rim.height/rim.width)), Image.LANCZOS)
        W, Hh = rim.size
        # name: tallest-font lines from the whole upper card
        res, _ = ocr(np.asarray(rim.crop((0, 0, W, int(Hh*0.74)))))
        lines = sorted([( (max(p[1] for p in b)-min(p[1] for p in b)), t) for b, t, _ in (res or []) if len(t.strip())>=2], key=lambda x:-x[0])
        namelines = [t for _, t in lines[:3]]
        # collector number
        cres, _ = ocr(np.asarray(rim.crop((0, int(Hh*0.90), int(W*0.55), int(Hh*0.99))).resize((int(W*0.55*4), int(Hh*0.09*4)), Image.LANCZOS)))
        cntxt = " ".join(t for _, t, _ in (cres or []))
        m = re.search(r"(\d{1,3})\s*[/Il|]\s*(\d{2,3})", cntxt)
        cnNum = m.group(1) if m else None
        if cnNum: ncn += 1
        cid, src, conf, nm = identify(namelines, cnNum, colour_rank(rim))
        if src == "cn+name": nlock += 1
        print(f"  {Path(f).stem[:8]}  -> {name_disp(cid)[:34]:34} [{src} {conf}]  cn={cnNum or '-':4} name:'{(namelines[0] if namelines else '')[:20]}'")
        rows.append((Path(f).stem[:8], rim, name_disp(cid), src, cnNum or ""))
    n = len(files)
    print(f"\ncollector number read: {ncn}/{n} ({100*ncn//max(1,n)}%)   number+name LOCK: {nlock}/{n} ({100*nlock//max(1,n)}%)")
    # contact sheet
    cols = 5; rws = (len(rows)+cols-1)//cols; tw, th = 200, 320
    sheet = Image.new("RGB", (cols*tw, rws*th), (15,15,15)); dd = ImageDraw.Draw(sheet)
    for i, (nm8, rim, disp, src, cn) in enumerate(rows):
        x = (i%cols)*tw; y = (i//cols)*th
        if rim is not None:
            im = rim.copy(); im.thumbnail((tw-8, th-48)); sheet.paste(im, (x+4, y+4))
        dd.text((x+6, y+th-42), nm8+" "+("["+src+"]" if src else ""), fill=(120,255,120) if src=="cn+name" else (255,220,120))
        dd.text((x+6, y+th-28), disp[:26] if disp else "—", fill=(255,255,255))
        dd.text((x+6, y+th-14), "cn="+cn, fill=(150,200,255))
    sheet.save(OUT/"_close.jpg", quality=88)
    print("contact sheet ->", OUT/"_close.jpg")


if __name__ == "__main__":
    main()
