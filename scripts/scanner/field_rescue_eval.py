"""Flavor-hijack rescue on RECORDED FIELD OCR lines (all scan_samples qa-snaps).

The offline det lines were too sparse for the rescue to ever fire; the field's
richer reads carry the body evidence. This replays hijack_rescue over every
field row's recorded ocrLines with the row's own top-guess character, and
reports (a) fires on the known hijack rows (truth known), (b) fires on rows
whose guess was verified CORRECT (false fires — the primary metric).

Usage: python scripts/scanner/field_rescue_eval.py <field_corpus.json path>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bench_select_eval import hijack_rescue, TRUTH  # noqa: E402  (import runs its eval prints once)

corpus_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "field_corpus.json")
rows = json.load(open(corpus_path, encoding="utf-8"))

# rows whose guess is KNOWN correct: bench TRUTH ids where the guess matched +
# every high-conf row (proxy — batch-6 audit: 3/72 high rows were wrong, so a
# fire on a high row is ~96% likely a false fire; flag for eyeball either way).
fires = []
for r in rows:
    top = r.get("top") or {}
    ocr = r.get("ocr") or []
    ch = top.get("name") or ""
    if not ch or len(ocr) < 1:
        continue
    try:
        rz = hijack_rescue(ch, ocr)
    except Exception:
        rz = None
    if rz is None:
        continue
    fires.append({
        "id": r["id"], "build": r.get("build"), "conf": r.get("conf"), "src": r.get("src"),
        "guess": (ch + " - " + (top.get("version") or "")).strip(" -"),
        "rescueTo": ((rz.get("n") or "") + " - " + (rz.get("v") or "")).strip(" -"),
        "truth": " - ".join(TRUTH[r["id"]]) if r["id"] in TRUTH else None,
        "lines": ocr[:8],
    })

print(f"rows scanned: {len(rows)}; rescue fired on {len(fires)}")
for f in fires:
    tag = ""
    if f["truth"]:
        tag = " [TRUTH: %s -> %s]" % (f["truth"], "FIX" if f["rescueTo"].lower().startswith(f["truth"].split(" - ")[0].lower()) else "WRONG")
    elif f["conf"] == "high":
        tag = " [high-conf row: probable FALSE FIRE]"
    print(f"  id {f['id']} ({f['build']},{f['conf']},{f['src']}): {f['guess']} -> {f['rescueTo']}{tag}")
    print(f"     lines: {f['lines']}")
