"""Dry-run a new season's ingest against a CLONE of the live DB so we can
compare leaderboards before committing.

Usage:
    python preview_ingest.py --xlsx <path> --season "Azurite Sea Winter 2025"

Reads from lorcana_elo_preview.db (cp of lorcana_elo.db) — never touches the
canonical DB. Run elo.py afterwards (also pointing at the preview DB) to see
the new ranks.
"""
import argparse, sys
from pathlib import Path

HERE = Path(__file__).parent

# Monkey-patch ingest_melee + elo to point at the preview DB instead of the
# canonical one. Both modules read DB_PATH at function-call time so reassigning
# the module-level constant before any function runs is enough.
import ingest_melee
import elo

PREVIEW = HERE / "lorcana_elo_preview.db"
ingest_melee.DB_PATH = PREVIEW
elo.DB_PATH = PREVIEW


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--season", required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if not PREVIEW.exists():
        sys.exit(f"{PREVIEW.name} missing — copy lorcana_elo.db -> lorcana_elo_preview.db first")

    work = list(ingest_melee.load_melee_xlsx(args.xlsx))
    print(f"PREVIEW: ingesting {len(work)} melee tournaments into {PREVIEW.name} ...")
    ok = skip = err = 0
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(ingest_melee.ingest_one, *w, args.season): w[0] for w in work}
        for f in as_completed(futs):
            tid, status, msg = f.result()
            tag = {"ok": "OK  ", "skip": "SKIP", "err": "ERR "}[status]
            print(f"  {tag} {tid}  {msg}")
            if status == "ok": ok += 1
            elif status == "skip": skip += 1
            else: err += 1
    print(f"\nIngest done: ok={ok} skip={skip} err={err}")

    print("\nRecomputing ELO on preview ...")
    ratings = elo.compute()
    print(f"  rated {len(ratings)} players (preview)")


if __name__ == "__main__":
    main()
