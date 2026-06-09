"""Ingest melee.gg tournament events into the same DB as the RPH events.

Melee tournament IDs are stored with a +100,000,000 offset to avoid collision
with RPH event IDs (both use raw integers in the same value range).

Usage:
    python ingest_melee.py --xlsx "C:\\path\\to\\Archazia.xlsx" --season "Archazia Spring 2025"
    python ingest_melee.py --ids 294389 279848 ...
"""
import argparse, json, re, sqlite3, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor

HERE = Path(__file__).parent
DB_PATH = HERE / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


def make_opener():
    cj = CookieJar()
    o = build_opener(HTTPCookieProcessor(cj))
    return o


def fetch_html(opener, tid):
    opener.addheaders = [("User-Agent", UA), ("Accept", "text/html")]
    with opener.open(f"https://melee.gg/Tournament/View/{tid}", timeout=30) as r:
        return r.read().decode("utf-8", errors="ignore")


def parse_rounds(html):
    """Return list of (round_id, round_name) from .round-selector buttons."""
    seen, seen_set = [], set()
    for m in re.finditer(
        r'<button[^>]*class="[^"]*round-selector[^"]*"[^>]*data-id="(\d+)"[^>]*data-name="([^"]+)"',
        html,
    ):
        rid = int(m.group(1)); name = m.group(2)
        if rid not in seen_set:
            seen.append((rid, name))
            seen_set.add(rid)
    return seen


