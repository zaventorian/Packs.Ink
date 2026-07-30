"""
flag_graded_outliers.py — ingest guard for graded_sales.

A single bad sale does real damage: the portfolio chart values a slab at its most
recent sale and forward-fills until the next one, so one wrong row IS the user's
portfolio for days. A $33,493 Baymax sale put a 2-day $67k spike on a $35k
collection; an $11,775 Kuzco sale then held the number ~$11.6k high for a week.

So: after every load, compare each sale against a robust local baseline for its own
(card_id, printing bucket, grader, grade) series and quarantine the ones that can't
be reconciled. This is the graded analogue of smooth_low_prices.py for raw prices,
and it borrows that script's two principles:

  • median, never mean — when several rows in a window are bad, the median still
    lands on a normal one.
  • compare against NEIGHBOURS IN TIME, not the whole series — a card that
    genuinely ramped 10x over a year must not have its recent (correct) sales
    flagged against its year-old floor.

Grouping by printing bucket matters as much as the threshold. A Challenge Promo
(C1) card's Top Prize foil and Prize Wall non-foil share one card_id but are
different markets (Cinderella - Stouthearted PSA 10: $1,707 foil vs $280
non-foil). Pooled, every foil sale looks like a 6x outlier and every non-foil one
like a crash; bucketed, both series are well behaved.

Writes excluded=true, exclude_reason='outlier' (migration 111) so the decision is
auditable and reversible in bulk — unlike the pre-111 rows, where a bare boolean
made every exclusion indistinguishable.

    python scripts/flag_graded_outliers.py                  # dry run + report
    python scripts/flag_graded_outliers.py --commit
    python scripts/flag_graded_outliers.py --unflag          # reverse ALL outlier flags
    python scripts/flag_graded_outliers.py --self-test       # synthetic cases only
"""
from __future__ import annotations

import argparse
import collections
import os
import statistics
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent

# ── Tunables ────────────────────────────────────────────────────────────────
# Deliberately loose. Real Lorcana graded prices move fast (Baymax PSA 10 went
# $180 -> $500 in two months, a legitimate 2.8x), so the bar is set to catch
# only the unreconcilable: currency-conversion artifacts, whole-lot prices
# landing on one card, and prize-tier/rarity conflation. Every case in the
# 2026-07 investigation was >= 18x.
UP_FACTOR = 6.0            # flag when price > UP_FACTOR x local median
DOWN_FACTOR = 1 / 6.0      # flag when price < DOWN_FACTOR x local median
NEIGHBOUR_WINDOW_DAYS = 120  # how far out to look for comparison sales
MAX_NEIGHBOURS = 12         # nearest-in-time neighbours to take the median of
MIN_NEIGHBOURS = 5          # below this we have no opinion — leave the row alone

FOIL_PRINTINGS = {"foil", "cold foil", "holofoil", "holo"}
NONFOIL_PRINTINGS = {"normal", "non-foil", "nonfoil"}


def bucket_of(printing):
    """Mirror of gradedSlotBucket() in Index.html. None = unclassified, which is
    kept distinct from an explicit non-foil: it is not evidence of anything."""
    s = (printing or "").strip().lower()
    if not s or s == "unknown":
        return None
    if s in FOIL_PRINTINGS:
        return "Foil"
    if s in NONFOIL_PRINTINGS:
        return "Non-Foil"
    return s


def group_key(row):
    """Unclassified rows are pooled under their own key rather than folded into
    Non-Foil — mixing them into a real bucket is what makes a split card's two
    markets contaminate each other."""
    return (row["card_id"], bucket_of(row.get("printing")),
            (row.get("grader") or "").lower(), str(row.get("grade")))


