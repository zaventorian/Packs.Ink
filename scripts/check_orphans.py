"""
Diagnostic: which TCGCSV products have prices but no Lorcast card metadata?
Helps us see what's truly sealed vs. what's a card we should have but missed.
"""
from __future__ import annotations

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

load_dotenv()
sb = Supabase()

# All productIds in today's prices_daily (paginated)
price_rows = sb.select(
    "prices_daily",
    columns="tcgplayer_product_id",
    filters={"source": "eq.tcgcsv"},
)
price_pids = {row["tcgplayer_product_id"] for row in price_rows}

# All productIds in cards
card_rows = sb.select(
    "cards",
    columns="tcgplayer_product_id",
    filters={"tcgplayer_product_id": "not.is.null"},
)
card_pids = {row["tcgplayer_product_id"] for row in card_rows}

orphans = price_pids - card_pids
print(f"Total priced products: {len(price_pids)}")
print(f"Total cards with tcgplayer_id: {len(card_pids)}")
print(f"Priced products NOT in cards (orphans): {len(orphans)}")
print(f"Cards with no current price: {len(card_pids - price_pids)}")

if orphans:
    # Fetch product names from TCGCSV to see what they are
    print("\nFetching orphan product names from TCGCSV...")
    groups = requests.get(
        "https://tcgcsv.com/tcgplayer/71/groups",
        headers={"User-Agent": "PacksInk/1.0"},
        timeout=60,
    ).json()
    groups = groups.get("results") or groups

    orphans_by_group: dict[str, list[str]] = {}
    for g in groups:
        gid = g["groupId"]
        gname = g["name"]
        prods = requests.get(
            f"https://tcgcsv.com/tcgplayer/71/{gid}/products",
            headers={"User-Agent": "PacksInk/1.0"},
            timeout=60,
        ).json()
        prods = prods.get("results") or prods
        for p in prods:
            if p["productId"] in orphans:
                orphans_by_group.setdefault(gname, []).append(p.get("name") or str(p["productId"]))

    print("\nOrphans by TCGPlayer group:")
    for gname, names in sorted(orphans_by_group.items(), key=lambda x: -len(x[1])):
        print(f"\n  {gname}  ({len(names)} products):")
        for n in sorted(names)[:8]:
            print(f"    - {n}")
        if len(names) > 8:
            print(f"    ... and {len(names) - 8} more")
