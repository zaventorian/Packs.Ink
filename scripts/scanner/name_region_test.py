"""
Does tightening the name det region (0.74 -> 0.66) reduce rules-text bleed without
losing real title reads? Run on the full-res close set; print name@0.74 vs name@0.66
and the non-empty count for each.

  python scripts/scanner/name_region_test.py [--real]
"""
from __future__ import annotations
import glob, sys
from pathlib import Path
import numpy as np
from PIL import Image
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from real_eval2 import detect, rectify
from qa_cn_test import name_read

folder = "real" if "--real" in sys.argv else "close"
files = sorted(glob.glob(str(HERE / "data" / folder / "*.jpg")))
n74 = n66 = same = 0
print(f"{len(files)} photos in data/{folder}\n{'file':10} {'name@0.74':24} {'name@0.66':24}")
print("-" * 64)
for f in files:
    rgb = np.asarray(Image.open(f).convert("RGB"))
    q = detect(rgb, True)[0]
    if q is None:
        continue
    rim = rectify(rgb, q)
    rimg = Image.fromarray(rim)
    if rimg.width != 1200:
        rimg = rimg.resize((1200, int(1200 * rimg.height / rimg.width)), Image.LANCZOS)
        rim = np.asarray(rimg)
    Hd, Wd = rim.shape[:2]
    a = name_read(rim, Hd, Wd, 0.74, 6)
    b = name_read(rim, Hd, Wd, 0.66, 6)
    a0, b0 = (a[0] if a else ""), (b[0] if b else "")
    if a0: n74 += 1
    if b0: n66 += 1
    if a0 == b0: same += 1
    flag = "" if a0 == b0 else "  <-- differs"
    print(f"{Path(f).stem[:8]:10} {a0[:24]:24} {b0[:24]:24}{flag}")
print("-" * 64)
print(f"non-empty top-1  @0.74: {n74}   @0.66: {n66}   identical top-1: {same}/{len(files)}")
