"""
Validate the collector-number fix on FULL-RES real photos (data/close + data/real)
— the flywheel thumbnails are 400px (cn text unreadable) so they can't validate a
fix. Here we detect+rectify the originals, upscale to 1200 wide (matching the
worker's 1200x1680 production rectify), then compare:
  - cn_current : the SHIPPED readNumber bottom-strip ROIs
  - cn_wide    : a tall lower-band pattern search (robust to a loose rectify)
and dump name-box geometry (text, height, y-centre) to design the name-bleed fix.

  python scripts/scanner/cn_compare.py            # close set
  python scripts/scanner/cn_compare.py --real     # far/loose set
  python scripts/scanner/cn_compare.py --names     # also dump name boxes
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
from qa_cn_test import parseCN, det_boxes, cn_current, cn_sweep, name_read
import re


def main():
    folder = "real" if "--real" in sys.argv else "close"
    files = sorted(glob.glob(str(HERE / "data" / folder / "*.jpg")))
    dump_names = "--names" in sys.argv
    ncur = nwide = ndet = 0
    print(f"{len(files)} photos in data/{folder}\n")
    print(f"{'file':10} {'name_read':22} {'cn_cur':>6} {'cn_swp':>7}  where")
    print("-" * 78)
    for f in files:
        stem = Path(f).stem[:8]
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None:
            print(f"{stem:10} NODET"); continue
        ndet += 1
        rim = rectify(rgb, q)
        rimg = Image.fromarray(rim)
        # upscale to 1200 wide to match the worker's production rectify resolution
        if rimg.width != 1200:
            rimg = rimg.resize((1200, int(1200 * rimg.height / rimg.width)), Image.LANCZOS)
            rim = np.asarray(rimg)
        Hd, Wd = rim.shape[:2]
        names = name_read(rim, Hd, Wd)
        n0 = names[0] if names else ""
        cur, _cw = cn_current(rim, Hd, Wd)
        wide, wwhere = cn_sweep(rim, Hd, Wd)
        if cur: ncur += 1
        if wide: nwide += 1
        print(f"{stem:10} {n0[:22]:22} {(cur or '-'):>6} {(wide or '-'):>7}  {wwhere or ''}")
        if dump_names:
            upper = rim[0:int(Hd * 0.74), 0:Wd]
            boxes = det_boxes(upper)
            cand = [(t, by1 - by0, (by0 + by1) / 2 / Hd) for (bx0, by0, bx1, by1, t) in boxes
                    if len(t.strip()) >= 2 and re.search(r"[A-Za-z]", t)]
            cand.sort(key=lambda r: -r[1])
            for t, h, yc in cand[:6]:
                print(f"        box h={h:5.0f} yc={yc:.2f}  '{t[:30]}'")
    n = len(files)
    print("-" * 78)
    print(f"detected           : {ndet}/{n}")
    print(f"cn CURRENT (shipped): {ncur}/{n} ({100*ncur//max(1,n)}%)   of detected: {100*ncur//max(1,ndet)}%")
    print(f"cn SWEEP  (proposed): {nwide}/{n} ({100*nwide//max(1,n)}%)   of detected: {100*nwide//max(1,ndet)}%")


if __name__ == "__main__":
    main()
