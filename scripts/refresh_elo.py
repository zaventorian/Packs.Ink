"""End-to-end weekly ELO refresh — designed to be called by Github Actions
or locally. Steps:

  1. Download the canonical SQLite DB from Supabase Storage
  2. Re-ingest every event in `scripts/elo/season_files/wilds_unknown.xlsx`
     (the smart skip in event_already_ingested() only re-pulls non-finished
     events, so this is cheap on subsequent runs)
  3. Detect + auto-apply high-confidence RPH account renames
  4. Run alias auto-merge for any new player handles
  5. Apply any approved aliases (manual review CSV could be committed)
  6. Recompute ELO from scratch
  7. Push to Supabase + clean up orphans
  8. Upload the updated SQLite DB back to Supabase Storage

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


def run_soft(cmd: list[str], cwd: Path | None = None) -> None:
    """Best-effort step: log a non-zero exit but DON'T abort the refresh. Use for
    supplementary work (e.g. live-API discovery) that must never block the core
    recompute when an upstream service is flaky."""
    print(f"\n$ {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, cwd=cwd, check=False)
    if r.returncode != 0:
        print(f"  ! soft step failed (rc={r.returncode}); continuing refresh", flush=True)


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

    # Store-driven SC backfill: the spreadsheet above is hand-curated and has
    # silently dropped stores that ran an SC (coverage regressed from 82 stores
    # in Whispers to 57 in Wilds Unknown before this). This step finds SCs at
    # stores we ALREADY count (matched by their durable RPH store_id) that the
    # sheet missed, for the current set, and ingests them — so a store with a
    # track record can't fall off the board. Best-effort (soft): hitting the
    # live RPH API must never block the weekly recompute; it's idempotent and
    # also re-queues not-yet-played SCs so they fill in once results post.
    run_soft([sys.executable, "discover_store_scs.py", "--ingest"], cwd=ELO_DIR)

    # Detect + apply RPH account renames. RPH has no stable user_id, so a renamed
    # account denormalizes its NEW display name onto historical matches — we re-scan
    # events and auto-apply only renames where the new name has overtaken nearly all
    # of a player's matches (high-confidence). Best-effort: detect_renames exits 0
    # even if RPH is unreachable, so it never blocks the weekly recompute; apply
    # is idempotent. Runs before the cross-platform alias merge so RPH canonical
    # names are settled before melee->rph matching keys on them.
    run([sys.executable, "detect_renames.py", "--auto-approve", "--workers", "8"], cwd=ELO_DIR)
    run([sys.executable, "apply_renames.py", "rename_candidates.csv"], cwd=ELO_DIR)

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
