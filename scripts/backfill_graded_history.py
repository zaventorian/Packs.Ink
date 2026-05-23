"""
backfill_graded_history.py — one-shot pull of every graded snapshot
TCGPriceLookup has on file (up to 1 year) for cards in our catalog.

Workflow:
    1. Paginate /v1/cards/search?game=lorcana to find every card with
       graded data + capture each card's TCGPriceLookup UUID + tcgplayer_id.
    2. For each such card, call /v1/cards/{uuid}/history?period=1y.
    3. Walk every snapshot's `prices` array, keep the ebay-graded entries,
       upsert into public.graded_prices_daily.

Idempotent — re-running is safe (primary key is
(tcgplayer_product_id, grader, grade, date), so re-pulls overwrite same-day
rows with the same data).

Usage:
    pip install -r requirements.txt
    python scripts/backfill_graded_history.py             # full catalog
    python scripts/backfill_graded_history.py --pids 510153,527802  # targeted
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Iterable

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

API_BASE = "https://api.tcgpricelookup.com/v1"
GAME_SLUG = "lorcana"
PAGE_SIZE = 100
HISTORY_PERIOD = "1y"
REQUEST_DELAY_SEC = 1.0     # avoid Cloudflare burst limit
RETRY_ON_RATE = 8
RETRY_SLEEP = 8


def call(session: requests.Session, key: str, url: str, params: dict | None = None) -> dict:
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-backfill/1.0"}
    for attempt in range(RETRY_ON_RATE):
        r = session.get(url, params=params or {}, headers=headers, timeout=45)
        if r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                raise RuntimeError(f"non-JSON body from {url}: {r.text[:200]}")
            if isinstance(data, dict) and data.get("error") == "Rate limit exceeded":
                print(f"  burst rate-limit on {url} (attempt {attempt+1}); sleep {RETRY_SLEEP}s")
                time.sleep(RETRY_SLEEP)
                continue
            return data
        if r.status_code == 429:
            print(f"  429 on {url} (attempt {attempt+1}); sleep {RETRY_SLEEP}s")
            time.sleep(RETRY_SLEEP)
            continue
        r.raise_for_status()
    raise RuntimeError(f"persistent rate-limit on {url}")


def collect_target_cards(session: requests.Session, key: str) -> list[tuple[str, int, str]]:
    """Page through the Lorcana catalog and return [(uuid, tcg_id, name)]
    for every card that currently has at least one graded entry."""
    out: list[tuple[str, int, str]] = []
    offset = 0
    total = None
    pages = 0
    while True:
        data = call(session, key, f"{API_BASE}/cards/search",
                    {"game": GAME_SLUG, "limit": PAGE_SIZE, "offset": offset})
        page = data.get("data") or []
        if total is None:
            total = int(data.get("total") or 0)
            print(f"Catalog total: {total} cards (paging {PAGE_SIZE} at a time)")
        pages += 1
        for card in page:
            graded = ((card.get("prices") or {}).get("graded")) or {}
            if not graded:
                continue
            tcg_id = card.get("tcgplayer_id")
            try:
                tcg_id_int = int(tcg_id) if tcg_id is not None else None
            except (TypeError, ValueError):
                tcg_id_int = None
            if tcg_id_int is None:
                continue
            out.append((card["id"], tcg_id_int, card.get("name") or ""))
        if not page or (offset + len(page)) >= total:
            break
        offset += len(page)
        time.sleep(REQUEST_DELAY_SEC)
    print(f"Found {len(out)} cards with graded data across {pages} pages")
    return out


def extract_history_rows(history: dict, tcg_id: int) -> list[dict]:
    """Walk a /history response and emit one row per
    (date, grader, grade) where source=ebay."""
    rows: list[dict] = []
    for snap in history.get("data") or []:
        date_str = snap.get("date")
        if not date_str:
            continue
        for p in snap.get("prices") or []:
            if p.get("source") != "ebay":
                continue
            grader = p.get("grader")
            grade  = p.get("grade")
            if not grader or grade is None:
                continue  # eBay raw entries (no grader) are out of scope
            avg_1d  = p.get("avg_1d")
            avg_7d  = p.get("avg_7d")
            avg_30d = p.get("avg_30d")
            low     = p.get("price_low")
            high    = p.get("price_high")
            if all(v is None for v in (avg_1d, avg_7d, avg_30d, low, high)):
                continue
            rows.append({
                "tcgplayer_product_id": tcg_id,
                "grader": str(grader).lower(),
                "grade":  str(grade),
                "date":   date_str,
                "ebay_avg_1d":  avg_1d,
                "ebay_avg_7d":  avg_7d,
                "ebay_avg_30d": avg_30d,
                "ebay_low_price":  low,
                "ebay_high_price": high,
                "source": "tcgpricelookup",
            })
    return rows


def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pids", default="",
                    help="Comma-separated tcgplayer_product_ids. When set, only "
                         "backfill these specific cards instead of walking the full "
                         "Lorcana catalog. Skips the search phase entirely.")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    api_key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not api_key:
        print("ERROR: TCGPRICELOOKUP_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)
    sb = Supabase()
    session = requests.Session()

    if args.pids.strip():
        # Targeted mode — look up just these pids in TCGPriceLookup's catalog
        # and skip the full-catalog walk.
        wanted = set()
        for tok in args.pids.split(","):
            tok = tok.strip()
            if tok.isdigit():
                wanted.add(int(tok))
        if not wanted:
            sys.exit("--pids was set but contained no integers.")
        print(f"Targeted backfill for pids: {sorted(wanted)}")
        all_targets = collect_target_cards(session, api_key)
        targets = [t for t in all_targets if t[1] in wanted]
        missing = wanted - {t[1] for t in targets}
        if missing:
            print(f"  WARN: {len(missing)} pid(s) not found in TCGPriceLookup graded set: {sorted(missing)}")
        if not targets:
            print("None of the requested pids have graded data on TCGPriceLookup. Exiting.")
            return
    else:
        # Phase 1: discover which cards have graded data (saves us from blindly
        # hitting /history on every Lorcana card).
        targets = collect_target_cards(session, api_key)
        if not targets:
            print("No graded targets found. Nothing to backfill.")
            return

    # Phase 2: pull /history per card and accumulate rows.
    all_rows: list[dict] = []
    for i, (uuid, tcg_id, name) in enumerate(targets, 1):
        time.sleep(REQUEST_DELAY_SEC)
        try:
            history = call(session, api_key, f"{API_BASE}/cards/{uuid}/history",
                           {"period": HISTORY_PERIOD})
        except Exception as e:
            print(f"  [{i}/{len(targets)}] {name} (tcg={tcg_id}): history failed — {e}")
            continue
        rows = extract_history_rows(history, tcg_id)
        all_rows.extend(rows)
        if i % 25 == 0 or i == len(targets):
            print(f"  [{i}/{len(targets)}] {name} (tcg={tcg_id}): +{len(rows)} snapshots · running total {len(all_rows)}")

    if not all_rows:
        print("History returned no rows. Done.")
        return

    # Phase 3: upsert.
    BATCH = 500
    upserted = 0
    for batch in chunked(all_rows, BATCH):
        sb.upsert("graded_prices_daily", batch,
                  on_conflict="tcgplayer_product_id,grader,grade,date")
        upserted += len(batch)
        print(f"  upserted {upserted}/{len(all_rows)} rows")

    # Refresh the matview so today's view picks up the newest snapshots.
    try:
        sb.rpc("refresh_graded_prices_latest")
        print("graded_prices_latest refreshed")
    except Exception as e:
        print(f"WARN: matview refresh failed: {e}")


if __name__ == "__main__":
    main()
