"""Hourly self-heal for the price matviews.

Compares card_prices_latest.max(price_date) to prices_daily.max(date). If the
matview is behind, calls refresh_card_prices_latest() / refresh_price_movers()
/ refresh_rarity_avg_daily() / refresh_sealed_prices_latest(). Exits non-zero
if any refresh fails so GitHub Actions surfaces it.

This is a safety net for the scenario where the main ETL successfully writes
prices_daily but its inline matview refresh fails silently (or never runs
because of an early exit). The dashboard would otherwise serve yesterday's
prices for up to 24 hours until the catalog cache TTL recycles.

Idempotent — safe to run every hour. Returns fast (no refresh) when the
matview is already up to date.

Usage:
    python scripts/matview_self_heal.py

Requires env vars SUPABASE_URL and SUPABASE_SERVICE_KEY. SUPABASE_ANON_KEY
is optional; when set it's used as a fallback if the service key gets a 403
on a matview read (i.e. a grant regression). RPCs still require the service
key — without it the refresh path can't run.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
import urllib.error
import json


def _sb_get(path: str, key: str | None = None) -> list[dict]:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = key or os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": "Bearer " + key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # 403 on a matview = role is missing GRANT SELECT. Try the anon key
        # as a fallback so the check can still run while a grant migration
        # is being applied. RPC writes (refresh_*) still require service_role,
        # so this is read-only resiliency.
        if e.code == 403 and key != os.environ.get("SUPABASE_ANON_KEY") and os.environ.get("SUPABASE_ANON_KEY"):
            print(f"  service key got 403 on {path} — retrying with anon key. "
                  "Apply supabase/45_matview_grants_service_role.sql to fix.", file=sys.stderr)
            return _sb_get(path, key=os.environ["SUPABASE_ANON_KEY"])
        raise


def _sb_rpc(fn: str) -> None:
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/rpc/" + fn
    req = urllib.request.Request(
        url,
        data=b"{}",
        headers={
            "apikey": os.environ["SUPABASE_SERVICE_KEY"],
            "Authorization": "Bearer " + os.environ["SUPABASE_SERVICE_KEY"],
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        r.read()


def latest_dates() -> tuple[str | None, str | None]:
    """Returns (matview_date, prices_daily_date) as 'YYYY-MM-DD' strings."""
    cpl = _sb_get("card_prices_latest?select=price_date&order=price_date.desc&limit=1")
    pd = _sb_get(
        "prices_daily?select=date&source=eq.tcgcsv&grade=eq.raw&order=date.desc&limit=1"
    )
    mv = cpl[0]["price_date"] if cpl else None
    pd_date = pd[0]["date"] if pd else None
    return mv, pd_date


def main() -> None:
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_SERVICE_KEY"):
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY env vars required.")

    mv_date, pd_date = latest_dates()
    print(f"card_prices_latest.max(price_date) = {mv_date}")
    print(f"prices_daily.max(date)             = {pd_date}")

    if not pd_date:
        print("No rows in prices_daily — nothing to compare against. Exiting.")
        return

    if mv_date == pd_date:
        print("Matview is up to date. No action needed.")
        return

    print(f"\nMatview lags by ≥1 day. Refreshing all derived views...")
    failures: list[str] = []
    for fn in (
        "refresh_card_prices_latest",
        "refresh_rarity_avg_daily",
        "refresh_price_movers",
        "refresh_sealed_prices_latest",
    ):
        try:
            _sb_rpc(fn)
            print(f"  Refreshed via {fn}().")
        except Exception as e:
            failures.append(fn)
            print(f"  FAILED: {fn}: {e}")

    if failures:
        sys.exit(f"\nSelf-heal could not refresh: {', '.join(failures)}")

    mv_after, _ = latest_dates()
    print(f"\nDone. card_prices_latest now at {mv_after}.")


if __name__ == "__main__":
    main()
