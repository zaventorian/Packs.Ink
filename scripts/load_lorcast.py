"""
load_lorcast.py — one-shot loader for Lorcana card + set metadata from Lorcast.

Idempotent: re-run any time Lorcast adds a new set or card. Existing rows are
upserted on primary key.

Usage:
    pip install -r requirements.txt
    cp .env.example .env   # then edit .env with your Supabase URL + secret key
    python load_lorcast.py

What it loads:
    - public.sets:   one row per Lorcana set
    - public.cards:  one row per unique card (with tcgplayer_product_id when present)

What it does NOT load:
    - prices_daily — that's TCGCSV's job (separate script)
"""
from __future__ import annotations

import time
from typing import Any

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

LORCAST_BASE = "https://api.lorcast.com/v0"


def get_json(url: str) -> Any:
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  retry in {wait}s ({e})")
            time.sleep(wait)


def transform_set(s: dict) -> dict:
    return {
        "id": s["id"],
        "code": s.get("code"),
        "name": s["name"],
        "released_at": s.get("released_at"),
        "card_count": s.get("card_count"),
    }


def transform_card(c: dict, set_id: str) -> dict:
    imgs = (c.get("image_uris") or {}).get("digital") or {}
    raw_type = c.get("type")
    if isinstance(raw_type, list):
        card_type = raw_type[0] if raw_type else None
    else:
        card_type = raw_type
    # Inks: Lorcast returns `inks: ["Emerald", "Sapphire"]` for dual-ink
    # cards (with `ink: null`) and `inks: ["Amber"]` (or similar) for
    # single-ink. We store the full array under `inks` and keep the
    # legacy scalar `ink` populated with the first entry for backwards
    # compatibility with code that hasn't migrated yet.
    inks = c.get("inks")
    if not inks:
        single = c.get("ink")
        inks = [single] if single else None
    primary_ink = inks[0] if inks else None

    return {
        "id": c["id"],
        "set_id": set_id,
        "name": c["name"],
        "version": c.get("version"),
        "collector_number": c.get("collector_number"),
        "rarity": c.get("rarity"),
        "ink": primary_ink,
        "inks": inks,
        "cost": c.get("cost"),
        "inkable": c.get("inkwell"),  # Lorcast's field name; we store it as `inkable`
        "card_type": card_type,
        "classifications": c.get("classifications"),
        "text": c.get("text"),
        "flavor_text": c.get("flavor_text"),
        "tcgplayer_product_id": c.get("tcgplayer_id"),
        "image_small": imgs.get("small"),
        "image_normal": imgs.get("normal"),
        "image_large": imgs.get("large"),
    }


def main() -> None:
    load_dotenv()
    sb = Supabase()

    print("Fetching sets from Lorcast...")
    sets_resp = get_json(f"{LORCAST_BASE}/sets")
    sets = sets_resp.get("results") if isinstance(sets_resp, dict) else sets_resp
    print(f"  found {len(sets)} sets")

    set_rows = [transform_set(s) for s in sets]
    sb.upsert("sets", set_rows, on_conflict="id")

    all_card_rows: list[dict] = []
    missing_tcg = 0

    for s in sets:
        sid = s["id"]
        sname = s.get("name", sid)
        print(f"Fetching cards for set: {sname}")
        cards_resp = get_json(f"{LORCAST_BASE}/sets/{sid}/cards")
        cards = cards_resp.get("results") if isinstance(cards_resp, dict) else cards_resp
        print(f"  {len(cards)} cards")
        for c in cards:
            row = transform_card(c, sid)
            if row["tcgplayer_product_id"] is None:
                missing_tcg += 1
            all_card_rows.append(row)

    print(f"\nTotal cards: {len(all_card_rows)} (missing tcgplayer_id: {missing_tcg})")
    sb.upsert("cards", all_card_rows, on_conflict="id")

    print("\nDone.")


if __name__ == "__main__":
    main()
