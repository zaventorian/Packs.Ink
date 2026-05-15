"""
etl_tcgcsv_daily.py — fetches today's TCGCSV prices for Lorcana and writes
one row per (product, printing) into prices_daily.

Idempotent on PK (tcgplayer_product_id, date, printing, source, grade): re-running
the same day overwrites that day's prices rather than duplicating.

Usage:
    python etl_tcgcsv_daily.py [--date YYYY-MM-DD]

Default date is "today" in UTC. Use --date to ingest a specific day.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests
from dotenv import load_dotenv

from supabase_client import Supabase
from tcgcsv_common import (
    LORCANA_CATEGORY_ID,
    TCGCSV_BASE,
    transform_price_rows,
)


USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests"


def get_json(url: str) -> Any:
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            wait = 2 ** attempt
            print(f"  retry in {wait}s ({e})")
            time.sleep(wait)


def fetch_groups(category_id: int) -> list[dict]:
    """List of TCGPlayer 'groups' (sets) for a category."""
    data = get_json(f"{TCGCSV_BASE}/{category_id}/groups")
    return data.get("results") or data


def fetch_group_prices(category_id: int, group_id: int) -> list[dict]:
    data = get_json(f"{TCGCSV_BASE}/{category_id}/{group_id}/prices")
    return data.get("results") or data


def update_set_group_mapping(sb: Supabase, groups: list[dict]) -> None:
    """Best-effort: match TCGCSV group names to sets.name and update
    tcgplayer_group_id. Idempotent and safe to skip on no-match."""
    sets_rows = sb.select("sets", columns="id,name,tcgplayer_group_id")
    by_name = {(s["name"] or "").lower(): s for s in sets_rows}
    updates: list[dict] = []
    for g in groups:
        gname = (g.get("name") or "").strip()
        # TCGCSV uses names like "Disney Lorcana: The First Chapter".
        # Lorcast uses just "The First Chapter".
        candidates = {gname.lower()}
        if ":" in gname:
            candidates.add(gname.split(":", 1)[1].strip().lower())
        match = None
        for c in candidates:
            if c in by_name:
                match = by_name[c]
                break
        if not match:
            continue
        if match.get("tcgplayer_group_id") == g.get("groupId"):
            continue
        updates.append({"id": match["id"], "tcgplayer_group_id": g.get("groupId")})
    if updates:
        print(f"  updating tcgplayer_group_id on {len(updates)} sets")
        failed = 0
        for u in updates:
            try:
                sb.update("sets", match={"id": u["id"]}, patch={"tcgplayer_group_id": u["tcgplayer_group_id"]})
            except Exception as e:
                failed += 1
                print(f"  set group update failed for {u['id']}: {e}")
        if failed:
            print(f"  WARNING: {failed}/{len(updates)} set group updates failed")


def detect_duplicate_snapshot(
    sb: Supabase, snapshot: date, new_rows: list[dict], threshold: float = 0.95
) -> tuple[float, int]:
    """Compare the fetched snapshot against the prior day's prices_daily rows.
    Returns (match_ratio, matched_count). A match_ratio > threshold indicates
    TCGCSV likely served stale data (or hadn't published today's snapshot yet)
    and we'd be polluting prices_daily with a duplicate that silently zeros
    out 1D movers downstream.
    """
    prior = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,low_price,market_price",
        filters={
            "source": "eq.tcgcsv",
            "grade": "eq.raw",
            "date": f"eq.{(snapshot - timedelta(days=1)).isoformat()}",
        },
    )
    prior_by_key: dict[tuple, tuple] = {}
    for r in prior:
        key = (r["tcgplayer_product_id"], r["printing"])
        prior_by_key[key] = (r.get("low_price"), r.get("market_price"))
    if not prior_by_key:
        return (0.0, 0)
    matched = 0
    compared = 0
    for r in new_rows:
        key = (r["tcgplayer_product_id"], r["printing"])
        if key not in prior_by_key:
            continue
        compared += 1
        if (r.get("low_price"), r.get("market_price")) == prior_by_key[key]:
            matched += 1
    if compared == 0:
        return (0.0, 0)
    return (matched / compared, matched)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Snapshot date YYYY-MM-DD (default: today UTC)")
    ap.add_argument(
        "--force",
        action="store_true",
        help="Skip the duplicate-snapshot guard. Use when you really want to "
             "write a snapshot that matches the prior day (rare).",
    )
    args = ap.parse_args()

    snapshot = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(timezone.utc).date()
    )

    load_dotenv()
    sb = Supabase()

    print(f"Snapshot date: {snapshot}")
    print(f"Fetching TCGPlayer groups for categoryId {LORCANA_CATEGORY_ID}...")
    groups = fetch_groups(LORCANA_CATEGORY_ID)
    print(f"  {len(groups)} groups")

    update_set_group_mapping(sb, groups)

    all_rows: list[dict] = []
    for g in groups:
        gid = g.get("groupId")
        gname = g.get("name", str(gid))
        prices = fetch_group_prices(LORCANA_CATEGORY_ID, gid)
        rows = transform_price_rows(prices, snapshot)
        print(f"  {gname}: {len(prices)} entries -> {len(rows)} price rows")
        all_rows.extend(rows)

    print(f"\nTotal price rows to upsert: {len(all_rows)}")
    if not all_rows:
        sys.exit("No price rows — aborting.")

    # Duplicate-snapshot guard. TCGCSV publishes their daily file ~20:00 UTC;
    # if the ETL runs before that, the API may serve yesterday's snapshot.
    # Writing it under today's date would silently zero out every 1D mover.
    # If >95% of fetched rows match yesterday's prices_daily exactly, abort.
    ratio, matched = detect_duplicate_snapshot(sb, snapshot, all_rows)
    print(f"Duplicate-snapshot check: {ratio:.1%} of rows match prior day ({matched} exact matches).")
    if ratio > 0.95 and not args.force:
        sys.exit(
            f"\nABORTED: {ratio:.1%} of fetched rows are byte-identical to "
            f"{(snapshot - timedelta(days=1)).isoformat()}. TCGCSV likely "
            "served a stale snapshot (their daily file lands ~20:00 UTC). "
            "Re-run after that, or pass --force to write anyway."
        )

    sb.upsert(
        "prices_daily",
        all_rows,
        on_conflict="tcgplayer_product_id,date,printing,source,grade",
    )

    # Refresh derived materialized views so the site reflects today's
    # snapshot. Failures here mean the site serves stale derived data while
    # raw prices_daily is fresh — track them and exit non-zero so cron
    # surfaces the breakage instead of silently succeeding.
    refresh_failures: list[str] = []
    for fn, hint in (
        ("refresh_card_prices_latest",   "supabase/12_card_prices_latest_matview.sql"),
        ("refresh_rarity_avg_daily",     "supabase/07_refresh_rpc.sql"),
        ("refresh_price_movers",         "supabase/10_price_movers_matview.sql"),
        ("refresh_sealed_prices_latest", "supabase/16_sealed_prices_latest.sql"),
    ):
        try:
            sb.rpc(fn)
            print(f"Refreshed via {fn}().")
        except Exception as e:
            refresh_failures.append(fn)
            print(f"Could not call {fn} (run {hint} to enable): {e}")

    if refresh_failures:
        sys.exit(
            f"\nFAIL: matview refresh failed for: {', '.join(refresh_failures)}. "
            "Raw prices_daily is up to date but derived views are stale."
        )
    print("\nDone.")


if __name__ == "__main__":
    main()
