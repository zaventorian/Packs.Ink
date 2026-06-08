"""End-to-end weekly ELO refresh — designed to be called by Github Actions
or locally. Steps:

  1. Download the canonical SQLite DB from Supabase Storage
  2. Re-ingest every event in `scripts/elo/season_files/wilds_unknown.xlsx`
     (the smart skip in event_already_ingested() only re-pulls non-finished
     events, so this is cheap on subsequent runs)
  3. Run alias auto-merge for any new player handles
  4. Apply any approved aliases (manual review CSV could be committed)
  5. Recompute ELO from scratch
  6. Push to Supabase + clean up orphans
  7. Upload the updated SQLite DB back to Supabase Storage

Designed to fail fast on any error so a partial state doesn't get persisted.

Env vars expected:
  SUPABASE_URL, SUPABASE_SERVICE_KEY
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent           # scripts/
ELO_DIR = HERE / "elo"
SEASON_FILE_DEFAULT = ELO_DIR / "season_files" / "wilds_unknown.xlsx"
SEASON_LABEL_DEFAULT = "Wilds Unknown Summer 2026"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"\n$ {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, check=False)
    if r.returncode != 0:
        sys.exit(f"step failed (rc={r.returncode}); aborting refresh to keep state clean")


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", type=Path, default=SEASON_FILE_DEFAULT)
    ap.add_argument("--season", default=SEASON_LABEL_DEFAULT)
    ap.add_argument("--skip-storage", action="store_true",
                    help="don't sync DB with Supabase Storage (for local testing)")
    args = ap.parse_args()

    if not args.skip_storage:
        run([sys.executable, str(HERE / "elo_db_storage.py"), "download"])

    if not args.xlsx.exists():
        sys.exit(f"season file missing: {args.xlsx}")

    run([sys.executable, "ingest.py", "--xlsx", str(args.xlsx),
         "--season", args.season, "--workers", "8"], cwd=ELO_DIR)

    # Auto-merge new player names. apply_aliases.py is idempotent.
    run([sys.executable, "suggest_aliases.py"], cwd=ELO_DIR)
    run([sys.executable, "apply_aliases.py", "aliases_auto.csv"], cwd=ELO_DIR)

    run([sys.executable, "elo.py"], cwd=ELO_DIR)

    run([sys.executable, "scripts/export_elo_to_supabase.py"], cwd=HERE.parent)

    if not args.skip_storage:
        run([sys.executable, str(HERE / "elo_db_storage.py"), "upload"])

    print("\nrefresh complete.")


if __name__ == "__main__":
    main()
