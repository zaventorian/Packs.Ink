"""
One-shot patcher: backfill `cards.strength / willpower / lore / move_cost`
from Lorcast.

Run after `supabase/43_card_tier2_stats.sql`. Idempotent — safe to re-run.

Updates row-by-row in small batches because the values are unique per
card (no group-by-value win like patch_card_inks gets). Uses a single
PATCH per card via PostgREST's `eq.<id>` filter; ~2k rows total, plenty
fast against the service-role endpoint.

Usage:
    python scripts/patch_card_tier2.py
"""
from __future__ import annotations

import os
import time

import requests
from dotenv import load_dotenv

from supabase_client import Supabase


LORCAST_BASE = "https://api.lorcast.com/v0"
UA = {"User-Agent": "PacksInk/1.0 patch-card-tier2"}


def fetch_json(url: str):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def main() -> None:
    load_dotenv()
    sb = Supabase()

    print("Fetching sets from Lorcast...")
    sets_resp = fetch_json(f"{LORCAST_BASE}/sets")
    sets = sets_resp.get("results") if isinstance(sets_resp, dict) else sets_resp
    print(f"  {len(sets)} sets")

    all_cards: list[dict] = []
    for s in sets:
        sid = s.get("id")
        if not sid:
            continue
        resp = fetch_json(f"{LORCAST_BASE}/sets/{sid}/cards")
        cards = resp.get("results") if isinstance(resp, dict) else resp or []
        print(f"  {s.get('name','?')[:32]:<32s}  {len(cards)} cards")
        all_cards.extend(cards)

    print(f"\nTotal Lorcast cards: {len(all_cards)}")

    print("Loading current rows from Supabase...")
    existing = sb.select("cards", columns="id,strength,willpower,lore,move_cost")
    cur = {r["id"]: r for r in existing}
    print(f"  {len(cur)} rows currently in Supabase")

    updates: list[tuple[str, dict]] = []
    missing = 0
    for c in all_cards:
        cid = c.get("id")
        if not cid:
            continue
        row = cur.get(cid)
        if row is None:
            missing += 1
            continue
        new = {
            "strength":  c.get("strength"),
            "willpower": c.get("willpower"),
            "lore":      c.get("lore"),
            "move_cost": c.get("move_cost"),
        }
        # Skip if already correct.
        if all(row.get(k) == v for k, v in new.items()):
            continue
        updates.append((cid, new))

    print(f"\nCards in Lorcast but not in our table: {missing}")
    print(f"Rows needing update: {len(updates)}")

    if not updates:
        print("Nothing to do.")
        return

    URL = os.environ["SUPABASE_URL"].rstrip("/")
    KEY = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }

    total = 0
    for cid, new in updates:
        params = {"id": f"eq.{cid}"}
        r = requests.patch(f"{URL}/rest/v1/cards", headers=headers,
                           params=params, json=new, timeout=60)
        if not r.ok:
            raise RuntimeError(f"PATCH failed for {cid} ({r.status_code}): {r.text[:300]}")
        total += 1
        if total % 200 == 0:
            print(f"  patched {total}/{len(updates)}")
    print(f"\nDone — {total} rows updated.")


if __name__ == "__main__":
    main()