def evaluate(series):
    """series: [{item_id, day, price}] for ONE group, sorted by day.
    Returns [(item_id, price, median, ratio)] for rows that fail the guard."""
    out = []
    n = len(series)
    if n < MIN_NEIGHBOURS + 1:
        return out
    for i, row in enumerate(series):
        # Neighbours = same group, within the window, excluding the row itself.
        near = [o for j, o in enumerate(series)
                if j != i and abs(o["day"] - row["day"]) <= NEIGHBOUR_WINDOW_DAYS]
        if len(near) < MIN_NEIGHBOURS:
            continue
        near.sort(key=lambda o: abs(o["day"] - row["day"]))
        med = statistics.median([o["price"] for o in near[:MAX_NEIGHBOURS]])
        if med <= 0:
            continue
        ratio = row["price"] / med
        if ratio > UP_FACTOR or ratio < DOWN_FACTOR:
            out.append((row["item_id"], row["price"], med, ratio))
    return out


# ── Self-test ───────────────────────────────────────────────────────────────
def self_test():
    """Cases that must hold before the thresholds are changed."""
    def mk(prices, start=0, step=7):
        return [{"item_id": f"i{i}", "day": start + i * step, "price": p}
                for i, p in enumerate(prices)]

    fails = []

    def check(name, series, expect_flagged_prices):
        got = sorted(round(p, 2) for _, p, _, _ in evaluate(series))
        want = sorted(expect_flagged_prices)
        if got != want:
            fails.append(f"  FAIL {name}: flagged {got}, expected {want}")
        else:
            print(f"  ok   {name}")

    # 1. Lone huge spike in a stable series -> flagged (the Baymax shape).
    check("lone spike", mk([180, 175, 190, 185, 200, 33493.66, 195, 185, 190]),
          [33493.66])
    # 2. Steady 2.8x ramp over months -> nothing flagged (real Baymax move).
    check("gradual ramp", mk([180, 200, 225, 250, 300, 350, 400, 450, 500]), [])
    # 3. Crash to near-zero -> flagged (mis-keyed cheap variant).
    check("lone crash", mk([600, 620, 590, 610, 605, 14.38, 600, 595, 610]),
          [14.38])
    # 4. Two markets pooled in one series -> BOTH tails flagged, which is why
    #    the caller must bucket by printing first. Documents the failure mode.
    pooled = mk([280, 290, 275, 285, 280, 1707, 1750, 1690, 1720])
    if not evaluate(pooled):
        fails.append("  FAIL pooled-markets: expected flags when buckets are mixed")
    else:
        print("  ok   pooled-markets (flags as designed -> bucket first)")
    # 5. Too few samples -> no opinion.
    check("sparse series", mk([100, 5000, 120]), [])
    # 6. A high sale that is only 3x the local median stays (under threshold).
    check("moderate 3x", mk([100, 110, 105, 95, 100, 300, 105, 110, 100]), [])

    print()
    if fails:
        print("SELF-TEST FAILED:")
        for f in fails:
            print(f)
        return False
    print("self-test: all cases pass")
    return True


# ── Supabase ────────────────────────────────────────────────────────────────
def fetch_all(sb, head):
    rows, off = [], 0
    while True:
        r = requests.get(f"{sb}/rest/v1/graded_sales", headers=head, timeout=90, params={
            "select": "item_id,card_id,grader,grade,printing,sale_price,sold_date,"
                      "excluded,exclude_reason,title",
            "offset": off, "limit": 1000, "order": "item_id"})
        r.raise_for_status()
        b = r.json()
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def patch_many(sb, head, item_ids, body, label):
    """PATCH in chunks using an in.() filter — one request per chunk, not per row."""
    CHUNK = 100
    for i in range(0, len(item_ids), CHUNK):
        ids = item_ids[i:i + CHUNK]
        quoted = ",".join('"' + s.replace('"', '""') + '"' for s in ids)
        r = requests.patch(f"{sb}/rest/v1/graded_sales", headers=head, timeout=60,
                           params={"item_id": f"in.({quoted})"}, json=body)
        r.raise_for_status()
        print(f"  {label}: {min(i + CHUNK, len(item_ids))}/{len(item_ids)}", flush=True)


