"""
One-shot patcher: backfill the `cards.inkable` column from Lorcast's
`inkwell` field. load_lorcast.py was reading the wrong key (`inkable`
instead of `inkwell`), so every existing row in our cards table has
inkable=NULL. This script fixes the existing data without re-loading
everything else.

Idempotent: safe to re-run. Only writes when the new value differs from
what's already in the row.
"""
from __future__ import annotations

import time
from collections import Counter

import requests
from dotenv import load_dotenv

from supabase_client import Supabase


LORCAST_BASE = "https://api.lorcast.com/v0"
UA = {"User-Agent": "PacksInk/1.0 patch-inkable"}


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

    all_cards = []
    for s in sets:
        sid = s.get("id")
        if not sid:
            continue
        cards = fetch_json(f"{LORCAST_BASE}/sets/{sid}/cards")
        if isinstance(cards, dict):
            cards = cards.get("results") or []
        print(f"  {s.get('name','?')[:32]:<32s}  {len(cards)} cards")
        all_cards.extend(cards)

    print(f"\nTotal Lorcast cards: {len(all_cards)}")

    # Build the patch payload: only cards whose inkwell value would change.
    # We include set_id in each row because the Supabase upsert path uses
    # INSERT ... ON CONFLICT DO UPDATE, and the INSERT half fails the
    # NOT NULL check on set_id otherwise.
    print("Loading current rows from Supabase...")
    existing = sb.select("cards", columns="id,set_id,inkable")
    cur = {r["id"]: r for r in existing}
    print(f"  {len(cur)} rows currently in Supabase")

    changes: list[dict] = []
    distrib = Counter()
    missing = 0
    for c in all_cards:
        cid = c.get("id")
        if not cid:
            continue
        v = c.get("inkwell")
        distrib[v] += 1
        row = cur.get(cid)
        if row is None:
            missing += 1
            continue
        if row.get("inkable") != v:
            changes.append({"id": cid, "set_id": row["set_id"], "inkable": v})

    print(f"\nLorcast inkwell distribution: {dict(distrib)}")
    print(f"Cards in Lorcast but not in our table: {missing}")
    print(f"Rows needing update: {len(changes)}")

    if not changes:
        print("Nothing to do.")
        return

    # Group ids by target value and PATCH in chunks. PostgREST PATCH lets us
    # update every matching row to the same value in one round-trip, so this
    # only takes (true_count + false_count) / BATCH requests — usually ~30.
    import os, requests
    URL = os.environ["SUPABASE_URL"].rstrip("/")
    KEY = os.environ["SUPABASE_SERVICE_KEY"]
    headers = {
        "apikey": KEY, "Authorization": f"Bearer {KEY}",
        "Content-Type": "application/json", "Prefer": "return=minimal",
    }
    by_value: dict = {True: [], False: [], None: []}
    for c in changes:
        by_value.setdefault(c["inkable"], []).append(c["id"])

    BATCH = 200
    total_updated = 0
    for value, ids in by_value.items():
        if not ids:
            continue
        print(f"\nSetting inkable={value} for {len(ids)} rows...")
        for i in range(0, len(ids), BATCH):
            chunk = ids[i:i+BATCH]
            params = {"id": f"in.({','.join(chunk)})"}
            body = {"inkable": value}
            r = requests.patch(f"{URL}/rest/v1/cards", headers=headers,
                               params=params, json=body, timeout=60)
            if not r.ok:
                raise RuntimeError(f"PATCH failed ({r.status_code}): {r.text[:300]}")
            total_updated += len(chunk)
            print(f"  patched {i+len(chunk)}/{len(ids)}")
    print(f"\nDone — {total_updated} rows updated.")


if __name__ == "__main__":
    main()
