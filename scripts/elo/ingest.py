"""Ingest Ravensburger Lorcana tournament events into SQLite.

Usage:
    python ingest.py --xlsx "C:\\path\\to\\events.xlsx" --season "Fabled Fall 2025"
    python ingest.py --ids 198237 203889 ...
    python ingest.py --urls https://tcg.ravensburgerplay.com/events/198237 ...

Idempotent: re-running skips events that already have matches recorded.
Exits 1 when any event fails to ingest.
"""
import argparse, json, re, sqlite3, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).parent
DB_PATH = HERE / "lorcana_elo.db"
SCHEMA = HERE / "schema.sql"
API = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}"
API_META = "https://api.ravensburgerplay.com/api/v2/events/{eid}/"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def http_get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    raise last


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript(SCHEMA.read_text())
    conn.commit()
    conn.close()


def get_or_create_player(conn, display_name, first_event_id):
    row = conn.execute(
        "SELECT player_id FROM players WHERE display_name = ?", (display_name,)
    ).fetchone()
    if row:
        return row["player_id"]
    cur = conn.execute(
        "INSERT INTO players (display_name, first_event_id) VALUES (?, ?)",
        (display_name, first_event_id),
    )
    return cur.lastrowid


def event_already_ingested(conn, event_id):
    """Skip an event only if it's FINISHED on the platform AND we already have
    matches for it. In-progress / not-started events keep getting re-pulled on
    weekly refreshes so newly entered rounds land in our DB."""
    row = conn.execute(
        """SELECT e.status, EXISTS(SELECT 1 FROM matches m WHERE m.event_id=e.event_id) AS has_matches
           FROM events e WHERE e.event_id = ?""", (event_id,),
    ).fetchone()
    if not row:
        return False
    return row["status"] == "EVENT_FINISHED" and bool(row["has_matches"])


def match_is_complete(m):
    """RPH gives every match its own status. A match in a round still being
    played comes back with its pairing but no result, and storing it then
    records a 0-0 no-winner row — which reads exactly like an agreed draw (0-0
    is always an ID) and could never be replaced afterwards, because the
    (round, table) guard in ingest_event skips a table we already hold. Found
    2026-09-28 at HoneyBee Games (919790): two semifinals captured mid-round by
    the 9/13 refresh sat in the DB as 0-0 draws while RPH recorded 2-1 wins.
    A payload with no status at all keeps the old behaviour."""
    st = m.get("status")
    return st is None or st == "COMPLETE"


def canonical_id(conn, pid):
    """Follow merged_into_id to the canonical player. Cycle-guarded."""
    seen = set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        row = conn.execute("SELECT merged_into_id FROM players WHERE player_id=?", (pid,)).fetchone()
        if not row or row[0] is None:
            return pid
        pid = row[0]
    return pid


def _name_ids(conn, name):
    """Canonical ids of every player stored under exactly this name, any platform
    (get_or_create_player matches on the name alone, so this must too)."""
    return {canonical_id(conn, r[0]) for r in conn.execute(
        "SELECT player_id FROM players WHERE display_name = ?", (name,))}


def same_players(conn, row, p1, p2):
    """Is the RPH pairing at this table still the pair stored in `row`? Each side
    must resolve to the stored player (following merges) or be a name we have
    never seen — a rename not applied yet — and at least one side must match
    positively. A name that resolves to someone ELSE means the table was
    re-paired, and moving a result onto the wrong two players is worse than
    leaving it alone."""
    matched = 0
    for p, stored in ((p1, row["player1_id"]), (p2, row["player2_id"])):
        ids = _name_ids(conn, p.get("tv_display_name"))
        if not ids:
            continue
        if canonical_id(conn, stored) not in ids:
            return False
        matched += 1
    return matched > 0


def sync_match_result(conn, row, p1, p2):
    """Bring a stored match's RESULT in line with a COMPLETE RPH match at the same
    (round, table): winner and games only, never the players, and never a row a
    person entered (source != 'api'). Covers a result captured before it was
    final and one the TO corrected after the fact (707597, the 6/28 Critical
    Games final, was re-scored on RPH after we pulled it). True if it changed."""
    if row["source"] != "api":
        return False
    side = 1 if p1.get("is_winner") else 2 if p2.get("is_winner") else None
    want = (row["player1_id"] if side == 1 else row["player2_id"] if side == 2 else None,
            p1.get("games_won"), p2.get("games_won"))
    if (row["winner_id"], row["games_won_p1"], row["games_won_p2"]) == want:
        return False
    if not same_players(conn, row, p1, p2):
        return False
    conn.execute("UPDATE matches SET winner_id=?, games_won_p1=?, games_won_p2=? WHERE match_id=?",
                 (*want, row["match_id"]))
    return True


