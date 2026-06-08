"""Apply approved aliases from a CSV: set players.merged_into_id on the source
player to point at the target player.

Reads the CSV format produced by suggest_aliases.py. Only rows where
approve='y' are applied. Default is melee -> rph. The pair can point either
direction in principle (e.g. RPH alt account merged into a primary RPH account)
as long as the columns identify two existing player_ids.

Usage:
    python apply_aliases.py aliases_auto.csv
    python apply_aliases.py alias_suggestions.csv --dry-run
    python apply_aliases.py custom.csv --revert      # undo: clear merged_into_id
"""
import argparse, csv, sqlite3, sys
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def follow(conn, pid, seen=None):
    """Resolve a player_id to the final canonical id by following merged_into_id chain."""
    seen = seen or set()
    if pid in seen: return pid
    seen.add(pid)
    row = conn.execute(
        "SELECT merged_into_id FROM players WHERE player_id = ?", (pid,)
    ).fetchone()
    if row and row[0]:
        return follow(conn, row[0], seen)
    return pid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--revert", action="store_true",
                    help="clear merged_into_id on the source players in this CSV")
    args = ap.parse_args()

    p = Path(args.csv_path)
    if not p.exists():
        print(f"file not found: {p}", file=sys.stderr); sys.exit(1)

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    applied = skipped = errs = 0
    for ln, row in enumerate(csv.DictReader(open(p, encoding="utf-8")), 2):
        if (row.get("approve","").strip().lower() != "y"):
            skipped += 1; continue

        try:
            src = int(row["melee_player_id"])
            tgt = int(row["rph_player_id"])
        except (KeyError, ValueError):
            print(f"  line {ln}: bad player_id"); errs += 1; continue

        if src == tgt:
            print(f"  line {ln}: src == tgt, skipping"); skipped += 1; continue

        # follow target chain so we never point at an already-merged player
        canonical = follow(conn, tgt)
        if canonical == src:
            print(f"  line {ln}: would create cycle (src already canonical of tgt), skipping")
            errs += 1; continue

        if args.revert:
            if not args.dry_run:
                conn.execute("UPDATE players SET merged_into_id = NULL WHERE player_id = ?", (src,))
            print(f"  REVERT  src={src} ({row['melee_name']})")
            applied += 1
            continue

        # show what we're about to do
        existing = conn.execute(
            "SELECT merged_into_id FROM players WHERE player_id = ?", (src,)
        ).fetchone()
        if existing and existing[0]:
            print(f"  line {ln}: {row['melee_name']!r} already merged into player_id={existing[0]}, skipping")
            skipped += 1; continue

        if not args.dry_run:
            conn.execute(
                "UPDATE players SET merged_into_id = ? WHERE player_id = ?",
                (canonical, src),
            )
        print(f"  MERGE  melee:{row['melee_name']!r}  ->  rph:{row['rph_name']!r}  (conf={row['confidence']})")
        applied += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f"\napplied={applied}  skipped={skipped}  errors={errs}")
    if args.dry_run:
        print("(dry-run — no changes written)")


if __name__ == "__main__":
    main()
