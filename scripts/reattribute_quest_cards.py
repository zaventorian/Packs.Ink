"""
reattribute_quest_cards.py — split graded sales that the eBay matcher lumped onto
a card's BOOSTER printing when they're actually the Illumineer's-Quest version
(different collector number, different product), using the slab label's collector#.

The matcher keys on name+cn, so a quest card that was missing from `cards` (or
whose listings omit the cn) has its sales orphaned onto the only/closest real
card. This reads each sale's slab label (collector#) via OCR and re-attributes
the ones whose number matches the quest card.

CROSS-SET by design: the booster and quest printings live in different sets, so
ocr_slab_audit.py's same-set reconcile() can't move them — this does it explicitly
for a known (from_card, to_card, to_cn) triple. Reuses ocr_slab_audit's OCR
helpers (same anonymous public-CDN GETs; same eBay-safety caveat — do NOT run from
the account holder's home IP while logged into eBay).

    python scripts/reattribute_quest_cards.py            # dry-run
    python scripts/reattribute_quest_cards.py --commit   # apply + refresh rollup
"""
from __future__ import annotations

import argparse
import sys
import time

import requests

from ocr_slab_audit import (crop_label, ocr_tesseract, parse_label, save_ocr,
                            UA, SB_URL, HEAD, DELAY)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (from_card_id, to_card_id, to_collector_number, label) triples.
JOBS = [
    ("crd_f478c96f7b1b45b790d74395480da563",   # Piglet - Pooh Pirate Captain #16 SR (Into the Inklands booster)
     "crd_custom_544487_piglet_pooh",          # Piglet - Pooh Pirate Captain #223 (Deep Trouble quest)
     "223", "Piglet - Pooh Pirate Captain → Deep Trouble #223"),
]


def fetch_sales(card_id):
    rows, off = [], 0
    while True:
        r = requests.get(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=60, params={
            "select": "item_id,title,image_url,sale_price,slab_ocr",
            "card_id": "eq." + card_id, "excluded": "is.false",
            "image_url": "not.is.null", "offset": off, "limit": 1000})
        r.raise_for_status()
        page = r.json()
        rows.extend(page)
        if len(page) < 1000:
            break
        off += 1000
    return rows


def move_sale(item_id, to_card):
    r = requests.patch(f"{SB_URL}/rest/v1/graded_sales",
                       headers={**HEAD, "Content-Type": "application/json", "Prefer": "return=minimal"},
                       params={"item_id": "eq." + item_id}, timeout=30,
                       json={"card_id": to_card})
    r.raise_for_status()


def refresh_rollup():
    r = requests.post(f"{SB_URL}/rest/v1/rpc/refresh_graded_sales_rollup", headers=HEAD, json={}, timeout=300)
    print("rollup refresh:", "ok" if r.status_code < 300 else f"HTTP {r.status_code} {r.text[:200]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="apply re-attributions (default: dry-run)")
    args = ap.parse_args()

    moved_total = 0
    for from_card, to_card, to_cn, label in JOBS:
        sales = fetch_sales(from_card)
        print(f"\n=== {label} ===\n{len(sales)} sale(s) on {from_card}")
        moved = stay = unreadable = 0
        for s in sales:
            ocr = s.get("slab_ocr")
            if not ocr:
                try:
                    img = requests.get(s["image_url"], headers=UA, timeout=30).content
                    ocr = ocr_tesseract(crop_label(img))
                    if args.commit:
                        save_ocr(s["item_id"], ocr)
                    time.sleep(DELAY)
                except Exception as e:
                    unreadable += 1
                    print(f"  [skip] {s['item_id']} OCR failed: {e}")
                    continue
            cn = parse_label(ocr).get("cn")
            price = s.get("sale_price")
            if cn == to_cn:
                moved += 1
                print(f"  [move] {s['item_id']} ${price} cn={cn} → {to_card}")
                if args.commit:
                    move_sale(s["item_id"], to_card)
            else:
                stay += 1
                print(f"  [stay] {s['item_id']} ${price} cn={cn or '?'} (booster/unreadable)")
        moved_total += moved
        print(f"  summary: moved {moved}, stayed {stay}, unreadable {unreadable}")

    if args.commit and moved_total:
        print(f"\nMoved {moved_total} sale(s). Refreshing rollup …")
        refresh_rollup()
    elif not args.commit:
        print("\nDRY-RUN — re-run with --commit to apply.")


if __name__ == "__main__":
    main()
