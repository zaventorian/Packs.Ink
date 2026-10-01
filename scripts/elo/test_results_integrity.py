"""Guards the four ways Elo results went wrong or missing on green runs.

    python scripts/elo/test_results_integrity.py

No network: RPH is a dict of canned payloads behind ingest.http_get, and every
DB is a temp SQLite built from schema.sql. Found by checking all 444 rph events
we hold against RPH on 2026-09-28:

  1. ingest stored a match from a round still being played as a 0-0 no-winner
     row — an "agreed draw" to the draw rule — and the (round, table) guard then
     kept the real result out forever. HoneyBee Games (919790), two semifinals.
  2. A result the TO corrected on RPH after we pulled it was never re-read.
     Critical Games (707597), the final.
  3. A renamed bye-holder got a second bye on each re-pull (675962).
  4. An event whose TO never closes it sits in RPH's "inProgress" bucket, which
     a past+upcoming search never returns (843303, zero matches for a week), and
     queued events were only re-pulled if a search happened to find them.
  5. Official standings were manual-only; the weekly job now runs them, which is
     only safe because they are fetched for FINISHED events alone and resolve
     names against the event's own players.
"""
from __future__ import annotations

import copy
import datetime
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
import ingest as ing                       # noqa: E402
import verify_results as vr                # noqa: E402
import backfill_official_standings as bos  # noqa: E402
import discover_store_scs as ds            # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


# ---------------------------------------------------------------- fake RPH
RPH: dict[str, object] = {}


def fake_get(url, retries=3):
    if url not in RPH:
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
    return copy.deepcopy(RPH[url])


ing.http_get = fake_get


def tv_url(eid):
    return ing.API.format(eid=eid) + "/tv/"


def put_event(eid, status, rounds):
    """rounds: [(round_id, round_number, round_status, [match dicts])]"""
    RPH[tv_url(eid)] = {
        "name": f"SC {eid}", "lifecycle_status": status, "starting_player_count": 8,
        "tournament_phases": [{"round_type": "SWISS", "rounds": [
            {"id": rid, "round_number": n, "round_type": "PLAY_VS_OPPONENT", "status": st}
            for rid, n, st, _ in rounds]}]}
    for rid, _, _, ms in rounds:
        RPH[tv_url(eid) + f"matches/?round_id={rid}"] = {"results": ms}


def m(table, a, b, winner=None, g=(2, 0), status="COMPLETE"):
    return {"table_number": table, "status": status, "match_is_bye": False, "players": [
        {"tv_display_name": a, "player_order": 1, "is_winner": winner == 1, "games_won": g[0]},
        {"tv_display_name": b, "player_order": 2, "is_winner": winner == 2, "games_won": g[1]}]}


def bye(name):
    return {"table_number": -1, "status": "COMPLETE", "match_is_bye": True, "players": [
        {"tv_display_name": name, "player_order": 1, "is_winner": True, "games_won": 2}]}


def new_db(td, name):
    path = Path(td) / name
    conn = sqlite3.connect(path)
    conn.executescript((HERE / "schema.sql").read_text())
    conn.commit()
    conn.close()
    return path


def q(path, sql, args=()):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql, args).fetchall()
    finally:
        conn.close()


def pid(path, name):
    r = q(path, "SELECT player_id FROM players WHERE display_name=?", (name,))
    return r[0][0] if r else None


def run(fn, *a, **k):
    buf = io.StringIO()
    with redirect_stdout(buf):
        out = fn(*a, **k)
    return out, buf.getvalue()


