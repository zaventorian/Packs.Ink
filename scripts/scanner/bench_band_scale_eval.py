"""Subtitle-band DET-SCALE sweep: the shipped band runs det on the ×2.5 strip
with limit_type=min side=736 — for a short-wide strip that means an EXTRA
~1.4-2.7× upscale on top of the ×2.5 (det input ~3-5M px, the reason nameMs
went 1.8s→7.3s median on-phone in batch 6). This measures whether the band's
version-accuracy win survives cheaper det scales:
  min736  — shipped config (baseline)
  nat     — no forced resize (ratio 1): det sees the ×2.5 strip as-is
  max1600 — long side capped at 1600 (downscale-only)
Prints version accuracy on the image-verified truth table + mean det pixels.
"""
import os, sys, json, re
import cv2
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ppocr_web_sim as P
from ocr_match_validate import rankNames_py
from bench_select_eval import (cache, cards, TRUTH, keyid, sel_old,
                               rank_versions_by_body)

BENCH = os.path.join(HERE, "data", "bench")

CONFIGS = {
    "min736": ("min", P.DET_SIDE),
    "nat": ("min", 1),          # ratio stays 1 -> natural x2.5 strip scale
    "max1600": ("max", 1600),
}

def band_strip(fname, entry):
    boxes = [b for b in entry.get("boxes", []) if len(b["t"].strip()) >= 2 and re.search(r"[A-Za-z]", b["t"])]
    if not boxes:
        return None
    name = max(boxes, key=lambda b: b["bh"])
    img = cv2.imread(os.path.join(BENCH, fname))
    if img is None:
        return None
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    H, W = rgb.shape[:2]
    nh = name["y1"] - name["y0"]
    y0 = int(max(0, name["y1"] - 0.15 * nh))
    y1 = int(min(H, name["y1"] + 3.4 * nh))
    x0 = int(max(0, name["x0"] - 2.0 * nh))
    band = rgb[y0:y1, x0:W]
    if not band.size:
        return None
    return cv2.resize(band, (int(band.shape[1] * 2.5), int(band.shape[0] * 2.5)))

def det_px(shape, limit_type, side):
    h, w = shape[:2]
    if limit_type == "max":
        ratio = side / max(w, h) if max(w, h) > side else 1
    else:
        ratio = side / min(w, h) if min(w, h) < side else 1
    rw = max(32, round(w * ratio / 32) * 32)
    rh = max(32, round(h * ratio / 32) * 32)
    return rw * rh

results = {k: [0, 0, 0, 0] for k in CONFIGS}   # right, wrong-ver, wrong-char, none
px = {k: [] for k in CONFIGS}
miss = {k: [] for k in CONFIGS}
rows = 0
for fname, entry in sorted(cache.items()):
    rid = keyid(fname)
    if rid not in TRUTH or "boxes" not in entry:
        continue
    strip = band_strip(fname, entry)
    rows += 1
    t_char, t_ver = TRUTH[rid]
    base_lines = sel_old(entry["boxes"])
    for cfg, (lt, side) in CONFIGS.items():
        lines = list(base_lines)
        if strip is not None:
            px[cfg].append(det_px(strip.shape, lt, side))
            try:
                for t, _bx, _bh in P.det_lines(strip, lt, side):
                    if len(t.strip()) >= 2 and t not in lines:
                        lines.append(t)
            except Exception:
                pass
        r = rankNames_py(lines, cards, 6)
        top = r["top"][0] if r["top"] else None
        if not top:
            results[cfg][3] += 1
            continue
        g_char = top.get("n") or top.get("name") or ""
        g_ver = top.get("v") or top.get("version") or ""
        bv = rank_versions_by_body(g_char, lines)
        if bv is not None:
            g_ver = bv
        if g_char.lower() != t_char.lower():
            results[cfg][2] += 1
            miss[cfg].append(f"charWRONG {rid}: {g_char} (truth {t_char})")
        elif g_ver == t_ver:
            results[cfg][0] += 1
        else:
            results[cfg][1] += 1
            miss[cfg].append(f"verWRONG {rid}: {g_char}-{g_ver} (truth {t_ver})")

print(f"rows evaluated: {rows}")
for cfg in CONFIGS:
    r = results[cfg]
    mp = (sum(px[cfg]) / len(px[cfg]) / 1e6) if px[cfg] else 0
    print(f"{cfg:8s}: RIGHT {r[0]:2d} | wrong-ver {r[1]:2d} | wrong-char {r[2]:2d} | none {r[3]} | mean det {mp:.2f}Mpx")
for cfg in CONFIGS:
    if cfg == "min736":
        continue
    base = set(miss["min736"]) if miss["min736"] else set()
    delta = [m for m in miss[cfg] if m not in base]
    if delta:
        print(f"-- {cfg} regressions vs min736:")
        for m in delta:
            print("   ", m)
