"""Probe TCGPriceLookup to determine if split-printing cards (LCP C1) are
indexed as ONE record per tcgplayer_id (printings conflated) or as TWO
separate records (we can distinguish them).

The ETL currently collapses every record sharing a tcgplayer_id under the
same row key. If TCGPriceLookup returns separate records for foil vs
non-foil, the second one's upsert silently overwrites the first — which
matches the symptom: PSA 10 reads the non-foil's market, CGC 8.5 reads
the foil's market, because each grade combo's "winner" depends on which
record happened to be processed last + had data for that combo.

This probe paginates the full Lorcana catalog, groups records by
tcgplayer_id, and dumps full record structure for any tcgplayer_id with
multiple records. It also takes targeted pids on the CLI and dumps every
record matching them.

Usage:
    python scripts/probe_graded_printings.py                  # full audit
    python scripts/probe_graded_printings.py 510153 527802    # specific pids

Requires TCGPRICELOOKUP_API_KEY in .env.
"""
from __future__ import annotations

import os
import sys
import time
import json
import argparse
from collections import defaultdict

import requests
from dotenv import load_dotenv

API_BASE = "https://api.tcgpricelookup.com/v1"
PAGE_SIZE = 100
REQUEST_DELAY_SEC = 1.0


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("pids", nargs="*", type=int,
                    help="Specific tcgplayer_product_ids to inspect in full. "
                         "Omit to audit the whole Lorcana catalog for duplicates.")
    args = ap.parse_args()

    key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not key:
        sys.exit("TCGPRICELOOKUP_API_KEY not set in .env")
    target_pids = set(args.pids or [])
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-probe/1.0"}
    session = requests.Session()

    by_tcg_id: dict[int, list[dict]] = defaultdict(list)
    targeted_records: dict[int, list[dict]] = defaultdict(list)
    total = None
    offset = 0
    pages = 0
    print("Paginating Lorcana catalog...")
    while True:
        r = session.get(f"{API_BASE}/cards/search",
                        params={"game": "lorcana", "limit": PAGE_SIZE, "offset": offset},
                        headers=headers, timeout=45)
        if r.status_code == 429:
            print("  rate limited; sleeping 8s")
            time.sleep(8); continue
        r.raise_for_status()
        data = r.json()
        page = data.get("data") or []
        if total is None:
            total = int(data.get("total") or 0)
            print(f"  total cards: {total}")
        pages += 1
        for c in page:
            tcg_raw = c.get("tcgplayer_id")
            if tcg_raw is None:
                continue
            try:
                tcg_id = int(tcg_raw)
            except (TypeError, ValueError):
                continue
            by_tcg_id[tcg_id].append(c)
            if tcg_id in target_pids:
                targeted_records[tcg_id].append(c)
        if not page or (offset + len(page)) >= total:
            break
        offset += len(page)
        time.sleep(REQUEST_DELAY_SEC)
    print(f"Done. Walked {pages} pages, indexed {sum(len(v) for v in by_tcg_id.values())} records "
          f"across {len(by_tcg_id)} distinct tcgplayer_ids.\n")

    # Report duplicates (the smoking gun).
    dupes = {tid: recs for tid, recs in by_tcg_id.items() if len(recs) > 1}
    print("=" * 70)
    print(f"tcgplayer_ids with MORE than one TCGPriceLookup record: {len(dupes)}")
    print("=" * 70)
    if not dupes:
        print("No duplicates found. Implication: TCGPriceLookup collapses Foil and")
        print("Non-Foil of the same tcgplayer_id into ONE record with mixed-printing")
        print("prices. We can NOT recover per-printing graded prices from this source.")
    else:
        print(f"{'tcg_id':<10}{'count':<8}name (first record)")
        print("-" * 70)
        for tid, recs in sorted(dupes.items()):
            name = recs[0].get("name") or "?"
            print(f"{tid:<10}{len(recs):<8}{name}")
        print()
        # Dump field-level diff for first 3 duplicate groups so we can see
        # what field actually distinguishes them.
        print("=" * 70)
        print("Field-level inspection of first 3 duplicate groups:")
        print("=" * 70)
        for tid, recs in list(sorted(dupes.items()))[:3]:
            print(f"\n--- tcgplayer_id = {tid} ---")
            for i, c in enumerate(recs):
                slim = {k: v for k, v in c.items() if k not in ("prices",)}
                print(f"  record {i+1}: {json.dumps(slim, indent=2)[:1500]}")
                # Show top-level grader summary for each record's prices
                graded = ((c.get("prices") or {}).get("graded")) or {}
                summary = {g: list(grades.keys())[:5] for g, grades in graded.items()
                           if isinstance(grades, dict)}
                print(f"  record {i+1} graded summary: {summary}")

    # Dump targeted pids in full regardless of duplicate status.
    if target_pids:
        print("\n" + "=" * 70)
        print(f"Full dump of targeted pids: {sorted(target_pids)}")
        print("=" * 70)
        for pid in sorted(target_pids):
            recs = targeted_records.get(pid, [])
            print(f"\n=== tcgplayer_id = {pid} ({len(recs)} record(s)) ===")
            if not recs:
                print("  NOT FOUND in catalog")
                continue
            for i, c in enumerate(recs):
                print(f"  record {i+1}:")
                # Strip the giant prices blob to keep output readable; print
                # a graded-only summary alongside.
                slim = {k: v for k, v in c.items() if k != "prices"}
                print(f"    fields: {json.dumps(slim, indent=4)[:2000]}")
                graded = ((c.get("prices") or {}).get("graded")) or {}
                if graded:
                    print(f"    graded keys: {sorted(graded.keys())}")
                    for grader in sorted(graded.keys()):
                        grades = graded[grader]
                        if isinstance(grades, dict):
                            print(f"      {grader}: grades={sorted(grades.keys())}")


if __name__ == "__main__":
    main()