def fetch_round_matches(opener, tid, rid):
    # melee's endpoint 500s without at least one columns[*] block in the form data
    form = {
        "draw": 1, "start": 0, "length": 500,
        "search[value]": "", "search[regex]": "false",
        "order[0][column]": 0, "order[0][dir]": "asc",
        "columns[0][data]": "TableNumber", "columns[0][name]": "",
        "columns[0][searchable]": "true", "columns[0][orderable]": "true",
        "columns[0][search][value]": "", "columns[0][search][regex]": "false",
    }
    opener.addheaders = [
        ("User-Agent", UA),
        ("Accept", "application/json, text/javascript, */*; q=0.01"),
        ("X-Requested-With", "XMLHttpRequest"),
        ("Referer", f"https://melee.gg/Tournament/View/{tid}"),
        ("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"),
    ]
    req = Request(
        f"https://melee.gg/Match/GetRoundMatches/{rid}",
        data=urlencode(form).encode(),
        method="POST",
    )
    with opener.open(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def get_or_create_melee_player(conn, username, display_name, first_event_id):
    row = conn.execute(
        "SELECT player_id FROM players WHERE platform='melee' AND display_name = ?",
        (username,),
    ).fetchone()
    if row:
        return row["player_id"]
    extra = display_name if (display_name and display_name != username) else None
    cur = conn.execute(
        """INSERT INTO players (display_name, platform, external_username, first_event_id)
           VALUES (?, 'melee', ?, ?)""",
        (username, extra, first_event_id),
    )
    return cur.lastrowid


def ingest_one(tid, store=None, location=None, event_date=None, season=None):
    conn = db()
    try:
        event_id = MELEE_OFFSET + tid
        # honor manual ignore
        row = conn.execute("SELECT is_ignored FROM events WHERE event_id = ?", (event_id,)).fetchone()
        if row and row["is_ignored"]:
            return tid, "skip", "ignored"
        if conn.execute("SELECT 1 FROM matches WHERE event_id = ? LIMIT 1", (event_id,)).fetchone():
            return tid, "skip", "already ingested"

        opener = make_opener()
        html = fetch_html(opener, tid)
        title_m = re.search(r"<title>([^<|]+)", html)
        name = title_m.group(1).strip() if title_m else f"Melee {tid}"

        rounds = parse_rounds(html)
        if not rounds:
            return tid, "skip", "no rounds visible (private/cancelled?)"

        round_payloads = [(rid, rname, fetch_round_matches(opener, tid, rid)) for rid, rname in rounds]

        with conn:
            conn.execute(
                """INSERT OR REPLACE INTO events
                   (event_id, name, store, location, event_date, season, num_players, status, platform)
                   VALUES (?, ?, ?, ?, ?, ?, NULL, 'EVENT_FINISHED', 'melee')""",
                (event_id, name, store, location, event_date, season),
            )
            total_matches = 0
            for rid, rname, payload in round_payloads:
                matches = payload.get("data", [])
                # round number: prefer the API's RoundNumber over parsing rname
                round_number = None
                if matches:
                    round_number = matches[0].get("RoundNumber")
                if round_number is None:
                    rn_m = re.search(r"(\d+)", rname or "")
                    round_number = int(rn_m.group(1)) if rn_m else 0
                for m in matches:
                    table_number = m.get("TableNumber")
                    competitors = m.get("Competitors", [])

                    if len(competitors) < 2:
                        # Single-competitor row — could be a bye OR a forfeit:
                        #   ByeReason set  → real algorithm-assigned bye (no ELO, counts as W)
                        #   LossReason set → forfeit / no-show (no ELO, counts as L)
                        # We distinguish via the `source` column so the display
                        # layer can show "BYE" vs "LOSS (forfeit)" correctly.
                        if competitors and competitors[0].get("Team", {}).get("Players"):
                            p = competitors[0]["Team"]["Players"][0]
                            pid = get_or_create_melee_player(
                                conn, p["Username"], p.get("DisplayName"), event_id
                            )
                            is_forfeit = (m.get("LossReason") is not None
                                          and m.get("ByeReason") is None)
                            if is_forfeit:
                                conn.execute(
                                    """INSERT OR IGNORE INTO matches
                                       (event_id, round_id, round_number, round_type, table_number,
                                        player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source)
                                       VALUES (?, ?, ?, 'PLAY_VS_OPPONENT', ?, ?, NULL, NULL, NULL, NULL, 0, 'forfeit')""",
                                    (event_id, rid, round_number, table_number, pid),
                                )
                            else:
                                conn.execute(
                                    """INSERT OR IGNORE INTO matches
                                       (event_id, round_id, round_number, round_type, table_number,
                                        player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source)
                                       VALUES (?, ?, ?, 'PLAY_VS_OPPONENT', ?, ?, NULL, ?, NULL, NULL, 1, 'api')""",
                                    (event_id, rid, round_number, table_number, pid, pid),
                                )
                            total_matches += 1
                        continue

                    c1, c2 = competitors[0], competitors[1]
                    pl1 = c1.get("Team", {}).get("Players", [{}])[0]
                    pl2 = c2.get("Team", {}).get("Players", [{}])[0]
                    u1, u2 = pl1.get("Username"), pl2.get("Username")
                    if not u1 or not u2:
                        continue
                    p1_id = get_or_create_melee_player(conn, u1, pl1.get("DisplayName"), event_id)
                    p2_id = get_or_create_melee_player(conn, u2, pl2.get("DisplayName"), event_id)
                    # Game scores: prefer GameWinsAndGameByes (filled in even when
                    # the loser's GameWins is null because they didn't confirm
                    # the result), fall back to GameWins.
                    gw1 = c1.get("GameWinsAndGameByes")
                    if gw1 is None: gw1 = c1.get("GameWins")
                    gw2 = c2.get("GameWinsAndGameByes")
                    if gw2 is None: gw2 = c2.get("GameWins")
                    # Winner: ResultString is authoritative ("Username won 2-0-0"
                    # / "Draw 1-1-1" / ""). Falling back to GameWins alone marked
                    # thousands of decided matches as draws because the loser's
                    # GameWins came back null when they didn't confirm the result.
                    rs = (m.get("ResultString") or "").strip()
                    rs_low = rs.lower()
                    winner_id = None
                    if m.get("HasResult"):
                        if rs_low.startswith("draw"):
                            winner_id = None  # explicit draw
                        elif rs_low.startswith(f"{(u1 or '').lower()} won"):
                            winner_id = p1_id
                        elif rs_low.startswith(f"{(u2 or '').lower()} won"):
                            winner_id = p2_id
                        elif gw1 is not None and gw2 is not None:
                            if gw1 > gw2: winner_id = p1_id
                            elif gw2 > gw1: winner_id = p2_id
                    conn.execute(
                        """INSERT OR IGNORE INTO matches
                           (event_id, round_id, round_number, round_type, table_number,
                            player1_id, player2_id, winner_id, games_won_p1, games_won_p2, is_bye, source)
                           VALUES (?, ?, ?, 'PLAY_VS_OPPONENT', ?, ?, ?, ?, ?, ?, 0, 'api')""",
                        (event_id, rid, round_number, table_number,
                         p1_id, p2_id, winner_id, gw1, gw2),
                    )
                    total_matches += 1

        return tid, "ok", f"{name[:50]} ({len(rounds)} rounds, {total_matches} matches)"
    except Exception as e:
        return tid, "err", repr(e)
    finally:
        conn.close()


def load_melee_xlsx(path):
    """Yield (tournament_id, store, location, event_date) from xlsx using melee.gg URLs.

    Searches for a melee.gg/Tournament/View/{id} link in any column."""
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.worksheets[0]
    for r in ws.iter_rows(min_row=2, values_only=False):
        date_val = r[0].value if len(r) > 0 else None
        store = r[2].value if len(r) > 2 else None
        loc = r[3].value if len(r) > 3 else None
        for c in r:
            link = (c.hyperlink.target if c.hyperlink else None) or c.value
            if not isinstance(link, str): continue
            m = re.search(r"melee\.gg/Tournament/View/(\d+)", link)
            if m:
                tid = int(m.group(1))
                date_iso = date_val.date().isoformat() if hasattr(date_val, "date") else None
                yield tid, store, loc, date_iso
                break


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx")
    ap.add_argument("--ids", nargs="*", type=int, default=[])
    ap.add_argument("--season", default=None)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    work = []
    if args.xlsx:
        work.extend(load_melee_xlsx(args.xlsx))
    for tid in args.ids:
        work.append((tid, None, None, None))
    if not work:
        print("no tournaments to ingest. pass --xlsx or --ids."); sys.exit(1)

    print(f"ingesting {len(work)} melee tournaments with {args.workers} workers...")
    ok = skip = err = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ingest_one, *w, args.season): w[0] for w in work}
        for f in as_completed(futs):
            tid, status, msg = f.result()
            tag = {"ok": "OK  ", "skip": "SKIP", "err": "ERR "}[status]
            print(f"  {tag} {tid}  {msg}")
            if status == "ok": ok += 1
            elif status == "skip": skip += 1
            else: err += 1

    print(f"\nDone. ok={ok} skip={skip} err={err}")


if __name__ == "__main__":
    main()
