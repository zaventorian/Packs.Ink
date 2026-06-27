"""
De-risk the PP-OCRv3 -> onnxruntime-web port BEFORE writing the JS worker.

This runs raw onnxruntime (NOT RapidOCR) with the EXACT preprocessing /
postprocessing the JS worker will use:
  - det preproc: resize min-side->736, round/32, (x/255 - mean)/std, NCHW
  - det postproc: threshold 0.3 -> dilate -> connected-components AXIS-ALIGNED
    boxes (NO contours/minAreaRect) -> mean-prob>=0.5 -> merge same-line
  - name: det the upper 0.74 of the rectified card, take the 3 tallest boxes, rec each
  - number: rec-ONLY on the bottom-left ROI strip (no det)
  - rec preproc: H=48, (x/255-0.5)/0.5, NCHW ; CTC greedy decode w/ the embedded dict
then runs the same identify() as pipeline_test.py.

GOAL: prediction PARITY with pipeline_test.py (rapidocr det+rec, eyeball-validated
~94% character on the 17 close photos). If my CC postproc matches rapidocr's
predictions, the JS port is de-risked.

  python scripts/scanner/ppocr_web_sim.py            # 17 close photos
  python scripts/scanner/ppocr_web_sim.py --all      # all 36
"""
from __future__ import annotations
import glob, json, re, sys
from pathlib import Path
import numpy as np
import cv2
import onnxruntime as ort
from PIL import Image
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
import descriptors as D
from real_eval2 import detect, rectify
from ocr_match_validate import prep_card, rankNames_py, normName, ocrCanon

REPO = HERE.parent.parent
SCAN = REPO / "scanner"
OLD = {"167f2075","193f94de","1ce4898e","1dfccf3c","20b4d242","264fa11e","5567f7b2",
       "71f4188b","7221bd8c","9b4c6a02","9e6acc7c","a6ae22bf","aa32a7e1","bfb32821",
       "c2fc1c0f","d7721408","ea620437","f4e177ee","fc3a09fb"}

DET_MEAN = np.array([0.485, 0.456, 0.406], np.float32)
DET_STD  = np.array([0.229, 0.224, 0.225], np.float32)
DET_THRESH, DET_BOX_THRESH, DET_SIDE = 0.3, 0.5, 736

_det = ort.InferenceSession(str(SCAN/"ch_PP-OCRv3_det_infer.onnx"), providers=["CPUExecutionProvider"])
_rec = ort.InferenceSession(str(SCAN/"ch_PP-OCRv3_rec_infer.onnx"), providers=["CPUExecutionProvider"])
_det_in = _det.get_inputs()[0].name
_rec_in = _rec.get_inputs()[0].name
_keys = (SCAN/"ppocr_keys_v1.txt").read_text(encoding="utf-8").split("\n")
DICT = ["blank"] + _keys + [" "]          # 6625 classes, index 0 = blank


# ---------- det ----------
def det_preproc(rgb, limit_type="min", side=DET_SIDE):
    h, w = rgb.shape[:2]
    if limit_type == "max":
        # cap the LONG side (for thin strips, so min-resize doesn't explode width)
        ratio = side / max(h, w) if max(h, w) > side else 1.0
    else:
        # limit_type='min': only upscale if the SHORT side is below the limit
        ratio = side / min(h, w) if min(h, w) < side else 1.0
    rh = int(round(h * ratio / 32) * 32) or 32
    rw = int(round(w * ratio / 32) * 32) or 32
    img = cv2.resize(rgb, (rw, rh))
    x = (img.astype(np.float32) / 255.0 - DET_MEAN) / DET_STD
    x = x.transpose(2, 0, 1)[None]                    # NCHW
    return x.astype(np.float32), rh / h, rw / w


