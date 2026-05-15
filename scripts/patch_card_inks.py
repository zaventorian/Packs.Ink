"""
One-shot patcher: backfill `cards.inks` (text[]) from Lorcast's `inks` field.

Lorcana introduced dual-ink cards (one card with two ink colors, e.g.
Ink Geyser = Emerald + Sapphire). Lorcast exposes this as
`inks: ["Emerald", "Sapphire"]` with `ink: null`. Our loader was only
reading `ink`, so dual cards landed with NULL — the deck-stats pie
bucketed them as "Unknown".

After running migration 27_card_inks_array.sql, this script populates
`inks` for every card. Idempotent: safe to re-run.

Groups updates by `inks` value so the PATCH count stays low (one PATCH
per unique inks combination — usually <30 combos across all cards).

Usage:
    python scripts/patch_card_inks.py
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict

import requests
from dotenv import load_dotenv

from supabase_client import Supabase


LORCAST_BASE = "https://api.lorcast.com/v0"
UA = {"User-Agent": "PacksInk/1.0 patch-card-inks"}


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


def resolve_inks(c: dict) -> list[str] | None:
    """Mirror load_lorcast.py's logic. Prefer the `inks` array; fall back to
    the legacy scalar `ink` for older cards."""
    inks = c.get("inks")
    if inks:
        return list(inks)
    single = c.get("ink")
    return [single] if single else None


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
    existing = sb.select("cards", columns="id,set_id,ink,inks")
    cur = {r["id"]: r for r in existing}
    print(f"  {len(cur)} rows currently in Supabase")

    distrib = Counter()
    missing = 0
    # Group changes by serialized inks value so we can do one PATCH per
    # unique combo (e.g. all "Amber" cards in one call, all
    # "Emerald,Sapphire" in another).
    by_inks: dict[str, list[str]] = defaultdict(list)
    inks_values: dict[str, list[str] | None] = {}

    for c in all_cards:
        cid = c.get("id")
        if not cid:
            continue
        new_inks = resolve_inks(c)
        distrib[tuple(new_inks) if new_inks else None] += 1
        row = cur.get(cid)
        if row is None:
            missing += 1
            continue
        # Skip if already correct.
        cur_inks = row.get("inks")
        if cur_inks == new_inks:
            continue
        key = json.dumps(new_inks, sort_keys=True)
        by_inks[key].append(cid)
        inks_values[key] = new_inks

    print(f"\nLorcast inks distribution (top):")
    for inks, n in distrib.most_common(15):
        print(f"  {str(inks):<40s} {n}")
    print(f"Cards in Lorcast but not in our table: {missing}")
    print(f"Rows needing update: {sum(len(v) for v in by_inks.values())}")

    if not by_inks:
        print("Nothing to do.")
        return

    URL = os.environ["SUPABASE_URL"].rstrip("/")
    KEY = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }

    BATCH = 200
    total_updated = 0
    for key, ids in by_inks.items():
        value = inks_values[key]
        print(f"\nSetting inks={value} for {len(ids)} rows...")
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i+BATCH]
            params = {"id": f"in.({','.join(chunk)})"}
            body = {"inks": value}
            r = requests.patch(f"{URL}/rest/v1/cards", headers=headers,
                               params=params, json=body, timeout=60)
            if not r.ok:
                raise RuntimeError(f"PATCH failed ({r.status_code}): {r.text[:300]}")
            total_updated += len(chunk)
            print(f"  patched {i+len(chunk)}/{len(ids)}")
    print(f"\nDone — {total_updated} rows updated.")


if __name__ == "__main__":
    main()