# An UPSERT, never INSERT OR REPLACE. REPLACE deletes the old row and inserts a
# new one, so every column not listed here went back to its default on each
# re-pull: `notes` (the mark that keeps verify_results --repair off an event a
# person corrected), `platform`, `is_ignored`, `ingested_at`. RPH's own fields
# follow RPH; a metadata field the caller doesn't know (None) keeps what we hold.
UPSERT_EVENT_SQL = """
    INSERT INTO events (event_id, name, store, location, event_date, season, num_players, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(event_id) DO UPDATE SET
      name        = excluded.name,
      store       = COALESCE(excluded.store, events.store),
      location    = COALESCE(excluded.location, events.location),
      event_date  = COALESCE(excluded.event_date, events.event_date),
      season      = COALESCE(excluded.season, events.season),
      num_players = COALESCE(excluded.num_players, events.num_players),
      status      = COALESCE(excluded.status, events.status)
"""


def ingest_event(event_id, store=None, location=None, event_date=None, season=None):
    """Pull one event + all its rounds and write to DB. Idempotent at event level."""
    conn = db()
    try:
        # Honor manual ignore flag — don't re-pull events the user marked as did-not-run
        row = conn.execute("SELECT is_ignored FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row and row["is_ignored"]:
            return event_id, "skip", "ignored (marked did-not-run)"
        if event_already_ingested(conn, event_id):
            return event_id, "skip", "already ingested"

        tv = http_get(API.format(eid=event_id) + "/tv/")
        name = tv["name"]
        status = tv.get("lifecycle_status")
        num_players = tv.get("starting_player_count")
        phases = tv.get("tournament_phases", [])

        # --ids / --urls mode supplies none of the event's metadata, so take what
        # the events API knows. The store matters as much as the date: without it
        # a hand-added event is stored with store=NULL and renders nameless in
        # every list that shows one. (The xlsx and discovery paths pass both, so
        # this only fills the gap the manual paths leave.)
        if event_date is None or store is None:
            try:
                meta = http_get(API_META.format(eid=event_id))
                if event_date is None:
                    raw_dt = meta.get("start_datetime") or ""
                    if raw_dt:
                        event_date = raw_dt[:10]  # "2026-06-13T15:00:00+00:00" → "2026-06-13"
                if store is None:
                    store = (meta.get("store") or {}).get("name") or None
            except Exception:
                pass

        # collect all rounds with their type label + parent phase type (SWISS vs RANKED_SINGLE_ELIMINATION)
        all_rounds = []  # (round_id, round_number, round_type, phase_type, round_status)
        for ph in phases:
            ph_type = ph.get("round_type")  # API stores phase 'type' under round_type at phase level
            for r in ph.get("rounds", []):
                all_rounds.append((r["id"], r["round_number"], r.get("round_type"), ph_type, r.get("status")))

        # If the event hasn't run yet (or has no exposed rounds), still record
        # the event metadata so future refreshes know to come back. The first
        # time we ingest a not-yet-played event we want it queued, not skipped.
        if not all_rounds:
            with conn:
                conn.execute(
                    UPSERT_EVENT_SQL,
                    (event_id, name, store, location, event_date, season, num_players, status),
                )
            return event_id, "queue", f"{name} (no rounds yet — queued for refresh)"

        # pull all rounds. An UPCOMING round that hasn't started yet (e.g. the
        # finals of a top cut while the semis are still running) has no matches
        # endpoint — RPH 404s it. Skip that one round instead of letting it abort
        # the whole event; it fills in on a later refresh once the round starts.
        # (Without this, any event mid-top-cut fails to ingest entirely.)
        round_payloads = {}
        for rid, _, _, _, _ in all_rounds:
            url = API.format(eid=event_id) + f"/tv/matches/?round_id={rid}"
            try:
                round_payloads[rid] = http_get(url)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    round_payloads[rid] = {"results": []}
                else:
                    raise

        # write everything in one transaction
        with conn:
            conn.execute(
                UPSERT_EVENT_SQL,
                (event_id, name, store, location, event_date, season, num_players, status),
            )

            # Dedup guard against a player's display-name spelling changing between
            # re-ingests of a not-yet-finished event. A changed name -> new
            # player_id, so the UNIQUE(...,player1_id) key no longer collides and
            # INSERT OR IGNORE would add a SECOND row for the same physical match
            # (there is exactly one table per round). Skip any (round, table) we
            # already have. Bit "LoL_METALLICFLARE" vs "LoL METALLICFLARE" once —
            # double-counted whole rounds across two pulls.
            existing_rt = {(r["round_id"], r["table_number"]): r for r in conn.execute(
                "SELECT match_id, round_id, table_number, player1_id, player2_id, winner_id, "
                "games_won_p1, games_won_p2, source FROM matches "
                "WHERE event_id=? AND is_bye=0 AND table_number IS NOT NULL", (event_id,))}

            # Byes need the same guard, by COUNT: RPH seats every bye at table -1
            # and a renamed bye-holder resolves to a new player_id, so the UNIQUE
            # key never collides and each re-pull of an unfinished event added a
            # second bye for the same seat (675962, Gemini Games 6/14: one R1 bye on
            # RPH, two in the DB under the holder's old and interim names). A round
            # only gains byes while it holds fewer than RPH shows.
            byes_held = {}
            for r in conn.execute(
                    "SELECT round_id, player1_id FROM matches WHERE event_id=? AND is_bye=1",
                    (event_id,)):
                byes_held.setdefault(r["round_id"], set()).add(r["player1_id"])

            unreported = corrected = 0
            for rid, rnum, rtype, phase_type, rstatus in all_rounds:
                d = round_payloads[rid]
                results = d.get("results", [])
                held = byes_held.setdefault(rid, set())
                bye_room = sum(1 for m in results
                               if m.get("match_is_bye") and m.get("players")) - len(held)
                for m in results:
                    players = m.get("players", [])
                    is_bye = bool(m.get("match_is_bye"))

                    if is_bye:
                        if not players or bye_room <= 0:
                            continue
                        p = players[0]
                        pid = get_or_create_player(conn, p["tv_display_name"], event_id)
                        if pid in held:
                            continue
                        conn.execute(
                            """INSERT OR IGNORE INTO matches
                               (event_id, round_id, round_number, round_type, table_number,
                                player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye)
                               VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, 1)""",
                            (event_id, rid, rnum, rtype, m.get("table_number"),
                             pid, pid, p.get("games_won")),
                        )
                        held.add(pid)
                        bye_room -= 1
                        continue

                    if len(players) < 2:
                        continue
                    if not match_is_complete(m):
                        unreported += 1  # fills in on the next pull; see match_is_complete
                        continue
                    tnum = m.get("table_number")
                    p1, p2 = sorted(players, key=lambda p: p.get("player_order") or 0)
                    if tnum is not None and (rid, tnum) in existing_rt:
                        # Same physical match already recorded (see guard above) —
                        # but its result may since have been finalised or corrected.
                        if sync_match_result(conn, existing_rt[(rid, tnum)], p1, p2):
                            corrected += 1
                        continue
                    p1_id = get_or_create_player(conn, p1["tv_display_name"], event_id)
                    p2_id = get_or_create_player(conn, p2["tv_display_name"], event_id)
                    winner_id = None
                    if p1.get("is_winner"):
                        winner_id = p1_id
                    elif p2.get("is_winner"):
                        winner_id = p2_id
                    conn.execute(
                        """INSERT OR IGNORE INTO matches
                           (event_id, round_id, round_number, round_type, table_number,
                            player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                        (event_id, rid, rnum, rtype, tnum,
                         p1_id, p2_id, winner_id,
                         p1.get("games_won"), p2.get("games_won")),
                    )

        # Record gaps: COMPLETE rounds with 0 exposed matches.
        # Even the API marks them complete, but no pairings were entered.
        gaps = 0
        with conn:
            for rid, rnum, rtype, phase_type, rstatus in all_rounds:
                n_in_db = conn.execute(
                    "SELECT COUNT(*) FROM matches WHERE event_id = ? AND round_id = ?",
                    (event_id, rid),
                ).fetchone()[0]
                if n_in_db == 0 and rstatus == "COMPLETE":
                    conn.execute(
                        """INSERT OR REPLACE INTO gap_rounds
                           (event_id, round_id, round_number, phase_type, expected_matches, filled_matches)
                           VALUES (?, ?, ?, ?, NULL, 0)""",
                        (event_id, rid, rnum, phase_type),
                    )
                    gaps += 1

        extra = (f", {unreported} unreported" if unreported else "") + \
                (f", {corrected} corrected" if corrected else "")
        return event_id, "ok", f"{name} ({len(all_rounds)} rounds, {gaps} gaps{extra})"
    except Exception as e:
        return event_id, "err", repr(e)
    finally:
        conn.close()


def load_from_xlsx(path):
    """Yield (event_id, store, location, event_date) tuples from the user's spreadsheet.

    Auto-detects the data sheet by looking for a row whose column A says 'Date'
    and column G says 'Play Hub Link' (case-insensitive). The user's per-season
    spreadsheets use either 'Events' or 'Sheet1' as the sheet name and sometimes
    reorder middle columns — but col A (date), C (store), D (location), G (link)
    have been stable across files."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)

    # Map known header tokens to canonical column names. We accept several
    # variants because the spreadsheet maintainers reorganize columns between
    # seasons (e.g. ROJ had a "Location" column; Wilds Unknown split it into
    # City + State; Whispers used "Play Hub Link" while Wilds Unknown uses
    # "Registration Link"). Auto-detecting the layout instead of hardcoding
    # column positions means new season files just work.
    def find_layout(ws):
        for i, row in enumerate(ws.iter_rows(min_row=1, max_row=10, values_only=True), 1):
            cols = {}
            for j, cell in enumerate(row):
                if not isinstance(cell, str): continue
                h = cell.strip().lower()
                if h.startswith("date"):                                  cols["date"]  = j
                elif h in ("store", "store name"):                        cols["store"] = j
                elif h == "city":                                         cols["city"]  = j
                elif h == "state":                                        cols["state"] = j
                elif h == "location":                                     cols["location"] = j
                elif h in ("play hub link", "registration link", "event link"):
                    cols["link"] = j
            if "date" in cols and "link" in cols:
                return i, cols
        return None, {}

    ws = None; hdr = None; cols = {}
    for candidate in wb.worksheets:
        h, c = find_layout(candidate)
        if h is not None:
            ws = candidate; hdr = h; cols = c; break
    if ws is None:
        raise ValueError(f"no data sheet found in {path} (need a header row with Date + Play Hub Link / Registration Link)")

    for r in ws.iter_rows(min_row=hdr + 1, values_only=False):
        if cols["link"] >= len(r):
            continue
        g = r[cols["link"]]
        link = (g.hyperlink.target if g.hyperlink else None) or g.value
        if not isinstance(link, str):
            continue
        m = re.search(r"/events/(\d+)", link)
        if not m:
            continue
        eid = int(m.group(1))
        date_val = r[cols["date"]].value if cols.get("date") is not None else None
        date_iso = date_val.date().isoformat() if hasattr(date_val, "date") else None
        store = r[cols["store"]].value if cols.get("store") is not None else None
        # Build location from City + State (new format) or the single Location cell (old).
        if "city" in cols:
            city = r[cols["city"]].value if cols["city"] < len(r) else None
            state = r[cols["state"]].value if "state" in cols and cols["state"] < len(r) else None
            loc = f"{city}, {state}" if (city and state) else (city or state or None)
        elif "location" in cols and cols["location"] < len(r):
            loc = r[cols["location"]].value
        else:
            loc = None
        yield eid, store, loc, date_iso


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", help="path to spreadsheet (uses col G for event URLs)")
    ap.add_argument("--ids", nargs="*", type=int, default=[])
    ap.add_argument("--urls", nargs="*", default=[])
    ap.add_argument("--season", default=None, help="season label to tag events with")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    init_db()
    work = []  # list of (eid, store, loc, date)
    if args.xlsx:
        work.extend(load_from_xlsx(args.xlsx))
    for eid in args.ids:
        work.append((eid, None, None, None))
    for u in args.urls:
        m = re.search(r"/events/(\d+)", u)
        if m:
            work.append((int(m.group(1)), None, None, None))

    if not work:
        print("no events to ingest. pass --xlsx, --ids, or --urls.", file=sys.stderr)
        sys.exit(1)

    print(f"ingesting {len(work)} events with {args.workers} workers...")
    counts = {"ok": 0, "skip": 0, "err": 0, "queue": 0}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(ingest_event, eid, store, loc, date, args.season): eid
            for eid, store, loc, date in work
        }
        for f in as_completed(futs):
            eid, status, msg = f.result()
            tag = {"ok":"OK  ","skip":"SKIP","err":"ERR ","queue":"QUEUE"}[status]
            print(f"  {tag} {eid}  {msg}")
            counts[status] += 1

    print(f"\nDone. ok={counts['ok']} queue={counts['queue']} skip={counts['skip']} err={counts['err']}")
    # Non-zero on any failed event. ingest_event turns an exception into "err",
    # so without this a failed --ids one-off inside refresh_elo.py ended green.
    # (refresh_elo runs the season-sheet ingest soft, so this can't cost a week.)
    if counts["err"]:
        sys.exit(f"{counts['err']} event(s) failed to ingest - see the ERR lines above")


if __name__ == "__main__":
    main()
