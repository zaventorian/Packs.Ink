"""
rematch_graded_unmatched.py - re-run the CURRENT matcher over graded_sales rows
that were NEVER attributed, and let the ones it can now resolve become visible.

WHY THIS EXISTS
---------------
terapeak_load.py --new-only is ON CONFLICT DO NOTHING (mandatory, so manual
excluded / card_id / grade fixes survive a re-load). The side effect nobody
wrote down: **every improvement to the matcher is invisible to rows already in
the table.** A sale that failed attribution the day it was scraped stays failed
for ever, and because an unmatched row is also auto-flagged excluded, nothing on
the site or in any report ever mentions it again.

That silently swallowed a $39,100 PSA 10 sale (item 298340921150, "Gold Mickey -
Brave Little Tailor ... DLC Top Prize", scraped 2026-06-22). Its title covers 4
of the card's 5 name tokens - it says "Gold Mickey", never "Mickey Mouse" - so
overlap was 0.80 against a 0.85 no-other-evidence gate. The matcher has since
learned "DLC" as a set hint and resolves the same title at score 1.20, but the
row was never asked again. Meanwhile that card's PSA 10 tier showed $3,760 and
"-79%" while its real latest PSA 10 sale was ten times that.

HOW THIS IS NOT reattribute_graded_sales.py
-------------------------------------------
That script walks EVERY row and excludes anything the matcher cannot place -
including rows a human deliberately attributed by hand - which is why the
graded-scrape skill forbids running it with --commit. This one is the opposite
shape, and the scoping is the whole safety argument:

  * it fetches ONLY card_id is null - a row that already has an attribution is
    never read, let alone written;
  * it skips any row with a concrete exclude_reason (foreign / troll / auto /
    lot / cn-conflict / outlier / manual) - those are verdicts, not failures;
  * the rows it therefore acts on have NEVER been attributed, so they have never
    appeared anywhere on the site, so there is no human decision about them to
    clobber. That is what makes un-excluding them safe;
  * it un-excludes only a row that can actually reach graded_sales_rollup (whose
    gate is card_id AND grade AND sale_price AND not excluded). A gradeless row
    is attributed but LEFT excluded and reported for the slab-OCR pass, rather
    than silently "fixed" into something that is still invisible.

It also tightens: a row whose title now reads as foreign / troll / autograph /
lot gets that recorded as its exclude_reason, so it stops being an anonymous
pre-migration-111 exclusion.

Dry run by default. Read-only until you pass --commit.

    python scripts/rematch_graded_unmatched.py                # dry run + report
    python scripts/rematch_graded_unmatched.py --commit       # apply + refresh
    python scripts/rematch_graded_unmatched.py --report-only  # just the stragglers
"""
from __future__ import annotations

import argparse
import collections
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_load import exclude_reason_for, printing_of
from terapeak_match import build_index, match_one, is_nonsingle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json"}

# A sale at or above this is loud enough that losing it silently is the bug this
# script exists to stop. Anything still unattributed above it gets NAMED at the
# end of every run, whether or not anything was written.
LOUD_USD = 500.0

SELECT = ("item_id,title,card_id,grader,grade,sale_price,sold_date,printing,"
          "excluded,exclude_reason,match_confidence")


def decide(row, by_cn, inv):
    """Pure: one unmatched row -> (patch_body_or_None, kind).

    Every early return here is a safety rail; see the module docstring. The
    ordering matters: an attributed row and a row carrying a real verdict are
    both refused BEFORE the matcher is consulted, so this can never re-litigate
    a decision that has already been made."""
    title = row.get("title") or ""

    # Defence in depth - the fetch already filters on card_id is null, but this
    # function is also the thing the guard test pins, so it states the rule too.
    if row.get("card_id"):
        return None, "skip:already-attributed"
    if row.get("exclude_reason"):
        return None, "skip:has-reason"

    reason = exclude_reason_for(title)
    if reason is None and is_nonsingle(title):
        reason = "lot"
    if reason:
        return {"excluded": True, "exclude_reason": reason}, "reason:" + reason

    card, conf, cn_conflict = match_one(title, by_cn, inv)
    if card is None:
        if cn_conflict:
            return ({"excluded": True, "exclude_reason": "cn-conflict",
                     "cn_conflict": True}, "reason:cn-conflict")
        return None, "skip:still-unmatched"

    body = {"card_id": card["id"], "match_confidence": conf, "cn_conflict": False}
    pr = printing_of(title)
    if pr:
        body["printing"] = pr

    # The rollup's gate is card_id AND grade AND sale_price AND not excluded.
    # Attribute either way (it is real information, and it is what lets the OCR
    # pass find the row), but only lift `excluded` when lifting it actually makes
    # the sale visible. Otherwise we would report a fix that fixed nothing.
    if row.get("grade") is None:
        return body, "attributed:needs-grade"
    if row.get("sale_price") is None:
        return body, "attributed:no-price"
    body["excluded"] = False
    return body, "attributed:now-visible"


