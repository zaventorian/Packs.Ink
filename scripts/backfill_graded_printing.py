"""
backfill_graded_printing.py — re-derive `printing` and `exclude_reason` on
EXISTING graded_sales rows from their titles. No re-scrape needed.

Why printing matters: a Challenge Promo (C1) card's Top Prize foil and Prize Wall
non-foil share ONE card_id but are different markets (Cinderella - Stouthearted
PSA 10: $1,707 foil vs $280 non-foil). The portfolio chart only lets a slab be
valued by sales of its own printing, and it DROPS unclassified rows on cards that
have both printings rather than guessing. So every row left at printing=NULL on a
split card is a sale we own but can't use — and, before the chart was fixed, was a
sale that could value the wrong slab.

`printing_of` now reads the Challenge prize tiers ("Top Prize"/"Top N" -> foil,
"Prize Wall"/"Side Event" -> non-foil), which the older title-only foil/holo test
missed. This backfills that.

Only ever ADDS a printing where it was NULL — never overwrites an existing value,
since those may have been hand-corrected via the admin review UI.

    python scripts/backfill_graded_printing.py            # dry run
    python scripts/backfill_graded_printing.py --commit
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_load import printing_of, exclude_reason_for
from terapeak_match import is_nonsingle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal"}


def fetch_all():
    rows, off = [], 0
    while True:
        r = requests.get(f"{SB}/rest/v1/graded_sales", headers=HEAD, timeout=90, params={
            "select": "item_id,title,printing,excluded,exclude_reason,sale_price",
            "offset": off, "limit": 1000, "order": "item_id"})
        r.raise_for_status()
        b = r.json()
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def patch_group(item_ids, body, label):
    CHUNK = 100
    for i in range(0, len(item_ids), CHUNK):
        ids = item_ids[i:i + CHUNK]
        quoted = ",".join('"' + s.replace('"', '""') + '"' for s in ids)
        r = requests.patch(f"{SB}/rest/v1/graded_sales", headers=HEAD, timeout=60,
                           params={"item_id": f"in.({quoted})"}, json=body)
        r.raise_for_status()
        print(f"  {label}: {min(i + CHUNK, len(item_ids))}/{len(item_ids)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--apply-exclusions", action="store_true",
                    help="also HIDE rows that are currently visible but now match a "
                         "reason (foreign / auto / lot). Off by default: filling in a "
                         "label changes nothing a user sees, but hiding a sale does, "
                         "and the foreign-language rule can strand a regional-only "
                         "card (Mickey - True Friend #25ja) with no sales at all.")
    args = ap.parse_args()

    print("Fetching graded_sales ...")
    rows = fetch_all()
    print(f"{len(rows)} sales\n")

    # printing: NULL -> inferred value, grouped so we can PATCH in bulk per value.
    add_printing = collections.defaultdict(list)
    # exclude_reason: fill in the reason for rows excluded before migration 111,
    # and newly-detected lots that predate the widened detector.
    add_reason = collections.defaultdict(list)
    new_lots = []

    for r in rows:
        t = r.get("title") or ""
        if r.get("printing") is None:
            p = printing_of(t)
            if p:
                add_printing[p].append(r["item_id"])

        reason = exclude_reason_for(t) or ("lot" if is_nonsingle(t) else None)
        if r.get("excluded"):
            # Already hidden — just label it if it has no label yet.
            if not r.get("exclude_reason") and reason:
                add_reason[reason].append(r["item_id"])
        elif reason:
            # Not hidden but should be (widened lot detection).
            new_lots.append((r, reason))

    print("=" * 70)
    for p, ids in sorted(add_printing.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(ids):6}  printing NULL -> {p}")
    for reason, ids in sorted(add_reason.items(), key=lambda kv: -len(kv[1])):
        print(f"  {len(ids):6}  exclude_reason (backfill label) -> {reason}")
    print(f"  {len(new_lots):6}  newly detected as lot/set -> excluded")
    print("=" * 70)

    if new_lots:
        by_reason = collections.Counter(reason for _, reason in new_lots)
        print("\nwould-hide breakdown: "
              + ", ".join(f"{n} {k}" for k, n in by_reason.most_common())
              + ("  [APPLYING]" if args.apply_exclusions else "  [SKIPPED — pass --apply-exclusions]"))
        for r, reason in new_lots[:12]:
            price = float(r.get("sale_price") or 0)
            print(f"  [{reason}] ${price:>10,.2f}  {(r.get('title') or '')[:62]}")

    if not args.commit:
        print("\nDRY RUN — re-run with --commit to apply.")
        return

    for p, ids in add_printing.items():
        patch_group(ids, {"printing": p}, f"printing={p}")
    for reason, ids in add_reason.items():
        patch_group(ids, {"exclude_reason": reason}, f"reason={reason}")
    if new_lots and args.apply_exclusions:
        by_reason = collections.defaultdict(list)
        for r, reason in new_lots:
            by_reason[reason].append(r["item_id"])
        for reason, ids in by_reason.items():
            patch_group(ids, {"excluded": True, "exclude_reason": reason}, f"exclude={reason}")

    print("Refreshing rollup ...")
    requests.post(f"{SB}/rest/v1/rpc/refresh_graded_sales_rollup", headers=HEAD, timeout=300)
    print("DONE.")


if __name__ == "__main__":
    main()
