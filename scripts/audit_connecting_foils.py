"""
Find TCGPlayer products that are listed separately as "(Foil)" companion
listings rather than getting a Cold Foil row attached to the base product.
These are typically Winterspell / Wilds Unknown cards whose foil art forms
a connecting mural across the set — TCGPlayer treats them as distinct SKUs.

We need to map each "(Foil)" companion back to its base card so the base
card's foil slot gets the right price (instead of looking empty in our UI).

Run:  python scripts/audit_connecting_foils.py [--csv out.csv]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time

import requests
from dotenv import load_dotenv

from supabase_client import Supabase


LORCANA_CATEGORY_ID = 71
SETS_OF_INTEREST = {"Winterspell", "Wilds Unknown"}

UA = {"User-Agent": "PacksInk/1.0 audit-connecting-foils"}


def fetch_json(url: str) -> dict | list:
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    return {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="Write the full mapping to CSV")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()

    print("Fetching TCGCSV groups...")
    groups = fetch_json(f"https://tcgcsv.com/tcgplayer/{LORCANA_CATEGORY_ID}/groups")
    groups = groups.get("results") if isinstance(groups, dict) else groups
    target_groups = [
        g for g in groups
        if any(s.lower() in (g.get("name") or "").lower() for s in SETS_OF_INTEREST)
        # Also accept "Disney Lorcana: X" prefix
    ]
    if not target_groups:
        # TCGCSV uses fuller names like "Disney Lorcana: Wilds Unknown"
        target_groups = [
            g for g in groups
            if any(s.lower() in (g.get("name") or "").lower() for s in
                   ["wilds unknown", "winterspell"])
        ]
    print(f"  {len(target_groups)} matching groups: {[g.get('name') for g in target_groups]}")

    # Pull all products per target group.
    base_by_name: dict[str, dict] = {}   # normalized non-foil name → product
    foil_companions: list[dict] = []     # products whose name ends in "(Foil)"
    for g in target_groups:
        gid = g.get("groupId")
        prods = fetch_json(f"https://tcgcsv.com/tcgplayer/{LORCANA_CATEGORY_ID}/{gid}/products")
        prods = prods.get("results") if isinstance(prods, dict) else prods
        print(f"  group {g.get('name')}: {len(prods)} products")
        for p in prods:
            name = (p.get("name") or "").strip()
            if name.endswith("(Foil)"):
                foil_companions.append({"group": g.get("name"), "name": name, "productId": p["productId"]})
            else:
                # Base print (any non-foil-companion).
                key = name.lower()
                base_by_name[key] = {"group": g.get("name"), "name": name, "productId": p["productId"]}

    print(f"\nFound {len(foil_companions)} '(Foil)' companion products")

    # Match each companion to a base by stripping " (Foil)" suffix.
    pairs: list[dict] = []
    unmatched: list[dict] = []
    for c in foil_companions:
        base_name = re.sub(r"\s*\(Foil\)\s*$", "", c["name"]).strip()
        base = base_by_name.get(base_name.lower())
        if base:
            pairs.append({
                "set": c["group"],
                "base_name": base["name"],
                "base_pid": base["productId"],
                "foil_name": c["name"],
                "foil_pid": c["productId"],
            })
        else:
            unmatched.append(c)

    print(f"  matched: {len(pairs)}")
    print(f"  unmatched: {len(unmatched)}")

    # Look up cards table to attach card_id for each base.
    if pairs:
        base_pids = [p["base_pid"] for p in pairs]
        print("\nLooking up our cards table for base products...")
        cards = sb.select(
            "cards",
            columns="id,name,version,rarity,collector_number,tcgplayer_product_id",
            filters={"tcgplayer_product_id": f"in.({','.join(str(p) for p in base_pids)})"},
        )
        card_by_pid = {int(c["tcgplayer_product_id"]): c for c in cards if c.get("tcgplayer_product_id") is not None}

        for row in pairs:
            card = card_by_pid.get(row["base_pid"])
            if card:
                row["card_id"] = card["id"]
                row["rarity"] = card.get("rarity")
                row["cn"] = card.get("collector_number")
            else:
                row["card_id"] = None

    # Display.
    if pairs:
        print()
        print("=" * 100)
        print("MATCHED PAIRS — these are connecting-art foils to wire into the catalog")
        print("=" * 100)
        print(f"{'set':<18s}  {'cn':>4s}  {'rarity':<10s}  {'base_pid':>8s}  {'foil_pid':>8s}  card_id")
        print("-" * 100)
        for r in sorted(pairs, key=lambda x: (x["set"], str(x.get("cn") or ""))):
            cid = r.get("card_id") or "(no card row)"
            print(f"{r['set'][:18]:<18s}  {str(r.get('cn') or ''):>4s}  {(r.get('rarity') or '')[:10]:<10s}  {r['base_pid']:>8d}  {r['foil_pid']:>8d}  {cid}  {r['base_name']}")

    if unmatched:
        print()
        print(f"Unmatched '(Foil)' companions ({len(unmatched)}):")
        for u in unmatched:
            print(f"  [{u['group']}] {u['name']} (pid {u['productId']})")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["set", "cn", "rarity", "card_id", "base_name", "base_pid", "foil_name", "foil_pid"])
            w.writeheader()
            for r in pairs:
                w.writerow({
                    "set": r["set"], "cn": r.get("cn"), "rarity": r.get("rarity"),
                    "card_id": r.get("card_id"), "base_name": r["base_name"], "base_pid": r["base_pid"],
                    "foil_name": r["foil_name"], "foil_pid": r["foil_pid"],
                })
        print(f"\nMapping written to {args.csv}")


if __name__ == "__main__":
    main()
