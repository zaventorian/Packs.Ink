"""Check the results we hold against RPH, round by round and table by table —
and with --repair, take RPH's result wherever a stored one is wrong.

    python verify_results.py --days 30             # recent events (weekly refresh)
    python verify_results.py --all                 # every rph event, ~450: minutes
    python verify_results.py --ids 919790 --repair
    python verify_results.py --db copy.db --all    # read a copy, not the live file

Why it exists: a green weekly refresh has twice held wrong or missing results
with nothing to say so. First, queued events were never re-offered (2026-09-13).
Then this pass, run over all 444 rph events on 2026-09-28, found:

  * HoneyBee Games 9/13 (919790): two semifinals captured mid-round, stored as
    0-0 no-winner rows — which the draw rule reads as agreed draws, so neither
    rating moved — while RPH recorded 2-1 wins. ingest.match_is_complete now
    keeps such rows out; this repairs any already in.
  * Critical Games 6/28 (707597): the final, re-scored on RPH by the TO after we
    pulled it. RPH's own standings had the other finalist 1st at 6-0.

plus four hand corrections, which is why repair skips protected events.

It keys on (round_id, table_number) and the winner's SIDE (player_order), never
on names, so a renamed account can't raise a false alarm.

--repair only ever moves a RESULT (winner + games) on an existing source='api'
row whose players still match — ingest.sync_match_result, the same function a
re-pull uses. It never inserts or deletes a row, and it leaves alone any event a
person has touched: one with events.notes, a locked official standing, or any
row that isn't source='api' (hand-entered finals carry negative round ids). A
hand correction must leave one of those marks, or the next pass reverts it.

Always exits 0: it is a report plus a best-effort repair, and the weekly refresh
runs it as a soft step.
"""
from __future__ import annotations

import argparse
import datetime
import sqlite3
import sys
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import ingest as ing

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent


def fetch(url):
    try:
        return ing.http_get(url)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def rph_event(event_id):
    """{'status', 'rounds': {round_id: {'n', 'matches': [...]}}} or None on 404.
    A round that hasn't started 404s on its matches endpoint; that is 'no
    matches yet', not an error."""
    base = ing.API.format(eid=event_id) + "/tv/"
    tv = fetch(base)
    if tv is None:
        return None
    out = {"status": tv.get("lifecycle_status"), "rounds": {}}
    for ph in tv.get("tournament_phases") or []:
        for r in ph.get("rounds") or []:
            d = fetch(base + f"matches/?round_id={r['id']}") or {}
            ms = []
            for m in d.get("results") or []:
                ps = sorted(m.get("players") or [], key=lambda p: p.get("player_order") or 0)
                if m.get("match_is_bye"):
                    if ps:
                        ms.append({"bye": True, "name": ps[0].get("tv_display_name")})
                    continue
                if len(ps) < 2:
                    continue
                ms.append({"bye": False, "table": m.get("table_number"),
                           "complete": ing.match_is_complete(m), "p1": ps[0], "p2": ps[1]})
            out["rounds"][r["id"]] = {"n": r["round_number"], "matches": ms}
    return out


def protection(conn, event_id):
    """Why a person's hand is on this event (so repair must not touch it), or None."""
    notes = conn.execute("SELECT notes FROM events WHERE event_id=?", (event_id,)).fetchone()
    if notes and (notes[0] or "").strip():
        return "has notes"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(event_standings_official)")}
    if "locked" in cols and conn.execute(
            "SELECT 1 FROM event_standings_official WHERE event_id=? AND locked=1 LIMIT 1",
            (event_id,)).fetchone():
        return "locked standings"
    if conn.execute("SELECT 1 FROM matches WHERE event_id=? AND (source <> 'api' OR round_id < 0) "
                    "LIMIT 1", (event_id,)).fetchone():
        return "hand-entered rows"
    return None


def side_of(row):
    w = row["winner_id"]
    if w is None:
        return None
    return 1 if w == row["player1_id"] else 2 if w == row["player2_id"] else None


