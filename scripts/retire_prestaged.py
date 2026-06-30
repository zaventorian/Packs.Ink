"""
retire_prestaged.py — drop pre-staged card rows once Lorcast publishes the real
card, so the site switches from our local art + TCGCSV data to Lorcast's.

A pre-staged row (id `crd_prestage_*`, written by prestage_set_cards.py) is a
stand-in for a revealed card Lorcast hadn't indexed yet. Once load_lorcast
inserts the genuine row for that (set_id, collector_number) — a NON-prestage id —
the stand-in is a duplicate and must go, or the catalog shows two tiles for the
same card. This deletes every prestage row whose (set_id, collector_number) now
has a real sibling, then refreshes card_prices_latest.

Wired into the daily metadata job AFTER load_lorcast / patch_pid_overrides /
link_preorder_pids, so the hand-off is automatic. Idempotent.

Usage:
    python scripts/retire_prestaged.py            # dry run
    python scripts/retire_prestaged.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase


def _norm_cn(cn):
    cn = str(cn or "").split("/", 1)[0].strip()
    if not cn:
        return None
    return str(int(cn)) if cn.isdigit() else cn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    rows = sb.select("cards", columns="id,set_id,collector_number")
    real_keys = set()
    prestage = []
    for r in rows:
        key = (r.get("set_id"), _norm_cn(r.get("collector_number")))
        if str(r.get("id", "")).startswith("crd_prestage_"):
            prestage.append((r["id"], key))
        else:
            real_keys.add(key)

    superseded = [pid for pid, key in prestage if key in real_keys]
    print(f"{len(prestage)} prestage row(s); {len(superseded)} superseded by a real Lorcast card.")
    for pid in superseded:
        print(f"  retire {pid}")

    if not superseded:
        print("Nothing to retire.")
        return
    if not args.commit:
        print("\nDry run — nothing deleted. Re-run with --commit.")
        return

    # Delete in chunks to keep the in.() filter a sane length.
    deleted = 0
    for i in range(0, len(superseded), 100):
        chunk = superseded[i:i + 100]
        sb.delete("cards", {"id": f"in.({','.join(chunk)})"})
        deleted += len(chunk)
    print(f"\nDeleted {deleted} prestage row(s).")
    try:
        sb.rpc("refresh_card_prices_latest")
        print("Refreshed card_prices_latest.")
    except Exception as e:
        print(f"matview refresh failed: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
