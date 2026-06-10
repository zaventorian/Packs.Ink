"""
patch_pid_overrides.py — push the client-side TCG_PID_OVERRIDES into the
cards table so the card_prices_latest matview's INNER JOIN picks them up.

Client-side overrides in Index.html are great for hot-fixing display, but
the matview can't see them — its JOIN on cards.tcgplayer_product_id only
fires when the column is populated in the DB. After this script runs:

  1. cards.tcgplayer_product_id gets set/overwritten for each (name, cn)
     entry in OVERRIDES below.
  2. We refresh card_prices_latest so prices_daily rows for those pids
     start joining through.

Re-run anytime the OVERRIDES list in Index.html changes.

Usage:
    python scripts/patch_pid_overrides.py
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

# Keep in sync with TCG_PID_OVERRIDES in Index.html.
OVERRIDES = {
    "A Whole New World|10": 654595,
    "Mad Hatter - Unruly Eccentric|16": 679565,
    "Stitch - High Badness Level|35": 673336,
    "Scrooge McDuck - S.H.U.S.H. Agent|36": 683650,
    "Belle - Apprentice Inventor|37": 651391,
    "Mulan - Disguised Soldier|38": 661852,
    "Goofy - Set for Adventure|39": 678645,
    "Beast - Gracious Prince|40": 651393,
    "Belle - Accomplished Mystic|41": 647598,
    "Stitch - Carefree Snowboarder|42": 683651,
    "Ariel - Curious Traveler|43": 692413,
    "Maleficent - Imperious Traveler|44": 692476,
    "Cruella De Vil - Judgmental Traveler|45": 692477,
    "Queen of Hearts - Impatient Traveler|46": 692478,
    "Cinderella - Resourceful Traveler|47": 692479,
    "Pocahontas - Steadfast Traveler|48": 692480,
    "Lenny - Toy Binoculars|49": 692481,
    "Zipper - Tiny Helper|50": 692482,
    "Will o' the Wisp - Forest Spirit|51": 692483,
    "Mickey Mouse - Playful Sorcerer|7": 559564,
    "Iago - Out of Reach|8": 630086,
    "Mickey Mouse - True Friend|36": 653906,            # Promo Set 2 — Puzzle Promo
    "Tinker Bell - Snowflake Collector|33": 673334,     # Promo Set 3 — SC Participant
    "Tinker Bell - Snowflake Collector|34": 673333,     # Promo Set 3 — SC Championship (foil)
    "Hiro Hamada - Armor Designer|24":  620277,
    "Hiro Hamada - Armor Designer|24B": 620276,
}


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    print(f"Applying {len(OVERRIDES)} pid override(s)…")
    applied = 0
    already = 0
    missing = 0
    for key, pid in OVERRIDES.items():
        name, cn = key.rsplit("|", 1)
        # cards.name + cards.version recompose the override key. Search by
        # collector_number and either full name or "base|version".
        candidates = []
        if " - " in name:
            base, version = name.split(" - ", 1)
            candidates.append((base, version))
        else:
            candidates.append((name, None))

        matched_rows = []
        for cand_name, cand_version in candidates:
            filters = {
                "name": f"eq.{cand_name}",
                "collector_number": f"eq.{cn}",
            }
            if cand_version is not None:
                filters["version"] = f"eq.{cand_version}"
            try:
                rows = sb.select("cards", columns="id,name,version,collector_number,tcgplayer_product_id", filters=filters)
            except Exception as e:
                print(f"  ERR select {cand_name} #{cn}: {e}")
                rows = []
            if rows:
                matched_rows = rows
                break

        if not matched_rows:
            print(f"  skip (no card row): {name} #{cn}")
            missing += 1
            continue

        for row in matched_rows:
            if row.get("tcgplayer_product_id") == pid:
                already += 1
                continue
            try:
                sb.update("cards", match={"id": row["id"]}, patch={"tcgplayer_product_id": pid})
                print(f"  {row['id'][:18]}..  {name} #{cn}  -> {pid}  (was {row.get('tcgplayer_product_id')})")
                applied += 1
            except Exception as e:
                print(f"  ERR update {row['id']}: {repr(e)[:200]}")

    print(f"\nApplied {applied}, already correct {already}, missing {missing}.")

    # Custom cards that need real cards rows so the matview JOIN fires.
    # Each Extras/Promo card Lorcast doesn't index goes here so prices_daily
    # entries flow into card_prices_latest via the cards JOIN.
    print("\nUpserting synthetic cards rows for Lorcast-missing products...")
    CHALLENGE_PROMO_SET = "set_e0eb34fc0fbb446886f84c34381d4dce"
    def tcg_img(pid, w):
        return f"https://tcgplayer-cdn.tcgplayer.com/product/{pid}_{w}w.jpg"
    synthetic_cards = [
        {  # Elsa - Queen Regent — Promo Set 2 #16 (Launch Location Exclusive,
           # Lorcast-unindexed). Stats mirror the base Elsa - Queen Regent.
            "id": "crd_custom_647091_elsa_queen_regent",
            "set_id": "set_1fd69818f6e44dd79e922f403aa4f6d9",  # Promo Set 2
            "name": "Elsa", "version": "Queen Regent",
            "rarity": "Promo", "ink": "Amethyst", "inks": ["Amethyst"],
            "collector_number": "16", "cost": 4, "inkable": True,
            "card_type": "Character",
            "classifications": ["Storyborn","Hero","Queen","Sorcerer"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(647091, 200), "image_normal": tcg_img(647091, 400), "image_large": tcg_img(647091, 400),
            "tcgplayer_product_id": 647091,
        },
        {  # Golden Mickey — Challenge Promo (C1) #5 (serial numbered)
            "id": "crd_custom_554628_golden_mickey",
            "set_id": CHALLENGE_PROMO_SET,
            "name": "Mickey Mouse", "version": "Brave Little Tailor",
            "rarity": "Promo", "ink": "Ruby", "inks": ["Ruby"],
            "collector_number": "5", "cost": 8, "inkable": False,
            "card_type": "Character",
            "classifications": ["Storyborn","Hero","King"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(554628, 200), "image_normal": tcg_img(554628, 400), "image_large": tcg_img(554628, 400),
            "tcgplayer_product_id": 554628,
        },
        {  # Illumineer's Quest: Palace Heist — Bolt - Superdog (223/204)
            "id": "crd_custom_634262_bolt_superdog",
            "set_id": "set_8f4cbf5aef324eb295c4add5673e684f",  # Ursula's Return host set
            "name": "Bolt", "version": "Superdog",
            "rarity": "Super Rare", "ink": "Amber", "inks": ["Amber","Steel"],
            "collector_number": "223", "cost": 5, "inkable": False,
            "card_type": "Character",
            "classifications": ["Floodborn","Hero"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(634262, 200), "image_normal": tcg_img(634262, 400), "image_large": tcg_img(634262, 400),
            "tcgplayer_product_id": 634262,
        },
        {  # Illumineer's Quest: Palace Heist — Goofy - Groundbreaking Chef (223/204)
            "id": "crd_custom_634263_goofy_groundbreaking",
            "set_id": "set_8f4cbf5aef324eb295c4add5673e684f",  # Ursula's Return host set
            "name": "Goofy", "version": "Groundbreaking Chef",
            "rarity": "Legendary", "ink": "Amber", "inks": ["Amber"],
            "collector_number": "223", "cost": 4, "inkable": False,
            "card_type": "Character",
            "classifications": ["Storyborn","Hero"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(634263, 200), "image_normal": tcg_img(634263, 400), "image_large": tcg_img(634263, 400),
            "tcgplayer_product_id": 634263,
        },
        {  # Illumineer's Quest: Palace Heist — Pinocchio - Strings Attached (224/204)
            "id": "crd_custom_634264_pinocchio_strings",
            "set_id": "set_8f4cbf5aef324eb295c4add5673e684f",  # Ursula's Return host set
            "name": "Pinocchio", "version": "Strings Attached",
            "rarity": "Legendary", "ink": "Amethyst", "inks": ["Amethyst"],
            "collector_number": "224", "cost": 4, "inkable": False,
            "card_type": "Character",
            "classifications": ["Storyborn","Hero"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(634264, 200), "image_normal": tcg_img(634264, 400), "image_large": tcg_img(634264, 400),
            "tcgplayer_product_id": 634264,
        },
        {  # Illumineer's Quest: Palace Heist — Elsa - Ice Maker (224/204)
            "id": "crd_custom_634265_elsa_ice_maker",
            "set_id": "set_8f4cbf5aef324eb295c4add5673e684f",  # Ursula's Return host set
            "name": "Elsa", "version": "Ice Maker",
            "rarity": "Super Rare", "ink": "Amethyst", "inks": ["Amethyst","Sapphire"],
            "collector_number": "224", "cost": 7, "inkable": False,
            "card_type": "Character",
            "classifications": ["Floodborn","Hero","Queen","Sorcerer"],
            "text": None, "flavor_text": None,
            "image_small": tcg_img(634265, 200), "image_normal": tcg_img(634265, 400), "image_large": tcg_img(634265, 400),
            "tcgplayer_product_id": 634265,
        },
    ]
    try:
        sb.upsert("cards", synthetic_cards, on_conflict="id")
        print(f"  upserted {len(synthetic_cards)} synthetic card(s).")
    except Exception as e:
        print(f"  upsert failed: {repr(e)[:300]}")

    print("\nRefreshing card_prices_latest matview...")
    try:
        sb.rpc("refresh_card_prices_latest")
        print("  matview refreshed.")
    except Exception as e:
        print(f"  refresh failed: {e}\n  → run `select public.refresh_card_prices_latest();` in the Supabase SQL editor.")

    print("\nDone.")


if __name__ == "__main__":
    main()
