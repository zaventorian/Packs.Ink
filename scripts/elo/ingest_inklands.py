"""Drive the Inklands ingest from inklands_scs.json (post-filter).

Feeds the per-event metadata (store, date, season) directly into
`ingest_melee.ingest_one` so the resulting events table rows have proper
store labels instead of NULLs — using --ids on ingest_melee.py wouldn't
carry that metadata.

For store labeling, we use the SHORTEST name from our existing DB's
stores-set for that organization (e.g. "Top Cut" over
"Top Cut Comics - Loves Park") to keep the leaderboard concise.

Usage:
    python ingest_inklands.py
    python ingest_inklands.py --workers 4
    python ingest_inklands.py --dry-run    # print plan, don't fetch
"""
import argparse, json, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import ingest_melee

SEASON = "Into the Inklands Spring 2024"


def pick_store(candidate: dict) -> str | None:
    """Pick the shortest existing-DB store name for this org."""
    stores = candidate.get("stores") or []
    if not stores: return None
    return min(stores, key=len)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="inklands_scs.json",
                    help="JSON file with candidate events (post-filter)")
    ap.add_argument("--skip", type=int, nargs="*", default=[88137],
                    help="tids to drop (default: Battle Brothers 4-player makeup)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(__file__).parent / args.source
    cands = json.loads(src.read_text())
    skip = set(args.skip)
    plan = [c for c in cands if c["tid"] not in skip]

    print(f"Planning to ingest {len(plan)} Inklands SCs (season='{SEASON}')")
    print(f"  skipping: {sorted(skip)}")
    if args.dry_run:
        print("\nDry-run plan:")
        for c in plan[:10]:
            print(f"  tid={c['tid']:<7} {c['date']}  {pick_store(c)!r:32}  {c['name'][:50]}")
        print(f"  ... ({len(plan)-10} more)" if len(plan) > 10 else "")
        return

    ok = skipped = err = 0
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {}
        for c in plan:
            tid = c["tid"]
            store = pick_store(c)
            date = c["date"] or None
            fut = ex.submit(ingest_melee.ingest_one, tid, store, None, date, SEASON)
            futs[fut] = c
        for f in as_completed(futs):
            c = futs[f]
            try:
                tid, status, msg = f.result()
            except Exception as e:
                tid, status, msg = c["tid"], "err", repr(e)
            tag = {"ok":"OK  ", "skip":"SKIP", "err":"ERR "}.get(status, status)
            print(f"  {tag} {tid}  {msg}")
            if status == "ok": ok += 1
            elif status == "skip": skipped += 1
            else:
                err += 1
                failures.append((tid, msg))

    print(f"\ndone. ok={ok} skip={skipped} err={err}")
    if failures:
        print("failures:")
        for tid, msg in failures:
            print(f"  {tid}: {msg}")
        sys.exit(1)


if __name__ == "__main__":
    main()
