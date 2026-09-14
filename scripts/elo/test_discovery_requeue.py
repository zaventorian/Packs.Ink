"""Guards the RE-QUEUE half of store-driven discovery, in discover_store_scs.py.

    python scripts/elo/test_discovery_requeue.py

No network — the DB is a temp SQLite and ingested_event_ids() is exercised for
real (it is the thing under test, so stubbing it would prove nothing).

Why this exists. Discovery is supposed to work in two passes for an SC it finds
before it is played: store the event with no rounds now ("queued for refresh"),
then come back for the results once the TO posts them. The second pass was dead.
ingested_event_ids() returned EVERY rph event_id in the table, so the moment an
event was queued it joined `have` and was never offered again — and ingest.py's
own pass only covers the hand-curated spreadsheet for the PREVIOUS set, so
nothing else would ever ask for it either.

It failed completely silently. The weekly refresh stayed green, and its own log
line read "0 at tracked stores & not yet ingested", which was true of the test it
was applying. Found 2026-09-13: all 30 of that weekend's Set Championships had
full results on RPH and 0 matches in the DB, and the five still in progress would
have been frozen forever at whatever partial state they were first seen in.

The fix is that discovery and ingest now apply the SAME test, and that is the
property worth locking down — the bug was not a wrong threshold, it was two
definitions of "done" that disagreed. Cf. elo_scope.py: a second copy of a rule
is the bug.
"""
from __future__ import annotations
import os, sqlite3, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_store_scs as m  # noqa: E402
import ingest as ing            # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


# (event_id, status, is_ignored, n_matches) -> the four states an event can be in
CASES = [
    (1, "EVENT_FINISHED",    0, 3),  # done: played, results held
    (2, "REGISTRATION_OPEN", 0, 0),  # queued while upcoming — THE bug
    (3, "EVENT_IN_PROGRESS", 0, 2),  # running, partial results so far
    (4, "EVENT_FINISHED",    0, 0),  # finished, TO never entered pairings
    (5, "EVENT_FINISHED",    1, 3),  # marked did-not-run by hand
    (6, "REGISTRATION_OPEN", 1, 0),  # ignored AND unplayed
]


def build(path):
    conn = sqlite3.connect(path)
    conn.executescript((HERE / "schema.sql").read_text())
    conn.executemany("INSERT INTO players (player_id, display_name, platform)"
                     " VALUES (?,?,'rph')", [(1, "A"), (2, "B")])
    for eid, status, ignored, nm in CASES:
        conn.execute(
            "INSERT INTO events (event_id, name, store, season, status, is_ignored, platform)"
            " VALUES (?,?,?,?,?,?,'rph')",
            (eid, f"SC {eid}", "Store 1", "Attack of the Vine! Fall 2026", status, ignored))
        for i in range(nm):
            conn.execute(
                "INSERT INTO matches (event_id, round_id, round_number, table_number,"
                " player1_id, player2_id, winner_id, is_bye, source)"
                " VALUES (?,?,?,?,1,2,1,0,'rph')",
                (eid, eid * 100 + i, i + 1, 1))
    # a melee event must never be considered here at all
    conn.execute("INSERT INTO events (event_id, name, status, is_ignored, platform)"
                 " VALUES (99, 'melee', 'EVENT_FINISHED', 0, 'melee')")
    conn.commit(); conn.close()


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    m.DB = Path(td) / "elo.db"
    build(m.DB)
    have = m.ingested_event_ids()

    print("an event is 'already ingested' only when FINISHED *and* holding matches")
    check("finished + matches -> not offered again", 1 in have, True)
    check("queued while upcoming -> STILL A CANDIDATE", 2 in have, False)
    check("in progress, partial results -> STILL A CANDIDATE", 3 in have, False)
    check("finished but no matches -> still a candidate", 4 in have, False)

    print("\nis_ignored stays suppressed either way (did-not-run is a human ruling)")
    check("ignored + matches -> not offered", 5 in have, True)
    check("ignored + unplayed -> not offered", 6 in have, True)

    print("\nonly the rph platform is in scope")
    check("melee event absent", 99 in have, False)

    print("\ndiscovery and ingest agree, case for case (the actual invariant)")
    conn = ing.db.__wrapped__() if hasattr(ing.db, "__wrapped__") else None
    ing.DB = m.DB
    conn = sqlite3.connect(m.DB); conn.row_factory = sqlite3.Row
    for eid, status, ignored, nm in CASES:
        if ignored:
            continue  # ingest_event checks is_ignored before this test, separately
        check(f"event {eid} ({status}, {nm} matches)",
              eid in have, ing.event_already_ingested(conn, eid))
    conn.close()

print("\nFAILED: " + ", ".join(failures) if failures else "\nall good")
sys.exit(1 if failures else 0)
