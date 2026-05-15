"""
Audit every product in our catalog that has a `Holofoil` printing in
prices_daily, and cross-reference with its card metadata + chase rarity.

The idea: Holofoil is TCGCSV's bucket for "card with a holographic finish".
That covers two distinct populations in our catalog:

  1. Chase rarities (Enchanted / Iconic / Epic) — these are *expected* to
     be Holofoil-only. Our rendering already maps them to "Cold Foil" via
     mapPrinting() because they only ever have one printing.

  2. One-off oddities — starter-deck-exclusive foils, set bonus inserts,
     etc. These currently get silently merged into the base card's "Foil"
     slot in the modal, even though they're priced very differently from
     the in-pack foil. Buzz Lightyear - On the Way (WU starter deck) is
     the canonical example.

Run:  python scripts/audit_holofoils.py [--csv out.csv]

Outputs a sorted table of every Holofoil row, flagged by which bucket it
falls into so we can hand-curate the "oddity" list.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv

from supabase_client import Supabase


CHASE_RARITIES = {"Enchanted", "Iconic", "Epic"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Also write the full audit to this CSV path")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()

    print("Fetching Holofoil price rows from prices_daily...")
    # Pull the latest snapshot per (product, printing). prices_daily is the
    # source of truth; we filter to today's max date client-side to keep
    # the response small.
    raw = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,date,low_price,market_price",
        filters={"printing": "eq.Holofoil", "source": "eq.tcgcsv", "grade": "eq.raw"},
    )
    # Latest row per product (Holofoil-only by filter).
    latest: dict[int, dict] = {}
    for r in raw:
        pid = r.get("tcgplayer_product_id")
        if pid is None:
            continue
        pid = int(pid)
        cur = latest.get(pid)
        if cur is None or (r.get("date") or "") > (cur.get("date") or ""):
            latest[pid] = r
    holofoil_rows = list(latest.values())
    print(f"  {len(holofoil_rows)} distinct Holofoil products (latest snapshots)")
    if not holofoil_rows:
        print("Nothing flagged Holofoil in prices_daily — exiting.")
        return

    # Build a price lookup keyed on product_id.
    price_by_pid = {int(r["tcgplayer_product_id"]): r for r in holofoil_rows if r.get("tcgplayer_product_id") is not None}
    product_ids = list(price_by_pid.keys())

    # Also fetch base "Normal" + "Cold Foil" prices for these same products
    # so we can compare side-by-side and spot the suspicious gap (e.g. Buzz
    # foil = $1 but holofoil = $18).
    print("Fetching companion Normal / Cold Foil rows for context...")
    other_by_pid: dict[int, dict[str, dict]] = defaultdict(dict)
    # Batch the IN-clause — too many product_ids in one URL trips PostgREST.
    BATCH = 80
    for i in range(0, len(product_ids), BATCH):
        chunk = product_ids[i:i+BATCH]
        other_rows = sb.select(
            "prices_daily",
            columns="tcgplayer_product_id,printing,date,low_price,market_price",
            filters={
                "tcgplayer_product_id": f"in.({','.join(str(p) for p in chunk)})",
                "printing": "in.(Normal,Cold Foil,Foil)",
                "source": "eq.tcgcsv",
                "grade": "eq.raw",
            },
        )
        # Keep just latest per (pid, printing).
        for r in other_rows:
            pid = r.get("tcgplayer_product_id")
            if pid is None:
                continue
            pid = int(pid)
            pr = r["printing"]
            cur = other_by_pid[pid].get(pr)
            if cur is None or (r.get("date") or "") > (cur.get("date") or ""):
                other_by_pid[pid][pr] = r

    # Card metadata.
    print("Fetching card metadata...")
    cards = sb.select(
        "cards",
        columns="id,name,version,rarity,set_id,collector_number,tcgplayer_product_id",
        filters={"tcgplayer_product_id": f"in.({','.join(str(p) for p in product_ids)})"},
    )
    card_by_pid = {int(c["tcgplayer_product_id"]): c for c in cards if c.get("tcgplayer_product_id") is not None}

    # Set names.
    print("Fetching set names...")
    sets = sb.select("sets", columns="id,name")
    set_name = {s["id"]: s["name"] for s in sets}

    # Categorize.
    rows: list[dict] = []
    for pid in product_ids:
        price = price_by_pid[pid]
        card = card_by_pid.get(pid)
        if not card:
            category = "no card match"
            display_name = f"(unknown product #{pid})"
            rarity = ""
            set_label = ""
            cn = ""
        else:
            rarity = card.get("rarity") or ""
            base_name = card.get("name") or ""
            ver = card.get("version") or ""
            display_name = f"{base_name} - {ver}" if ver else base_name
            set_label = set_name.get(card.get("set_id"), "")
            cn = card.get("collector_number") or ""
            category = "chase rarity" if rarity in CHASE_RARITIES else "oddity (needs review)"

        normal = other_by_pid.get(pid, {}).get("Normal")
        cold_foil = other_by_pid.get(pid, {}).get("Cold Foil") or other_by_pid.get(pid, {}).get("Foil")

        rows.append({
            "category": category,
            "pid": pid,
            "set": set_label,
            "cn": cn,
            "rarity": rarity,
            "name": display_name,
            "normal_low": normal["low_price"] if normal else None,
            "foil_low":   cold_foil["low_price"] if cold_foil else None,
            "holofoil_low": price.get("low_price"),
            "holofoil_market": price.get("market_price"),
        })

    # Sort: oddities first (they're the interesting ones), then by set+cn.
    rows.sort(key=lambda r: (0 if r["category"] == "oddity (needs review)" else 1, r["set"], str(r["cn"]), r["pid"]))

    oddities = [r for r in rows if r["category"] == "oddity (needs review)"]
    chases = [r for r in rows if r["category"] == "chase rarity"]
    unmatched = [r for r in rows if r["category"] == "no card match"]

    print()
    print(f"Total Holofoil products: {len(rows)}")
    print(f"  chase rarity (expected): {len(chases)}")
    print(f"  oddity (needs review):   {len(oddities)}")
    print(f"  no card match:           {len(unmatched)}")
    print()

    if oddities:
        print("=" * 100)
        print("ODDITIES — need a curation decision (variant label, set bucket, etc.)")
        print("=" * 100)
        print(f"{'pid':>7s}  {'set':<24s} {'cn':>4s}  {'rarity':<10s}  {'normal':>7s}  {'foil':>7s}  {'holo':>7s}  name")
        print("-" * 100)
        for r in oddities:
            def f(x):
                return "" if x is None else f"${float(x):.2f}"
            print(f"{r['pid']:>7d}  {r['set'][:24]:<24s} {str(r['cn']):>4s}  {r['rarity'][:10]:<10s}  {f(r['normal_low']):>7s}  {f(r['foil_low']):>7s}  {f(r['holofoil_low']):>7s}  {r['name']}")

    if unmatched:
        print()
        print("=" * 100)
        print("NO CARD MATCH — Holofoil price rows whose product_id isn't in cards table")
        print("=" * 100)
        for r in unmatched:
            print(f"  pid={r['pid']:>7d}  holo_low=${(r['holofoil_low'] or 0):.2f}")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nFull audit written to {args.csv}")


if __name__ == "__main__":
    main()
