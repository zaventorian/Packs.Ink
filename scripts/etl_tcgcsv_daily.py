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
    group_name_candidates,
    transform_price_rows,
)


USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests"

# TCGCSV publishes their daily file ~20:00 UTC. A run before that sees
# yesterday's file, so the row it writes under today's date holds the
# PREVIOUS evening's snapshot.
PUBLISH_CUTOFF_UTC = (20, 15)


def _parse_ts(val: str | None) -> datetime | None:
    """Parse a PostgREST timestamptz. Returns None if absent/unparseable."""
    if not val:
        return None
    try:
        ts = datetime.fromisoformat(val.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def get_json(url: str) -> Any:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            if attempt == 2:
                break
            wait = 2 ** attempt
            print(f"  retry in {wait}s ({e})")
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def fetch_groups(category_id: int) -> list[dict]:
    """List of TCGPlayer 'groups' (sets) for a category."""
    data = get_json(f"{TCGCSV_BASE}/{category_id}/groups")
    # Explicit key-presence check: a valid empty response is {"results": []},
    # and `... or data` would wrongly fall through to the raw dict for that.
    return data.get("results") if isinstance(data, dict) and "results" in data else data


def fetch_group_prices(category_id: int, group_id: int) -> list[dict]:
    data = get_json(f"{TCGCSV_BASE}/{category_id}/{group_id}/prices")
    return data.get("results") if isinstance(data, dict) and "results" in data else data


def update_set_group_mapping(sb: Supabase, groups: list[dict]) -> None:
    """Best-effort: match TCGCSV group names to sets.name and update
    tcgplayer_group_id. Idempotent and safe to skip on no-match."""
    sets_rows = sb.select("sets", columns="id,name,tcgplayer_group_id")
    by_name = {(s["name"] or "").lower(): s for s in sets_rows}
    updates: list[dict] = []
    for g in groups:
        gname = (g.get("name") or "").strip()
        match = None
        for c in group_name_candidates(gname):
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


def _latest_snapshot_before(sb: Supabase, snapshot: date) -> str | None:
    """Return the most-recent prices_daily date strictly before `snapshot`
    (tcgcsv/raw), or None if there's no prior snapshot at all (first-ever
    load). Used as a fallback when the immediately-preceding day has no rows
    so a multi-day ETL gap still compares against the last real data instead
    of treating a stale TCGCSV file as fresh."""
    rows = sb.select(
        "prices_daily",
        columns="date",
        limit=1,
        filters={
            "source": "eq.tcgcsv",
            "grade": "eq.raw",
            "date": f"lt.{snapshot.isoformat()}",
            "order": "date.desc",
        },
    )
    return rows[0]["date"] if rows else None


def detect_duplicate_snapshot(
    sb: Supabase, snapshot: date, new_rows: list[dict], threshold: float = 0.95
) -> tuple[float, int]:
    """Compare the fetched snapshot against the prior day's prices_daily rows.
    Returns (match_ratio, matched_count). A match_ratio > threshold indicates
    TCGCSV likely served stale data (or hadn't published today's snapshot yet)
    and we'd be polluting prices_daily with a duplicate that silently zeros
    out 1D movers downstream.

    If the immediately-preceding day (snapshot - 1) has no rows (an ETL gap),
    fall back to the most-recent available snapshot strictly before today so a
    2-day gap still compares against real data. Only when there's NO prior
    snapshot at all (genuine first-ever load) do we return (0.0, 0) = write.
    """
    compare_date = (snapshot - timedelta(days=1)).isoformat()
    prior = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,low_price,market_price",
        filters={
            "source": "eq.tcgcsv",
            "grade": "eq.raw",
            "date": f"eq.{compare_date}",
        },
        order="tcgplayer_product_id.asc,printing.asc",
    )
    if not prior:
        fallback = _latest_snapshot_before(sb, snapshot)
        if fallback is None:
            return (0.0, 0)  # no prior data at all → first-ever load, write it
        compare_date = fallback
        print(f"  prior day empty; comparing against last snapshot {compare_date}")
        prior = sb.select(
            "prices_daily",
            columns="tcgplayer_product_id,printing,low_price,market_price",
            filters={
                "source": "eq.tcgcsv",
                "grade": "eq.raw",
                "date": f"eq.{compare_date}",
            },
            order="tcgplayer_product_id.asc,printing.asc",
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

    # Idempotency check: skip the fetch when this date's rows are already the
    # best data available, so the several cron retries per day don't re-fetch
    # gigabytes. Still refresh matviews — they may have failed on the run that
    # wrote prices_daily, so a later retry can recover them.
    #
    # But "rows exist" alone is NOT enough. Rows written before TCGCSV's
    # ~20:00 UTC drop hold the PREVIOUS evening's snapshot, and a bare
    # exists-check lets them lock out the post-publish run. That is exactly
    # what regressed on 2026-07-26: a TCGCSV outage left that date empty, the
    # 01:00 UTC retry then claimed each following date first, and every 20:30
    # UTC run became a no-op — so the freshest publish was discarded daily and
    # the whole series ran a day behind.
    #
    # So skip only if the stored rows were written AFTER today's publish
    # window. Earlier ones get re-fetched and overwritten once it opens. If
    # that re-fetch is byte-identical to the prior day (TCGCSV published
    # late), the duplicate-snapshot guard below returns without writing,
    # leaving inserted_at pre-cutoff so the next cron firing tries again.
    publish_cutoff = datetime(
        snapshot.year,
        snapshot.month,
        snapshot.day,
        PUBLISH_CUTOFF_UTC[0],
        PUBLISH_CUTOFF_UTC[1],
        tzinfo=timezone.utc,
    )
    if not args.force:
        try:
            existing = sb.select(
                "prices_daily",
                columns="inserted_at",
                limit=1,
                filters={
                    "date": f"eq.{snapshot.isoformat()}",
                    "source": "eq.tcgcsv",
                    "grade": "eq.raw",
                },
                order="inserted_at.desc",
            )
            if existing:
                written = _parse_ts(existing[0].get("inserted_at"))
                now = datetime.now(timezone.utc)
                # Only ever re-fetch the CURRENT UTC date. TCGCSV serves only
                # today's prices, so re-fetching an explicit --date backfill
                # would overwrite that day's history with today's numbers.
                stale_claim = (
                    snapshot == now.date()
                    and now >= publish_cutoff
                    and (written is None or written < publish_cutoff)
                )
                if stale_claim:
                    seen = f"{written:%Y-%m-%d %H:%M}" if written else "unknown time"
                    print(
                        f"Snapshot {snapshot} exists but was written {seen} UTC, "
                        f"before the {publish_cutoff:%H:%M} UTC publish window "
                        "— re-fetching to pick up today's file."
                    )
                else:
                    print(f"Today's snapshot ({snapshot}) is already loaded. Skipping fetch.")
                    _refresh_matviews(sb)
                    return
        except Exception as e:
            print(f"  (idempotency probe failed, continuing with fetch: {e})")

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
    # If >95% of fetched rows match yesterday's prices_daily exactly, exit 0
    # so cron retries don't spam failure emails — this is normal "no new
    # data yet", not a real error.
    ratio, matched = detect_duplicate_snapshot(sb, snapshot, all_rows)
    print(f"Duplicate-snapshot check: {ratio:.1%} of rows match prior day ({matched} exact matches).")
    if ratio > 0.95 and not args.force:
        print(
            f"\nSKIP: {ratio:.1%} of fetched rows are byte-identical to "
            f"{(snapshot - timedelta(days=1)).isoformat()}. TCGCSV likely "
            "hasn't published today's snapshot yet (their daily file lands "
            "~20:00 UTC). This is normal — a later cron firing will pick it up."
        )
        return

    # Stamp write time explicitly: ON CONFLICT DO UPDATE won't touch the
    # column default, so without this an overwrite keeps the original
    # inserted_at and the publish-window check above can never clear.
    written_at = datetime.now(timezone.utc).isoformat()
    for r in all_rows:
        r["inserted_at"] = written_at

    sb.upsert(
        "prices_daily",
        all_rows,
        on_conflict="tcgplayer_product_id,date,printing,source,grade",
    )

    _refresh_matviews(sb)
    print("\nDone.")


def _refresh_matviews(sb: "Supabase") -> None:
    """Refresh the price matviews. Exits non-zero if any REQUIRED refresh fails
    (matview staleness is a real failure worth alerting on, unlike the
    duplicate-snapshot skip)."""
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

    # The market indices are OPTIONAL, on purpose. Every matview above is
    # load-bearing for a price the site displays, so a stale one is a data bug
    # worth an alert. The indices are a benchmark overlay: if they go stale the
    # site still prices every card correctly, it just can't say "vs market" for
    # a day. Failing the whole ETL over that would train us to ignore its
    # alerts, and this refresh is the slowest one on the site (full history over
    # ~3M rows), so it is also the likeliest to trip a timeout.
    try:
        sb.rpc("refresh_market_index")
        print("Refreshed via refresh_market_index().")
    except Exception as e:
        print(
            "WARN: refresh_market_index failed (run supabase/128_market_index.sql "
            f"to enable): {e}"
        )

    if refresh_failures:
        sys.exit(
            f"\nFAIL: matview refresh failed for: {', '.join(refresh_failures)}. "
            "Raw prices_daily is up to date but derived views are stale."
        )


if __name__ == "__main__":
    main()
