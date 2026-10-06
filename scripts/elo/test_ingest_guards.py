"""Guards what ingest.py does to an event row it already holds, and how a failed
ingest is reported.

    python scripts/elo/test_ingest_guards.py

No network: RPH is a dict of canned payloads behind ingest.http_get, and every DB
is a temp SQLite built from the repo's schema.sql.

  1. A re-pull UPDATES the event row; it never replaces it. ingest wrote the
     events row with INSERT OR REPLACE, which in SQLite deletes the old row and
     inserts a new one — so `notes`, `platform`, `is_ignored` and `ingested_at`
     went back to their defaults on every re-pull. `notes` is the mark that keeps
     verify_results.py --repair off an event a person corrected by hand, so a
     re-pull silently armed the repair against the correction. A metadata field
     the caller didn't know (None) no longer erases the stored value either.
"""
from __future__ import annotations

import copy
import io
import os
import sqlite3
import sys
import tempfile
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import ingest as ing  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


RPH: dict[str, object] = {}


def fake_get(url, retries=3):
    if url not in RPH:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return copy.deepcopy(RPH[url])


ing.http_get = fake_get


def tv_url(eid):
    return ing.API.format(eid=eid) + "/tv/"


def put_event(eid, status, rounds, name=None):
    RPH[tv_url(eid)] = {
        "name": name or f"SC {eid}", "lifecycle_status": status, "starting_player_count": 8,
        "tournament_phases": [{"round_type": "SWISS", "rounds": [
            {"id": rid, "round_number": n, "round_type": "PLAY_VS_OPPONENT", "status": st}
            for rid, n, st, _ in rounds]}]}
    for rid, _, _, ms in rounds:
        RPH[tv_url(eid) + f"matches/?round_id={rid}"] = {"results": ms}


def m(table, a, b, winner=1, g=(2, 0)):
    return {"table_number": table, "status": "COMPLETE", "match_is_bye": False, "players": [
        {"tv_display_name": a, "player_order": 1, "is_winner": winner == 1, "games_won": g[0]},
        {"tv_display_name": b, "player_order": 2, "is_winner": winner == 2, "games_won": g[1]}]}


def new_db(td, name):
    path = Path(td) / name
    conn = sqlite3.connect(path)
    conn.executescript((HERE / "schema.sql").read_text())
    conn.commit()
    conn.close()
    return path


def row(path, eid, cols):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(f"SELECT {cols} FROM events WHERE event_id=?", (eid,)).fetchone()
    finally:
        conn.close()


def exec_(path, sql, args=()):
    conn = sqlite3.connect(path)
    try:
        conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()


def quiet(fn, *a, **k):
    with redirect_stdout(io.StringIO()):
        return fn(*a, **k)


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    print("a re-pull updates the event row, it does not replace it")
    db = new_db(td, "upsert.db")
    ing.DB_PATH = db
    put_event(7, "EVENT_IN_PROGRESS", [(71, 1, "COMPLETE", [m(1, "A", "B")])])
    quiet(ing.ingest_event, 7, store="Shop", location="Town, IL", event_date="2026-09-20",
          season="Set X Fall 2026")
    exec_(db, "UPDATE events SET notes='hand-corrected final; do not repair', "
              "ingested_at='2026-09-21 10:00:00' WHERE event_id=7")
    put_event(7, "EVENT_FINISHED", [(71, 1, "COMPLETE", [m(1, "A", "B")]),
                                    (72, 2, "COMPLETE", [m(1, "A", "B", 2, (1, 2))])],
              name="SC 7 (renamed)")
    eid, status, _ = quiet(ing.ingest_event, 7, store="Shop", location="Town, IL",
                           event_date="2026-09-20", season="Set X Fall 2026")
    check("the re-pull itself is ok", status, "ok")
    check("notes survive the re-pull", row(db, 7, "notes")[0], "hand-corrected final; do not repair")
    check("ingested_at keeps the FIRST ingest time", row(db, 7, "ingested_at")[0], "2026-09-21 10:00:00")
    check("name and status follow RPH", row(db, 7, "name,status"), ("SC 7 (renamed)", "EVENT_FINISHED"))
    check("its matches are all there", sqlite3.connect(db).execute(
        "SELECT COUNT(*) FROM matches WHERE event_id=7").fetchone()[0], 2)

    print("\nthe queued (no rounds yet) path keeps notes too")
    put_event(8, "EVENT_NOT_STARTED", [])
    quiet(ing.ingest_event, 8, store="Shop", location="Town, IL", event_date="2026-10-20",
          season="Set Y")
    exec_(db, "UPDATE events SET notes='moved to Sunday' WHERE event_id=8")
    quiet(ing.ingest_event, 8, store="Shop", location="Town, IL", event_date="2026-10-20",
          season="Set Y")
    check("notes survive a queue re-pull", row(db, 8, "notes")[0], "moved to Sunday")

    print("\nunknown metadata does not erase what is stored")
    RPH[ing.API_META.format(eid=8)] = {"start_datetime": None, "store": {}}
    quiet(ing.ingest_event, 8)            # an --ids style call: store/date/season unknown
    check("store, location, date and season are kept",
          row(db, 8, "store,location,event_date,season"), ("Shop", "Town, IL", "2026-10-20", "Set Y"))

    print("\nplatform is never reset")
    exec_(db, "UPDATE events SET platform='rph-manual' WHERE event_id=8")
    quiet(ing.ingest_event, 8, store="Shop", season="Set Y")
    check("platform kept", row(db, 8, "platform")[0], "rph-manual")

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
