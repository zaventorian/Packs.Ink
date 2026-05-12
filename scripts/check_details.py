"""
Detailed diagnostics on data we've loaded:
  1. Distribution of `printing` values in prices_daily (Holofoil vs Cold Foil vs Normal).
  2. Orphan TCGCSV products with "(Foil)" or "(Epic)" suffixes — variant-art orphans.
  3. The 9 unpriced cards with set names resolved.
"""
from __future__ import annotations

from collections import Counter

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

load_dotenv()
sb = Supabase()
UA = {"User-Agent": "PacksInk/1.0"}


# ── 1. Printing distribution ──────────────────────────────────────────────
print("=" * 70)
print("1. Distinct 'printing' values in prices_daily (today)")
print("=" * 70)
rows = sb.select("prices_daily", columns="printing", filters={"source": "eq.tcgcsv"})
counts = Counter(r["printing"] for r in rows)
for p, n in counts.most_common():
    print(f"  {p:20s}  {n:>5} rows")


# ── 2. Variant-suffix orphans ─────────────────────────────────────────────
print()
print("=" * 70)
print("2. Orphan products with variant suffix in name (likely Lorcast gaps)")
print("=" * 70)

price_rows = sb.select("prices_daily", columns="tcgplayer_product_id", filters={"source": "eq.tcgcsv"})
price_pids = {r["tcgplayer_product_id"] for r in price_rows}
card_rows = sb.select("cards", columns="tcgplayer_product_id", filters={"tcgplayer_product_id": "not.is.null"})
card_pids = {r["tcgplayer_product_id"] for r in card_rows}
orphans = price_pids - card_pids

groups = requests.get("https://tcgcsv.com/tcgplayer/71/groups", headers=UA, timeout=60).json()
groups = groups.get("results") or groups

suffix_orphans: list[tuple[str, str]] = []  # (group_name, product_name)
SUFFIXES = ("(Foil)", "(Epic)", "(Enchanted)", "(Iconic)", "(Promo)")
for g in groups:
    prods = requests.get(
        f"https://tcgcsv.com/tcgplayer/71/{g['groupId']}/products",
        headers=UA, timeout=60,
    ).json()
    prods = prods.get("results") or prods
    for p in prods:
        if p["productId"] not in orphans:
            continue
        name = p.get("name") or ""
        if any(suf in name for suf in SUFFIXES):
            suffix_orphans.append((g["name"], name))

print(f"Found {len(suffix_orphans)} orphans with variant suffix:\n")
by_group: dict[str, list[str]] = {}
for gn, pn in suffix_orphans:
    by_group.setdefault(gn, []).append(pn)
for gn, names in sorted(by_group.items()):
    print(f"  {gn}  ({len(names)}):")
    for n in sorted(names):
        print(f"    - {n}")
    print()


# ── 3. The 9 unpriced cards, with set names ──────────────────────────────
print("=" * 70)
print("3. The 9 unpriced cards (Lorcast has them, TCGCSV had no price today)")
print("=" * 70)
sets = sb.select("sets", columns="id,name")
set_name = {s["id"]: s["name"] for s in sets}

unpriced_cards = sb.select(
    "cards",
    columns="id,name,version,set_id,rarity,tcgplayer_product_id",
    filters={"tcgplayer_product_id": "not.is.null"},
)
unpriced = [c for c in unpriced_cards if c["tcgplayer_product_id"] not in price_pids]
for c in unpriced:
    title = c["name"] + (" - " + c["version"] if c.get("version") else "")
    print(f"  [{c['rarity']:>9s}] {title}")
    print(f"    set: {set_name.get(c['set_id'], c['set_id'])}   pid: {c['tcgplayer_product_id']}")