def compare(conn, event_id, db_status, remote):
    """(issues, fixable): human-readable differences, and (row, p1, p2) for every
    stored result that differs from a COMPLETE RPH match at the same table."""
    issues, fixable = [], []
    if remote["status"] != db_status:
        issues.append(f"status db={db_status} rph={remote['status']} (a re-pull settles this)")
    rows = conn.execute(
        """SELECT match_id, round_id, table_number, is_bye, player1_id, player2_id, winner_id,
                  games_won_p1, games_won_p2, source FROM matches WHERE event_id=?""",
        (event_id,)).fetchall()
    by_round = {}
    for r in rows:
        by_round.setdefault(r["round_id"], []).append(r)
    for rid, rr in remote["rounds"].items():
        got = by_round.get(rid, [])
        want = rr["matches"]
        tag = f"R{rr['n']}"
        pending = sum(1 for m in want if not m["bye"] and not m["complete"])
        if pending:
            issues.append(f"{tag}: {pending} match(es) not yet reported on RPH")
        nb_db, nb_r = sum(1 for x in got if x["is_bye"]), sum(1 for m in want if m["bye"])
        if nb_db != nb_r:
            issues.append(f"{tag}: byes db={nb_db} rph={nb_r}")
        nm_db = sum(1 for x in got if not x["is_bye"])
        nm_r = sum(1 for m in want if not m["bye"] and m["complete"])
        if nm_db != nm_r:
            issues.append(f"{tag}: matches db={nm_db} rph={nm_r}")
        at = {x["table_number"]: x for x in got if not x["is_bye"] and x["table_number"] is not None}
        for m in want:
            if m["bye"] or not m["complete"]:
                continue
            x = at.get(m["table"])
            if x is None:
                continue
            p1, p2 = m["p1"], m["p2"]
            rside = 1 if p1.get("is_winner") else 2 if p2.get("is_winner") else None
            rg = (p1.get("games_won"), p2.get("games_won"))
            if side_of(x) != rside or (x["games_won_p1"], x["games_won_p2"]) != rg:
                issues.append(f"{tag} t{m['table']}: db side={side_of(x)} "
                              f"{x['games_won_p1']}-{x['games_won_p2']}  rph side={rside} "
                              f"{rg[0]}-{rg[1]}  ({p1.get('tv_display_name')} v "
                              f"{p2.get('tv_display_name')})")
                fixable.append((x, p1, p2))
    for rid, got in by_round.items():
        if rid not in remote["rounds"]:
            issues.append(f"round {rid}: {len(got)} row(s) in db, not on RPH")
    return issues, fixable


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ing.DB_PATH)
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("--days", type=int, default=30,
                       help="events dated within this many days (default 30)")
    scope.add_argument("--all", action="store_true", help="every rph event with matches")
    scope.add_argument("--ids", nargs="+", type=int, help="just these events")
    ap.add_argument("--repair", action="store_true",
                    help="take RPH's result for stored results that differ (see docstring)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    q = ("SELECT event_id, event_date, status, store FROM events e WHERE platform='rph' "
         "AND is_ignored=0 AND EXISTS(SELECT 1 FROM matches m WHERE m.event_id=e.event_id)")
    params: list = []
    if args.ids:
        q += f" AND event_id IN ({','.join('?' * len(args.ids))})"
        params += args.ids
    elif not args.all:
        q += " AND event_date >= ?"
        params.append((datetime.date.today() - datetime.timedelta(days=args.days)).isoformat())
    events = conn.execute(q + " ORDER BY event_date, event_id", params).fetchall()
    print(f"verifying {len(events)} event(s) against RPH"
          f"{' (repair on)' if args.repair else ''}...", flush=True)

    def pull(eid):
        try:
            return eid, rph_event(eid), None
        except Exception as e:  # one flaky event must not sink the rest
            return eid, None, e

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        remote = {eid: (r, err) for eid, r, err in ex.map(pull, [e["event_id"] for e in events])}

    differ = fixed = unfixed = errors = 0
    for e in events:
        eid = e["event_id"]
        r, err = remote[eid]
        if err is not None or r is None:
            errors += 1
            print(f"\ne{eid} {e['event_date']} {e['store']}: couldn't read RPH ({err or '404'})")
            continue
        issues, fixable = compare(conn, eid, e["status"], r)
        if not issues:
            continue
        differ += 1
        print(f"\ne{eid} {e['event_date']} {e['store']}  [{e['status']}]")
        for i in issues:
            print(f"    {i}")
        if not fixable:
            continue
        why = protection(conn, eid)
        if why:
            unfixed += len(fixable)
            print(f"    -> protected: {why} (a person has corrected this event); repair leaves it")
            continue
        if not args.repair:
            print(f"    -> {len(fixable)} result(s) differ; --repair would take RPH's")
            continue
        with conn:
            n = sum(1 for row, p1, p2 in fixable if ing.sync_match_result(conn, row, p1, p2))
            if n and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                  "AND name='event_standings_official'").fetchone():
                # Standings fetched before the correction may describe the old
                # result; clearing them makes backfill_official_standings re-fetch.
                # (Protected events — locked ones included — never reach here.)
                conn.execute("DELETE FROM event_standings_official WHERE event_id=?", (eid,))
        fixed += n
        unfixed += len(fixable) - n
        print(f"    -> repaired {n} of {len(fixable)}"
              + ("" if n == len(fixable) else " (the rest: players no longer match; review)"))

    conn.close()
    print(f"\n{differ} of {len(events)} event(s) differ from RPH; "
          f"{fixed} result(s) repaired, {unfixed} left alone (protected, or players no "
          f"longer match), {errors} unreadable")
    if fixed:
        print("re-run flag_intentional_draws.py, elo.py and backfill_official_standings.py "
              "so the repaired results are classified, rated and re-ranked")


if __name__ == "__main__":
    main()
