"""Import manually-filled match results into the DB with source='manual'.

CSV columns expected (extras are ignored):
    event_id, round_number, table_number,
    player1_display_name, player2_display_name, winner_display_name,
    games_won_p1, games_won_p2

Blank rows and rows without both player names are skipped (template rows).

Idempotent: re-running with the same CSV won't duplicate matches. To overwrite
an entry, edit the CSV and pass --replace.

Usage:
    python apply_manual.py manual_results.csv
    python apply_manual.py manual_results.csv --replace
"""
import argparse, csv, sqlite3, sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def find_player(conn, name):
    name = name.strip()
    row = conn.execute(
        "SELECT player_id FROM players WHERE display_name = ?", (name,)
    ).fetchone()
    if row:
        return row["player_id"]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--replace", action="store_true",
                    help="overwrite existing manual entries for the same (event, round, table)")
    ap.add_argument("--create-missing-players", action="store_true",
                    help="create players that aren't already in the DB (off by default — warns instead)")
    args = ap.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"file not found: {csv_path}", file=sys.stderr); sys.exit(1)

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    inserted = skipped = errors = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for ln, row in enumerate(rdr, 2):
            p1n = (row.get("player1_display_name") or "").strip()
            p2n = (row.get("player2_display_name") or "").strip()
            if not p1n or not p2n:
                skipped += 1
                continue

            try:
                eid = int(row["event_id"])
                rnum = int(row["round_number"])
                tnum = int(row["table_number"]) if (row.get("table_number") or "").strip() else None
            except (KeyError, ValueError) as e:
                print(f"  line {ln}: bad number — {e}"); errors += 1; continue

            wn = (row.get("winner_display_name") or "").strip()
            gw1 = row.get("games_won_p1"); gw1 = int(gw1) if (gw1 or "").strip() else None
            gw2 = row.get("games_won_p2"); gw2 = int(gw2) if (gw2 or "").strip() else None

            # look up players
            def lookup(n):
                pid = find_player(conn, n)
                if pid is None:
                    if args.create_missing_players:
                        cur = conn.execute(
                            "INSERT INTO players (display_name, first_event_id) VALUES (?, ?)",
                            (n, eid),
                        )
                        return cur.lastrowid
                    return None
                return pid

            p1_id = lookup(p1n); p2_id = lookup(p2n)
            if p1_id is None or p2_id is None:
                missing = [n for n, pid in [(p1n, p1_id), (p2n, p2_id)] if pid is None]
                print(f"  line {ln}: player not found: {missing} (use --create-missing-players to add)")
                errors += 1; continue

            winner_id = None
            if wn:
                if wn == p1n: winner_id = p1_id
                elif wn == p2n: winner_id = p2_id
                else:
                    print(f"  line {ln}: winner '{wn}' is neither p1 nor p2"); errors += 1; continue

            # find a fake round_id — we don't have the real RB round id, so synthesize
            # one keyed on (event_id, round_number). Negative to avoid colliding with RB ids.
            round_id = -((eid % 100_000_000) * 100 + rnum)  # avoid int32 overflow for melee event_ids

            # check existing
            existing = conn.execute(
                """SELECT match_id, source FROM matches
                   WHERE event_id=? AND round_id=? AND table_number IS ?""",
                (eid, round_id, tnum),
            ).fetchone()
            if existing and not args.replace:
                print(f"  line {ln}: already present (match_id={existing['match_id']}, source={existing['source']}) — use --replace to overwrite")
                skipped += 1; continue
            if existing and args.replace:
                conn.execute("DELETE FROM matches WHERE match_id = ?", (existing["match_id"],))

            conn.execute(
                """INSERT INTO matches
                   (event_id, round_id, round_number, round_type, table_number,
                    player1_id, player2_id, winner_id, games_won_p1, games_won_p2,
                    is_bye, source)
                   VALUES (?, ?, ?, 'PLAY_VS_OPPONENT', ?, ?, ?, ?, ?, ?, 0, 'manual')""",
                (eid, round_id, rnum, tnum, p1_id, p2_id, winner_id, gw1, gw2),
            )
            inserted += 1

    # recompute filled_matches counter on gap_rounds
    conn.execute("""
        UPDATE gap_rounds
        SET filled_matches = (
            SELECT COUNT(*) FROM matches m
            WHERE m.event_id = gap_rounds.event_id
              AND m.round_number = gap_rounds.round_number
              AND m.source = 'manual'
        )
    """)
    conn.commit()

    print(f"\ninserted={inserted}  skipped={skipped}  errors={errors}")

    # report remaining gaps
    remaining = conn.execute("""
        SELECT e.event_id, e.store, g.round_number, g.phase_type, g.filled_matches
        FROM gap_rounds g JOIN events e ON e.event_id = g.event_id
        WHERE e.is_ignored = 0 AND g.filled_matches = 0
        ORDER BY e.event_date, g.round_number
    """).fetchall()
    if remaining:
        print(f"\nstill-empty gap rounds: {len(remaining)}")
        for r in remaining:
            print(f"  e{r['event_id']} {r['store'][:25]:<25} R{r['round_number']} ({r['phase_type']})")
    else:
        print("\nall gap rounds have at least one manual entry. Re-run elo.py to update ratings.")


if __name__ == "__main__":
    main()
