"""
etl_tcgpricelookup_daily.py — daily pull of graded card prices from
TCGPriceLookup (Trader tier). Paginates /v1/cards/search?game=lorcana,
extracts the `prices.graded.<grader>.<grade>.ebay` blob from each card,
upserts into graded_prices_daily, and refreshes graded_prices_latest.

Lorcana has ~5700 cards in their catalog at 100/page → ~58 requests/run.
Trader quota is 10k/day, so this leaves plenty of headroom.

Usage:
    pip install -r requirements.txt
    # .env must define SUPABASE_URL, SUPABASE_SERVICE_KEY, TCGPRICELOOKUP_API_KEY
    python scripts/etl_tcgpricelookup_daily.py

What it stores:
    public.graded_prices_daily (tcgplayer_product_id, grader, grade, date,
                                ebay_avg_1d, ebay_avg_7d, ebay_avg_30d)

What it does NOT store:
    - Raw TCGPlayer prices (that's etl_tcgcsv_daily.py's job)
    - Card metadata (that's load_lorcast.py's job)
    - Any card without a tcgplayer_product_id (no anchor to our catalog)
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date
from typing import Iterable

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

API_BASE = "https://api.tcgpricelookup.com/v1"
GAME_SLUG = "lorcana"
PAGE_SIZE = 100
# Conservative inter-request sleep so we don't trip Cloudflare's per-second
# burst limit (independent of the 10k/day quota).
REQUEST_DELAY_SEC = 1.0
RETRY_ON_RATE = 8     # one minute of patience before we give up
RETRY_SLEEP = 8


def fetch_page(session: requests.Session, key: str, offset: int) -> dict:
    """Hit /v1/cards/search with one retry pass for transient 429s."""
    url = f"{API_BASE}/cards/search"
    params = {"game": GAME_SLUG, "limit": PAGE_SIZE, "offset": offset}
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-etl/1.0"}
    for attempt in range(RETRY_ON_RATE):
        r = session.get(url, params=params, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 or (r.status_code == 200 and r.text.startswith('{"error": "Rate limit')):
            print(f"  rate limited at offset={offset} (attempt {attempt+1}/{RETRY_ON_RATE}); sleeping {RETRY_SLEEP}s")
            time.sleep(RETRY_SLEEP)
            continue
        r.raise_for_status()
    raise RuntimeError(f"persistent rate-limit at offset={offset}")


def extract_rows(card: dict, today: str) -> list[dict]:
    """Pull graded prices out of one card record. Skips cards without a
    tcgplayer_product_id or without any graded data."""
    tcg_id = card.get("tcgplayer_id")
    if not tcg_id:
        return []
    try:
        tcg_id_int = int(tcg_id)
    except (TypeError, ValueError):
        return []
    graded = ((card.get("prices") or {}).get("graded")) or {}
    if not graded:
        return []
    rows = []
    for grader, grades in graded.items():
        if not isinstance(grades, dict):
            continue
        for grade, vals in grades.items():
            if not isinstance(vals, dict):
                continue
            ebay = vals.get("ebay") or {}
            avg_1d  = ebay.get("avg_1d")
            avg_7d  = ebay.get("avg_7d")
            avg_30d = ebay.get("avg_30d")
            # All three null → nothing to learn from this entry; skip.
            if avg_1d is None and avg_7d is None and avg_30d is None:
                continue
            rows.append({
                "tcgplayer_product_id": tcg_id_int,
                "grader": str(grader).lower(),
                "grade": str(grade),
                "date": today,
                "ebay_avg_1d":  avg_1d,
                "ebay_avg_7d":  avg_7d,
                "ebay_avg_30d": avg_30d,
                "source": "tcgpricelookup",
            })
    return rows


def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    api_key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not api_key:
        print("ERROR: TCGPRICELOOKUP_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)
    sb = Supabase()
    session = requests.Session()
    today = date.today().isoformat()

    # Page through the whole Lorcana catalog. The first response also tells
    # us the true total so we know when to stop.
    all_rows: list[dict] = []
    cards_with_graded = 0
    total_cards = None
    offset = 0
    pages = 0
    while True:
        data = fetch_page(session, api_key, offset)
        page = data.get("data") or []
        if total_cards is None:
            total_cards = int(data.get("total") or 0)
            print(f"Catalog total: {total_cards} cards · page size {PAGE_SIZE} · expected pages {(total_cards+PAGE_SIZE-1)//PAGE_SIZE}")
        pages += 1
        for card in page:
            extracted = extract_rows(card, today)
            if extracted:
                cards_with_graded += 1
                all_rows.extend(extracted)
        if not page or (offset + len(page)) >= total_cards:
            break
        offset += len(page)
        time.sleep(REQUEST_DELAY_SEC)
    print(f"Pulled {pages} pages · {cards_with_graded} cards with graded data · {len(all_rows)} graded-price rows")

    if not all_rows:
        print("No graded rows to upsert. Done.")
        return

    # Upsert in batches. Conflict target = primary key
    # (tcgplayer_product_id, grader, grade, date), so re-runs same-day are
    # idempotent.
    BATCH = 500
    upserted = 0
    for batch in chunked(all_rows, BATCH):
        res = sb.upsert(
            "graded_prices_daily", batch,
            on_conflict="tcgplayer_product_id,grader,grade,date",
        )
        upserted += len(batch)
        print(f"  upserted {upserted}/{len(all_rows)} rows")
    print(f"Upsert complete · {upserted} rows total")

    # Refresh the latest matview so site queries pick up today's data.
    try:
        sb.rpc("refresh_graded_prices_latest")
        print("graded_prices_latest refreshed")
    except Exception as e:
        print(f"WARN: matview refresh failed (run migration 32_graded_prices.sql?): {e}")


if __name__ == "__main__":
    main()
