"""
Audit Wilds Unknown (or any set) cards whose foil printing is missing from
our catalog. For each card in our `cards` table:

  - Check prices_daily for a Cold Foil / Foil / Holofoil row on the card's
    tcgplayer_product_id.
  - If none, scan TCGCSV's product listing for the same set looking for
    any product whose name resembles this card (with or without a "(Foil)"
    suffix) — those are candidates for the CONNECTING_FOILS map.

Run:  python scripts/audit_missing_foils.py [--set "Wilds Unknown"]
"""
from __future__ import annotations

import argparse
import re
import time

import requests
from dotenv import load_dotenv

from supabase_client import Supabase


LORCANA_CATEGORY_ID = 71
UA = {"User-Agent": "PacksInk/1.0 audit-missing-foils"}


def fetch_json(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def normalize_name(s):
    """Lower, strip punctuation, collapse whitespace — for fuzzy matching."""
    s = (s or "").lower()
    s = re.sub(r"\(foil\)", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="Wilds Unknown", help="Set name to audit (default: Wilds Unknown)")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()

    print(f"Looking up '{args.set}' set_id...")
    sets = sb.select("sets", columns="id,name")
    set_row = next((s for s in sets if (s["name"] or "").lower() == args.set.lower()), None)
    if not set_row:
        print(f"  set '{args.set}' not found")
        return
    set_id = set_row["id"]
    print(f"  set_id={set_id}")

    print("Fetching cards in set...")
    cards = sb.select(
        "cards",
        columns="id,name,version,rarity,collector_number,tcgplayer_product_id",
        filters={"set_id": f"eq.{set_id}"},
    )
    cards = [c for c in cards if c.get("tcgplayer_product_id")]
    print(f"  {len(cards)} cards with tcgplayer_product_id")

    # Fetch every prices_daily row for these products, all printings — we
    # only need to know IF the foil row exists, not the prices themselves.
    pids = [c["tcgplayer_product_id"] for c in cards]
    print("Fetching price-row existence (all printings) for these products...")
    have_printing = {}  # product_id -> set of printings
    BATCH = 100
    for i in range(0, len(pids), BATCH):
        chunk = pids[i:i+BATCH]
        rows = sb.select(
            "prices_daily",
            columns="tcgplayer_product_id,printing",
            filters={
                "tcgplayer_product_id": f"in.({','.join(str(p) for p in chunk)})",
                "source": "eq.tcgcsv",
                "grade": "eq.raw",
            },
        )
        for r in rows:
            pid = int(r["tcgplayer_product_id"])
            have_printing.setdefault(pid, set()).add(r["printing"])

    # Identify cards missing a foil-class row.
    FOIL_PRINTINGS = {"Cold Foil", "Foil", "Holofoil"}
    chase = {"Enchanted", "Iconic", "Epic"}
    missing = []
    for c in cards:
        if (c.get("rarity") or "").lower() in {r.lower() for r in chase}:
            continue  # chase cards only have one printing by design
        printings = have_printing.get(c["tcgplayer_product_id"], set())
        if not (printings & FOIL_PRINTINGS):
            missing.append(c)
    print(f"\n{len(missing)} cards missing any foil printing\n")

    # Fetch TCGCSV product list for this set group to look for companion entries.
    print("Locating matching TCGCSV group...")
    groups = fetch_json(f"https://tcgcsv.com/tcgplayer/{LORCANA_CATEGORY_ID}/groups")
    groups = groups.get("results") if isinstance(groups, dict) else groups
    target = next((g for g in groups
                   if args.set.lower() in (g.get("name") or "").lower()), None)
    if not target:
        print("  no matching TCGCSV group; bailing on companion lookup.")
        return
    gid = target["groupId"]
    print(f"  group {target.get('name')} (id {gid})")
    prods = fetch_json(f"https://tcgcsv.com/tcgplayer/{LORCANA_CATEGORY_ID}/{gid}/products")
    prods = prods.get("results") if isinstance(prods, dict) else prods
    print(f"  {len(prods)} TCGCSV products")

    # Index TCGCSV products by normalized name.
    by_name = {}
    by_pid = {p["productId"]: p for p in prods}
    for p in prods:
        nname = normalize_name(p.get("name") or "")
        by_name.setdefault(nname, []).append(p)

    # For each missing-foil card, look for any other TCGCSV product whose
    # name fuzzy-matches but lives at a different productId.
    print("=" * 100)
    print(f"MISSING FOILS in {args.set} — candidate matches from TCGCSV")
    print("=" * 100)
    print(f"{'cn':>4s}  {'rarity':<10s}  {'base_pid':>8s}  {'foil_pid':>8s}  base_name -> candidate")
    print("-" * 100)

    found = 0
    no_candidates = []
    for c in missing:
        base_name = (c["name"] or "")
        if c.get("version"):
            base_name = f"{base_name} - {c['version']}"
        nkey = normalize_name(base_name)
        matches = by_name.get(nkey, [])
        # Drop the base itself.
        candidates = [p for p in matches if p["productId"] != c["tcgplayer_product_id"]]
        if candidates:
            for cand in candidates:
                print(f"{(c['collector_number'] or ''):>4s}  {(c['rarity'] or '')[:10]:<10s}  "
                      f"{c['tcgplayer_product_id']:>8d}  {cand['productId']:>8d}  {base_name} -> {cand.get('name')}")
            found += 1
        else:
            no_candidates.append(c)

    print()
    print(f"Cards with candidates: {found}")
    print(f"Cards with no candidate match: {len(no_candidates)}")
    if no_candidates:
        print()
        print("Cards with NO companion-foil candidate (true missing prints):")
        for c in no_candidates:
            base_name = (c["name"] or "")
            if c.get("version"):
                base_name = f"{base_name} - {c['version']}"
            print(f"  {(c['collector_number'] or ''):>4s}  {(c['rarity'] or '')[:10]:<10s}  pid={c['tcgplayer_product_id']:>8d}  {base_name}")


if __name__ == "__main__":
    main()
