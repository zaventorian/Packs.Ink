"""Guards the attendance scrape behind the Stores tab's Tickets and Fans.

    python scripts/elo/test_attendance_targets.py

No network — _get is stubbed.

rph_event_attendance used to be filled only when someone dispatched the scrape by
hand. That happened around 2026-08-19 and never again: by 2026-09-10, 212 of the
216 events played at tracked stores since then had no roster, each one counted as
an event nobody attended, and every workflow was green. A store owner asked why
nothing they had hosted was showing up. Two things are locked down:

  1. SELECTION. Unscanned past events at tracked stores are queued. Scanned ones
     are not — unless they started inside the recheck window, because a scan row
     is what makes an event skip forever and one read mid-play would otherwise
     keep that roster. Events that haven't started, and stores we don't track,
     never are, and both filters happen on the server.
  2. WIRING. discover_scs.yml runs the scrape on its SCHEDULE, after the history
     top-up — not only behind a manual dispatch. That condition was the bug.
"""
from __future__ import annotations
import datetime, os, re, sys
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import scrape_event_attendance as m  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


NOW = datetime.datetime(2026, 9, 10, 15, 0, tzinfo=datetime.timezone.utc)
TRACKED = [10, 11]
HISTORY = [                                    # event_id, store_id, start
    (1, 10, "2026-08-01T23:00:00+00:00"),      # old, scanned
    (2, 10, "2026-08-28T23:00:00+00:00"),      # old, never scanned
    (3, 11, "2026-09-09T16:00:00+00:00"),      # yesterday, scanned mid-play
    (4, 99, "2026-09-04T23:00:00+00:00"),      # a store we don't track
    (5, 10, "2026-09-12T16:00:00+00:00"),      # hasn't started
    (6, 11, "2026-09-06T18:00:00+00:00"),      # four days ago, scanned
]
SCANNED = {1, 3, 6}
history_queries = []


def _offset(path):
    found = re.search(r"offset=(\d+)", path)
    return int(found.group(1)) if found else 0


def fake_get(path):
    if path.startswith("elo_tracked_stores"):
        return [{"store_id": s} for s in TRACKED]
    if path.startswith("rph_event_attendance_scans"):
        return [{"event_id": e} for e in sorted(SCANNED)] if _offset(path) == 0 else []
    if path.startswith("lorcana_events_history"):
        q = unquote(path)
        history_queries.append(q)
        if _offset(path):
            return []
        stores = re.search(r"store_id=in\.\(([^)]*)\)", q)
        before = re.search(r"start_datetime=lt\.([^&]+)", q)
        rows = [{"event_id": e, "store_id": s, "store_name": f"Store {s}", "start_datetime": t}
                for e, s, t in HISTORY]
        # A query missing either filter gets EVERYTHING back, so a dropped filter
        # fails the selection checks below rather than passing by luck.
        if stores:
            ids = {int(x) for x in stores.group(1).split(",")}
            rows = [r for r in rows if r["store_id"] in ids]
        if before:
            cutoff = datetime.datetime.fromisoformat(before.group(1))
            rows = [r for r in rows if datetime.datetime.fromisoformat(r["start_datetime"]) < cutoff]
        return rows
    raise AssertionError(f"unexpected query: {path}")


def ids(rows):
    return [r["event_id"] for r in rows]


m._get = fake_get

print("selection")
check("default: only the never-scanned past event at a tracked store",
      ids(m.target_events(False, None, 0, NOW)), [2])
check("recheck 3 days: yesterday's scanned event is read again",
      ids(m.target_events(False, None, 3, NOW)), [2, 3])
got = m.target_events(False, None, 5, NOW)
check("recheck 5 days reaches back to the 6th, oldest first", ids(got), [2, 6, 3])
check("only the re-reads are flagged as re-reads",
      {r["event_id"]: bool(r.get("_recheck")) for r in got}, {2: False, 6: True, 3: True})
check("--refresh takes every started event at a tracked store",
      ids(m.target_events(True, None, 0, NOW)), [1, 2, 6, 3])
check("--limit caps the oldest-first list", ids(m.target_events(False, 1, 5, NOW)), [2])
wide = ids(m.target_events(True, None, 30, NOW))
check("an event that hasn't started is never queued", 5 in wide, False)
check("an untracked store's event is never queued", 4 in wide, False)
check("every history read filters by store AND start on the server",
      bool(history_queries) and all("store_id=in.(" in q and "start_datetime=lt." in q
                                    for q in history_queries), True)

print("\nwiring: the scrape runs on the schedule, after the history top-up")
wf = (HERE.parents[1] / ".github" / "workflows" / "discover_scs.yml").read_text(encoding="utf-8")
steps = re.split(r"\n      - name: ", wf)


def step_running(fragment):
    return next((s for s in steps if fragment in s), None)


def condition(step):
    found = re.search(r"\n        if: \$\{\{(.*?)\}\}", step or "")
    return found.group(1) if found else ""


att = step_running("scrape_event_attendance.py --recheck-days")
top = step_running("scrape_store_history.py --since")
for label, st in (("attendance scrape", att), ("history top-up", top)):
    check(f"a step runs the {label}", st is not None, True)
    cond = condition(st)
    check(f"the {label} runs on the schedule, not only on a manual dispatch",
          "github.event_name != 'workflow_dispatch'" in cond
          and "github.event_name == 'workflow_dispatch' &&" not in cond, True)
check("the top-up runs before the scrape reads the history it fills",
      0 <= wf.find("scrape_store_history.py --since") < wf.find("scrape_event_attendance.py --recheck-days"),
      True)
check("this guard runs before the scrape",
      bool(att) and 0 <= att.find("test_attendance_targets.py")
      < att.find("scrape_event_attendance.py --recheck-days"), True)

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all attendance-target guards pass")