def cc_boxes(prob, ratio_h, ratio_w):
    """connected-components axis-aligned boxes from the DB prob map. Returns
    [(x0,y0,x1,y1,height_in_src)] in SOURCE coords. No contours/minAreaRect —
    the card is rectified so text is axis-aligned."""
    H, W = prob.shape
    binm = (prob > DET_THRESH).astype(np.uint8)
    binm = cv2.dilate(binm, np.ones((2, 2), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(binm, connectivity=8)
    boxes = []
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if ww <= 3 or hh <= 3:
            continue
        # box score = mean prob over the component's bbox (rapidocr box_score_fast)
        sub = prob[y:y+hh, x:x+ww]
        if sub.mean() < DET_BOX_THRESH:
            continue
        # unclip approx: small proportional pad (rapidocr unclip_ratio=1.6 ~ a few px)
        pad = max(1, int(hh * 0.2))
        x0 = max(0, x - pad); y0 = max(0, y - pad)
        x1 = min(W, x + ww + pad); y1 = min(H, y + hh + pad)
        boxes.append([x0, y0, x1, y1])
    # merge boxes on the same text line (vertical overlap + small horizontal gap)
    boxes = merge_lines(boxes)
    out = []
    for x0, y0, x1, y1 in boxes:
        out.append((x0/ratio_w, y0/ratio_h, x1/ratio_w, y1/ratio_h, (y1-y0)/ratio_h))
    return out


def merge_lines(boxes):
    boxes = sorted(boxes, key=lambda b: (b[1], b[0]))
    merged = []
    for b in boxes:
        hit = None
        for m in merged:
            # vertical overlap fraction vs the shorter box
            ov = min(b[3], m[3]) - max(b[1], m[1])
            minh = min(b[3]-b[1], m[3]-m[1]) or 1
            if ov / minh > 0.5:
                gap = max(b[0], m[0]) - min(b[2], m[2])
                if gap < 0.6 * minh:            # close horizontally -> same line
                    hit = m; break
        if hit:
            hit[0] = min(hit[0], b[0]); hit[1] = min(hit[1], b[1])
            hit[2] = max(hit[2], b[2]); hit[3] = max(hit[3], b[3])
        else:
            merged.append(list(b))
    return merged


# ---------- rec ----------
def rec_one(crop_rgb):
    h, w = crop_rgb.shape[:2]
    if h < 2 or w < 2:
        return ""
    tw = max(8, int(round(48 * w / h)))
    img = cv2.resize(crop_rgb, (tw, 48)).astype(np.float32)
    x = ((img / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)[None].astype(np.float32)
    logits = _rec.run(None, {_rec_in: x})[0][0]        # [T, 6625]
    idx = logits.argmax(1)
    out, prev = [], 0
    for t in idx:
        if t != 0 and t != prev and t < len(DICT):
            out.append(DICT[t])
        prev = t
    return "".join(out)


def det_lines(rgb, limit_type="min", side=DET_SIDE):
    """det the image, rec each box -> [(text, x0, height)]."""
    x, rh, rw = det_preproc(rgb, limit_type, side)
    prob = _det.run(None, {_det_in: x})[0][0, 0]       # [H, W]
    boxes = cc_boxes(prob, rh, rw)
    res = []
    for x0, y0, x1, y1, hsrc in boxes:
        crop = rgb[int(y0):int(y1), int(x0):int(x1)]
        if crop.size == 0:
            continue
        txt = rec_one(crop)
        if len(txt.strip()) >= 1:
            res.append((txt, x0, hsrc))
    return res


def read_number(rim, Hd, Wd):
    """det+rec the bottom-left collector-number ROI (upscaled). Mirrors the
    validated cn_roi_tune winner ('low .96-1.0 x5' -> 64%): crop, upscale x5, det
    with limit_type='min' 736, rec each box left-to-right, regex "147/204"->"147"."""
    for (y0, y1, x1, up) in [(0.955, 1.0, 0.50, 5), (0.93, 1.0, 0.60, 5)]:
        strip = rim[int(Hd*y0):int(Hd*y1), 0:int(Wd*x1)]
        if strip.size == 0:
            continue
        strip = cv2.resize(strip, (strip.shape[1]*up, strip.shape[0]*up), interpolation=cv2.INTER_CUBIC)
        lines = det_lines(strip, "min", DET_SIDE)
        # left-to-right so "147/204" reads in order even if det split it
        txt = " ".join(t for t, x0, h in sorted(lines, key=lambda r: r[1]))
        m = re.search(r"(\d{1,3})\s*[/Il|1]\s*(\d{2,3})", txt)
        if m:
            return m.group(1)
    return None


# ---------- identify (mirror pipeline_test.py) ----------
def main():
    cards = json.loads((SCAN/"text.json").read_text(encoding="utf-8"))
    for c in cards: prep_card(c)
    byid = {c["id"]: c for c in cards}
    cnLoose = {}
    for c in cards:
        if c.get("cn"):
            num = re.sub(r"\D", "", str(c["cn"]))
            if num: cnLoose.setdefault(num, []).append(c["id"])
    man = json.loads((SCAN/"index.json").read_text(encoding="utf-8"))
    N = man["count"]
    colour = np.frombuffer((SCAN/"color.bin").read_bytes(), np.int8).astype(np.float32).reshape(N, 432)
    cid_at = [m["id"] for m in man["cards"]]

    def colour_rank(rim, k=12):
        qv = D.color_sig(rim); s = colour @ qv; return [cid_at[i] for i in np.argsort(-s)[:k]]

    def name_disp(cid):
        c = byid.get(cid); return ((c.get("n") or "") + (" - " + c["v"] if c.get("v") else "")) if c else str(cid)

    def identify(lines, cnNum, colRanked):
        nm = rankNames_py(lines, cards, 6)
        nameIds = [t["id"] for t in nm["top"]]
        numIds = cnLoose.get(re.sub(r"\D","",cnNum), []) if cnNum else []
        numSet = set(numIds)
        if numIds:
            for nid in nameIds:
                if nid in numSet: return nid, "cn+name", "high"
        if nm["conf"] == "high" and nameIds: return nameIds[0], "name", "high"
        if numIds:
            namepos = {t["id"]: i for i, t in enumerate(nm["top"])}
            colpos = {c: i for i, c in enumerate(colRanked)}
            numIds = sorted(numIds, key=lambda x: (namepos.get(x, 99), colpos.get(x, 999)))
            return numIds[0], "cn", ("medium" if len(numIds) <= 2 else "low")
        return (nameIds[0] if nameIds else (colRanked[0] if colRanked else None)), "fallback", nm["conf"]

    folder = HERE/"data"/"close"
    files = sorted(glob.glob(str(folder/"*.jpg")))
    if "--all" not in sys.argv:
        files = [f for f in files if Path(f).stem[:8] not in OLD]
    print(f"{len(files)} photos (PP-OCRv3 raw onnxruntime + CC postproc)\n")
    preds = {}
    ncn = nlock = 0
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"  {Path(f).stem[:8]}  NODET"); continue
        rim = rectify(rgb, q)
        rimg = Image.fromarray(rim)
        if rimg.width < 700:
            rimg = rimg.resize((1000, int(1000*rimg.height/rimg.width)), Image.LANCZOS)
            rim = np.asarray(rimg)
        Wd, Hd = rimg.size
        # name: det the upper 0.74, tallest 3 boxes that look like a NAME
        # (>=2 chars AND contain a letter — excludes the tall cost/lore digits)
        upper = rim[0:int(Hd*0.74), 0:Wd]
        cand = [(t, h) for t, _x, h in det_lines(upper)
                if len(t.strip()) >= 2 and re.search(r"[A-Za-z]", t)]
        cand.sort(key=lambda r: -r[1])
        namelines = [t for t, _h in cand[:3]]
        # number: det+rec the bottom-left ROI (upscaled) -> the version lever
        cnNum = read_number(rim, Hd, Wd)
        if cnNum: ncn += 1
        cid, src, conf = identify(namelines, cnNum, colour_rank(rimg))
        if src == "cn+name": nlock += 1
        preds[Path(f).stem[:8]] = name_disp(cid)
        print(f"  {Path(f).stem[:8]}  -> {name_disp(cid)[:34]:34} [{src} {conf}]  cn={cnNum or '-':4} name:'{(namelines[0] if namelines else '')[:20]}'")
    n = len(files)
    print(f"\ncollector number read: {ncn}/{n} ({100*ncn//max(1,n)}%)   number+name LOCK: {nlock}/{n} ({100*nlock//max(1,n)}%)")
    (HERE/"data"/"_websim_preds.json").write_text(json.dumps(preds, indent=0), encoding="utf-8")
    print("preds ->", HERE/"data"/"_websim_preds.json")


if __name__ == "__main__":
    main()
