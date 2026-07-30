"""
Pull every qa-snap's recorded OCR lines + truth labels into
scripts/scanner/data/replay_corpus.json for the node_eval/replay_lines.mjs
matcher A/B harness.

Truth sources, in precedence order:
  1. tester labels — reviewed rows' card_id is human truth (corrected=true rows
     are hard negatives), card_id-level (rarity-exact);
  2. the image-verified historical TRUTH table in bench_select_eval.py,
     (name, version)-level (batches 2-6).

Needs SUPABASE_URL + SUPABASE_SERVICE_KEY (gitignored .env — same as
pull_scan_samples.py).
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
OUT = HERE / "data" / "replay_corpus.json"


def _load_env():
    for p in (REPO / ".env", REPO / "scripts" / ".env", HERE / ".env"):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _historical_truth():
    """Extract the TRUTH dict from bench_select_eval.py without importing it
    (the module reads bench data files at top level)."""
    src = (HERE / "bench_select_eval.py").read_text(encoding="utf-8")
    m = re.search(r"^TRUTH = \{.*?^\}", src, re.M | re.S)
    m2 = re.search(r"^TRUTH\.update\(\{.*?^\}\)", src, re.M | re.S)
    ns: dict = {}
    exec((m.group(0) if m else "TRUTH = {}") + "\n" + (m2.group(0) if m2 else ""), ns)
    return ns.get("TRUTH", {})


def main():
    _load_env()
    url = os.environ.get("SUPABASE_URL") or "https://umwqowkiatjjltologrd.supabase.co"
    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        sys.exit("need SUPABASE_SERVICE_KEY in .env")
    H = {"apikey": key, "Authorization": f"Bearer {key}"}

    rows, start = [], 0
    while True:
        r = requests.get(f"{url}/rest/v1/scan_samples", params={
            "select": "id,card_id,predicted_card_id,reviewed,corrected,user_id,created_at,"
                      "lines:debug->ocrLines,build:debug->>build,kind:debug->>kind,"
                      "source:debug->>source,conf:debug->>conf,"
                      "verUnsure:debug->>verUnsure,cands:debug->candidates",
            "debug->>kind": "eq.qa-snap",
            "order": "id.asc",
        }, headers={**H, "Range": f"{start}-{start + 999}"}, timeout=60)
        batch = r.json()
        if not isinstance(batch, list):
            sys.exit(f"query failed: {batch}")
        rows += batch
        if len(batch) < 1000:
            break
        start += 1000

    ti = json.loads((HERE / "data" / "text_index.json").read_text(encoding="utf-8"))
    byid = {c["id"]: c for c in ti}
    hist = _historical_truth()

    out = []
    for r in rows:
        truth_id = r["card_id"] if (r.get("reviewed") and r.get("card_id")) else None
        truth_nv = None
        if truth_id and truth_id in byid:
            c = byid[truth_id]
            truth_nv = [c["name"], c.get("version") or ""]
        elif r["id"] in hist:
            truth_nv = list(hist[r["id"]])
        # Reconstruct the live colour ranking from debug.candidates: the entries
        # carrying a colourScore ARE the colour candidate list (the merged array
        # is not stored in colour order, so sort it here). Lets the replay
        # exercise the colour-dependent paths — baseGuard's sibling test and the
        # reprint ≈ flag — instead of the no-colour fallback.
        cands = r.get("cands") or []
        col = sorted((c for c in cands if isinstance(c, dict) and c.get("colourScore") is not None),
                     key=lambda c: -c["colourScore"])
        out.append({
            "id": r["id"], "build": r.get("build"), "user": (r.get("user_id") or "")[:8],
            "lines": r.get("lines") or [], "pred": r.get("predicted_card_id"),
            "reviewed": bool(r.get("reviewed")), "corrected": bool(r.get("corrected")),
            "source": r.get("source"), "conf": r.get("conf"),
            "ver_unsure": (r.get("verUnsure") == "true"),
            "colour": [c["id"] for c in col],
            "truth_id": truth_id, "truth_nv": truth_nv,
        })
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    n_lines = sum(1 for o in out if o["lines"])
    n_tid = sum(1 for o in out if o["truth_id"])
    n_tnv = sum(1 for o in out if o["truth_nv"])
    print(f"wrote {OUT.name}: {len(out)} snaps, {n_lines} with lines, "
          f"{n_tid} card_id truths, {n_tnv} name+version truths")


if __name__ == "__main__":
    main()
