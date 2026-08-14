"""Synthetic content monitor for Packs.Ink.

Catches the failure mode that plain uptime monitoring (UptimeRobot) misses:
the site returns HTTP 200 but is serving STALE or EMPTY price data. That
happens when a matview lags (ETL wrote prices_daily but the refresh_* never
ran), when the daily ETL silently broke, or when a bad deploy ships a shell
that hydrates but never loads data.

UptimeRobot only sees "packs.ink answered 200" — it can't see that the
catalog the client renders is yesterday's (or older). The same blind spot
applies to the matviews: a `price_movers` that refreshed to 0 rows still
serves 200s. This monitor closes both gaps with two independent server-side
checks (no headless browser needed — the price DATA is client-rendered, so
the HTML never contains prices; matview freshness is the data-staleness
signal and the HTML check only proves the app shell deployed):

  CHECK A — data freshness (Supabase REST, anon key):
    * card_prices_latest.max(price_date) must be within the grace window
      (UTC). This is the same signal the in-app stale-data footer pill uses.
    * price_movers must have a plausible row count (>= MIN_MOVERS_ROWS). A
      refresh that emptied the matview, or a never-refreshed view, fails here.

  CHECK B — deploy health (HTTP GET https://packs.ink/):
    * status 200 AND the returned HTML contains the stable app-shell markers
      (title, styles.css link, #root mount node). Proves the real shell
      loaded, not a 200 error page / SPA fallback.

Exit 0 only when ALL checks pass; non-zero otherwise so a failed GitHub
Actions run emails on failure — matching the ETL alerting model (real
failures surface as workflow failures; healthy runs are silent).

Reads SUPABASE_URL + SUPABASE_ANON_KEY from env. The anon key is the right
credential here — these are read-only reads of grant-public matviews, the
same data the browser fetches; no service_role needed.

Usage:
    python scripts/synthetic_monitor.py

Requires env vars SUPABASE_URL and SUPABASE_ANON_KEY.
"""
from __future__ import annotations

import datetime as dt
import os
import sys

import requests

# --- Tunable thresholds (module-level constants) ---------------------------

# Staleness is measured from 21:00 UTC of the newest price_date — the hour the
# TCGCSV snapshot actually lands and the cron loads it — plus this grace window,
# mirroring the in-app footer pill (Index.html Footer). Anchoring to midnight
# instead (the 2026-06-27 version) made every healthy afternoon read as 36-44h
# old, so the 12:00-20:00 UTC runs false-alarmed daily. With the 21:00 anchor a
# healthy site peaks at ~23.5h right before the next snapshot; a fully missed
# ETL cycle crosses 30h a few hours after the last retry cron and alerts.
STALE_GRACE_HOURS = 30

# Minimum plausible row count for the price_movers matview. Since migration 120
# it IS ~one row per (card, printing) with a price: the old ">= $5 in some
# window" gate is gone, because it was silently hiding 89% of the catalog from
# the Screener (every Common, among others). Population went 622 -> ~5,800 and
# now tracks the catalog, so the floor moves with it.
#
# 3000 is roughly half the expected count: high enough to catch a refresh that
# truncated or half-populated, low enough that it can't false-alarm on ordinary
# catalog churn. The old 300 would have sat below even the pre-120 population
# and would no longer notice anything short of a total wipe.
MIN_MOVERS_ROWS = 3000

# Production URL for the deploy-health check.
SITE_URL = "https://packs.ink/"

# Stable app-shell markers that must appear in the deployed HTML. Picked to be
# resilient across deploys (they live in <head>/body and don't change with
# content): the page title, the stylesheet link (version query stripped via
# substring match), and the React mount node. If the shell loaded, all three
# are present; a 200 error page / SPA fallback / blank deploy won't have them.
SHELL_MARKERS = (
    # Substring (not the full closing tag) so an SEO title suffix like
    # "Packs.Ink — The Ultimate Disney Lorcana Tool" still matches, while
    # per-view titles ("Artist Alley — …") won't false-match the home shell.
    "<title>Packs.Ink",
    "styles.css",
    '<div id="root">',
)

# Per-request network timeout (seconds). The project requires a timeout on
# every outbound request.
REQUEST_TIMEOUT = 30


# --- Supabase REST helpers (anon-key reads) --------------------------------


def _sb_headers(key: str) -> dict[str, str]:
    return {
        "apikey": key,
        "Authorization": "Bearer " + key,
        "Accept": "application/json",
    }


def _sb_get(path: str, *, extra_headers: dict[str, str] | None = None) -> requests.Response:
    """GET against the PostgREST endpoint with the anon key. Returns the raw
    Response so callers can read JSON or the Content-Range header."""
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_ANON_KEY"]
    headers = _sb_headers(key)
    if extra_headers:
        headers.update(extra_headers)
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r


# --- Check A: data freshness -----------------------------------------------


