"""Apply approved RPH renames detected by detect_renames.py.

For each row with approve='y', we:
  1. Take db_player_id (the existing canonical record we want to keep)
  2. Rename it to candidate_new_name

If another player already has candidate_new_name (because we ingested a fresh
event under that name before running the detector), we merge that "new" record
INTO the old player_id first — so the old id stays canonical with full history,
absorbs the few matches under the new name, then takes the new name itself.

Order of ops handles the UNIQUE(platform, display_name) constraint: we first
rename the conflicting record to a stash name, then merge it, then rename the
keeper. Idempotent: re-running with the same CSV is a no-op.

Usage:
    python apply_renames.py rename_candidates.csv
    python apply_renames.py rename_candidates.csv --dry-run
"""
import argparse, csv, sqlite3, sys
from pathlib import Path

# Windows consoles default to cp1252 and choke on emoji in player names.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    p = Path(args.csv_path)
    if not p.exists():
        print(f"file not found: {p}", file=sys.stderr); sys.exit(1)

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    applied = skipped = errs = 0

    for ln, row in enumerate(csv.DictReader(open(p, encoding="utf-8")), 2):
        if (row.get("approve", "").strip().lower() != "y"):
            skipped += 1; continue

        try:
            pid = int(row["db_player_id"])
            new_name = row["candidate_new_name"].strip()
            old_name = row["current_db_name"].strip()
        except (KeyError, ValueError):
            print(f"  line {ln}: bad row"); errs += 1; continue

        # Verify the keeper still has the old name
        cur = conn.execute("SELECT display_name, platform FROM players WHERE player_id=?", (pid,)).fetchone()
        if not cur:
            print(f"  line {ln}: player_id={pid} not found"); errs += 1; continue
        if cur["display_name"] != old_name:
            print(f"  line {ln}: player_id={pid} display_name is '{cur['display_name']}' (expected '{old_name}') — already renamed?")
            skipped += 1; continue
        platform = cur["platform"]

        # Is there a conflicting record at the target name?
        conflict = conn.execute(
            "SELECT player_id FROM players WHERE platform=? AND display_name=? AND player_id != ?",
            (platform, new_name, pid),
        ).fetchone()

        if args.dry_run:
            tag = "RENAME+MERGE" if conflict else "RENAME"
            print(f"  {tag}  pid={pid}  '{old_name}' -> '{new_name}'" +
                  (f"  (absorbing pid={conflict['player_id']})" if conflict else ""))
            applied += 1
            continue

        try:
            with conn:
                if conflict:
                    other = conflict["player_id"]
                    # Stash the conflicting record's name so we can free up the target.
                    stash_name = f"__pre_merge__{other}_{new_name}"
                    conn.execute("UPDATE players SET display_name=? WHERE player_id=?", (stash_name, other))
                    # Set its merged_into_id to the keeper.
                    conn.execute("UPDATE players SET merged_into_id=? WHERE player_id=?", (pid, other))
                # Apply the rename to the keeper. The keeper is canonical by
                # definition, so its own merged_into_id MUST be null — otherwise
                # if it still points at `other` (e.g. from a prior week's merge
                # in the opposite direction) we create a 2-cycle (other->keeper,
                # keeper->other) that elo.py's resolver can't break, leaving both
                # records rated separately. Clearing it here keeps the chain acyclic.
                conn.execute("UPDATE players SET display_name=?, merged_into_id=NULL WHERE player_id=?", (new_name, pid))
            print(f"  RENAME  pid={pid}  '{old_name}' -> '{new_name}'" +
                  (f"  (merged pid={conflict['player_id']} in)" if conflict else ""))
            applied += 1
        except sqlite3.IntegrityError as e:
            print(f"  line {ln}: constraint err — {e}"); errs += 1

    conn.close()
    print(f"\napplied={applied}  skipped={skipped}  errors={errs}")
    if args.dry_run:
        print("(dry-run — no changes written)")
    elif applied:
        print("\nRecompute ELO + re-export:")
        print("  python elo.py --top 10 --min-matches 5")
        print("  python ../export_elo_to_supabase.py")


if __name__ == "__main__":
    main()
