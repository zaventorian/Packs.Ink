"""
cleanup_stale_graded_printings.py — purge graded_prices_daily rows whose
(pid, printing) combo doesn't correspond to a real TCGPriceLookup record.

Why: migration 49 added `printing` to graded_prices_daily with a default
of 'Normal' so every pre-migration row got stamped 'Normal'. For cards
that TCGPriceLookup actually only indexes as Holofoil (Enchanteds, Iconics,
chase rares), those stale 'Normal' rows now coexist alongside the freshly-
written 'Holofoil' rows — the modal renders both as separate sections with
near-identical data, which looks like a duplicate-printing bug.

This script:
    1. Paginates TCGPriceLookup's Lorcana catalog, builds the authoritative
       set of (tcgplayer_id, variant) combos.
    2. Compares against distinct (pid, printing) combos in our DB.
    3. Deletes any rows whose combo doesn't appear upstream.

Run with --dry-run first to see what would be deleted. Then re-run with
--commit to actually delete.

Usage:
    python scripts/cleanup_stale_graded_printings.py            # dry run
    python scripts/cleanup_stale_graded_printings.py --commit   # delete
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

API_BASE = "https://api.tcgpricelookup.com/v1"
PAGE_SIZE = 100
REQUEST_DELAY_SEC = 1.0


def collect_valid_combos(session, key):
    """Walk the full Lorcana catalog and return set of (pid, variant)."""
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-cleanup/1.0"}
    valid = set()
    offset = 0
    total = None
    pages = 0
    print("Paginating Lorcana catalog...")
    while True:
        r = session.get(f"{API_BASE}/cards/search",
                        params={"game": "lorcana", "limit": PAGE_SIZE, "offset": offset},
                        headers=headers, timeout=45)
        if r.status_code == 429:
            print("  rate-limited; sleeping 8s")
            time.sleep(8); continue
        r.raise_for_status()
        data = r.json()
        page = data.get("data") or []
        if total is None:
            total = int(data.get("total") or 0)
        pages += 1
        for c in page:
            tcg_raw = c.get("tcgplayer_id")
            if tcg_raw is None: continue
            try:
                pid = int(tcg_raw)
            except (TypeError, ValueError):
                continue
            variant = (c.get("variant") or "Normal").strip() or "Normal"
            valid.add((pid, variant))
        if not page or (offset + len(page)) >= total:
            break
        offset += len(page)
        time.sleep(REQUEST_DELAY_SEC)
    print(f"  walked {pages} pages, found {len(valid)} valid (pid, variant) combos\n")
    return valid


def collect_db_combos(sb):
    """Pull (pid, printing) combos from graded_prices_latest (one row per
    pid/printing/grader/grade combo) and aggregate to (pid, printing)."""
    print("Pulling distinct (pid, printing) combos from graded_prices_latest...")
    rows = sb.select("graded_prices_latest", "tcgplayer_product_id,printing")
    out = defaultdict(int)
    for r in rows:
        out[(r["tcgplayer_product_id"], r["printing"])] += 1
    print(f"  found {len(out)} distinct (pid, printing) combos in DB\n")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true",
                    help="Actually delete. Default is dry-run.")
    args = ap.parse_args()

    load_dotenv()
    key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not key:
        sys.exit("TCGPRICELOOKUP_API_KEY not set in .env")
    sb = Supabase()
    session = requests.Session()

    valid = collect_valid_combos(session, key)
    db = collect_db_combos(sb)

    stale = []
    for combo, count in db.items():
        if combo not in valid:
            stale.append((combo, count))
    stale.sort(key=lambda x: -x[1])

    if not stale:
        print("Nothing to delete. All DB combos match TCGPriceLookup.")
        return

    print(f"Stale (pid, printing) combos: {len(stale)}")
    print(f"{'pid':<10}{'printing':<15}{'matview rows'}")
    print("-" * 50)
    total_to_delete_estimate = 0
    for (pid, printing), count in stale[:50]:
        print(f"{pid:<10}{printing:<15}{count}")
        total_to_delete_estimate += count
    if len(stale) > 50:
        print(f"... and {len(stale) - 50} more")
    print()

    if not args.commit:
        print("DRY RUN — re-run with --commit to delete these rows from")
        print("graded_prices_daily (matview rows shown above; daily-history")
        print("row counts may be larger). Estimated lower bound on rows to")
        print(f"delete from graded_prices_daily: {total_to_delete_estimate}+")
        return

    # COMMIT mode — delete rows by (pid, printing) pairs. Batch by pid for
    # query brevity.
    print("Deleting stale rows...")
    by_pid = defaultdict(list)
    for (pid, printing), _ in stale:
        by_pid[pid].append(printing)
    total_deleted = 0
    for pid, printings in by_pid.items():
        # Delete one printing at a time so we don't depend on PostgREST
        # supporting compound IN filters.
        for printing in printings:
            res = sb.delete(
                "graded_prices_daily",
                filters={
                    "tcgplayer_product_id": "eq." + str(pid),
                    "printing": "eq." + printing,
                },
            )
            n = len(res) if isinstance(res, list) else 0
            total_deleted += n
            if n:
                print(f"  pid={pid} printing={printing}: deleted {n} rows")
    print(f"\nDone. Deleted {total_deleted} rows from graded_prices_daily.")
    print("Refreshing graded_prices_latest matview...")
    try:
        sb.rpc("refresh_graded_prices_latest")
        print("  refreshed.")
    except Exception as e:
        print(f"  WARN: refresh failed: {e} — run SELECT public.refresh_graded_prices_latest(); manually")


if __name__ == "__main__":
    main()
