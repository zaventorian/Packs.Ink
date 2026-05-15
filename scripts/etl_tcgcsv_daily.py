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
from datetime import date, datetime, timezone
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="Snapshot date YYYY-MM-DD (default: today UTC)")
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
