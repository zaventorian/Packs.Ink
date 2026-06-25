"""
reattribute_graded_sales.py — re-run the (improved) matcher over EXISTING
graded_sales rows and fix attribution in place. No re-scrape needed.

For every row it re-evaluates the title with terapeak_match.match_one (which now
rejects lots/sets/packs/demos and explicit collector#-conflicts):

  • lot / pack / demo / cn-conflict  -> excluded = true   (drop from rollup)
  • a DIFFERENT valid card           -> card_id moved      (e.g. 2022 D23 Expo
                                                            BLT off the 2024 card)
  • same card                        -> no change

Never un-excludes a row. Dry-run by default — prints a summary + samples.
Pass --commit to write, then it refreshes graded_sales_rollup.

    python scripts/reattribute_graded_sales.py            # dry run
    python scripts/reattribute_graded_sales.py --commit
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_match import build_index, match_one, is_nonsingle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json"}


def fetch_sales():
    rows, off = [], 0
    while True:
        r = requests.get(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=60, params={
            "select": "item_id,title,card_id,excluded", "offset": off, "limit": 1000, "order": "item_id"})
        r.raise_for_status()
        b = r.json()
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def patch(item_id, body):
    r = requests.patch(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=30,
                       params={"item_id": f"eq.{item_id}"}, json=body)
    r.raise_for_status()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (else dry run)")
    args = ap.parse_args()

    print("Building catalog index ...")
    by_cn, inv, ncards, _ = build_index()
    print(f"catalog: {ncards} cards")
    print("Fetching graded_sales ...")
    rows = fetch_sales()
    print(f"{len(rows)} sales\n")

    changes = []   # (item_id, body, kind, title)
    stats = collections.Counter()
    for r in rows:
        title = r.get("title") or ""
        cur_id = r.get("card_id")
        cur_excl = bool(r.get("excluded"))
        if is_nonsingle(title):
            stats["nonsingle"] += 1
            if not cur_excl:
                changes.append((r["item_id"], {"excluded": True}, "exclude:nonsingle", title))
            continue
        card, conf, cn_conflict = match_one(title, by_cn, inv)
        if card is None:
            stats["nomatch/cn-conflict"] += 1
            if not cur_excl:
                changes.append((r["item_id"], {"excluded": True}, "exclude:nomatch", title))
        elif cur_id and card["id"] != cur_id:
            stats["reattributed"] += 1
            changes.append((r["item_id"], {"card_id": card["id"], "cn_conflict": False},
                            f"move->{card['name']} - {card.get('version')}", title))
        else:
            stats["unchanged"] += 1

    print("=" * 60)
    for k, n in stats.most_common():
        print(f"  {n:6}  {k}")
    print(f"  {len(changes):6}  ROWS TO CHANGE")
    print("=" * 60)
    print("\nsamples:")
    for item_id, body, kind, title in changes[:25]:
        print(f"  [{kind}] {title[:64]}")

    if not args.commit:
        print(f"\nDRY RUN — re-run with --commit to apply {len(changes)} changes.")
        return

    print(f"\nApplying {len(changes)} changes ...")
    for i, (item_id, body, _, _) in enumerate(changes):
        patch(item_id, body)
        if i % 200 == 0:
            print(f"  {i}/{len(changes)}", flush=True)
    print("Refreshing rollup ...")
    requests.post(f"{SB_URL}/rest/v1/rpc/refresh_graded_sales_rollup", headers=HEAD, timeout=300)
    print("DONE.")


if __name__ == "__main__":
    main()
