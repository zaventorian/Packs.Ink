"""Backfill official per-event placements from the platform standings APIs.

Our locally-computed `event_rank` (in elo_event_standings_v) ranks by raw
`(points DESC, wins DESC)` and discards byes from the record. Real-world
standings use OMW% tiebreakers and respect bracket-cut champions, so the
official rank from RPH / melee can differ — sometimes putting the Final
winner correctly at #1 even when their raw points are tied with someone
who went 4-0 in Swiss then lost in SF.

This script fetches /tv/standings/ for every non-ignored event and writes
the official rank, full W/L/D record (including byes-as-wins), and the
OMW%/MW% tiebreaker percentages into elo_event_standings_official.

The view `elo_event_standings_v` then reads from this table first and
falls back to computed values for events we haven't backfilled.

Usage:
    python backfill_official_standings.py                 # everything
    python backfill_official_standings.py --season "..."  # one season
    python backfill_official_standings.py --event 387810  # one event
    python backfill_official_standings.py --workers 8 --force
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DB = Path(__file__).parent / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000
RPH_API = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}/tv/standings/"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def http_json(url: str, retries: int = 3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(0.4 * (i + 1))
    raise last


def ensure_local_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS event_standings_official (
        event_id      INTEGER NOT NULL,
        player_id     INTEGER NOT NULL,
        place         INTEGER NOT NULL,
        matches_won   INTEGER,
        matches_lost  INTEGER,
        matches_drawn INTEGER,
        match_points  INTEGER,
        mw_pct        REAL,
        omw_pct       REAL,
        gw_pct        REAL,
        fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
        PRIMARY KEY (event_id, player_id)
    );
    CREATE INDEX IF NOT EXISTS event_standings_official_event_idx
        ON event_standings_official (event_id);
    """)
    conn.commit()


def resolve_player_id(conn: sqlite3.Connection, platform: str, display_name: str) -> int | None:
    """Find the canonical player_id for a name. Follows merged_into_id chain."""
    row = conn.execute(
        "SELECT player_id, merged_into_id FROM players WHERE platform=? AND display_name=?",
        (platform, display_name),
    ).fetchone()
    if not row:
        return None
    pid, merged = row
    seen = set()
    while merged and merged not in seen:
        seen.add(pid); pid = merged
        nxt = conn.execute("SELECT merged_into_id FROM players WHERE player_id=?", (pid,)).fetchone()
        merged = nxt[0] if nxt else None
    return pid


def fetch_rph_event(event_id: int) -> list[dict] | None:
    """Returns list of standings dicts, or None on failure."""
    try:
        d = http_json(RPH_API.format(eid=event_id))
        return d.get("results") or []
    except Exception as e:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--event", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even events we've already backfilled")
    args = ap.parse_args()

    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    ensure_local_table(conn)

    q = """SELECT e.event_id, e.platform, e.season
           FROM events e WHERE e.is_ignored=0 AND e.platform='rph'"""
    params: list = []
    if args.season:
        q += " AND e.season=?"; params.append(args.season)
    if args.event:
        q += " AND e.event_id=?"; params.append(args.event)
    if not args.force:
        q += " AND NOT EXISTS (SELECT 1 FROM event_standings_official o WHERE o.event_id=e.event_id)"
    rows = conn.execute(q, params).fetchall()
    print(f"backfilling {len(rows)} RPH events with {args.workers} workers...")

    def work(eid: int):
        data = fetch_rph_event(eid)
        return eid, data

    inserted = unmatched = err = 0
    samples_unmatched = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, r["event_id"]): r["event_id"] for r in rows}
        done = 0
        for f in as_completed(futs):
            eid, data = f.result()
            done += 1
            if data is None:
                err += 1; continue
            if not data:
                continue  # event hasn't run yet; standings empty
            for s in data:
                name = s.get("tv_display_name")
                if not name: continue
                pid = resolve_player_id(conn, "rph", name)
                if pid is None:
                    unmatched += 1
                    if len(samples_unmatched) < 6:
                        samples_unmatched.append(f"e{eid}: {name}")
                    continue
                conn.execute(
                    """INSERT OR REPLACE INTO event_standings_official
                       (event_id, player_id, place, matches_won, matches_lost, matches_drawn,
                        match_points, mw_pct, omw_pct, gw_pct, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (eid, pid, s.get("rank"), s.get("matches_won"), s.get("matches_lost"),
                     s.get("matches_drawn"), s.get("total_match_points"),
                     round(100 * (s.get("match_win_percentage") or 0), 2),
                     round(100 * (s.get("opponent_match_win_percentage") or 0), 2),
                     round(100 * (s.get("game_win_percentage") or 0), 2)),
                )
                inserted += 1
            if done % 30 == 0:
                conn.commit()
                print(f"  ...{done}/{len(rows)}")
    conn.commit()
    print(f"\ninserted {inserted} standings rows  err={err}  unmatched={unmatched}")
    if samples_unmatched:
        print("first few unmatched names (likely melee handles that played an RPH event):")
        for s in samples_unmatched: print(f"  {s}")


if __name__ == "__main__":
    main()