def check_freshness() -> list[str]:
    """Returns a list of failure messages (empty == pass)."""
    failures: list[str] = []

    # A1: newest price_date in card_prices_latest fresh (21:00 UTC anchor + grace).
    try:
        rows = _sb_get(
            "card_prices_latest?select=price_date&order=price_date.desc&limit=1"
        ).json()
        latest = rows[0]["price_date"] if rows else None
        if not latest:
            failures.append("card_prices_latest returned no rows (empty catalog matview).")
        else:
            latest_date = dt.date.fromisoformat(latest)
            now = dt.datetime.now(dt.timezone.utc)
            today = now.date()
            snapshot_landed = dt.datetime.combine(
                latest_date, dt.time(21, 0), tzinfo=dt.timezone.utc
            )
            age_hours = (now - snapshot_landed).total_seconds() / 3600
            if age_hours > STALE_GRACE_HOURS:
                failures.append(
                    f"card_prices_latest is stale: newest price_date {latest} "
                    f"landed ~{age_hours:.1f}h ago (UTC now {today}); "
                    f"threshold is {STALE_GRACE_HOURS}h past its 21:00 UTC snapshot."
                )
            else:
                print(
                    f"  [A1 PASS] card_prices_latest newest price_date {latest} "
                    f"(~{age_hours:.1f}h past its 21:00 UTC snapshot, "
                    f"<= {STALE_GRACE_HOURS}h)."
                )
    except Exception as e:
        failures.append(f"card_prices_latest freshness query failed: {e}")

    # A2: price_movers has a plausible row count. Use a HEAD-style exact count
    # via Prefer: count=exact + Range 0-0 — PostgREST returns the total in the
    # Content-Range header (".../N") without streaming all rows.
    try:
        r = _sb_get(
            "price_movers?select=card_id",
            extra_headers={
                "Prefer": "count=exact",
                "Range-Unit": "items",
                "Range": "0-0",
            },
        )
        content_range = r.headers.get("Content-Range", "")
        # Format is "start-end/total" or "*/total"; total is after the slash.
        total_str = content_range.split("/")[-1] if "/" in content_range else ""
        if not total_str or not total_str.isdigit():
            failures.append(
                f"price_movers count unparseable from Content-Range header: "
                f"{content_range!r}"
            )
        else:
            total = int(total_str)
            if total < MIN_MOVERS_ROWS:
                failures.append(
                    f"price_movers row count too low: {total} rows "
                    f"(< {MIN_MOVERS_ROWS}); matview is empty or broken."
                )
            else:
                print(
                    f"  [A2 PASS] price_movers has {total} rows "
                    f"(>= {MIN_MOVERS_ROWS})."
                )
    except Exception as e:
        failures.append(f"price_movers count query failed: {e}")

    return failures


# --- Check B: deploy health ------------------------------------------------


def check_deploy() -> list[str]:
    """Returns a list of failure messages (empty == pass)."""
    failures: list[str] = []
    try:
        r = requests.get(
            SITE_URL,
            timeout=REQUEST_TIMEOUT,
            headers={"User-Agent": "PacksInk-SyntheticMonitor/1.0"},
        )
    except requests.RequestException as e:
        # A network error reaching the site is itself a failure — report it,
        # don't let it crash the run.
        return [f"GET {SITE_URL} failed (network error): {e}"]

    if r.status_code != 200:
        failures.append(f"GET {SITE_URL} returned HTTP {r.status_code} (expected 200).")
        # No point sniffing markers on a non-200 body.
        return failures

    html = r.text
    missing = [m for m in SHELL_MARKERS if m not in html]
    if missing:
        failures.append(
            f"GET {SITE_URL} returned 200 but the HTML is missing app-shell "
            f"markers {missing!r} — likely an error page or bad deploy, not the "
            f"real shell."
        )
    else:
        print(
            f"  [B PASS] {SITE_URL} returned 200 with all "
            f"{len(SHELL_MARKERS)} app-shell markers present."
        )
    return failures


# --- Entry point -----------------------------------------------------------


def main() -> None:
    if not os.environ.get("SUPABASE_URL") or not os.environ.get("SUPABASE_ANON_KEY"):
        sys.exit("SUPABASE_URL and SUPABASE_ANON_KEY env vars required.")

    print("=== Packs.Ink synthetic content monitor ===")

    print("\nCHECK A — data freshness (Supabase matviews):")
    a_failures = check_freshness()

    print("\nCHECK B — deploy health (https://packs.ink/):")
    b_failures = check_deploy()

    print("\n--- Summary ---")
    print(f"CHECK A (data freshness): {'PASS' if not a_failures else 'FAIL'}")
    for f in a_failures:
        print(f"    - {f}")
    print(f"CHECK B (deploy health):  {'PASS' if not b_failures else 'FAIL'}")
    for f in b_failures:
        print(f"    - {f}")

    all_failures = a_failures + b_failures
    if all_failures:
        sys.exit(
            f"\nSynthetic monitor FAILED with {len(all_failures)} issue(s) — "
            "see above."
        )
    print("\nAll synthetic checks passed.")


if __name__ == "__main__":
    main()
