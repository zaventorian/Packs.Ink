"""Guards the archive, prune and tracked-store-feed behaviour in discover_events.py.

    python scripts/elo/test_events_archive.py

No network, no database — urlopen is stubbed. Five things are being locked
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
  4. GRACE. The scan reads an index that moves under it and misses the odd live
     event every night. A single miss must not delete one: on 2026-09-10 the
     prune deleted a Set Championship that RPH still listed.
  5. TRACKED-STORE FEEDS. Each tracked store's own upcoming feed is folded into
     the scan before anything is classified or written. Both store-filter
     spellings are unioned, store.id is re-checked, and one unreadable feed
     never costs the others.
"""
from __future__ import annotations
import datetime, inspect, io, json, os, re, sys, time, urllib.error, urllib.request
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_events as de  # noqa: E402

RUN_START = "2026-08-19T00:00:00+00:00"
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


def run(past_rows, archive_fails=False, archive_missing=False, deletes=None):
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
            if deletes is not None:
                deletes.append(url)
            return Resp(b"[]", {"Content-Range": "*/0"})
        raise AssertionError("unexpected request: " + method + " " + url)

    real = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        # pulled/before_upcoming chosen to clear both completeness guards.
        de.prune(RUN_START, pulled=9000, before_upcoming=9000)
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

print("grace")
deletes = []
run([], deletes=deletes)
unlisted = [u for u in deletes if "last_seen_at=lt." in u]
check("one delete for upcoming rows RPH stopped listing", len(unlisted), 1)
if unlisted:
    cutoff = datetime.datetime.fromisoformat(
        unquote(re.search(r"last_seen_at=lt\.([^&]+)", unlisted[0]).group(1)))
    unseen_h = (datetime.datetime.fromisoformat(RUN_START) - cutoff).total_seconds() / 3600
    # A daily job, with room for GitHub's cron to slip six hours either way.
    check("an event the previous scan saw survives one miss", unseen_h >= 24 + 6, True)
    check("an event two scans in a row missed is pruned", unseen_h < 48 - 6, True)

print("tracked-store feeds")


def ev_at(eid, store):
    return {"id": eid, "name": f"event {eid}", "store": {"id": store}}


FEEDS = {  # (store-filter spelling, store) -> what RPH returns for it
    ("store", 1): [ev_at(101, 1), ev_at(102, 99)],
    ("store_id", 1): [ev_at(101, 1), ev_at(103, 1)],
    ("store", 3): [ev_at(104, 3)],
    ("store_id", 3): [],
}
statuses = set()


def feed_urlopen(req, timeout=None):
    url = req.full_url
    if "elo_tracked_stores" in url:
        return Resp(json.dumps([{"store_id": s} for s in (1, 2, 3)]).encode())
    q = parse_qs(urlparse(url).query)
    statuses.update(q.get("display_statuses", []))
    param = "store" if "store" in q else "store_id"
    sid = int(q[param][0])
    if sid == 2:
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, io.BytesIO(b"boom"))
    return Resp(json.dumps({"results": FEEDS[(param, sid)], "next": None}).encode())


real_open, real_sleep = urllib.request.urlopen, time.sleep
urllib.request.urlopen, time.sleep = feed_urlopen, (lambda s: None)
try:
    merged = de.add_tracked_store_feeds([ev_at(104, 3), ev_at(200, 50)])
    _, failed = de.fetch_tracked_upcoming([1, 2, 3])
finally:
    urllib.request.urlopen, time.sleep = real_open, real_sleep
ids = [e["id"] for e in merged]
check("the feeds asked RPH for upcoming events only", statuses, {"upcoming"})
check("both store-filter spellings are unioned", sorted(i for i in ids if i in (101, 103)), [101, 103])
check("a row RPH files under another store is dropped", 102 in ids, False)
check("an event the scan already had isn't added twice", ids.count(104), 1)
check("the scan's own rows are kept", 200 in ids, True)
check("an unreadable feed is reported, not fatal", failed, [2])

print("wiring")
src = inspect.getsource(de.main)
order = [src.find(s) for s in ("add_tracked_store_feeds(", "derive_prerelease_templates(",
                               "upsert_events(", "prune(")]
check("main folds the feeds in before classifying, upserting and pruning",
      order[0] >= 0 and order == sorted(order), True)

print()
print(f"{len(failures)} failure(s)" if failures else "all passed")
sys.exit(1 if failures else 0)
