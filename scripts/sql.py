"""
Run SQL against the project database from any session.

    python scripts/sql.py -c "select count(*) from cards"      # a query: prints rows
    python scripts/sql.py supabase/177_admin_exec_sql.sql       # a file: runs it
    python scripts/sql.py --rows -f some_query.sql              # a file that is one query

It calls the service-role-only admin_exec_sql() RPC (migration 177) over
PostgREST, so it needs nothing but the service key: scripts/.env locally, the
proxy-injected key in a cloud session. The Supabase connector is still the
first choice; this is the route for when it is missing or refuses.

A statement runs inside a function: no BEGIN/COMMIT, VACUUM or CREATE INDEX
CONCURRENTLY. A -c string is treated as a query (rows come back) when it starts
with select / with / values / table; pass --exec or --rows to say otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def load_env() -> None:
    """scripts/.env is gitignored, so a worktree has none: fall back to the
    main checkout's copy."""
    candidates = [HERE / ".env", HERE.parent / ".env"]
    try:
        common = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"], cwd=HERE,
            capture_output=True, text=True, timeout=10).stdout.strip()
        if common:
            root = (HERE / common).resolve().parent if not os.path.isabs(common) else Path(common).parent
            candidates += [root / "scripts" / ".env", root / ".env"]
    except Exception:
        pass
    for path in candidates:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def looks_like_query(sql: str) -> bool:
    head = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    return head in ("select", "with", "values", "table")


def run(sql: str, rows: bool) -> object:
    from supabase_client import Supabase
    sb = Supabase()
    if rows:
        sql = sql.strip().rstrip(";")
    r = requests.post(
        f"{sb.url}/rest/v1/rpc/admin_exec_sql",
        headers={**sb.auth_headers(), "Content-Type": "application/json"},
        json={"p_sql": sql, "p_rows": rows}, timeout=330)
    if r.status_code >= 300:
        try:
            err = r.json()
            msg = f"{err.get('code', r.status_code)}: {err.get('message', r.text)}"
            if err.get("details"):
                msg += f"\n  {err['details']}"
            if err.get("hint"):
                msg += f"\n  hint: {err['hint']}"
        except Exception:
            msg = f"HTTP {r.status_code}: {r.text[:500]}"
        if r.status_code in (401, 403) or "42501" in msg:
            msg += "\n  (needs the SERVICE key; the anon key is refused by design)"
        if "PGRST202" in msg:
            msg += "\n  (admin_exec_sql is missing: apply supabase/177_admin_exec_sql.sql through the connector)"
        sys.exit(msg)
    return r.json()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="a .sql file to run")
    ap.add_argument("-c", "--command", help="SQL text")
    ap.add_argument("-f", "--file", dest="file2", help="a .sql file to run")
    ap.add_argument("--rows", action="store_true", help="treat it as one query and print its rows")
    ap.add_argument("--exec", dest="exec_", action="store_true", help="run it and return nothing")
    args = ap.parse_args()

    path = args.file or args.file2
    if bool(path) == bool(args.command):
        ap.error("give a .sql file or -c \"...\", not both")
    sql = args.command if args.command else Path(path).read_text(encoding="utf8")
    rows = args.rows or (not args.exec_ and bool(args.command) and looks_like_query(sql))

    load_env()
    out = run(sql, rows)
    if rows:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
        print(f"-- {len(out)} row(s)", file=sys.stderr)
    else:
        print("ok")


if __name__ == "__main__":
    main()
