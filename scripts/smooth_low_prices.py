"""
smooth_low_prices.py — detects phantom spikes in `prices_daily.low_price`
and writes a smoothed value into `prices_daily.low_price_smoothed` for use
by the collection-value chart only.

Why this exists: TCGCSV's low_price is the lowest *active listing*, not the
lowest sale. A single mispriced listing pins Low at a fake number for days
even when NM Market never moves. That fake number drags the user's
collection chart up and back down by thousands. Example: Black Cauldron
Cold Foil 2026-05-14 -> 2026-05-26 saw Low go ~$14 -> $2,140 -> $99 -> $15
while Market never left the $13.62-$14.15 band.

Algorithm (per (tcgplayer_product_id, printing) series):

  For each historical day D in [today-60, today-8]:
    pre  = median of low_price in [D-30, D-1]   (require >= 15 days)
    post = median of low_price in [D+8, D+45]   (require >= 10 days)
    Both medians use raw low_price (NOT coalesce'd) so the algorithm
    converges on a stable answer rather than running away iteratively.

    snap_back = (0.7 <= post/pre <= 1.3)
    anomalous = (Low(D) > 2.5 * pre) OR (Low(D) < 0.4 * pre)

    If snap_back AND anomalous:
      low_price_smoothed[D] = (pre + post) / 2
    Else:
      low_price_smoothed[D] = NULL   (raw low_price passes through)

Median (not mean) is used throughout because medians are robust: even when
6 of 20 days in a window are spikes, the median still picks a normal-day
value. Trimmed mean works too but median is one knob fewer.

Settling lag: a spike like 2026-05-14 won't be smoothed until ~3 weeks
later when the post-window contains enough non-spike days to clear the
post/pre snap-back check. This is intentional — we can't tell at the time
whether a spike is real or phantom; only the snap-back proves it. The
client always renders today's row from raw low_price for the same reason.

Idempotent: re-runs overwrite the trailing 60 days. Days outside that
window stay frozen. Days the algorithm doesn't flag are reset to NULL
(handles cases where a previously-smoothed day no longer qualifies — e.g.
the post-window's median shifted as a real move materialized).

Usage:
    python smooth_low_prices.py [--days N] [--dry-run] [--pid PID] [--verbose]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from statistics import median

from dotenv import load_dotenv

from supabase_client import Supabase


# --- Algorithm parameters ----------------------------------------------------

# How many trailing days to recompute on each run. Older days are stable
# (their pre/post windows don't change), so we don't need to re-touch them.
DEFAULT_DAYS = 60

# Skip the most recent N days entirely — we don't have enough post-data yet,
# and the user explicitly wants today/recent days to show raw values so the
# chart is honest in the moment.
RECENT_SKIP = 7

# Per-day anomaly check: rolling pre-baseline window and minimum samples.
PRE_DAYS_BACK = 30
PRE_MIN_SAMPLES = 15

# Stretch detection: consecutive anomalous days collapse into one stretch.
# We tolerate small gaps inside a stretch (a brief return to baseline
# mid-phantom is part of the phantom — Black Cauldron's May 16 = $13 between
# May 15 = $119 and May 18 = $61 is a textbook example).
GAP_TOLERANCE_DAYS = 3

# Outer (per-stretch) baseline windows — used for the snap-back check and
# for the substituted value. Post window starts after a settling delay so
# any tail of the phantom doesn't pollute the post-median.
POST_DAYS_OFFSET = 8       # post window starts at stretch_end + 8
POST_DAYS_FORWARD = 21     # post window ends at stretch_end + 21
POST_MIN_SAMPLES = 10

# Duration cap. Phantom-vs-trend is the load-bearing distinction; this is
# the dividing line. ≤ 14 days = treat as phantom; > 14 days = treat as
# real (meta hype etc) and leave raw even if post snaps back later.
MAX_PHANTOM_DURATION_DAYS = 14

# Snap-back check — post must be within this band of pre (ratio).
SNAP_LOW = 0.7
SNAP_HIGH = 1.3

# Anomaly check — Low(D) must deviate this much from rolling pre.
UP_SPIKE = 2.5
DOWN_SPIKE = 0.4


# --- Data fetch / shape ------------------------------------------------------

def fetch_prices_window(sb: Supabase, since: date, pid: int | None = None) -> list[dict]:
    """Pull every prices_daily row at date >= since for source=tcgcsv,
    grade=raw. Paginated via the client's Range header. No upper bound is
    needed — today's date is the natural cap and we never query the future.

    When `pid` is set, the filter is pushed into the SQL query so debug runs
    (--pid X) don't pay the full-catalog scan cost.
    """
    filters = {
        "source": "eq.tcgcsv",
        "grade": "eq.raw",
        "date": f"gte.{since.isoformat()}",
    }
    if pid is not None:
        filters["tcgplayer_product_id"] = f"eq.{pid}"
    return sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,date,low_price,low_price_smoothed",
        filters=filters,
        page_size=1000,
        order="tcgplayer_product_id.asc,printing.asc,date.asc",
    )


def group_by_series(rows: list[dict]) -> dict[tuple, list[dict]]:
    """Bucket rows by (product, printing) and sort each bucket by date asc."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r["tcgplayer_product_id"], r["printing"])
        groups[key].append(r)
    for series in groups.values():
        series.sort(key=lambda r: r["date"])
    return groups


