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
    public.graded_prices_daily (tcgplayer_product_id, printing, grader, grade,
                                date, ebay_avg_1d, ebay_avg_7d, ebay_avg_30d)

    `printing` is taken from each TCGPriceLookup record's `variant` field
    ("Normal" / "Cold Foil" / "Holofoil"). Split-printing cards (LCP C1,
    most of TFC's rare foils) appear as TWO records sharing one
    tcgplayer_id, so capturing variant is what keeps foil and non-foil
    graded prices separate.

What it does NOT store:
    - Raw TCGPlayer prices (that's etl_tcgcsv_daily.py's job)
    - Card metadata (that's load_lorcast.py's job)
    - Any card without a tcgplayer_product_id (no anchor to our catalog)
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import date, datetime, timezone
from typing import Iterable

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), "graded_overrides.json")

API_BASE = "https://api.tcgpricelookup.com/v1"
GAME_SLUG = "lorcana"
PAGE_SIZE = 100
# Conservative inter-request sleep so we don't trip Cloudflare's per-second
# burst limit (independent of the 10k/day quota).
REQUEST_DELAY_SEC = 1.0
RETRY_ON_RATE = 8     # one minute of patience before we give up
RETRY_SLEEP = 8


def fetch_page(session: requests.Session, key: str, offset: int) -> dict:
    """Hit /v1/cards/search with retries for transient 429s, network errors,
    and read timeouts. TCGPriceLookup occasionally hangs past the 30s default
    (run #80 failed at offset=N with a ReadTimeout on what was otherwise a
    healthy endpoint), so we use a longer per-attempt timeout AND catch the
    RequestException family so a single slow response is a sleep+retry, not
    a workflow failure."""
    url = f"{API_BASE}/cards/search"
    params = {"game": GAME_SLUG, "limit": PAGE_SIZE, "offset": offset}
    headers = {"X-API-Key": key, "User-Agent": "packs.ink-etl/1.0"}
    last_err: Exception | None = None
    for attempt in range(RETRY_ON_RATE):
        try:
            r = session.get(url, params=params, headers=headers, timeout=60)
        except requests.exceptions.RequestException as e:
            last_err = e
            print(f"  network error at offset={offset} (attempt {attempt+1}/{RETRY_ON_RATE}): {e}; sleeping {RETRY_SLEEP}s")
            time.sleep(RETRY_SLEEP)
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429 or (r.status_code == 200 and r.text.startswith('{"error": "Rate limit')):
            print(f"  rate limited at offset={offset} (attempt {attempt+1}/{RETRY_ON_RATE}); sleeping {RETRY_SLEEP}s")
            time.sleep(RETRY_SLEEP)
            continue
        # 5xx — treat like a transient and retry rather than blowing up.
        if 500 <= r.status_code < 600:
            last_err = RuntimeError(f"server {r.status_code}: {r.text[:200]}")
            print(f"  server error {r.status_code} at offset={offset} (attempt {attempt+1}/{RETRY_ON_RATE}); sleeping {RETRY_SLEEP}s")
            time.sleep(RETRY_SLEEP)
            continue
        r.raise_for_status()
    raise RuntimeError(f"persistent failure at offset={offset}: {last_err}")


def extract_rows(card: dict, today: str) -> list[dict]:
    """Pull graded prices out of one card record. Skips cards without a
    tcgplayer_product_id or without any graded data.

    Each row carries `printing` from the record's `variant` field. For
    split-printing cards (same tcgplayer_id, different variants — TFC
    Cold Foils, C1 Holofoils, etc.) the catalog returns multiple records;
    each one becomes its own row keyed by (pid, printing, grader, grade)."""
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
    # Default to "Normal" when variant is missing — matches the migration
    # backfill and our prices_daily convention.
    printing = (card.get("variant") or "Normal").strip() or "Normal"
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
                "printing": printing,
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


