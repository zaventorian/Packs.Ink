"""raw_topup.py — scrape RAW (ungraded) eBay sales for the raw_watchlist cards.

The graded twin (terapeak_topup.py) sweeps six GRADER keywords. This sweeps the
~22 CARD-NAME queries in scripts/raw_watchlist.py, which is the whole difference:
a grader sweep finds slabs of every card, a name sweep finds every product
wearing one card's name. scripts/raw_match.py is where that is dealt with; this
file only has to fetch honestly.

    python scripts/raw_topup.py              # every query, top-up mode
    python scripts/raw_topup.py --deep       # ignore cutoffs, pull each query to exhaustion
    python scripts/raw_topup.py --query "Brave Little Tailor"   # one query (substring match)

Requires the same CDP Chrome as the graded scrape -- see the graded-scrape skill.
Exit codes: 0 done · 2 not logged in / no research page · 3 captcha mid-run
(progress is saved; re-running resumes via the JSONL dedup).

⚠ OUTPUT GOES TO scripts/raw_output/, NEVER scripts/terapeak_output/. The graded
loader's `terapeak_clean.load_all_dedup()` globs `terapeak_output/lorcana_*.jsonl`
and its filename filter would not reject a raw file: `classify()` returns
NEEDS_GRADE for any title with no grade token, so every raw sale in a misplaced
file would be inserted into graded_sales under a grader invented from the
filename. Nothing would error and the graded rollup would quietly gain a
grader called TAILOR.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from playwright.sync_api import sync_playwright  # noqa: E402

import terapeak_scrape as ts  # noqa: E402

# ⚠ terapeak_topup reads sys.argv AT IMPORT TIME to pick its grader list, so it
# is imported behind a neutralised argv. Importing it rather than copying its
# helpers is deliberate: click_by / wait_swap / ensure_all_sites / is_newest_first
# encode hard-won knowledge about eBay's SPA (never page.goto, All-sites lives in
# a native <select>, the sort check must be strictly monotonic), and a second
# copy would drift from the first the next time eBay moves a selector.
_argv = sys.argv
sys.argv = [_argv[0]]
import terapeak_topup as tt  # noqa: E402
sys.argv = _argv

from raw_watchlist import WATCHLIST, queries  # noqa: E402

RAW_OUT = HERE / "raw_output"
TODAY = date.today()


def slug(q):
    return "raw_" + "".join(ch if ch.isalnum() else "_" for ch in q.lower()).strip("_")[:60]


def file_max_date(path):
    mx = None
    if not path.exists():
        return None
    for line in path.open(encoding="utf-8"):
        if not line.strip():
            continue
        try:
            d = tt.pdate(json.loads(line).get("date_last_sold_text"))
        except Exception:
            continue
        if d and (mx is None or d > mx):
            mx = d
    return mx


def scrape_query(page, q, deep):
    """One watchlist query, newest-first, bounded. Returns new-row count or
    "CHALLENGE"."""
    inp = page.locator('input[placeholder*="keyword" i]').first
    if not inp.count():
        sys.exit("SAFETY STOP: keyword input not found — is Terapeak open in Chrome?")
    prev = tt.first_id(page)
    inp.click()
    inp.fill(q)
    inp.press("Enter")
    tt.wait_swap(page, prev)
    time.sleep(2.0)

    if tt.market(page) != "ALL":
        tt.ensure_all_sites(page)

    rows = tt.rows_now(page)
    if not rows:
        print(f"  no results for {q}")
        return 0

    # Same two-click sort dance as the grader sweep: a keyword Enter resets the
    # table to best-match order, and a best-match page whose first row happens to
    # be recent looks sorted. tt.is_newest_first is the strict check.
    if not tt.is_newest_first(rows):
        sels = ['[role="columnheader"]:has-text("Date last sold")',
                'th:has-text("Date last sold")',
                'button:has-text("Date last sold")', 'text="Date last sold"']
        for _ in range(2):
            prev = tt.first_id(page)
            tt.click_by(page, sels, "date header")
            tt.wait_swap(page, prev)
            time.sleep(1.5)
            rows = tt.rows_now(page)
            if tt.is_newest_first(rows):
                break
        if not tt.is_newest_first(rows):
            print(f"  SKIP {q}: could not get newest-first sort")
            return 0

    prev = tt.first_id(page)
    if tt.click_by(page, ['button[aria-label="Go to first page"]'], "first page"):
        tt.wait_swap(page, prev)
        time.sleep(1.0)

    out_path = RAW_OUT / f"{slug(q)}.jsonl"
    mx = file_max_date(out_path)
    # ⚠ A first pull for a query is DEEP (no cutoff), unlike the grader sweep,
    # which always tops up. These cards sell a handful of times a year, so the
    # whole point is the back catalogue -- Terapeak's archive is the only place
    # a 2023 sale of a card TCGplayer never priced still exists. After that the
    # file's own max date bounds it, exactly as the grader sweep does.
    cutoff = None if (deep or mx is None) else (mx - timedelta(days=2))
    seen = ts._load_seen(out_path)
    print(f"  file_max={mx}  cutoff={cutoff or 'DEEP (exhaust)'}  existing={len(seen)}")

    out_f = out_path.open("a", encoding="utf-8")
    total_new, page_num = 0, 0
    try:
        while page_num < tt.MAX_PAGES:
            page_num += 1
            if ts.detect_challenge(page):
                print(f"\n>>> CAPTCHA on {q} page {page_num}. STOPPING (saved {total_new}).")
                return "CHALLENGE"
            rows = tt.rows_now(page)
            if not rows:
                break
            newest = tt.pdate(rows[0].get("date_last_sold_text"))
            if cutoff and newest and newest < cutoff:
                print(f"  page {page_num}: newest {newest} < cutoff -> caught up")
                break
            cur_first = tt.first_id(page)
            n_new = 0
            for r in rows:
                k = ts._row_key(r)
                if k in seen:
                    continue
                seen.add(k)
                # Tag the row with the query that found it. raw_sales.source_query
                # is what makes a bad sweep auditable after the fact -- without it
                # a wrong row cannot be traced back to the net that caught it.
                r["_query"] = q
                out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                n_new += 1
            out_f.flush()
            total_new += n_new
            print(f"  page {page_num}: {len(rows)} rows "
                  f"[{rows[0].get('date_last_sold_text')} .. {rows[-1].get('date_last_sold_text')}] "
                  f"+{n_new} (total {total_new}) mk={tt.market(page)}")
            if not tt.click_by(page, ['button[aria-label="Go to next page"]'], "next"):
                break
            tt.wait_swap(page, cur_first)
            time.sleep(random.uniform(6.0, 10.0))
    finally:
        out_f.close()
    print(f"  DONE {q}: +{total_new} across {page_num} pages (file now {len(seen)})")
    return total_new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", action="store_true",
                    help="ignore per-file cutoffs and pull every query to exhaustion")
    ap.add_argument("--query", default=None,
                    help="only queries containing this substring (case-insensitive)")
    args = ap.parse_args()

    RAW_OUT.mkdir(exist_ok=True)
    qs = queries()
    if args.query:
        qs = [q for q in qs if args.query.lower() in q.lower()]
        if not qs:
            sys.exit(f"no watchlist query contains {args.query!r}")
    print(f"{len(qs)} queries, {len(WATCHLIST)} cards -> {RAW_OUT}")

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
        except Exception as e:
            print(f"cannot reach CDP Chrome on 9222: {e}")
            return 2
        ctx = browser.contexts[0]
        page = next((pg for pg in ctx.pages if "ebay.com/sh/research" in (pg.url or "")), None)
        if page is None:
            print("no Terapeak research page open in the CDP Chrome")
            return 2
        if ts.detect_challenge(page):
            print("challenge/sign-in showing — clear it in the Chrome window, then re-run")
            return 2
        tt.ensure_all_sites(page)

        for i, q in enumerate(qs, 1):
            print(f"\n[{i}/{len(qs)}] {q}")
            r = scrape_query(page, q, args.deep)
            if r == "CHALLENGE":
                return 3
            # The grader sweep waits 45-120s between queries. Same here: 22
            # keyword switches in a row is the shape of traffic Distil watches
            # for, and the burner account is not worth saving ten minutes.
            if i < len(qs):
                time.sleep(random.uniform(45.0, 90.0))
    print("\nALL DONE. Next: python scripts/raw_load.py --from-jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