# --- Smoothing core ----------------------------------------------------------

def to_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _window_vals(
    by_date: dict[str, float | None],
    start_iso: str,
    end_iso: str,
) -> list[float]:
    return [
        v for k, v in by_date.items()
        if start_iso <= k <= end_iso and v is not None
    ]


def compute_smoothed_for_series(
    series: list[dict],
    eval_start: date,
    eval_end: date,
) -> dict[str, float | None]:
    """For every date in [eval_start, eval_end] that exists in `series`,
    return the smoothed value if the day belongs to a confirmed phantom
    stretch, else None (None lets raw low_price pass through downstream).

    Two-phase algorithm:
      Phase 1: per-day rolling pre-baseline median; mark anomalous days.
      Phase 2: group consecutive anomalous days into stretches (tolerating
               brief mid-phantom dips, e.g. Black Cauldron's May 16 = $13
               between May 15 = $119 and May 18 = $61); for each stretch
               apply the duration cap + snap-back check; smooth EVERY day
               in qualifying stretches (including the intermediate "normal"
               gap days, which are part of the phantom episode).

    Why stretch-based and not per-day: a per-day check can't distinguish
    "phantom that lasted 13 days" from "real move that lasted 13 days that
    is now over" — both have pre ≈ post ≈ old baseline if pre/post windows
    reach beyond the deviation. The duration cap is the only thing that
    separates phantom from meta-hype, and it has to be measured against
    the full stretch, not a single day.

    `series` is rows for one (product, printing), sorted by date ascending.
    Dates are ISO strings ("YYYY-MM-DD").
    """
    by_date: dict[str, float | None] = {r["date"]: to_float(r["low_price"]) for r in series}
    if not by_date:
        return {}

    sorted_dates = sorted(by_date.keys())
    eval_start_iso = eval_start.isoformat()
    eval_end_iso = eval_end.isoformat()

    # Initialize the eval-window output to None (raw passes through). We'll
    # overwrite with smoothed values for any day that lands in a qualifying
    # stretch. Days outside the eval window are NOT emitted — they were
    # frozen by a prior run and shouldn't be re-touched.
    out: dict[str, float | None] = {
        d: None for d in sorted_dates
        if eval_start_iso <= d <= eval_end_iso and by_date[d] is not None
    }

    # --- Phase 1: mark anomalous days -------------------------------------
    anomalous: list[str] = []
    for d_iso in sorted_dates:
        low = by_date[d_iso]
        if low is None:
            continue
        d_obj = date.fromisoformat(d_iso)
        pre_start = (d_obj - timedelta(days=PRE_DAYS_BACK)).isoformat()
        pre_end = (d_obj - timedelta(days=1)).isoformat()
        pre_vals = _window_vals(by_date, pre_start, pre_end)
        if len(pre_vals) < PRE_MIN_SAMPLES:
            continue
        pre = median(pre_vals)
        if pre <= 0:
            continue
        ratio = low / pre
        if ratio >= UP_SPIKE or ratio <= DOWN_SPIKE:
            anomalous.append(d_iso)

    if not anomalous:
        return out

    # --- Phase 2: group into stretches (gap-tolerant) ---------------------
    stretches: list[tuple[str, str]] = []
    cur_start = anomalous[0]
    cur_end = anomalous[0]
    for d_iso in anomalous[1:]:
        gap_days = (date.fromisoformat(d_iso) - date.fromisoformat(cur_end)).days
        if gap_days <= GAP_TOLERANCE_DAYS:
            cur_end = d_iso
        else:
            stretches.append((cur_start, cur_end))
            cur_start = d_iso
            cur_end = d_iso
    stretches.append((cur_start, cur_end))

    # --- Phase 3: evaluate each stretch -----------------------------------
    for (s_iso, e_iso) in stretches:
        s_obj = date.fromisoformat(s_iso)
        e_obj = date.fromisoformat(e_iso)
        duration = (e_obj - s_obj).days + 1
        if duration > MAX_PHANTOM_DURATION_DAYS:
            continue  # too long → treat as a real move, leave raw

        pre_start = (s_obj - timedelta(days=PRE_DAYS_BACK)).isoformat()
        pre_end = (s_obj - timedelta(days=1)).isoformat()
        post_start = (e_obj + timedelta(days=POST_DAYS_OFFSET)).isoformat()
        post_end = (e_obj + timedelta(days=POST_DAYS_FORWARD)).isoformat()

        pre_vals = _window_vals(by_date, pre_start, pre_end)
        post_vals = _window_vals(by_date, post_start, post_end)
        if len(pre_vals) < PRE_MIN_SAMPLES or len(post_vals) < POST_MIN_SAMPLES:
            continue  # not enough surrounding data yet — try again next run

        pre = median(pre_vals)
        post = median(post_vals)
        if pre <= 0:
            continue
        ratio = post / pre
        if not (SNAP_LOW <= ratio <= SNAP_HIGH):
            continue  # post didn't snap back → real move, leave raw

        smoothed_val = round((pre + post) / 2, 4)
        d_obj = s_obj
        while d_obj <= e_obj:
            d_iso = d_obj.isoformat()
            if eval_start_iso <= d_iso <= eval_end_iso and d_iso in out:
                out[d_iso] = smoothed_val
            d_obj += timedelta(days=1)

    return out


