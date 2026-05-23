"""Probe TCGPriceLookup for the furthest-back graded history available
for a single TCGPlayer product id.

Tries every plausible `period` value the API might accept and reports
the earliest date + total snapshot count returned. Helps answer "is the
gap on our side (need a backfill re-run) or upstream (TCGPriceLookup
doesn't have it either)?"

Usage:
    python scripts/probe_graded_history.py 527802
    python scripts/probe_graded_history.py 527802 --grader psa --grade 10

Requires TCGPRICELOOKUP_API_KEY in .env.
"""
from __future__ import annotations

import os
import sys
import argparse
import time

import requests
from dotenv import load_dotenv

API_BASE = "https://api.tcgpricelookup.com/v1"
PERIODS = ["1m", "3m", "6m", "1y", "2y", "5y", "all", "max"]


def headers(key: str) -> dict:
    return {"X-API-Key": key, "User-Agent": "packs.ink-probe/1.0"}


def find_uuid(session: requests.Session, key: str, tcg_id: int) -> tuple[str, str] | None:
    """Page Lorcana catalog until we find the card with matching tcgplayer_id."""
    offset = 0
    page_size = 100
    while True:
        r = session.get(f"{API_BASE}/cards/search",
                        params={"game": "lorcana", "limit": page_size, "offset": offset},
                        headers=headers(key), timeout=45)
        if r.status_code == 429:
            time.sleep(8); continue
        r.raise_for_status()
        data = r.json()
        page = data.get("data") or []
        for card in page:
            try:
                if int(card.get("tcgplayer_id") or 0) == tcg_id:
                    return card["id"], (card.get("name") or "")
            except (TypeError, ValueError):
                pass
        total = int(data.get("total") or 0)
        if not page or (offset + len(page)) >= total:
            return None
        offset += len(page)
        time.sleep(1.0)


def probe_period(session: requests.Session, key: str, uuid: str, period: str,
                 grader: str | None, grade: str | None) -> dict:
    """Return {ok, count_total, earliest_date, latest_date, matching_count}."""
    r = session.get(f"{API_BASE}/cards/{uuid}/history",
                    params={"period": period},
                    headers=headers(key), timeout=60)
    if r.status_code != 200:
        return {"ok": False, "status": r.status_code, "body": r.text[:200]}
    js = r.json()
    snaps = js.get("data") or []
    dates = [s.get("date") for s in snaps if s.get("date")]
    matching = 0
    earliest_match = None
    latest_match = None
    if grader or grade:
        g = (grader or "").lower()
        gr = str(grade) if grade is not None else None
        for snap in snaps:
            d = snap.get("date")
            for p in snap.get("prices") or []:
                if p.get("source") != "ebay":
                    continue
                if g and str(p.get("grader") or "").lower() != g:
                    continue
                if gr is not None and str(p.get("grade")) != gr:
                    continue
                matching += 1
                if earliest_match is None or (d and d < earliest_match):
                    earliest_match = d
                if latest_match is None or (d and d > latest_match):
                    latest_match = d
    return {
        "ok": True,
        "snapshots": len(snaps),
        "earliest": min(dates) if dates else None,
        "latest":   max(dates) if dates else None,
        "matching_rows": matching if (grader or grade) else None,
        "matching_earliest": earliest_match,
        "matching_latest": latest_match,
    }


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("tcgplayer_product_id", type=int)
    ap.add_argument("--grader", default=None, help="Filter rows by grader (psa/bgs/cgc/sgc/tag)")
    ap.add_argument("--grade",  default=None, help="Filter rows by grade (10, 9.5, 9, ...)")
    args = ap.parse_args()

    key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not key:
        sys.exit("TCGPRICELOOKUP_API_KEY not set in .env")

    session = requests.Session()

    print(f"Looking up pid {args.tcgplayer_product_id} in TCGPriceLookup catalog...")
    found = find_uuid(session, key, args.tcgplayer_product_id)
    if not found:
        sys.exit("Card not found in TCGPriceLookup's Lorcana catalog. "
                 "Either the pid is wrong or they haven't indexed this card yet.")
    uuid, name = found
    print(f"Found: {name} (uuid={uuid})\n")

    if args.grader or args.grade:
        print(f"Filtering to grader={args.grader or '*'} grade={args.grade or '*'}\n")

    print(f"{'period':<8}{'snapshots':<12}{'earliest':<14}{'latest':<14}{'matched':<10}{'first match':<14}{'last match'}")
    print("-" * 90)
    for p in PERIODS:
        try:
            res = probe_period(session, key, uuid, p, args.grader, args.grade)
        except Exception as e:
            print(f"{p:<8}ERROR: {e}")
            time.sleep(2)
            continue
        if not res["ok"]:
            print(f"{p:<8}HTTP {res.get('status')} — {res.get('body','')[:60]}")
        else:
            print(f"{p:<8}{res['snapshots']:<12}{(res['earliest'] or '—'):<14}{(res['latest'] or '—'):<14}"
                  f"{(res['matching_rows'] if res['matching_rows'] is not None else '—'):<10}"
                  f"{(res['matching_earliest'] or '—'):<14}{(res['matching_latest'] or '—')}")
        time.sleep(1.2)

    print()


if __name__ == "__main__":
    main()
