"""
Gating-correctness check: does skipping the collector-number read when the name is
already a confident match change the top-1? Compares, on the close set:
  COMBINED = identify(name + number)           (always read the number)
  GATED    = identify(name); if source!='name' then read number + re-identify
Top-1 must be identical (the gate only skips cn when the name already decides it).

  python scripts/scanner/qa_gate_test.py [--real]
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
from qa_cn_test import name_read, cn_current
import close_identify_eval as E   # reuse identify() + colour_rank + disp


def main():
    folder = "real" if "--real" in sys.argv else "close"
    files = sorted(glob.glob(str(HERE / "data" / folder / "*.jpg")))
    diff = 0; skipped = 0
    print(f"{len(files)} photos in data/{folder}\n{'file':10} {'combined':30} {'gated':30} cn?")
    print("-" * 76)
    for f in files:
        rgb = np.asarray(Image.open(f).convert("RGB"))
        q = detect(rgb, True)[0]
        if q is None: continue
        rim = rectify(rgb, q); rimg = Image.fromarray(rim)
        if rimg.width != 1200:
            rimg = rimg.resize((1200, int(1200 * rimg.height / rimg.width)), Image.LANCZOS); rim = np.asarray(rimg)
        Hd, Wd = rim.shape[:2]
        col = E.colour_rank(rimg)
        names = name_read(rim, Hd, Wd, 0.74, 6)
        cn, _ = cn_current(rim, Hd, Wd)
        # combined: always read number
        comb_id, comb_src = E.identify(names, cn, col)
        # gated (mirrors Index.html identifyGated): name first; read number when
        # the name isn't decisive OR the character has near-tied versions (the
        # cn is the version disambiguator on a tight rectify). A cn re-identify
        # may only move the answer WITHIN the same character name.
        from ocr_match_validate import rankNames_py
        nm = rankNames_py(names, E.cards, 6)
        ns = nm["top"]
        version_tied = len(ns) >= 2 and ns[0]["name"] == ns[1]["name"] and (ns[0]["score"] - ns[1]["score"]) < 0.06
        g_id, g_src = E.identify(names, None, col)
        read_cn = "skip"
        if g_src != "name" or version_tied:
            g2_id, g2_src = E.identify(names, cn, col); read_cn = (cn or "-")
            if g_src != "name":
                g_id, g_src = g2_id, g2_src
            else:
                c2 = next((n for n in ns if n["id"] == g2_id), None)
                if c2 is not None and c2["name"] == ns[0]["name"]:
                    g_id, g_src = g2_id, g2_src
        else:
            skipped += 1
        if comb_id != g_id: diff += 1
        flag = "  <-- DIFF" if comb_id != g_id else ""
        print(f"{Path(f).stem[:8]:10} {E.disp(comb_id)[:30]:30} {E.disp(g_id)[:30]:30} {read_cn}{flag}")
    print("-" * 76)
    print(f"top-1 differs combined vs gated: {diff}/{len(files)}   (number read SKIPPED on {skipped} confident-name cards)")


if __name__ == "__main__":
    main()
