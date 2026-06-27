"""
Download the scanner flywheel (scan_samples table + scan-samples bucket) to a
local folder so the failures can be reviewed / used to fine-tune the scanner.

Needs read access to the PRIVATE bucket — set these env vars (e.g. in a gitignored
.env that you `source`, or inline):
    SUPABASE_URL=https://<ref>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   # service role bypasses RLS

    python scripts/scanner/pull_scan_samples.py [--reviewed-only] [--wrong-only]

Saves to scripts/scanner/data/flywheel/ :
  <created>__<R|W|?>__pred-<predictedName>__truth-<truthName>.jpg
where R=marked right, W=marked wrong (corrected), ?=unreviewed. A wrong file's
pred != truth — those are the hard negatives worth staring at.
Also writes labels.json (the full table) for programmatic use.
"""
from __future__ import annotations
import argparse, json, os, re, sys
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "flywheel"
REPO = HERE.parent.parent

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_SERVICE_KEY")


def slug(s):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", (s or "unknown"))[:48]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reviewed-only", action="store_true")
    ap.add_argument("--wrong-only", action="store_true", help="only corrected=true (hard negatives)")
    a = ap.parse_args()
    if not URL or not KEY:
        sys.exit("Set SUPABASE_URL + SUPABASE_SERVICE_KEY env vars first (service-role key — it bypasses RLS to read the private bucket).")
    OUT.mkdir(parents=True, exist_ok=True)
    H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

    # card_id -> display name, from the shipped scanner index (no DB round-trip).
    names = {}
    idx = REPO / "scanner" / "index.json"
    if idx.exists():
        for c in json.loads(idx.read_text(encoding="utf-8")).get("cards", []):
            names[c["id"]] = c.get("name", "") + (" - " + c["version"] if c.get("version") else "")
    nm = lambda cid: names.get(cid, cid or "—")

    q = "select=id,card_id,predicted_card_id,corrected,reviewed,image_path,created_at,printing&order=created_at.desc&limit=2000"
    filt = []
    if a.reviewed_only:
        filt.append("reviewed=eq.true")
    if a.wrong_only:
        filt.append("corrected=eq.true")
    url = f"{URL}/rest/v1/scan_samples?{q}" + ("&" + "&".join(filt) if filt else "")
    rows = requests.get(url, headers=H, timeout=30).json()
    if not isinstance(rows, list):
        sys.exit(f"query failed: {rows}")
    (OUT / "labels.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"{len(rows)} rows. downloading images...")

    got = nodl = 0
    for r in rows:
        path = r.get("image_path")
        if not path:
            nodl += 1; continue
        try:
            resp = requests.get(f"{URL}/storage/v1/object/scan-samples/{path}", headers=H, timeout=30)
            if resp.status_code != 200:
                nodl += 1; continue
            flag = "?" if not r.get("reviewed") else ("W" if r.get("corrected") else "R")
            stamp = (r.get("created_at") or "")[:19].replace(":", "").replace("-", "").replace("T", "_")
            fn = f"{stamp}__{flag}__pred-{slug(nm(r.get('predicted_card_id')))}__truth-{slug(nm(r.get('card_id')))}.jpg"
            (OUT / fn).write_bytes(resp.content); got += 1
        except Exception as e:
            nodl += 1
    n = len(rows)
    rev = [r for r in rows if r.get("reviewed")]
    wrong = [r for r in rev if r.get("corrected")]
    print(f"saved {got} images ({nodl} missing) to {OUT}")
    if rev:
        print(f"reviewed: {len(rev)}  |  right: {len(rev)-len(wrong)}  wrong: {len(wrong)}  |  accuracy: {100*(len(rev)-len(wrong))/len(rev):.1f}%")
    else:
        print("no reviewed rows yet (label them in the app's Scan Review panel).")


if __name__ == "__main__":
    main()