# --- Main --------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"How many trailing days to recompute (default {DEFAULT_DAYS}).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would change without writing.")
    ap.add_argument("--pid", type=int, default=None,
                    help="Restrict to a single tcgplayer_product_id (debug).")
    ap.add_argument("--verbose", action="store_true",
                    help="Log every series's flagged days.")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()

    today = datetime.now(timezone.utc).date()
    # Eval window: smooth days [today - days, today - RECENT_SKIP).
    # Fetch window needs lookahead AND lookbehind context around the eval
    # window — pre needs [eval_start - PRE_DAYS_BACK, ...], post needs
    # [..., eval_end + POST_DAYS_FORWARD].
    eval_end = today - timedelta(days=RECENT_SKIP)
    eval_start = today - timedelta(days=args.days)
    fetch_since = eval_start - timedelta(days=PRE_DAYS_BACK)

    print(
        f"Eval window: {eval_start} -> {eval_end} "
        f"(today={today}, fetch from {fetch_since})"
    )

    t0 = time.time()
    rows = fetch_prices_window(sb, fetch_since, pid=args.pid)
    print(f"Fetched {len(rows):,} rows in {time.time()-t0:.1f}s")

    groups = group_by_series(rows)
    print(f"{len(groups):,} (product, printing) series in scope")

    # Compute smoothed values.
    # We emit a row for EVERY (pid, printing, date) in the eval window, even
    # ones that resolve to NULL — that way idempotent re-runs reset days
    # that previously qualified but no longer do.
    patches: list[dict] = []  # list of {pid, printing, date, value-or-None}
    flagged_total = 0
    for (pid, printing), series in groups.items():
        per_day = compute_smoothed_for_series(series, eval_start, eval_end)
        if not per_day:
            continue
        # Only emit a patch if the desired value differs from what's already
        # stored — keeps the write footprint small.
        existing = {r["date"]: to_float(r.get("low_price_smoothed")) for r in series}
        for d_iso, new_val in per_day.items():
            cur = existing.get(d_iso)
            same = (cur is None and new_val is None) or (
                cur is not None and new_val is not None and abs(cur - new_val) < 1e-4
            )
            if same:
                continue
            patches.append({
                "tcgplayer_product_id": pid,
                "printing": printing,
                "date": d_iso,
                "value": new_val,
            })
            if new_val is not None:
                flagged_total += 1
                if args.verbose:
                    raw = next((r["low_price"] for r in series if r["date"] == d_iso), None)
                    print(f"  pid={pid} {printing} {d_iso}: raw={raw} -> smoothed={new_val}")

    print(
        f"{len(patches):,} patches needed "
        f"({flagged_total:,} new/changed smoothings, "
        f"{len(patches)-flagged_total:,} clears to NULL)"
    )

    # A runaway patch count usually means a parameter retune flagged half the
    # catalog as phantom — loud-log it so the regression is visible in the run.
    if len(patches) > 2000:
        print(
            f"  WARNING: {len(patches):,} patches is unusually high (>2000). "
            "A normal day is in the low hundreds — check whether an algorithm "
            "tunable was changed."
        )

    if args.dry_run:
        print("--dry-run: not writing.")
        return 0

    if not patches:
        print("No changes.")
        return 0

    # Batch the PATCHes. `prices_daily`'s PK is composite (pid, printing, date,
    # source, grade), so we can't `in.()` on a single column across the whole
    # set. But within one (printing, date, value) bucket every row shares
    # printing + date + the target low_price_smoothed value, so we can collapse
    # them into ONE PATCH that targets `tcgplayer_product_id=in.(...)` +
    # `printing=eq` + `date=eq` (+ the fixed source/grade). Single-pid buckets
    # are still one call — no worse than the old serial path.
    buckets: dict[tuple, list] = defaultdict(list)
    for p in patches:
        # NULL clears can't share a bucket key with a real value; use a
        # sentinel so the clear-to-NULL group is its own bucket.
        val_key = "__null__" if p["value"] is None else p["value"]
        buckets[(p["printing"], p["date"], val_key)].append(p["tcgplayer_product_id"])

    # Cap the in.() list per call so a large bucket (e.g. the clear-to-NULL
    # group on a day many cards qualify+clear) can't blow the PostgREST URL
    # length limit. 200 pids/call keeps the query string comfortably short.
    IN_CHUNK = 200

    t1 = time.time()
    written = 0
    calls = 0
    last_print = t1
    for (printing, d_iso, val_key), pids in buckets.items():
        value = None if val_key == "__null__" else val_key
        # Dedup pids defensively (a (printing,date) can only appear once per
        # pid in `patches`, but be safe).
        uniq_pids = sorted(set(pids))
        for chunk_start in range(0, len(uniq_pids), IN_CHUNK):
            chunk = uniq_pids[chunk_start:chunk_start + IN_CHUNK]
            in_filter = "in.(" + ",".join(str(x) for x in chunk) + ")"
            sb.update(
                "prices_daily",
                match={
                    "printing": printing,
                    "date": d_iso,
                    "source": "tcgcsv",
                    "grade": "raw",
                },
                params={"tcgplayer_product_id": in_filter},
                patch={"low_price_smoothed": value},
            )
            written += len(chunk)
            calls += 1
            if time.time() - last_print > 5:
                print(f"  wrote {written}/{len(patches)} ({calls} batched calls)")
                last_print = time.time()
    print(
        f"Wrote {written:,} patches in {calls:,} batched calls "
        f"in {time.time()-t1:.1f}s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