def load_overrides(today: str) -> tuple[list[dict], list[dict]]:
    """Load scripts/graded_overrides.json and return (insert_rows, delete_rows).
    insert_rows go through the normal upsert path (they win on PK collision
    because they're applied AFTER TCGPriceLookup rows in the same batch).
    delete_rows specify a key that should be removed from today's snapshot.
    Returns ([], []) when the file is missing or empty."""
    if not os.path.exists(OVERRIDES_PATH):
        return [], []
    try:
        with open(OVERRIDES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"WARN: failed to read {OVERRIDES_PATH}: {e}")
        return [], []
    inserts = []
    for r in (data.get("overrides") or []):
        row = {k: v for k, v in r.items() if k != "notes"}
        if row.get("date") == "today":
            row["date"] = today
        row.setdefault("source", "manual_override")
        # Require the PK fields; skip silently if malformed.
        if not all(k in row for k in ("tcgplayer_product_id", "printing", "grader", "grade", "date")):
            continue
        inserts.append(row)
    deletes = []
    for r in (data.get("delete") or []):
        deletes.append({k: v for k, v in r.items() if k != "notes"})
    return inserts, deletes


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    api_key = os.environ.get("TCGPRICELOOKUP_API_KEY")
    if not api_key:
        print("ERROR: TCGPRICELOOKUP_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)
    sb = Supabase()
    session = requests.Session()
    # UTC, to match the TCGCSV raw ETL's snapshot date. date.today() is LOCAL,
    # so a near-midnight local run would stamp graded prices a day off from the
    # raw prices they're displayed alongside.
    today = datetime.now(timezone.utc).date().isoformat()

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

    # Load manual overrides; applied AFTER the main upsert so they win on
    # PK collision (same-date upserts replace). They go in a SEPARATE upsert
    # call because override rows carry extra columns (ebay_low_price /
    # ebay_high_price) that the regular rows don't — PostgREST rejects
    # batches with heterogeneous key sets (PGRST102 "All object keys must
    # match"). Deletes run last to clear rows we explicitly don't want.
    override_inserts, override_deletes = load_overrides(today)

    if not all_rows and not override_inserts:
        print("No graded rows to upsert. Done.")
        return

    # Upsert regular TCGPriceLookup rows in batches. Conflict target = PK
    # (tcgplayer_product_id, printing, grader, grade, date), so re-runs
    # same-day are idempotent.
    BATCH = 500
    upserted = 0
    for batch in chunked(all_rows, BATCH):
        res = sb.upsert(
            "graded_prices_daily", batch,
            on_conflict="tcgplayer_product_id,printing,grader,grade,date",
        )
        upserted += len(batch)
        print(f"  upserted {upserted}/{len(all_rows)} rows")
    print(f"Upsert complete · {upserted} rows total")

    # Separate pass for override rows — same conflict target, but isolated
    # so the key signature stays homogeneous within each PostgREST batch.
    if override_inserts:
        print(f"Applying {len(override_inserts)} manual override rows from graded_overrides.json")
        for batch in chunked(override_inserts, BATCH):
            sb.upsert(
                "graded_prices_daily", batch,
                on_conflict="tcgplayer_product_id,printing,grader,grade,date",
            )
        print(f"  override upsert complete · {len(override_inserts)} rows")

    # Apply deletes — for each (pid, printing, grader, grade) entry, drop
    # today's row so the override insert isn't shadowed by a TCGPriceLookup
    # row we'd rather suppress. Skips historical rows (date != today) so we
    # don't blow away history.
    if override_deletes:
        print(f"Applying {len(override_deletes)} manual delete entries from graded_overrides.json")
        for d in override_deletes:
            try:
                res = sb.delete("graded_prices_daily", filters={
                    "tcgplayer_product_id": "eq." + str(d["tcgplayer_product_id"]),
                    "printing": "eq." + d["printing"],
                    "grader":   "eq." + d["grader"],
                    "grade":    "eq." + d["grade"],
                    "date":     "eq." + today,
                })
                n = len(res) if isinstance(res, list) else 0
                if n:
                    print(f"  deleted {n} rows for pid={d['tcgplayer_product_id']} {d['printing']} {d['grader']} {d['grade']} (today)")
            except Exception as e:
                print(f"  WARN: delete failed for {d}: {e}")

    # Refresh the latest matview so site queries pick up today's data.
    try:
        sb.rpc("refresh_graded_prices_latest")
        print("graded_prices_latest refreshed")
    except Exception as e:
        print(f"WARN: matview refresh failed (run migration 32_graded_prices.sql?): {e}")


if __name__ == "__main__":
    main()
