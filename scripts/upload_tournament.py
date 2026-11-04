"""Upload one tournament straight to the database, no Bulk Upload modal.

    python scripts/upload_tournament.py event.json            # dry run, writes nothing
    python scripts/upload_tournament.py event.json --commit   # upload

event.json is the object admin_import_tournament takes (supabase/201 and 202):
    {"name": "...", "event_date": "2026-10-31", "format": "core", "num_players": 778,
     "rows": [{"place": "1st", "player_name": "...", "decklist": "4 Card - Version\\n..."}]}
Places are 1st / 2nd / 3rd / Top 4 / Top 8 / ... or an ordinal ("129th"). Leave
out deck_name: a nameless tournament deck renders as "<Event> - <Place>".

The service key comes from scripts/.env (gitignored). The function refuses the
commit, writing nothing, on any unmatched card line, unreadable place, empty
list, bad format, or a tournament already stored under the same name and date.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def call(event, commit):
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    # No User-Agent override: the edge in front of PostgREST 401s a browser-like
    # agent even with a valid key (see watch_calendar_sources.py).
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/rpc/admin_import_tournament",
        data=json.dumps({"p_event": event, "p_commit": commit}).encode("utf-8"),
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Content-Type": "application/json", "Accept": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:2000]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("event_json", type=Path)
    ap.add_argument("--commit", action="store_true", help="upload (default is a dry run)")
    ap.add_argument("--report", type=Path, help="also write the full per-row report here")
    args = ap.parse_args()

    event = json.loads(args.event_json.read_text(encoding="utf-8"))
    res = call(event, args.commit)
    if args.report:
        args.report.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    rows = res.get("rows") or []
    totals = {}
    for r in rows:
        totals[r["total"]] = totals.get(r["total"], 0) + 1
    print(f"{res.get('name')}  {res.get('event_date')}  {res.get('format')}  "
          f"players={res.get('num_players')}  rows={len(rows)}")
    print("deck totals:", ", ".join(f"{t}: {n}" for t, n in sorted(totals.items())))
    for r in rows:
        if r.get("unmatched") or r.get("over_cap"):
            print(f"  row {r['row']} {r['place']} {r['player']}: "
                  f"unmatched={r.get('unmatched')} over_cap={r.get('over_cap')}")
    problems = res.get("problems") or []
    print("problems:", "none" if not problems else "")
    for p in problems:
        print("  -", p)
    if res.get("committed"):
        print("UPLOADED as tournament", res.get("tournament_id"))
    elif args.commit:
        print("NOT uploaded")
    else:
        print("dry run: nothing written" + ("" if problems else "; ready for --commit"))


if __name__ == "__main__":
    main()
