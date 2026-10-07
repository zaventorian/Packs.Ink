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

It runs in the weekly refresh (refresh_elo.py) as of 2026-09-28. Until then it
was manual-only and last run in July, so all 67 finished Attack of the Vine!
SCs went up with NO official standings: event pages ranked by raw points —
byes dropped from every record, no OMW%, and a points tie decided "champion"
alphabetically. Two rules make it safe to run unattended:

  * Only EVENT_FINISHED events with matches. An event is fetched once and never
    again (unless --force), so fetching one mid-play would freeze a partial
    table. --include-unfinished is for season-end finalisation by hand, when a
    TO ran every round but never closed the event.
  * Names resolve ONLY against the players who actually played THAT event
    (resolve_in_event), then by an exact and unique W-L-D record for a renamed
    account whose new name nobody has yet (pair_by_record). The old global,
    platform-filtered lookup missed a melee account at an RPH event (ingest
    matches on the name alone, so it reuses the melee player_id) and anyone
    parked as __pre_merge__<id>_<name> — and could land a renamed player on a
    second row made under the new name elsewhere.

Every run also re-keys rows whose player has since been merged
(recanonicalize_standings): the view joins on the canonical id, so those rows
were invisible. verify_results.py --repair clears an event's standings when it
corrects one of its results, so the next run re-fetches them.

Usage:
    python backfill_official_standings.py                 # everything
    python backfill_official_standings.py --season "..."  # one season
    python backfill_official_standings.py --event 387810  # one event
    python backfill_official_standings.py --workers 8 --force
    python backfill_official_standings.py --db copy.db    # a copy, not the live file
