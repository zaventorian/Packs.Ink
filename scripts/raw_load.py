"""raw_load.py — load RAW (ungraded) eBay sales into Supabase `raw_sales`.

Two sources, one attribution path (scripts/raw_match.py):

  --backfill-graded   Recover raw sales ALREADY SITTING IN graded_sales. The
                      grader sweeps search "Lorcana" "PSA" etc, and eBay returns
                      plenty of listings whose titles never say PSA at all. Those
                      land in graded_sales as grade-null rows, which the graded
                      rollup ignores by design -- so they have been invisible
                      since the day they were scraped. Measured 2026-09-20:
                      113 of them are real raw sales of watchlist cards, spanning
                      2023-10 to 2026-09 and 19 of the 24 cards, including the
                      $16,406 Rapunzel - Gifted with Healing 4/C1 Foil that
                      justified this whole feature. This is why the pipeline can
                      ship with data before a single new page is scraped.

  --from-jsonl        The ongoing source: whatever scripts/raw_topup.py has
                      written to scripts/raw_output/.

DRY RUN BY DEFAULT. `--commit` is the deliberate act, matching
flag_intentional_draws.py and discord_digest.py. The reason is the asymmetry that
governs this whole pipeline: these cards are on the watchlist precisely because
the site shows a fossil or a dash for them, so any number published here will be
believed, and every mis-attribution available is an order of magnitude wrong.

⚠ INSERT-ONLY unless `--merge` is passed. Same rule, and same reason, as
`terapeak_load.py --new-only`: once a human has corrected an `excluded` or a
`card_id`, a re-load that re-derives attribution from the title silently undoes
it. `--merge` exists for the early days when there are no manual fixes to lose;
after that it is the banned button.

⚠ A backfilled row keeps its eBay item_id and therefore exists in BOTH tables.
That is correct and deliberate -- graded_sales is the scrape LEDGER (what the
sweep saw) and raw_sales is the price SOURCE. Nothing is deleted from
graded_sales: the row there is grade-null, so the graded rollup already ignores
it, and deleting it would make the next `--new-only` grader load re-insert it.

    python scripts/raw_load.py --backfill-graded              # dry run, prints everything
    python scripts/raw_load.py --backfill-graded --commit
    python scripts/raw_load.py --from-jsonl --commit
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import json
import os
import statistics
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

import terapeak_match as tm
from raw_match import raw_verdict, build_watchlist_index, _printing_of
from raw_watchlist import WATCHLIST

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
RAW_OUT = HERE / "raw_output"
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json"}

# A card with fewer than this many sales has no usable median, so the review
# report says nothing about it rather than calling its only sale an outlier.
# Same floor, and the same reasoning, as flag_graded_outliers.py.
OUTLIER_MIN_NEIGHBOURS = 5
OUTLIER_FACTOR = 6.0

# Mirrors public.graded_sale_pkey(printing, split_printing, foil_split), which is
# what migration 163's rollup groups by.
#
# ⚠ The report MUST group the way the rollup will, or it reviews buckets that do
# not exist. The first cut grouped on the raw `printing` string and so showed a
# "Foil" and an "Unknown" bucket for Promo Set 1 #1 -- a card with split_printing
# false and foil_split false, whose every sale the rollup puts in ONE bucket.
# Splitting a card's sales in the report hides exactly the price spread the
# report exists to surface.
FOIL_WORDS = {"foil", "cold foil", "holofoil", "holo"}


def sale_pkey(printing, split, foil_split):
    if split:
        return printing or "Unknown"
    if foil_split:
        return "Foil" if (printing or "").lower().strip() in FOIL_WORDS else "Non-Foil"
    return ""


def parse_date(s):
    for fmt in ("%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime((s or "").strip(), fmt).date().isoformat()
        except Exception:
            pass
    return None


def sb_get_all(path, select, extra=""):
    out, off = [], 0
    while True:
        r = requests.get(f"{SB_URL}/rest/v1/{path}?select={select}&order=item_id.asc"
                         f"&offset={off}&limit=1000{extra}", headers=HEAD, timeout=180)
        r.raise_for_status()
        b = r.json()
        out += b
        if len(b) < 1000:
            return out
        off += 1000


def watchlist_tokens():
    return sorted({(ver or name).lower() for _s, _c, name, ver, _q, _p in WATCHLIST})


def source_backfill_graded():
    """Rows already in graded_sales that may be raw sales of watchlist cards.

    ⚠ `grade is null` is a HARD prerequisite, not an optimisation. Four rows in
    the corpus carry a stored grade (filled later by the slab-OCR pass or by
    hand) while their titles say nothing about grading at all -- raw_match's gate
    1 reads titles and cannot see that, so this is the one piece of evidence only
    the backfill has, and dropping it would publish four slabs as raw prices."""
    rows = sb_get_all("graded_sales",
                      "item_id,title,listing_url,image_url,sale_price,shipping,"
                      "quantity_sold,bids,sold_date,listing_type,grade,scraped_at")
    toks = watchlist_tokens()
    out = []
    for r in rows:
        if r.get("grade"):
            continue
        t = (r.get("title") or "").lower()
        if not any(x in t for x in toks):
            continue
        r["_source_query"] = "backfill:graded_sales"
        out.append(r)
    return out


def source_jsonl():
    """Rows scraped by raw_topup.py.

    ⚠ Read from scripts/raw_output/, NEVER scripts/terapeak_output/. The graded
    loader's `terapeak_clean.load_all_dedup()` globs `terapeak_output/lorcana_*
    .jsonl` and would swallow a raw file whole: `classify()` returns NEEDS_GRADE
    for a title with no grade token, so every raw sale would be inserted into
    graded_sales carrying a grader invented from the filename."""
    seen, out = set(), []
    for f in sorted(glob.glob(str(RAW_OUT / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            key = r.get("item_id") or f"{r.get('title')}|{r.get('avg_sold_price')}"
            if key in seen:
                continue
            seen.add(key)
            r["_source_query"] = r.get("_query") or Path(f).stem
            out.append(r)
    return out


def to_row(r, card, conf, cn_conflict, reason):
    # The two sources spell the money columns differently: the scraper writes
    # Terapeak's own field names, graded_sales writes the loader's. Normalise
    # here rather than in each source, so a new source only has to supply one.
    price = r.get("sale_price", r.get("avg_sold_price"))
    ship = r.get("shipping", r.get("avg_shipping"))
    qty = r.get("quantity_sold", r.get("total_sold"))
    sold = r.get("sold_date") or r.get("date_last_sold_text")
    return {
        "item_id": r.get("item_id"),
        "title": r.get("title"),
        "listing_url": r.get("listing_url"),
        "image_url": r.get("image_url") or r.get("thumbnail_url"),
        "sale_price": price,
        "shipping": ship,
        "quantity_sold": qty,
        "bids": r.get("bids"),
        "sold_date": parse_date(sold) if not (sold or "")[:4].isdigit() else (sold or "")[:10],
        "listing_type": r.get("listing_type"),
        "source_query": r.get("_source_query"),
        "scraped_at": r.get("scraped_at"),
        "card_id": card["id"] if card else None,
        "printing": _printing_of(r.get("title") or ""),
        "match_confidence": conf,
        "cn_conflict": cn_conflict,
        "excluded": reason is not None,
        "exclude_reason": reason,
    }


def fetch_printing_flags(card_ids):
    """split_printing / foil_split for the watchlist cards -- the curated flags
    graded_sale_pkey reads. Not in terapeak_match's catalog select, so fetched
    here rather than widening that shared query."""
    flags = {}
    ids = [c for c in card_ids if c]
    for i in range(0, len(ids), 100):
        chunk = ",".join(ids[i:i + 100])
        r = requests.get(f"{SB_URL}/rest/v1/cards?select=id,split_printing,foil_split"
                         f"&id=in.({chunk})", headers=HEAD, timeout=60)
        r.raise_for_status()
        for c in r.json():
            flags[c["id"]] = (bool(c.get("split_printing")), bool(c.get("foil_split")))
    return flags


def review_report(rows, label_of, flags):
    """Print what a human should look at. This REPORTS, it never excludes.

    Price cannot decide identity here (see raw_match's module docstring: using
    "too cheap to be the promo" to drop a row makes the published price a
    function of the assumption). So a suspicious price is a question for someone
    who can open the listing, not a verdict this script is entitled to reach."""
    inc = [r for r in rows if not r["excluded"] and r["sale_price"]]
    by_card = collections.defaultdict(list)
    for r in inc:
        split, foil_split = flags.get(r["card_id"], (False, False))
        by_card[(r["card_id"], sale_pkey(r["printing"], split, foil_split))].append(r)

    print("\n--- per card/printing ---")
    flagged = []
    for key, rs in sorted(by_card.items(), key=lambda x: -len(x[1])):
        ps = sorted(float(r["sale_price"]) for r in rs)
        med = statistics.median(ps)
        line = (f"  {label_of(key[0]):<34} {(key[1] or '-'):<9} n={len(rs):<3} "
                f"${ps[0]:,.0f}..${ps[-1]:,.0f}  median ${med:,.0f}")
        if len(rs) >= OUTLIER_MIN_NEIGHBOURS:
            for r in rs:
                p = float(r["sale_price"])
                if p > med * OUTLIER_FACTOR or p < med / OUTLIER_FACTOR:
                    flagged.append((label_of(key[0]), key[1], p, med, r["title"]))
        print(line)

    multi = [r for r in inc if (r["quantity_sold"] or 1) > 1]
    if multi:
        print(f"\n--- {len(multi)} multi-quantity listings (sale_price is a per-unit "
              f"average; also a mis-attribution hint on a card with few copies) ---")
        for r in multi[:12]:
            print(f"  x{r['quantity_sold']:<3} ${float(r['sale_price']):>10,.2f}  "
                  f"{(r['title'] or '')[:62]}")

    if flagged:
        print(f"\n--- {len(flagged)} price outliers (>{OUTLIER_FACTOR:g}x from the card's "
              f"median, >={OUTLIER_MIN_NEIGHBOURS} sales). NOT excluded -- open these ---")
        for lab, pr, p, med, title in sorted(flagged, key=lambda x: -x[2])[:20]:
            print(f"  ${p:>11,.2f} vs median ${med:>9,.2f}  {lab} {pr}\n      {(title or '')[:76]}")


def upsert(rows, merge):
    head = dict(HEAD)
    head["Prefer"] = ("resolution=merge-duplicates,return=minimal" if merge
                      else "resolution=ignore-duplicates,return=minimal")
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        for attempt in range(4):
            r = requests.post(f"{SB_URL}/rest/v1/raw_sales", headers=head,
                              json=batch, timeout=90)
            if r.status_code < 300:
                break
            if r.status_code >= 500 or r.status_code == 429:
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit(f"upsert HTTP {r.status_code}: {r.text[:300]}")
        else:
            raise SystemExit("upsert failed after retries")
        print(f"  {min(i + 500, len(rows))}/{len(rows)}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--backfill-graded", action="store_true")
    src.add_argument("--from-jsonl", action="store_true")
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--merge", action="store_true",
                    help="UPDATE existing rows too. Clobbers manual fixes -- see the header.")
    args = ap.parse_args()

    print("Building catalog index ...")
    by_cn, inv, ncards, nsets = tm.build_index()
    wl = build_watchlist_index(by_cn, inv)
    label = {}
    for c_list in by_cn.values():
        for c in c_list:
            label[c["id"]] = f"{c['_set']} #{c['_cn']} {c.get('name') or ''}"
    print(f"catalog: {ncards} cards / {nsets} sets, watchlist: {len(wl)} cards")

    src_rows = source_backfill_graded() if args.backfill_graded else source_jsonl()
    print(f"source rows: {len(src_rows)}")

    out, counts = [], collections.Counter()
    for r in src_rows:
        card, conf, cc, reason = raw_verdict(r.get("title") or "", by_cn, inv, wl)
        counts[reason or "INCLUDED"] += 1
        if not r.get("item_id"):
            counts["skip-no-item-id"] += 1
            continue
        # Only INCLUDED rows and near-misses are worth storing. A Pokemon lot that
        # merely shares a word with a watchlist card is not part of this dataset
        # and would only make the table harder to audit.
        if reason in ("other-tcg", "sealed", "lot", "accessory", "merch"):
            continue
        out.append(to_row(r, card, conf, cc, reason))

    print("\n--- verdicts ---")
    for k, v in counts.most_common():
        print(f"  {k:<16} {v:6}")

    flags = fetch_printing_flags({r["card_id"] for r in out if r["card_id"]})
    review_report(out, lambda cid: label.get(cid, cid or "?"), flags)

    inc = sum(1 for r in out if not r["excluded"])
    print(f"\n{len(out)} rows prepared, {inc} of them counting as raw prices.")
    if not args.commit:
        print("DRY RUN — nothing written. Re-run with --commit.")
        return 0

    print(f"Writing ({'MERGE' if args.merge else 'insert-only'}) ...")
    upsert(out, args.merge)
    r = requests.post(f"{SB_URL}/rest/v1/rpc/refresh_raw_sales_rollup",
                      headers=HEAD, json={}, timeout=300)
    print("refreshed raw_sales_rollup" if r.status_code < 300
          else f"WARN: rollup refresh HTTP {r.status_code}: {r.text[:200]}")
    print("DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
