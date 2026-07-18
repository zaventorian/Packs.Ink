"""Subtitle-BAND experiment: after the name box is found, det+rec a ×2.5
upscaled strip directly below it (subtitle + type line live there). Measures
end-to-end version accuracy (rankNames + body tiebreak + hijack rescue) with
and without the band lines, against the image-verified truth table.
"""
import os, sys, json, re
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ppocr_web_sim as P
from ocr_match_validate import rankNames_py, prep_card
from bench_select_eval import (cache, cards, TRUTH, keyid, sel_old,
                               rank_versions_by_body, hijack_rescue, canon, tris)

BENCH = os.path.join(HERE, "data", "bench")
BAND_CACHE_PATH = os.path.join(BENCH, "_bandcache.json")
band_cache = json.load(open(BAND_CACHE_PATH, encoding="utf-8")) if os.path.exists(BAND_CACHE_PATH) else {}

def band_lines(fname, entry):
    if fname in band_cache: return band_cache[fname]
    out = []
    try:
        boxes = [b for b in entry.get("boxes", []) if len(b["t"].strip()) >= 2 and re.search(r"[A-Za-z]", b["t"])]
        if boxes:
            name = max(boxes, key=lambda b: b["bh"])
            img = cv2.imread(os.path.join(BENCH, fname))
            if img is not None:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                H, W = rgb.shape[:2]
                nh = name["y1"] - name["y0"]
                y0 = int(max(0, name["y1"] - 0.15 * nh))
                y1 = int(min(H, name["y1"] + 3.4 * nh))
                x0 = int(max(0, name["x0"] - 2.0 * nh))
                band = rgb[y0:y1, x0:W]
                if band.size:
                    band = cv2.resize(band, (int(band.shape[1] * 2.5), int(band.shape[0] * 2.5)))
                    for t, _bx, _bh in P.det_lines(band, "min", P.DET_SIDE):
                        if len(t.strip()) >= 2:
                            out.append(t)
    except Exception:
        pass
    band_cache[fname] = out
    return out

def run(policy_band, policy_rescue):
    stats = [0, 0, 0, 0]
    misses = []
    for fname, entry in sorted(cache.items()):
        rid = keyid(fname)
        if rid not in TRUTH or "boxes" not in entry: continue
        t_char, t_ver = TRUTH[rid]
        lines = sel_old(entry["boxes"])
        if policy_band:
            lines = lines + [l for l in band_lines(fname, entry) if l not in lines]
        r = rankNames_py(lines, cards, 6)
        top = r["top"][0] if r["top"] else None
        if not top:
            stats[3] += 1; continue
        g_char = top.get("n") or top.get("name") or ""
        g_ver = top.get("v") or top.get("version") or ""
        if policy_rescue:
            rz = hijack_rescue(g_char, lines)
            if rz is not None:
                g_char, g_ver = rz.get("n") or "", rz.get("v") or ""
        bv = rank_versions_by_body(g_char, lines)
        if bv is not None: g_ver = bv
        if g_char.lower() != t_char.lower():
            stats[2] += 1; misses.append(f"  charWRONG {rid}: {g_char} (truth {t_char})")
        elif g_ver == t_ver:
            stats[0] += 1
        else:
            stats[1] += 1; misses.append(f"  verWRONG {rid}: {g_char}-{g_ver} (truth {t_ver})")
    return stats, misses

for name, band, rescue in (("baseline", False, False), ("band", True, False), ("band+rescue", True, True)):
    stats, misses = run(band, rescue)
    print(f"{name:12s}: RIGHT {stats[0]} | wrong-ver {stats[1]} | wrong-char {stats[2]} | none {stats[3]}")
    if name == "band+rescue":
        print("\n".join(misses))
json.dump(band_cache, open(BAND_CACHE_PATH, "w"))
