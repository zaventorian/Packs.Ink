"""
Calibrate the name-confidence rule on REAL field reads (the fix for the scanner
"doesn't trust its own correct answers" problem).

Field finding (21 QA debug snaps, 2026-06-28..30): the name matcher's top-1 was
right on nearly every snap that had any OCR, at scores 0.37-0.50 — but the shipped
rule (high>=0.80 / medium>=0.58, ABSOLUTE score only) labeled them low/medium, so
identify() ran the dead-weight collector-number read (0/21 field read rate,
~1.2-1.5s) and ambient mode never set the text lock (the badge cycling).

This script re-OCRs every labeled real-phone image with the WORKER-EXACT PP-OCR
name read (qa_cn_test.name_read), then grid-searches confidence rules that use
  s0        = top-1 score
  marginChar= s0 - best score among cards of a DIFFERENT character name
  consensus = how many of the top-4 share top-1's character name
and reports precision/coverage per rule. The winner ships in scanner.js rankNames.

Data: scripts/scanner/data/flywheel/*.jpg  (truth in filename)
      scripts/scanner/data/qa/qa_<id>.jpg  (truth in qa_cn_test.TRUTH + additions)

  python scripts/scanner/conf_calibration.py [--refresh]
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

from ocr_match_validate import prep_card, textScore, ocrCanon, toks, normName
from qa_cn_test import name_read, TRUTH as QA_TRUTH

REPO = HERE.parent.parent
CACHE = HERE / "data" / "_name_cache_worker.json"

QA_TRUTH = dict(QA_TRUTH)
QA_TRUTH[100] = "Julieta's Arepas"
QA_TRUTH[101] = "Amazu's Inkcaster"
# 102 = art-box misdetection, card unknown -> excluded

cards = json.loads((REPO / "scanner" / "text.json").read_text(encoding="utf-8"))
for c in cards: prep_card(c)


def rank_full(lines, k=12):
    """rankNames mirror returning the top-k with scores (not conf)."""
    queries = []
    for ln in lines:
        qn = ocrCanon(ln)
        if len(qn) >= 3: queries.append((qn, qn.replace(" ", ""), toks(ln), trigrams(qn)))
    if not queries: return []
    best = []
    for c in cards:
        s = max((textScore(qn, qs, qt, qtr, c) for qn, qs, qt, qtr in queries), default=0)
        best.append((s, c))
    best.sort(key=lambda x: -x[0])
    return [(s, c) for s, c in best[:k]]


def trigrams(s):
    s = "  " + s.replace(" ", "") + "  "
    return set(s[i:i+3] for i in range(len(s)-2))


def stats_of(ranked):
    """(s0, marginChar, consensus4, top_card) from a rank_full list."""
    if not ranked: return None
    s0, c0 = ranked[0]
    n0 = normName(c0.get("n") or "")
    marginChar = s0  # if no different-name card in top-12, margin is huge
    for s, c in ranked[1:]:
        if normName(c.get("n") or "") != n0:
            marginChar = s0 - s
            break
    consensus = sum(1 for s, c in ranked[:4] if normName(c.get("n") or "") == n0)
    return s0, marginChar, consensus, c0


def truth_ok(truth, card):
    """CHARACTER-level correctness (the conf rule is character confidence by
    design — version is colour/cn/tap's job). The flywheel filename slug mangles
    apostrophes to spaces and appends '---<version>', so compare the space-squashed
    character part against the card's name (equality or near-equality)."""
    from ocr_match_validate import levSim
    tchar = normName(truth.split("---")[0].replace("   ", "|").split("|")[0]).replace(" ", "")
    pchar = normName(card.get("n") or "").replace(" ", "")
    if not tchar or not pchar: return False
    return tchar == pchar or levSim(tchar, pchar) >= 0.85


def collect():
    if CACHE.exists() and "--refresh" not in sys.argv:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    samples = []
    # flywheel (truth in filename)
    for f in sorted(glob.glob(str(HERE / "data" / "flywheel" / "2026*.jpg"))):
        m = re.search(r"truth-([^_]+)", Path(f).stem)
        if not m: continue
        truth = m.group(1).replace("-", " ").strip()
        if truth in ("unknown", "—", ""): continue
        rim = np.asarray(Image.open(f).convert("RGB"))
        H, W = rim.shape[:2]
        lines = name_read(rim, H, W, 0.74, 6)
        samples.append({"src": Path(f).name, "truth": truth, "lines": lines})
        print("ocr", Path(f).name[:60])
    # QA snaps (truth map)
    for f in sorted(glob.glob(str(HERE / "data" / "qa" / "qa_*.jpg"))):
        cid = int(Path(f).stem.split("_")[1])
        if cid not in QA_TRUTH: continue
        rim = np.asarray(Image.open(f).convert("RGB"))
        H, W = rim.shape[:2]
        lines = name_read(rim, H, W, 0.74, 6)
        samples.append({"src": Path(f).name, "truth": QA_TRUTH[cid], "lines": lines})
        print("ocr", Path(f).name)
    CACHE.write_text(json.dumps(samples), encoding="utf-8")
    return samples


RULES = {
    # name: fn(s0, marginChar, consensus) -> "high" | "medium" | "low"
    "OLD (abs only)": lambda s0, mc, cn: "high" if s0 >= 0.80 else "medium" if s0 >= 0.58 else "low",
    # FINAL = what ships in scanner.js rankNames (2026-07-10 calibration):
    # 63 field reads -> OLD: 6 high / 0 wrong; FINAL: 54 high / 0 wrong.
    # wrong top-1s max out at s0=0.321, mc=0.069 -> buffers of ~0.04 s0 / 0.03 mc.
    "FINAL (ships)":  lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.42 and mc >= 0.10) or (s0 >= 0.36 and mc >= 0.15)) else ("medium" if (s0 >= 0.34 and mc >= 0.05) else "low"),
    "A s>=.45&m>=.12": lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.45 and mc >= 0.12) or (s0 >= 0.40 and cn >= 4 and mc >= 0.10)) else ("medium" if (s0 >= 0.40 and mc >= 0.05) else "low"),
    "B s>=.42&m>=.10": lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.42 and mc >= 0.10) or (s0 >= 0.38 and cn >= 4 and mc >= 0.10)) else ("medium" if (s0 >= 0.38 and mc >= 0.05) else "low"),
    "C s>=.40&m>=.15": lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.40 and mc >= 0.15) or (s0 >= 0.36 and cn >= 4 and mc >= 0.12)) else ("medium" if (s0 >= 0.36 and mc >= 0.05) else "low"),
    "D s>=.35&m>=.15": lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.35 and mc >= 0.15) or (s0 >= 0.33 and cn >= 4 and mc >= 0.12)) else ("medium" if (s0 >= 0.33 and mc >= 0.04) else "low"),
    "E s>=.38&m>=.13": lambda s0, mc, cn: "high" if (s0 >= 0.72 or (s0 >= 0.38 and mc >= 0.13) or (s0 >= 0.35 and cn >= 4 and mc >= 0.10)) else ("medium" if (s0 >= 0.35 and mc >= 0.04) else "low"),
}