"""
from __future__ import annotations
import argparse, json, re, sqlite3, sys, time, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request

import ingest_melee  # opener + parse_rounds helper

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB = Path(__file__).parent / "lorcana_elo.db"
STASH = re.compile(r"^__pre_merge__\d+_(.+)$")
MELEE_OFFSET = 100_000_000
RPH_API = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}/tv/standings/"
MELEE_STANDINGS_URL = "https://melee.gg/Standing/GetRoundStandings"
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
        locked        INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (event_id, player_id)
    );
    CREATE INDEX IF NOT EXISTS event_standings_official_event_idx
        ON event_standings_official (event_id);
    """)
    # `locked` was added to the live DB by hand; the export reads it, so a DB
    # created from this function alone must have it too.
    if "locked" not in {r[1] for r in conn.execute("PRAGMA table_info(event_standings_official)")}:
        conn.execute("ALTER TABLE event_standings_official ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    conn.commit()


def canonical(conn: sqlite3.Connection, pid: int | None) -> int | None:
    """Follow the merged_into_id chain to the canonical player. Cycle-guarded."""
    seen = set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        nxt = conn.execute("SELECT merged_into_id FROM players WHERE player_id=?", (pid,)).fetchone()
        if not nxt or nxt[0] is None:
            return pid
        pid = nxt[0]
    return pid


def recanonicalize_standings(conn: sqlite3.Connection) -> tuple[int, int]:
    """Re-key rows whose player has since been merged into someone else. The view
    joins standings to ratings on the CANONICAL player, so a row keyed on a
    merged-away id is simply never shown — 162 were on 2026-09-28 (LoL_RamenShop's
    1st at 159335 among them), stranded by merges made after their event was
    backfilled. Only the key moves. If the canonical player already holds a row
    for that event, it wins — unless only the merged one is locked."""
    rows = conn.execute(
        """SELECT o.event_id, o.player_id, o.locked FROM event_standings_official o
           JOIN players p ON p.player_id = o.player_id
           WHERE p.merged_into_id IS NOT NULL""").fetchall()
    rekeyed = dropped = 0
    with conn:
        for eid, pid, locked in rows:
            can = canonical(conn, pid)
            if can == pid:
                continue  # a merge cycle resolves to itself; elo.py treats it the same way
            have = conn.execute("SELECT locked FROM event_standings_official "
                                "WHERE event_id=? AND player_id=?", (eid, can)).fetchone()
            if have is not None:
                if locked and not have[0]:
                    conn.execute("DELETE FROM event_standings_official "
                                 "WHERE event_id=? AND player_id=?", (eid, can))
                else:
                    conn.execute("DELETE FROM event_standings_official "
                                 "WHERE event_id=? AND player_id=?", (eid, pid))
                    dropped += 1
                    continue
            conn.execute("UPDATE event_standings_official SET player_id=? "
                         "WHERE event_id=? AND player_id=?", (can, eid, pid))
            rekeyed += 1
    return rekeyed, dropped


def event_name_index(conn: sqlite3.Connection, event_id: int) -> dict[str, int]:
    """name -> canonical player_id for everyone who has a match (or bye) in this
    event, under every name they are known by here: their row's name, their
    canonical's name, and the original name inside a __pre_merge__ stash. A name
    that points at two different people is dropped, so it is paired by record
    (pair_by_record) rather than guessed."""
    pids = {r[0] for r in conn.execute(
        "SELECT player1_id FROM matches WHERE event_id=? UNION "
        "SELECT player2_id FROM matches WHERE event_id=? AND player2_id IS NOT NULL",
        (event_id, event_id))}
    idx: dict[str, int] = {}
    clash: set[str] = set()
    for pid in pids:
        can = canonical(conn, pid)
        names = set()
        for p in {pid, can}:
            row = conn.execute("SELECT display_name FROM players WHERE player_id=?", (p,)).fetchone()
            if row and row[0]:
                names.add(row[0])
                m = STASH.match(row[0])
                if m:
                    names.add(m.group(1))
        for n in names:
            if n in idx and idx[n] != can:
                clash.add(n)
            idx.setdefault(n, can)
    for n in clash:
        idx.pop(n, None)
    return idx


def resolve_in_event(idx: dict[str, int], folded: dict[str, int], name: str) -> int | None:
    """Only ever a player who played THIS event. There is deliberately no lookup
    across the whole DB: a renamed account's new name can already belong to a
    separate row created at some other event (788186: "[IF] BrentsToys" is our
    Brents31, and the weekend's ingest had made a second player under the new
    name), so a global match finds the right person on the wrong row — which a
    later merge then strands. Anyone unresolved here goes to pair_by_record."""
    if name in idx:
        return idx[name]
    return folded.get(name.casefold())


def played(s: dict) -> bool:
    return (s["mw"] or 0) + (s["ml"] or 0) + (s["md"] or 0) > 0


def event_records(conn: sqlite3.Connection, event_id: int) -> dict[int, tuple[int, int, int]]:
    """(won, lost, drawn) per canonical player from the rows we hold for this
    event, a bye counting as a win the way the platform's standings count it."""
    rec: dict[int, list[int]] = {}
    for p1, p2, w, bye in conn.execute(
            "SELECT player1_id, player2_id, winner_id, is_bye FROM matches WHERE event_id=?",
            (event_id,)):
        c1 = canonical(conn, p1)
        if bye:
            rec.setdefault(c1, [0, 0, 0])[0] += 1
            continue
        if p2 is None:
            # A forfeit / no-show (single-competitor row that is not a bye) is a
            # LOSS for its player, as ingest_melee records it. Counted as a draw it
            # broke that player's record, and the opponent side resolved to a
            # None key that pair_by_record could try to write as player_id NULL.
            rec.setdefault(c1, [0, 0, 0])[1] += 1
            continue
        cw = canonical(conn, w) if w is not None else None
        for c in (c1, canonical(conn, p2)):
            r = rec.setdefault(c, [0, 0, 0])
            r[0 if cw == c else 2 if cw is None else 1] += 1
    return {k: tuple(v) for k, v in rec.items()}


def pair_by_record(conn, event_id: int, left: list[dict], assigned: set[int]) -> list[tuple[dict, int]]:
    """A renamed account's standings row carries its NEW name, which resolves to
    nobody who played until the rename pass catches up — and a backfilled event is
    never fetched again, so that placement would be lost for good (785295: "March
    8th" is our UglyCapybara39, 3rd at 4-2-1). A leftover row that played pairs
    with a player who played the event and has no row yet when their W-L-D is
    identical AND unique on both sides: no other leftover row, and no other
    unplaced player, has that record. Anything ambiguous stays unmatched."""
    rows = [s for s in left if played(s)]
    rec = event_records(conn, event_id)
    spare = {pid: r for pid, r in rec.items() if pid not in assigned}

    def key(s):
        return (s["mw"] or 0, s["ml"] or 0, s["md"] or 0)

    n_rows = Counter(key(s) for s in rows)
    n_spare = Counter(spare.values())
    return [(s, next(p for p, r in spare.items() if r == key(s)))
            for s in rows if n_rows[key(s)] == 1 and n_spare[key(s)] == 1]


def fetch_rph_event(event_id: int) -> list[dict] | None:
    """Returns list of normalized standings dicts, or None on failure.
    Each dict: name, rank, mw, ml, md, pts, mw_pct, omw_pct, gw_pct."""
    try:
        d = http_json(RPH_API.format(eid=event_id))
        out = []
        for s in (d.get("results") or []):
            out.append({
                "name":   s.get("tv_display_name"),
                "rank":   s.get("rank"),
                "mw":     s.get("matches_won"),
                "ml":     s.get("matches_lost"),
                "md":     s.get("matches_drawn"),
                "pts":    s.get("total_match_points"),
                "mw_pct": round(100 * (s.get("match_win_percentage") or 0), 2),
                "omw_pct":round(100 * (s.get("opponent_match_win_percentage") or 0), 2),
                "gw_pct": round(100 * (s.get("game_win_percentage") or 0), 2),
            })
        return out
    except Exception:
        return None


def fetch_melee_event(event_id: int) -> list[dict] | None:
    """Melee equivalent. Returns normalized standings using the final-round
    standings from /Standing/GetRoundStandings (the bracket-cut-aware ranking
    melee renders on the Standings tab)."""
    tid = event_id - MELEE_OFFSET
    try:
        opener = ingest_melee.make_opener()
        html = ingest_melee.fetch_html(opener, tid)
        rounds = ingest_melee.parse_rounds(html)
        if not rounds:
            return []
        # Iterate in REVERSE and use the most-recent round that has standings.
        # If a tournament's bracket round (e.g. SF) was started but never
        # finished, that round returns 0 standings but the prior round (QF)
        # still has the complete current rankings.
        opener.addheaders = [
            ("User-Agent", ingest_melee.UA),
            ("Accept", "application/json, text/javascript, */*; q=0.01"),
            ("X-Requested-With", "XMLHttpRequest"),
            ("Referer", f"https://melee.gg/Tournament/View/{tid}"),
            ("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"),
        ]
        d = None
        for rid, _ in reversed(rounds):
            form = {
                "draw": 1, "start": 0, "length": 500,
                "search[value]": "", "search[regex]": "false",
                "order[0][column]": 0, "order[0][dir]": "asc",
                "columns[0][data]": "Rank", "columns[0][name]": "",
                "columns[0][searchable]": "true", "columns[0][orderable]": "true",
                "columns[0][search][value]": "", "columns[0][search][regex]": "false",
                "roundId": rid,
            }
            req = Request(MELEE_STANDINGS_URL, data=urlencode(form).encode(), method="POST")
            with opener.open(req, timeout=30) as r:
                d_try = json.load(r)
            if d_try.get("data"):
                d = d_try
                break
        if d is None:
            return []
        out = []
        for s in d.get("data") or []:
            # Username is melee's stable identity; that's what we keyed players on.
            team_players = s.get("Team", {}).get("Players") or []
            if not team_players: continue
            uname = team_players[0].get("Username")
            if not uname: continue
            out.append({
                "name":    uname,
                "rank":    s.get("Rank"),
                "mw":      s.get("MatchWins"),
                "ml":      s.get("MatchLosses"),
                "md":      s.get("MatchDraws"),
                "pts":     s.get("Points"),
                "mw_pct":  None,  # melee doesn't expose match-win % directly,
                                  # leave null; the view falls back to compute.
                "omw_pct": round(100 * (s.get("OpponentMatchWinPercentage") or 0), 2),
                "gw_pct":  round(100 * (s.get("TeamGameWinPercentage") or 0), 2),
            })
        return out
    except Exception:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--event", type=int, default=None)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--force", action="store_true",
                    help="re-fetch even events we've already backfilled")
    ap.add_argument("--include-unfinished", action="store_true",
                    help="also fetch events the platform hasn't marked EVENT_FINISHED "
                         "(season-end finalisation by hand; see the module docstring)")
    ap.add_argument("--db", type=Path, default=DB)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db); conn.row_factory = sqlite3.Row
    ensure_local_table(conn)
    rekeyed, dropped = recanonicalize_standings(conn)
    if rekeyed or dropped:
        print(f"re-keyed {rekeyed} standings row(s) onto the merged player's canonical id"
              + (f"; dropped {dropped} the canonical already held" if dropped else ""))

    q = ("SELECT e.event_id, e.platform, e.season FROM events e WHERE e.is_ignored=0"
         " AND EXISTS (SELECT 1 FROM matches m WHERE m.event_id=e.event_id)")
    params: list = []
    if not args.include_unfinished:
        q += " AND e.status='EVENT_FINISHED'"
    if args.season:
        q += " AND e.season=?"; params.append(args.season)
    if args.event:
        q += " AND e.event_id=?"; params.append(args.event)
    if not args.force:
        q += " AND NOT EXISTS (SELECT 1 FROM event_standings_official o WHERE o.event_id=e.event_id)"
    # Locked events are ALWAYS skipped — even with --force. These hold hand-
    # corrected placements where the platform API returned garbage we don't
    # want to re-clobber (e.g. e276338's bogus Whispers SC Final). To re-fetch
    # a locked event, manually clear locked=0 in event_standings_official first.
    q += " AND NOT EXISTS (SELECT 1 FROM event_standings_official o WHERE o.event_id=e.event_id AND o.locked=1)"
    rows = conn.execute(q, params).fetchall()
    print(f"backfilling {len(rows)} events with {args.workers} workers (RPH + melee)...")

    def work(row):
        eid, plat = row["event_id"], row["platform"]
        if plat == "rph":
            return eid, plat, fetch_rph_event(eid)
        if plat == "melee":
            return eid, plat, fetch_melee_event(eid)
        return eid, plat, None

    inserted = unmatched = err = empty = collided = events_written = paired = never_played = 0
    samples_unmatched = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, r): r["event_id"] for r in rows}
        done = 0
        for f in as_completed(futs):
            eid, plat, data = f.result()
            done += 1
            if data is None:
                err += 1; continue
            if not data:
                empty += 1
                continue  # the platform has no standings for it (yet)
            idx = event_name_index(conn, eid)
            folded = {}
            for n, pid in idx.items():
                folded.setdefault(n.casefold(), pid)
            seen: set[int] = set()

            def put(s, pid):
                conn.execute(
                    """INSERT OR REPLACE INTO event_standings_official
                       (event_id, player_id, place, matches_won, matches_lost, matches_drawn,
                        match_points, mw_pct, omw_pct, gw_pct, fetched_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
                    (eid, pid, s["rank"], s["mw"], s["ml"], s["md"], s["pts"],
                     s["mw_pct"], s["omw_pct"], s["gw_pct"]),
                )

            # One event, one transaction. A re-fetch (--force) replaces the event's
            # table outright, so a player no longer listed can't linger; locked
            # events never get here.
            with conn:
                conn.execute("DELETE FROM event_standings_official WHERE event_id=? AND locked=0", (eid,))
                left: list[dict] = []
                for s in data:
                    name = s["name"]
                    if not name: continue
                    pid = resolve_in_event(idx, folded, name)
                    if pid is None:
                        left.append(s)
                        continue
                    if pid in seen:
                        collided += 1  # two standings names resolved to one player
                    seen.add(pid)
                    put(s, pid)
                    inserted += 1
                for s, pid in (pair_by_record(conn, eid, left, seen) if left else []):
                    put(s, pid)
                    seen.add(pid)
                    inserted += 1
                    paired += 1
                    left = [x for x in left if x is not s]
                for s in left:
                    if not played(s):
                        never_played += 1  # registered, played nothing: nothing to show
                        continue
                    unmatched += 1
                    if len(samples_unmatched) < 8:
                        rec = f"{s['mw'] or 0}-{s['ml'] or 0}-{s['md'] or 0}"
                        samples_unmatched.append(f"e{eid} [{plat}]: {s['name']} ({rec})")
            events_written += 1
            if done % 30 == 0:
                print(f"  ...{done}/{len(rows)}")
    print(f"\n{events_written} events written, {inserted} standings rows  "
          f"empty={empty}  err={err}  unmatched={unmatched}  collided={collided}  "
          f"paired-by-record={paired}  never-played={never_played}")
    if samples_unmatched:
        print("unmatched rows that played (W-L-D) — their placement falls back to the computed one:")
        for s in samples_unmatched: print(f"  {s}")


if __name__ == "__main__":
    main()
