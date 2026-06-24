"""
terapeak_load.py — load cleaned + matched Terapeak graded sales into Supabase
`graded_sales` (migration 71). This is a NEW table, separate from the old
TCGPriceLookup graded data (graded_prices_daily/_latest).

Loads the single-graded-card buckets (GRADED + NEEDS_GRADE); the EXCLUDE_*
buckets (lots/sealed/accessory/raw/other-TCG) are skipped — they aren't
single-card sales. Each row carries the matcher's card_id + grader + grade plus
two quality columns (match_confidence, cn_conflict) so nothing is blindly
trusted and the slab-OCR pass can target the uncertain rows. Re-runnable
(upsert on item_id) — re-matching never requires re-scraping.

    python scripts/terapeak_load.py --limit 200   # test
    python scripts/terapeak_load.py               # full load
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_clean import load_all_dedup, classify
from terapeak_match import build_index, match_one

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {
    "apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}


def parse_date(s):
    try:
        return datetime.datetime.strptime(s, "%b %d, %Y").date().isoformat()
    except Exception:
        return None


def printing_of(title: str):
    t = (title or "").lower()
    if re.search(r"non[\s-]?foil", t):
        return "Non-Foil"
    if "cold foil" in t:
        return "Cold Foil"
    if "foil" in t or "holo" in t:
        return "Foil"
    return None


# Foreign-language listings (Chinese / Japanese / Korean printings) are a
# separate market — keep the rows but flag `excluded` so they don't blend into a
# card's graded price history (migration 76). Full words any-case OR standalone
# UPPERCASE language codes (verified no English false positives).
FOREIGN_WORD_RE = re.compile(
    r"\b(chinese|japanese|korean|china|japan|korea|"
    r"german|germany|deutsch|deutsche|"
    r"french|francais|française|francaise|"
    r"italian|italiano|italien|italienne)\b", re.I)
# Uppercase language codes (case-sensitive so we don't catch English words like
# "it"/"de"). JPN/JAP/KOR/CHN are the 3-letter Asian forms; GER/DEU/FR/FRA are the
# European edition tags eBay sellers append (e.g. "GERMAN DE 1", "Lorcana FR 2").
# Note: "IT"/"ITA" are intentionally excluded — uppercase "IT" is almost always an
# English card name ("It Means No Worries", "Wreck-It Ralph", "Let It Go"), not Italy.
FOREIGN_CODE_RE = re.compile(r"\b(ZH|JA|JP|JPN|JAP|KR|KOR|CN|CHN|GER|DEU|FR|FRA)\b")
# Bare uppercase "DE" is the German-edition tag, but it collides with the character
# name "Cruella de Vil" — only treat a standalone uppercase DE as German when the
# title isn't "...de vil..." (genuinely-German Cruella sales are still caught by the
# "german"/"deutsch" word above).
DE_TAG_RE = re.compile(r"\bDE\b")
DE_VIL_RE = re.compile(r"de\s+vil", re.I)


def is_foreign_lang(title: str) -> bool:
    t = title or ""
    if FOREIGN_WORD_RE.search(t) or FOREIGN_CODE_RE.search(t):
        return True
    return bool(DE_TAG_RE.search(t) and not DE_VIL_RE.search(t))


# Troll / not-actually-graded listings: a RAW card the seller claims *would*
# grade (e.g. "PSA 10 CONTENDER", "would grade 10"). Parsed as graded (it says
# "PSA 10") but it's not a real graded sale — flag excluded.
TROLL_RE = re.compile(
    r"contender|\b(would|will|could|should)\s+grade|"
    r"gem\s*mint\s*(candidate|contender|worthy)|"
    r"\b(psa|cgc|bgs)\s*10\s*(candidate|worthy|quality)\b", re.I)


def is_troll_listing(title: str) -> bool:
    return bool(TROLL_RE.search(title or ""))


# Autographed / artist-signed / sketch cards are a separate (much pricier) market —
# an artist signature or 1/1 sketch isn't comparable to a plain graded copy, so they
# blow out the price history. Flag excluded. NOTE: do NOT match bare "1/1" — it
# collides with "Pop 1/1" (a normal card that's simply the only one PSA-graded).
# `\bautograph` has NO trailing boundary so it also catches autographed/autographs
# (the `\bautograph\b` form missed "Autographed", which slipped a $1k sale through).
AUTOGRAPH_RE = re.compile(
    r"\b(auto|signed|signature|jsa|sketch|witnessed|inscribed)\b"
    r"|\bautograph|psa/?dna|hand.?drawn", re.I)


def is_autograph(title: str) -> bool:
    return bool(AUTOGRAPH_RE.search(title or ""))


def is_excluded(title: str) -> bool:
    return is_foreign_lang(title) or is_troll_listing(title) or is_autograph(title)


def upsert(batch):
    for attempt in range(4):
        try:
            r = requests.post(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD,
                              json=batch, timeout=60)
            if r.status_code < 300:
                return
            if r.status_code >= 500:
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit(f"upsert HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            time.sleep(3 * (attempt + 1))
            last = e
    raise SystemExit(f"upsert failed after retries: {last}")


def refresh_rollup():
    """Rebuild graded_sales_rollup (Last Sold / Avg-of-5 per card+grader+grade)
    so the site reflects the rows we just loaded. Migration 73."""
    try:
        r = requests.post(f"{SB_URL}/rest/v1/rpc/refresh_graded_sales_rollup",
                          headers=HEAD, json={}, timeout=300)
        if r.status_code < 300:
            print("refreshed graded_sales_rollup")
        else:
            print(f"WARN: rollup refresh HTTP {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        print(f"WARN: rollup refresh failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap rows (testing)")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args()

    print("Loading + classifying sales ...")
    rows, _, _ = load_all_dedup()
    print("Building catalog index ...")
    by_cn, inv, ncards, nsets = build_index()
    print(f"catalog: {ncards} cards / {nsets} sets")

    out = []
    stats = {"matched": 0, "unmatched": 0, "no_grade": 0, "conflict": 0, "skip_no_id": 0}
    for r in rows:
        cat, grader, grade = classify(r.get("title", ""), r["_file_grader"])
        if cat not in ("GRADED", "NEEDS_GRADE"):
            continue
        item_id = r.get("item_id")
        if not item_id:
            stats["skip_no_id"] += 1
            continue
        title = r.get("title", "")
        card, conf, cn_conflict = match_one(title, by_cn, inv)
        if card:
            stats["matched"] += 1
        else:
            stats["unmatched"] += 1
        if cat == "NEEDS_GRADE":
            stats["no_grade"] += 1
            grade = None
        if cn_conflict:
            stats["conflict"] += 1
        out.append({
            "item_id": item_id,
            "title": title,
            "listing_url": r.get("listing_url"),
            "image_url": r.get("thumbnail_url"),
            "sale_price": r.get("avg_sold_price"),
            "shipping": r.get("avg_shipping"),
            "quantity_sold": r.get("total_sold"),
            "bids": r.get("bids"),
            "sold_date": parse_date(r.get("date_last_sold_text")),
            "listing_type": r.get("listing_type"),
            "source_query": r.get("_file_grader"),
            "scraped_at": r.get("scraped_at"),
            "card_id": card["id"] if card else None,
            "grader": grader,
            "grade": grade,
            "printing": printing_of(title),
            "match_confidence": conf,
            "cn_conflict": cn_conflict,
            "excluded": is_excluded(title),
        })
        if args.limit and len(out) >= args.limit:
            break

    print(f"\nprepared {len(out)} rows  "
          f"(matched {stats['matched']}, unmatched {stats['unmatched']}, "
          f"no-grade {stats['no_grade']}, cn-conflict {stats['conflict']}, "
          f"skipped-no-id {stats['skip_no_id']})")

    print("Upserting ...")
    for i in range(0, len(out), args.batch):
        upsert(out[i:i + args.batch])
        print(f"  {min(i + args.batch, len(out))}/{len(out)}", flush=True)
    print("Refreshing rollup ...")
    refresh_rollup()
    print("DONE.")


if __name__ == "__main__":
    main()
