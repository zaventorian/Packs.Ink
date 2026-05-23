"""Dump the raw /history response for one card so we can see the actual
field shape TCGPriceLookup is returning.

Usage:
    python scripts/dump_graded_history.py 527802 [--period 1y] [--snapshots 2]
"""
from __future__ import annotations

import os
import sys
import json
import time
import argparse

import requests
from dotenv import load_dotenv

API_BASE = "https://api.tcgpricelookup.com/v1"


def _get(session, url, params, headers, max_tries=8):
    """Retry on 429 with backoff. TCGPriceLookup is sensitive to bursts."""
    for attempt in range(max_tries):
        r = session.get(url, params=params, headers=headers, timeout=60)
        if r.status_code == 429:
            wait = 8 + attempt * 4
            print(f"  429 on {url} (attempt {attempt+1}); sleeping {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError(f"persistent 429 on {url}")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("tcgplayer_product_id", type=int)
    ap.add_argument("--period", default="1y")
    ap.add_argument("--snapshots", type=int, default=2,
                    help="How many snapshots to print in full (default 2)")
    args = ap.parse_args()

    key = os.environ["TCGPRICELOOKUP_API_KEY"]
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-dump/1.0"}
    session = requests.Session()

    # Find UUID by paging the catalog.
    print(f"Locating pid {args.tcgplayer_product_id}...")
    offset = 0
    uuid = None; name = None
    while True:
        r = _get(session, f"{API_BASE}/cards/search",
                 {"game": "lorcana", "limit": 100, "offset": offset}, headers)
        data = r.json()
        for c in data.get("data") or []:
            try:
                if int(c.get("tcgplayer_id") or 0) == args.tcgplayer_product_id:
                    uuid = c["id"]; name = c.get("name") or ""
                    break
            except (TypeError, ValueError):
                pass
        if uuid: break
        total = int(data.get("total") or 0)
        if offset + 100 >= total: break
        offset += 100
        time.sleep(1.5)  # avoid burst rate-limit between pages
    if not uuid:
        sys.exit("Card not found.")
    print(f"Found {name} (uuid={uuid})\n")

    # Also dump what /search returned for this card — we want to compare
    # /search's price shape against /history's price shape.
    print("=" * 70)
    print(f"/cards/{uuid} (search-style detail):")
    print("=" * 70)
    time.sleep(1.5)
    try:
        r = _get(session, f"{API_BASE}/cards/{uuid}", {}, headers)
        detail = r.json()
        print(json.dumps(detail.get("prices") or {}, indent=2)[:3000])
    except Exception as e:
        print(f"detail fetch failed: {e}")
    print()

    print("=" * 70)
    print(f"/cards/{uuid}/history?period={args.period}:")
    print("=" * 70)
    time.sleep(1.5)
    r = _get(session, f"{API_BASE}/cards/{uuid}/history", {"period": args.period}, headers)
    js = r.json()
    snaps = js.get("data") or []
    print(f"Total snapshots: {len(snaps)}\n")
    if snaps:
        print(f"Top-level keys: {sorted((snaps[0] or {}).keys())}")
        if snaps[0].get("prices"):
            print(f"First-snapshot prices[0] keys: {sorted((snaps[0]['prices'][0] or {}).keys())}")
        print()

    # Print full JSON of first N snapshots
    for i, s in enumerate(snaps[:args.snapshots]):
        print(f"--- snapshot {i+1}/{len(snaps)} (date={s.get('date')}) ---")
        print(json.dumps(s, indent=2)[:4000])
        print()

    # Also count entries by source / grader across the whole response, even if
    # we can't match. Tells us at a glance whether graded ever appears.
    by_source = {}
    by_grader = {}
    for s in snaps:
        for p in s.get("prices") or []:
            src = str(p.get("source"))
            by_source[src] = by_source.get(src, 0) + 1
            g = p.get("grader")
            if g:
                key = f"{g}|{p.get('grade')}"
                by_grader[key] = by_grader.get(key, 0) + 1
    print("=" * 70)
    print("Across all snapshots:")
    print(f"  by source: {by_source}")
    print(f"  by grader|grade: {by_grader}")


if __name__ == "__main__":
    main()
