"""OCR every bench rect's NAME REGION once, caching ALL det boxes with full
geometry + rec text. Selection-policy experiments (which boxes become the
identify() lines) then re-run instantly against the cache without re-OCR.

Mirrors scanner-ocr-worker.js's name read: det the upper 0.74 at min-side
DET_SIDE, rec every box. Output: data/bench/_boxcache.json
  { "<file>": {"w": W, "h": H, "boxes": [{"t","x0","y0","x1","y1","bh"}]} }
"""
import os, sys, json, glob
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ppocr_web_sim as P

BENCH = os.path.join(HERE, "data", "bench")
OUT = os.path.join(BENCH, "_boxcache.json")

cache = {}
if os.path.exists(OUT):
    cache = json.load(open(OUT, encoding="utf-8"))

files = sorted(glob.glob(os.path.join(BENCH, "*_rect.jpg")))
done = 0
for f in files:
    key = os.path.basename(f)
    if key in cache:
        continue
    img = cv2.imread(f)
    if img is None:
        cache[key] = {"err": "unreadable"}
        continue
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    H, W = rgb.shape[:2]
    region = rgb[0:int(H * 0.74), 0:W]
    try:
        x, rh, rw = P.det_preproc(region, "min", P.DET_SIDE)
        prob = P._det.run(None, {P._det_in: x})[0][0, 0]
        boxes = P.cc_boxes(prob, rh, rw)
        rows = []
        for x0, y0, x1, y1, hsrc in boxes:
            crop = region[int(y0):int(y1), int(x0):int(x1)]
            if crop.size == 0:
                continue
            txt = P.rec_one(crop)
            if len(txt.strip()) >= 1:
                rows.append({"t": txt, "x0": round(x0, 1), "y0": round(y0, 1),
                             "x1": round(x1, 1), "y1": round(y1, 1), "bh": round(hsrc, 1)})
        cache[key] = {"w": W, "h": H, "boxes": rows}
    except Exception as e:
        cache[key] = {"err": str(e)[:80]}
    done += 1
    if done % 20 == 0:
        json.dump(cache, open(OUT, "w"))
        print(f"{done} processed…", flush=True)

json.dump(cache, open(OUT, "w"))
print("cached", len(cache), "images →", OUT)