with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
    # ------------------------------------------------------ 1. ingest
    print("ingest: a match not yet reported is never stored")
    db = new_db(td, "ingest.db")
    ing.DB_PATH = db
    put_event(1, "EVENT_IN_PROGRESS", [
        (11, 1, "COMPLETE", [m(1, "A", "B", 1), m(2, "C", "D", 1, (2, 1)), bye("E")]),
        (12, 2, "IN_PROGRESS", [m(1, "A", "C", None, (0, 0), status="IN_PROGRESS"),
                                m(2, "B", "D", 2, (0, 2))]),
    ])
    eid, status, msg = ing.ingest_event(1, store="S", location="L", event_date="2026-09-27",
                                        season="Set X")
    check("first pull ok", status, "ok")
    check("unreported match counted in the message", "1 unreported" in msg, True)
    check("only COMPLETE matches stored", q(db, "SELECT COUNT(*) FROM matches WHERE event_id=1 "
                                                "AND is_bye=0")[0][0], 3)
    check("no 0-0 placeholder at R2 t1",
          q(db, "SELECT COUNT(*) FROM matches WHERE round_id=12 AND table_number=1")[0][0], 0)

    print("\ningest: the re-pull fills it in, and a renamed bye-holder gets no second bye")
    put_event(1, "EVENT_FINISHED", [
        (11, 1, "COMPLETE", [m(1, "A", "B", 1), m(2, "C", "D", 1, (2, 1)), bye("E renamed")]),
        (12, 2, "COMPLETE", [m(1, "A", "C", 1, (2, 1)), m(2, "B", "D", 2, (0, 2))]),
    ])
    ing.ingest_event(1, store="S", location="L", event_date="2026-09-27", season="Set X")
    check("R2 t1 now stored with its real winner",
          q(db, "SELECT winner_id, games_won_p1, games_won_p2 FROM matches WHERE round_id=12 "
                "AND table_number=1"), [(pid(db, "A"), 2, 1)])
    check("still exactly one R1 bye", q(db, "SELECT COUNT(*) FROM matches WHERE round_id=11 "
                                            "AND is_bye=1")[0][0], 1)
    check("renamed bye-holder not even created as a player", pid(db, "E renamed"), None)
    check("event status now finished",
          q(db, "SELECT status FROM events WHERE event_id=1")[0][0], "EVENT_FINISHED")

    print("\ningest: a genuinely new bye in a round still lands")
    put_event(2, "EVENT_IN_PROGRESS", [(21, 1, "COMPLETE", [bye("E"), m(1, "A", "B", 1)])])
    ing.ingest_event(2, store="S", event_date="2026-09-27", season="Set X")
    put_event(2, "EVENT_IN_PROGRESS", [(21, 1, "COMPLETE", [bye("E"), bye("F"), m(1, "A", "B", 1)])])
    ing.ingest_event(2, store="S", event_date="2026-09-27", season="Set X")
    check("second bye added", sorted(r[0] for r in q(
        db, "SELECT p.display_name FROM matches mm JOIN players p ON p.player_id=mm.player1_id "
            "WHERE mm.round_id=21 AND mm.is_bye=1")), ["E", "F"])

    print("\ningest: a stored result that is wrong is corrected on re-pull — carefully")
    conn = sqlite3.connect(db)
    for name in ("P", "Q", "X", "Y"):
        conn.execute("INSERT INTO players (display_name) VALUES (?)", (name,))
    P, Q, X, Y = (conn.execute("SELECT player_id FROM players WHERE display_name=?", (n,)).fetchone()[0]
                  for n in ("P", "Q", "X", "Y"))
    for e, src in ((3, "api"), (4, "manual"), (5, "api"), (6, "api")):
        conn.execute("INSERT INTO events (event_id, name, store, event_date, season, status) "
                     "VALUES (?, 'x', 'S', '2026-09-20', 'Set X', 'EVENT_IN_PROGRESS')", (e,))
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, "
                     "player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source) "
                     "VALUES (?, ?, 1, 1, ?, ?, NULL, 0, 0, 0, ?)", (e, e * 10, P, Q, src))
    conn.commit()
    conn.close()
    put_event(3, "EVENT_FINISHED", [(30, 1, "COMPLETE", [m(1, "P", "Q", 2, (1, 2))])])
    put_event(4, "EVENT_FINISHED", [(40, 1, "COMPLETE", [m(1, "P", "Q", 2, (1, 2))])])
    put_event(5, "EVENT_FINISHED", [(50, 1, "COMPLETE", [m(1, "X", "Y", 2, (1, 2))])])
    put_event(6, "EVENT_FINISHED", [(60, 1, "COMPLETE", [m(1, "P renamed", "Q", 1, (2, 0))])])
    _, _, msg3 = ing.ingest_event(3, store="S", event_date="2026-09-20", season="Set X")
    for e in (4, 5, 6):
        ing.ingest_event(e, store="S", event_date="2026-09-20", season="Set X")

    def res(e):
        return q(db, "SELECT winner_id, games_won_p1, games_won_p2 FROM matches WHERE event_id=?",
                 (e,))

    check("0-0 placeholder takes RPH's decisive result", res(3), [(Q, 1, 2)])
    check("... and says so", "1 corrected" in msg3, True)
    check("a hand-entered (source='manual') row is never overwritten", res(4), [(None, 0, 0)])
    check("a re-paired table (both names are other known players) is left alone", res(5),
          [(None, 0, 0)])
    check("one side renamed (unknown name), other side matches -> corrected", res(6), [(P, 2, 0)])

    # ------------------------------------------------------ 2. verify_results
    print("\nverify_results: finds the difference, repairs it, clears stale standings")
    vdb = new_db(td, "verify.db")
    conn = sqlite3.connect(vdb)
    bos.ensure_local_table(conn)
    for name in ("P", "Q", "R", "S"):
        conn.execute("INSERT INTO players (display_name) VALUES (?)", (name,))
    P, Q, R, S = (conn.execute("SELECT player_id FROM players WHERE display_name=?", (n,)).fetchone()[0]
                  for n in ("P", "Q", "R", "S"))
    today = datetime.date.today().isoformat()
    for e, notes in ((70, None), (71, "hand-corrected: see thread"), (72, None)):
        conn.execute("INSERT INTO events (event_id, name, store, event_date, season, status, notes) "
                     "VALUES (?, 'x', 'S', ?, 'Set X', 'EVENT_FINISHED', ?)", (e, today, notes))
        # t1: wrong winner (P stored, RPH says Q). t2: agrees.
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source) "
                     "VALUES (?, ?, 1, 1, ?, ?, ?, 2, 1, 0, 'api')", (e, e * 10, P, Q, P))
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source) "
                     "VALUES (?, ?, 1, 2, ?, ?, ?, 2, 0, 0, 'api')", (e, e * 10, R, S, R))
        conn.execute("INSERT INTO event_standings_official (event_id, player_id, place) "
                     "VALUES (?, ?, 1)", (e, P))
    conn.execute("UPDATE event_standings_official SET locked=1 WHERE event_id=72")
    conn.commit()
    conn.close()
    for e in (70, 71, 72):
        put_event(e, "EVENT_FINISHED", [(e * 10, 1, "COMPLETE",
                                         [m(1, "P", "Q", 2, (1, 2)), m(2, "R", "S", 1, (2, 0))])])

    c = sqlite3.connect(vdb)
    c.row_factory = sqlite3.Row
    issues, fixable = vr.compare(c, 70, "EVENT_FINISHED", vr.rph_event(70))
    check("one differing table reported", len(fixable), 1)
    check("the agreeing table is not", any("t2" in i for i in issues), False)
    check("notes protect an event", vr.protection(c, 71), "has notes")
    check("locked standings protect an event", vr.protection(c, 72), "locked standings")
    check("an untouched event is not protected", vr.protection(c, 70), None)
    c.close()

    argv = sys.argv
    sys.argv = ["verify_results.py", "--db", str(vdb), "--ids", "70", "71", "72", "--repair",
                "--workers", "1"]
    _, out = run(vr.main)
    sys.argv = argv
    check("unprotected event repaired", q(vdb, "SELECT winner_id, games_won_p1, games_won_p2 "
                                               "FROM matches WHERE event_id=70 AND table_number=1"),
          [(Q, 1, 2)])
    check("... and its standings cleared for re-fetch",
          q(vdb, "SELECT COUNT(*) FROM event_standings_official WHERE event_id=70")[0][0], 0)
    check("event with notes untouched", q(vdb, "SELECT winner_id FROM matches WHERE event_id=71 "
                                               "AND table_number=1"), [(P,)])
    check("event with locked standings untouched, standings kept",
          (q(vdb, "SELECT winner_id FROM matches WHERE event_id=72 AND table_number=1"),
           q(vdb, "SELECT COUNT(*) FROM event_standings_official WHERE event_id=72")[0][0]),
          ([(P,)], 1))
    check("summary counts the repair", "1 result(s) repaired" in out, True)

    # ------------------------------------------------------ 3. standings backfill
    print("\nbackfill_official_standings: finished events only, names resolved in-event")
    sdb = new_db(td, "standings.db")
    conn = sqlite3.connect(sdb)
    conn.execute("INSERT INTO players (player_id, display_name, platform) VALUES (10, 'Bob', 'melee')")
    conn.execute("INSERT INTO players (player_id, display_name, platform) VALUES (14, 'Dave (new)', 'rph')")
    conn.execute("INSERT INTO players (player_id, display_name, platform, merged_into_id) "
                 "VALUES (13, '__pre_merge__13_Dave', 'rph', 14)")
    conn.execute("INSERT INTO players (player_id, display_name, platform) VALUES (15, 'Eve', 'rph')")
    for e, status in ((80, "EVENT_FINISHED"), (81, "EVENT_IN_PROGRESS"), (82, "EVENT_FINISHED"),
                      (83, "EVENT_FINISHED")):
        conn.execute("INSERT INTO events (event_id, name, event_date, status, platform) "
                     "VALUES (?, 'x', '2026-09-20', ?, 'rph')", (e, status))
    for e in (80, 81, 83):
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, is_bye) VALUES (?, ?, 1, 1, 10, 13, 10, 0)", (e, e))
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, is_bye) VALUES (?, ?, 1, -1, 15, NULL, 15, 1)", (e, e))
    # 84/85: a renamed account's standings row carries a name nobody has yet.
    conn.execute("INSERT INTO players (player_id, display_name, platform) VALUES (20, 'Fay', 'rph')")
    conn.execute("INSERT INTO players (player_id, display_name, platform) VALUES (21, 'Gus', 'rph')")
    for e in (84, 85):
        conn.execute("INSERT INTO events (event_id, name, event_date, status, platform) "
                     "VALUES (?, 'x', '2026-09-20', 'EVENT_FINISHED', 'rph')", (e,))
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, is_bye) VALUES (?, ?, 1, 1, 20, 21, 20, 0)", (e, e))
    # 86: the 788186 shape — two renamed accounts left over with distinct records,
    # and one new name ALREADY belongs to a separate row from another event.
    conn.executemany("INSERT INTO players (player_id, display_name, platform) VALUES (?, ?, 'rph')",
                     [(30, "Hal"), (31, "Ivy"), (32, "Jo"), (33, "Ivy New")])
    conn.execute("INSERT INTO events (event_id, name, event_date, status, platform) "
                 "VALUES (86, 'x', '2026-09-20', 'EVENT_FINISHED', 'rph')")
    for rnd, (a, b, w) in enumerate([(30, 31, 30), (30, 32, 30), (31, 32, 31)], start=1):
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, is_bye) VALUES (86, ?, ?, 1, ?, ?, ?, 0)",
                     (860 + rnd, rnd, a, b, w))
    conn.commit()
    bos.ensure_local_table(conn)
    conn.execute("INSERT INTO event_standings_official (event_id, player_id, place, locked) "
                 "VALUES (83, 10, 1, 1)")
    # 88: a row left keyed on a player merged away since (13 -> 14), and 89 where
    # the canonical already holds its own row for the event.
    for e in (88, 89):
        conn.execute("INSERT INTO events (event_id, name, event_date, status, platform) "
                     "VALUES (?, 'x', '2026-01-10', 'EVENT_FINISHED', 'rph')", (e,))
        conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, player1_id,"
                     " player2_id, winner_id, is_bye) VALUES (?, ?, 1, 1, 13, 10, 13, 0)", (e, e))
    conn.execute("INSERT INTO event_standings_official (event_id, player_id, place) VALUES (88, 13, 1)")
    conn.execute("INSERT INTO event_standings_official (event_id, player_id, place) VALUES (89, 13, 1)")
    conn.execute("INSERT INTO event_standings_official (event_id, player_id, place) VALUES (89, 14, 2)")
    conn.commit()
    conn.close()

    SHEETS = {
        80: [{"name": n, "rank": i + 1, "mw": 1, "ml": 0, "md": 0, "pts": 3, "mw_pct": 100.0,
              "omw_pct": 50.0, "gw_pct": 60.0} for i, n in enumerate(["Bob", "dave", "Eve", "Nobody"])],
        81: [{"name": "Bob", "rank": 1, "mw": 1, "ml": 0, "md": 0, "pts": 3, "mw_pct": 1.0,
              "omw_pct": 1.0, "gw_pct": 1.0}],
        83: [{"name": "Eve", "rank": 1, "mw": 1, "ml": 0, "md": 0, "pts": 3, "mw_pct": 1.0,
              "omw_pct": 1.0, "gw_pct": 1.0}],
        84: [{"name": "Fay", "rank": 1, "mw": 1, "ml": 0, "md": 0, "pts": 3, "mw_pct": 1.0,
              "omw_pct": 1.0, "gw_pct": 1.0},
             {"name": "Gus Renamed", "rank": 2, "mw": 0, "ml": 1, "md": 0, "pts": 0,
              "mw_pct": 0.0, "omw_pct": 1.0, "gw_pct": 0.0}],
        85: [{"name": "Fay", "rank": 1, "mw": 1, "ml": 0, "md": 0, "pts": 3, "mw_pct": 1.0,
              "omw_pct": 1.0, "gw_pct": 1.0},
             {"name": "Gus Renamed", "rank": 2, "mw": 1, "ml": 1, "md": 0, "pts": 3,
              "mw_pct": 0.5, "omw_pct": 1.0, "gw_pct": 0.5}],
        86: [{"name": n, "rank": i + 1, "mw": w, "ml": l, "md": 0, "pts": 3 * w, "mw_pct": 0.0,
              "omw_pct": 0.0, "gw_pct": 0.0}
             for i, (n, w, l) in enumerate([("Hal", 2, 0), ("Ivy New", 1, 1), ("Jo New", 0, 2),
                                            ("Kim", 0, 0)])],
    }
    asked = []

    def fake_fetch(eid):
        asked.append(eid)
        return copy.deepcopy(SHEETS.get(eid, []))

    bos.fetch_rph_event = fake_fetch
    sys.argv = ["backfill_official_standings.py", "--db", str(sdb), "--workers", "1"]
    _, out = run(bos.main)
    check("only finished events with matches and no standings are fetched (not in-progress, "
          "not empty, not locked, not already backfilled)", sorted(asked), [80, 84, 85, 86])
    check("a row keyed on a merged-away player is re-keyed onto the canonical",
          q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=88"), [(14, 1)])
    check("... and dropped where the canonical already holds the event's row",
          q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=89"), [(14, 2)])
    check("renamed accounts pair by unique record — never onto a same-named row from elsewhere",
          dict(q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=86")),
          {30: 1, 31: 2, 32: 3})
    check("a registrant who never played is counted, not written", "never-played=1" in out, True)
    rows = dict(q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=80"))
    check("a melee-platform player at an RPH event resolves", rows.get(10), 1)
    check("an old name parked as __pre_merge__ resolves (case-insensitively) to the canonical",
          rows.get(14), 2)
    check("a player whose only row is a bye resolves", rows.get(15), 3)
    check("a renamed account's row pairs with the one leftover player when records agree",
          dict(q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=84")),
          {20: 1, 21: 2})
    check("... and stays unmatched when they don't",
          dict(q(sdb, "SELECT player_id, place FROM event_standings_official WHERE event_id=85")),
          {20: 1})
    check("unknown names are reported, not guessed (Nobody at 80, Gus Renamed at 85)",
          "unmatched=2" in out and "paired-by-record=3" in out, True)
    check("locked event keeps its hand-set row",
          q(sdb, "SELECT player_id FROM event_standings_official WHERE event_id=83"), [(10,)])

    asked.clear()
    run(bos.main)
    check("a backfilled event is not fetched again", asked, [])

    SHEETS[80] = SHEETS[80][:2]
    sys.argv = ["backfill_official_standings.py", "--db", str(sdb), "--workers", "1", "--force"]
    run(bos.main)
    check("--force replaces the table outright (a player no longer listed is gone)",
          sorted(r[0] for r in q(sdb, "SELECT player_id FROM event_standings_official "
                                      "WHERE event_id=80")), [10, 14])

    asked.clear()
    sys.argv = ["backfill_official_standings.py", "--db", str(sdb), "--workers", "1",
                "--include-unfinished"]
    run(bos.main)
    check("--include-unfinished reaches the in-progress event", 81 in asked, True)
    sys.argv = argv

    # ------------------------------------------------------ 4. discovery
    print("\ndiscovery: inProgress is pulled, unfinished events are re-pulled by id")
    check("PULL_STATUSES includes RPH's third bucket", "inProgress" in ds.PULL_STATUSES, True)
    seen_params = []

    def fake_json(url):
        from urllib.parse import parse_qs, urlparse
        seen_params.append({k: v[0] for k, v in parse_qs(urlparse(url).query).items()})
        return {"results": [], "next": None}

    ds.d.http_json = fake_json
    ds.pull_store_scs({5171}, "Set X", (datetime.date(2026, 8, 28), None), [], {})
    inprog = [p for p in seen_params if p.get("display_statuses") == "inProgress"]
    check("store feeds ask for inProgress", bool(inprog), True)
    check("... bounded to the season like past",
          all(p.get("start_date_after") == "2026-08-28" for p in inprog), True)
    seen_params.clear()
    ds.pull_set_scs("Set X", ["Set X Set Championship"], [], {})
    check("name nets ask for inProgress",
          any(p.get("display_statuses") == "inProgress" for p in seen_params), True)

    ddb = new_db(td, "disc.db")
    ds.DB = ddb
    today = datetime.date(2026, 9, 28)
    conn = sqlite3.connect(ddb)
    conn.execute("INSERT INTO players (player_id, display_name) VALUES (1, 'A'), (2, 'B')")
    # (eid, date, status, ignored, played)
    CASES = [
        (90, "2026-09-26", "REGISTRATION_OPEN", 0, 0),   # queued, unplayed, recent -> yes
        (91, "2026-09-20", "EVENT_IN_PROGRESS", 0, 0),   # stuck, no matches yet -> yes (843303)
        (92, "2026-06-14", "EVENT_IN_PROGRESS", 0, 1),   # played, old -> yes (any age)
        (93, "2026-06-14", "REGISTRATION_CLOSED", 0, 0), # unplayed, old -> aged out
        (94, "2026-09-20", "EVENT_FINISHED", 0, 1),      # done -> no
        (95, "2026-09-20", "EVENT_IN_PROGRESS", 1, 1),   # ignored -> no
        (96, "2026-10-03", "REGISTRATION_OPEN", 0, 0),   # future -> no
        (97, "2026-09-20", "EVENT_FINISHED", 0, 0),      # finished, never had matches -> yes
    ]
    for eid, date, status, ign, played in CASES:
        conn.execute("INSERT INTO events (event_id, name, store, location, event_date, season, status,"
                     " is_ignored, platform) VALUES (?, 'x', ?, 'City, ST', ?, 'Set X', ?, ?, 'rph')",
                     (eid, f"Store {eid}", date, status, ign))
        if played:
            conn.execute("INSERT INTO matches (event_id, round_id, round_number, table_number, "
                         "player1_id, player2_id, winner_id, is_bye) VALUES (?, ?, 1, 1, 1, 2, 1, 0)",
                         (eid, eid))
    conn.commit()
    conn.close()
    got = [r["event_id"] for r in ds.unfinished_events(today)]
    check("unfinished selection", got, [92, 91, 97, 90])

    calls = []
    real_ingest = ds.ing.ingest_event
    ds.ing.ingest_event = lambda eid, **kw: (calls.append((eid, kw)) or (eid, "queue", "stub"))
    run(ds.requeue_unfinished, {90}, today)
    ds.ing.ingest_event = real_ingest
    check("events discovery already offered are not pulled twice",
          sorted(e for e, _ in calls), [91, 92, 97])
    kw = dict(calls)[92]
    check("the event's own store / location / date / season are passed through",
          (kw["store"], kw["location"], kw["event_date"], kw["season"]),
          ("Store 92", "City, ST", "2026-06-14", "Set X"))

print("\nFAILED: " + ", ".join(failures) if failures else "\nall good")
sys.exit(1 if failures else 0)