def fetch_unmatched():
    rows, off = [], 0
    while True:
        r = requests.get(SB_URL + "/rest/v1/graded_sales", headers=HEAD, timeout=60,
                         params={"select": SELECT, "card_id": "is.null",
                                 "order": "item_id", "offset": off, "limit": 1000})
        r.raise_for_status()
        b = r.json()
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def patch(item_id, body):
    r = requests.patch(SB_URL + "/rest/v1/graded_sales", headers=HEAD, timeout=30,
                       params={"item_id": "eq." + str(item_id)}, json=body)
    r.raise_for_status()


def money(v):
    try:
        return "${:,.0f}".format(float(v))
    except (TypeError, ValueError):
        return "$?"


def price_of(row):
    try:
        return float(row.get("sale_price") or 0)
    except (TypeError, ValueError):
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="write changes (else dry run)")
    ap.add_argument("--report-only", action="store_true",
                    help="skip the matcher pass; just name the loud stragglers")
    ap.add_argument("--loud", type=float, default=LOUD_USD,
                    help="straggler report threshold in USD (default %d)" % LOUD_USD)
    args = ap.parse_args()

    print("Building catalog index ...")
    by_cn, inv, ncards, _ = build_index()
    print("catalog: %d cards" % ncards)
    print("Fetching NEVER-ATTRIBUTED graded_sales rows (card_id is null) ...")
    rows = fetch_unmatched()
    print("%d unmatched rows\n" % len(rows))

    changes, stats, touched = [], collections.Counter(), set()
    for r in rows:
        if args.report_only:
            stats["skip:report-only"] += 1
            continue
        body, kind = decide(r, by_cn, inv)
        stats[kind] += 1
        if body:
            changes.append((r, body, kind))
            if kind.startswith("attributed"):
                touched.add(r["item_id"])

    print("=" * 72)
    for k, n in sorted(stats.items(), key=lambda kv: -kv[1]):
        print("  %6d  %s" % (n, k))
    print("-" * 72)
    visible = [c for c in changes if c[2] == "attributed:now-visible"]
    recovered = sum(price_of(r) for r, _, _ in visible)
    print("  %6d  ROWS TO CHANGE   (%d become visible, %s of sales)"
          % (len(changes), len(visible), money(recovered)))
    print("=" * 72)

    if visible:
        print("\nBecoming visible (top 20 by price):")
        for r, b, _ in sorted(visible, key=lambda c: -price_of(c[0]))[:20]:
            print("  %10s  %s  %s %s  -> %-34s %s"
                  % (money(r.get("sale_price")), r.get("sold_date"), r.get("grader"),
                     r.get("grade"), b["card_id"][:34], (r.get("title") or "")[:50]))

    needs = [c for c in changes if c[2] == "attributed:needs-grade"]
    if needs:
        print("\nAttributed but still hidden - NO GRADE in the title (%d); these are"
              " the slab-OCR pass's job (terapeak_ocr_reconcile.py):" % len(needs))
        for r, b, _ in sorted(needs, key=lambda c: -price_of(c[0]))[:10]:
            print("  %10s  %s  %s" % (money(r.get("sale_price")), r.get("sold_date"),
                                      (r.get("title") or "")[:62]))

    # The straggler report is the half that keeps this from happening again: a
    # five-figure sale we cannot place should be something a human is TOLD about,
    # not something that decays into a silent excluded row.
    loud = [r for r in rows if price_of(r) >= args.loud and r["item_id"] not in touched]
    if loud:
        print("\n!! STILL UNATTRIBUTED at >= %s (%d). Each is a real sale we are not"
              " showing:" % (money(args.loud), len(loud)))
        for r in sorted(loud, key=price_of, reverse=True)[:20]:
            print("  %10s  %s  reason=%-10s %s"
                  % (money(r.get("sale_price")), r.get("sold_date"),
                     str(r.get("exclude_reason")), (r.get("title") or "")[:54]))

    if args.report_only:
        return
    if not args.commit:
        print("\nDRY RUN - re-run with --commit to apply %d changes." % len(changes))
        return

    print("\nApplying %d changes ..." % len(changes))
    for i, (r, body, _) in enumerate(changes):
        patch(r["item_id"], body)
        if i and i % 200 == 0:
            print("  %d/%d" % (i, len(changes)), flush=True)
    print("Refreshing rollup ...")
    rr = requests.post(SB_URL + "/rest/v1/rpc/refresh_graded_sales_rollup",
                       headers=HEAD, timeout=300)
    print("  rollup refresh HTTP %d" % rr.status_code)
    print("DONE.")


if __name__ == "__main__":
    main()
