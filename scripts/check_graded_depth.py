"""Quick diagnostic: how many days of graded history do we have for a card?

Usage:
    python scripts/check_graded_depth.py "Cinderella" "Ballroom Sensation"
    python scripts/check_graded_depth.py 506829                # if you already know the pid
    python scripts/check_graded_depth.py "Cinderella" "Ballroom Sensation" --grader cgc --grade 9.5

Prints, per (grader, grade) combination tracked for the card:
    - earliest date written
    - latest date written
    - day count
    - first/last price + min/max in the window
"""
from __future__ import annotations

import os
import sys
import json
import urllib.parse
import urllib.request
import argparse

from dotenv import load_dotenv


def sb_get(path: str) -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ["SUPABASE_ANON_KEY"]
    req = urllib.request.Request(
        url,
        headers={"apikey": key, "Authorization": "Bearer " + key, "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def find_pid(name: str, version: str) -> int | None:
    q = "cards?select=id,name,version,collector_number,set_id,tcgplayer_product_id"
    q += "&name=eq." + urllib.parse.quote(name)
    q += "&version=eq." + urllib.parse.quote(version)
    rows = sb_get(q)
    if not rows:
        print(f"No card found matching name='{name}' version='{version}'.")
        return None
    if len(rows) > 1:
        print(f"Multiple matches — pick a pid manually:")
        for r in rows:
            print(f"  pid={r['tcgplayer_product_id']}  cn={r['collector_number']}  set={r['set_id']}")
        return None
    return rows[0]["tcgplayer_product_id"]


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("name_or_pid")
    ap.add_argument("version", nargs="?", default=None)
    ap.add_argument("--grader", default=None)
    ap.add_argument("--grade", default=None)
    args = ap.parse_args()

    if args.name_or_pid.isdigit():
        pid = int(args.name_or_pid)
    else:
        if not args.version:
            sys.exit("Provide both NAME and VERSION (or a numeric pid).")
        pid = find_pid(args.name_or_pid, args.version)
        if pid is None:
            sys.exit(1)

    print(f"\nProduct ID: {pid}")

    # Pull EVERY graded_prices_daily row for this pid (range-paginate manually,
    # the PostgREST default 1000 cap is fine for one card).
    q = (
        "graded_prices_daily?select=date,grader,grade,ebay_avg_1d,ebay_avg_7d,ebay_avg_30d"
        "&tcgplayer_product_id=eq." + str(pid)
        + "&order=grader.asc,grade.asc,date.asc"
    )
    if args.grader:
        q += "&grader=eq." + args.grader.lower()
    if args.grade:
        q += "&grade=eq." + str(args.grade)
    rows = sb_get(q)

    if not rows:
        print("No graded_prices_daily rows for this product.")
        return

    # Group by (grader, grade)
    from collections import defaultdict
    buckets = defaultdict(list)
    for r in rows:
        buckets[(r["grader"], r["grade"])].append(r)

    print(f"\n{'Grader':<8}{'Grade':<8}{'Days':<8}{'First':<14}{'Last':<14}{'First $':<12}{'Last $':<12}{'Min $':<10}{'Max $':<10}{'Unique vals'}")
    print("-" * 110)
    for (grader, grade), pts in sorted(buckets.items()):
        prices = [float(p["ebay_avg_1d"]) for p in pts if p["ebay_avg_1d"] is not None]
        unique = len(set(prices))
        first = pts[0]
        last = pts[-1]
        fmt = lambda v: f"${float(v):.2f}" if v is not None else "—"
        print(
            f"{grader:<8}{grade:<8}{len(pts):<8}{first['date']:<14}{last['date']:<14}"
            f"{fmt(first.get('ebay_avg_1d')):<12}{fmt(last.get('ebay_avg_1d')):<12}"
            f"{fmt(min(prices) if prices else None):<10}{fmt(max(prices) if prices else None):<10}{unique}"
        )

    print()


if __name__ == "__main__":
    main()