def main():
    samples = collect()
    evald = []
    for s in samples:
        ranked = rank_full(s["lines"])
        st = stats_of(ranked)
        if st is None:
            evald.append({**s, "s0": 0, "mc": 0, "cons": 0, "ok": False, "pred": None})
            continue
        s0, mc, cons, c0 = st
        evald.append({**s, "s0": s0, "mc": mc, "cons": cons,
                      "ok": truth_ok(s["truth"], c0),
                      "pred": (c0.get("n") or "") + (" - " + c0["v"] if c0.get("v") else "")})
    n = len(evald)
    read = [e for e in evald if e["s0"] > 0]
    okall = sum(1 for e in read if e["ok"])
    print(f"\n{n} labeled field images; {len(read)} produced a name read")
    print(f"name-matcher top-1 char accuracy on reads: {okall}/{len(read)} ({100*okall/max(1,len(read)):.0f}%)\n")

    hdr = f"{'rule':18} {'HIGH n':>7} {'HIGH ok':>8} {'HIGH WRONG':>10} {'prec%':>6} | {'MED n':>6} {'MED ok':>7} {'prec%':>6}"
    print(hdr); print("-" * len(hdr))
    for name, fn in RULES.items():
        hi = [e for e in read if fn(e["s0"], e["mc"], e["cons"]) == "high"]
        md = [e for e in read if fn(e["s0"], e["mc"], e["cons"]) == "medium"]
        hok = sum(1 for e in hi if e["ok"]); mok = sum(1 for e in md if e["ok"])
        print(f"{name:18} {len(hi):>7} {hok:>8} {len(hi)-hok:>10} {100*hok/max(1,len(hi)):>5.0f}% | {len(md):>6} {mok:>7} {100*mok/max(1,len(md)):>5.0f}%")

    # show the wrong-HIGH cases for the candidate rules (the failure to stare at)
    for name, fn in RULES.items():
        if name.startswith("OLD"): continue
        bad = [e for e in read if fn(e["s0"], e["mc"], e["cons"]) == "high" and not e["ok"]]
        if bad:
            print(f"\nWRONG-HIGH under {name}:")
            for e in bad:
                print(f"  {e['src'][:52]:52} truth={e['truth'][:24]:24} pred={e['pred'][:30]:30} s0={e['s0']:.3f} mc={e['mc']:.3f} cons={e['cons']} lines={e['lines'][:3]}")


if __name__ == "__main__":
    main()