def to_day(d):
    y, m, dd = (int(x) for x in str(d).split("-")[:3])
    return y * 372 + m * 31 + dd     # monotone, good enough for day-gap math


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (else dry run)")
    ap.add_argument("--unflag", action="store_true",
                    help="clear every exclude_reason='outlier' flag and exit")
    ap.add_argument("--self-test", action="store_true", help="run synthetic cases and exit")
    ap.add_argument("--samples", type=int, default=40)
    args = ap.parse_args()

    if args.self_test:
        sys.exit(0 if self_test() else 1)
    if not self_test():
        sys.exit("refusing to run against real data with a failing self-test")
    print()

    load_dotenv(HERE / ".env")
    sb = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    head = {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json", "Prefer": "return=minimal"}

    if args.unflag:
        r = requests.get(f"{sb}/rest/v1/graded_sales", headers=head, timeout=60,
                         params={"select": "item_id", "exclude_reason": "eq.outlier",
                                 "limit": 10000})
        r.raise_for_status()
        ids = [x["item_id"] for x in r.json()]
        print(f"{len(ids)} rows flagged as outliers")
        if not ids:
            return
        if not args.commit:
            print("DRY RUN — re-run with --commit --unflag to clear them.")
            return
        patch_many(sb, head, ids, {"excluded": False, "exclude_reason": None}, "unflag")
        requests.post(f"{sb}/rest/v1/rpc/refresh_graded_sales_rollup", headers=head, timeout=300)
        print("DONE.")
        return

    print("Fetching graded_sales ...")
    rows = fetch_all(sb, head)
    print(f"{len(rows)} sales\n")

    groups = collections.defaultdict(list)
    by_id = {}
    for r in rows:
        if r.get("card_id") is None or r.get("grade") is None:
            continue
        if r.get("sale_price") is None:
            continue
        # Already-excluded rows still inform the baseline?  No — a quarantined row
        # is not evidence of a market price. Skip them entirely.
        if r.get("excluded") and r.get("exclude_reason") != "outlier":
            continue
        by_id[r["item_id"]] = r
        groups[group_key(r)].append({
            "item_id": r["item_id"], "day": to_day(r["sold_date"]),
            "price": float(r["sale_price"])})

    flagged = []
    for k, series in groups.items():
        series.sort(key=lambda o: o["day"])
        flagged.extend(evaluate(series))

    already = [f for f in flagged if by_id[f[0]].get("exclude_reason") == "outlier"]
    fresh = [f for f in flagged if by_id[f[0]].get("exclude_reason") != "outlier"]
    # Rows previously flagged that no longer look like outliers (more data arrived).
    stale = [r["item_id"] for r in rows
             if r.get("exclude_reason") == "outlier"
             and r["item_id"] not in {f[0] for f in flagged}]

    print("=" * 74)
    print(f"  {len(groups):6}  groups evaluated (card_id x printing x grader x grade)")
    print(f"  {len(flagged):6}  rows fail the guard  ({UP_FACTOR}x up / {DOWN_FACTOR:.3f}x down)")
    print(f"  {len(already):6}  already flagged")
    print(f"  {len(fresh):6}  NEW rows to quarantine")
    print(f"  {len(stale):6}  previously flagged, now within range (would un-flag)")
    print("=" * 74)

    fresh.sort(key=lambda f: -abs(f[3]))
    print(f"\nworst {min(len(fresh), args.samples)} new:")
    for item_id, price, med, ratio in fresh[:args.samples]:
        r = by_id[item_id]
        print(f"  {ratio:8.1f}x  ${price:>10,.2f} vs med ${med:>9,.2f}  "
              f"[{bucket_of(r.get('printing')) or '-'}] {(r.get('title') or '')[:52]}")

    if not args.commit:
        print(f"\nDRY RUN — re-run with --commit to quarantine {len(fresh)} rows.")
        return

    if fresh:
        patch_many(sb, head, [f[0] for f in fresh],
                   {"excluded": True, "exclude_reason": "outlier"}, "flag")
    if stale:
        patch_many(sb, head, stale,
                   {"excluded": False, "exclude_reason": None}, "unflag")
    print("Refreshing rollup ...")
    requests.post(f"{sb}/rest/v1/rpc/refresh_graded_sales_rollup", headers=head, timeout=300)
    print("DONE.")


if __name__ == "__main__":
    main()
