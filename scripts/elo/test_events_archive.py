"""Guards the archive-before-sweep behaviour in discover_events.py.

    python scripts/elo/test_events_archive.py

No network, no database — urlopen is stubbed. Three things are being locked
down, all of which fail silently and irreversibly in production:

  1. ORDERING. The sweep deletes the only record that a store ran a given
     event. If a delete can ever happen before (or without) a successful
     archive, that history is gone for good — RPH's feed lists upcoming events
     only, so there is nothing to re-pull it from.
  2. FAILURE MODE. If the archive table is missing (migration 121 not applied
     yet) or the write errors, the sweep must not run at all. Accumulating rows
     in lorcana_events is recoverable; deleting them is not.
  3. COLUMN CONTRACT. HISTORY_COLS is copied straight through to the archive
     table, so a column added to one and not the other is dropped silently.
"""
from __future__ import annotations
import io, json, os, re, sys, urllib.error, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_events as de  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


class Resp(io.BytesIO):
    """Minimal urlopen context-manager stand-in."""
    def __init__(self, body=b"[]", headers=None):
        super().__init__(body)
        self.headers = headers or {}
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


def run(past_rows, archive_fails=False, archive_missing=False):
    """Drive prune() against a stubbed API; return the ordered call log."""
    calls = []
    served = {"offset": 0}

    def fake_urlopen(req, timeout=None):
        url, method = req.full_url, req.get_method()
        if "lorcana_events_history" in url and method == "POST":
            calls.append("archive_write")
            if archive_missing:
                raise urllib.error.HTTPError(
                    url, 404, "Not Found", {},
                    io.BytesIO(b'{"code":"PGRST205","message":"lorcana_events_history"}'))
            if archive_fails:
                raise urllib.error.HTTPError(url, 500, "Server Error", {}, io.BytesIO(b"boom"))
            return Resp()
        if method == "GET" and "select=" in url and "start_datetime=lt." in url:
            calls.append("archive_read")
            off = served["offset"]
            page = past_rows[off:off + 500]
            served["offset"] = off + len(page)
            return Resp(json.dumps(page).encode())
        if method == "DELETE":
            # The guard delete (unlisted upcoming) and the past sweep both land
            # here; only the latter carries a start_datetime=lt. filter.
            calls.append("delete_past" if "start_datetime=lt." in url else "delete_unlisted")
            return Resp(b"[]", {"Content-Range": "*/0"})
        raise AssertionError("unexpected request: " + method + " " + url)

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        # pulled/before_upcoming chosen to clear both completeness guards.
        de.prune("2026-08-19T00:00:00+00:00", pulled=9000, before_upcoming=9000)
    finally:
        urllib.request.urlopen = real
    return calls


print("ordering")
rows = [{"event_id": i} for i in range(3)]
calls = run(rows)
check("archive write precedes the past sweep",
      calls.index("archive_write") < calls.index("delete_past"), True)
check("past sweep runs once the archive succeeded", "delete_past" in calls, True)

print("failure modes")
calls = run(rows, archive_missing=True)
check("archive table missing -> nothing swept", "delete_past" in calls, False)
check("...and the unlisted-upcoming delete still ran", "delete_unlisted" in calls, True)

calls = run(rows, archive_fails=True)
check("archive write errors -> nothing swept", "delete_past" in calls, False)

print("paging")
calls = run([{"event_id": i} for i in range(1100)])
check("1100 rows archived in 3 pages", calls.count("archive_write"), 3)
check("still swept afterwards", "delete_past" in calls, True)

print("empty")
calls = run([])
check("no past rows -> no archive write", "archive_write" in calls, False)
check("...and the sweep still runs", "delete_past" in calls, True)

print("column contract")
sql = (HERE.parents[1] / "supabase" / "121_lorcana_events_history.sql").read_text(encoding="utf-8")
body = sql.split("create table if not exists public.lorcana_events_history", 1)[1].split(");", 1)[0]
sql_cols = set(re.findall(r"^\s{2}([a-z_]+)\s+\S", body, re.M)) - {"archived_at"}
py_cols = set(de.HISTORY_COLS.split(","))
check("every archived column exists in the table", sorted(py_cols - sql_cols), [])
check("no table column is missed by the copy", sorted(sql_cols - py_cols), [])

print()
print(f"{len(failures)} failure(s)" if failures else "all passed")
sys.exit(1 if failures else 0)
