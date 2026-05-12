"""
etl_tcgcsv_backfill.py — one-shot historical backfill of TCGCSV daily prices
from 2024-02-08 (start of public archive) through yesterday.

Idempotent + resumable:
  - Skips dates already present in prices_daily.
  - Caches downloaded .7z files in scripts/backfill_cache/ so re-runs don't
    re-download. Safe to interrupt with Ctrl-C and resume.

Usage:
    python etl_tcgcsv_backfill.py
    python etl_tcgcsv_backfill.py --start 2024-02-08 --end 2024-02-29
    python etl_tcgcsv_backfill.py --limit 10           # do at most 10 dates this run

Notes:
  - One archive ~ 2-3 MB. 825 days ~ 2 GB cached locally. The cache lives
    in scripts/backfill_cache/ and is .gitignored. Delete it when done if
    you want the disk back.
  - Lorcana archives before set 1 release (~2023-08-25) won't have data;
    these are simply skipped if 0 rows are found.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import py7zr
import requests
from dotenv import load_dotenv

from supabase_client import Supabase
from tcgcsv_common import LORCANA_CATEGORY_ID, transform_price_rows

ARCHIVE_URL = "https://tcgcsv.com/archive/tcgplayer/prices-{d}.ppmd.7z"
USER_AGENT = "PacksInk/1.0 (+https://packs.ink)"
EARLIEST = date(2024, 2, 8)
CACHE_DIR = Path(__file__).parent / "backfill_cache"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def already_loaded_dates(sb: Supabase) -> set[date]:
    """Return the set of dates already present in prices_daily for tcgcsv source."""
    rows = sb.select(
        "prices_daily",
        columns="date",
        filters={"source": "eq.tcgcsv"},
    )
    return {date.fromisoformat(r["date"]) for r in rows}


def _atomic_rename(src: Path, dst: Path) -> None:
    """os.replace with retries — Windows OneDrive sometimes briefly locks
    newly-written files via its file watcher. Wait it out."""
    last_err = None
    for attempt in range(8):
        try:
            os.replace(src, dst)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.5 * (2 ** attempt))
    raise last_err  # type: ignore[misc]


def download_archive(d: date) -> Path | None:
    """Download the archive for date d to the cache. Returns path on success,
    None on 404 (no archive for that date)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"prices-{d.isoformat()}.ppmd.7z"
    if p.exists() and p.stat().st_size > 0:
        return p
    url = ARCHIVE_URL.format(d=d.isoformat())
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            tmp = p.with_suffix(p.suffix + ".part")
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            _atomic_rename(tmp, p)
            return p
        except requests.RequestException as e:
            wait = 2 ** attempt
            print(f"    download retry {attempt + 1}/3 in {wait}s ({e})")
            time.sleep(wait)
    raise RuntimeError(f"Failed to download archive for {d}")


def extract_lorcana_prices(archive_path: Path, d: date) -> list[dict]:
    """Extract every Lorcana group's prices file from the archive and return
    a flat list of raw price entries (dicts as TCGCSV returns them)."""
    prefix = f"{d.isoformat()}/{LORCANA_CATEGORY_ID}/"
    raw_entries: list[dict] = []
    with tempfile.TemporaryDirectory() as td:
        with py7zr.SevenZipFile(archive_path, "r") as a:
            targets = [
                n for n in a.getnames()
                if n.startswith(prefix) and n.endswith("/prices")
            ]
            if not targets:
                return []
            a.extract(path=td, targets=targets)
        for t in targets:
            p = Path(td) / t
            try:
                with open(p, "rb") as f:
                    j = json.load(f)
                results = j.get("results") if isinstance(j, dict) else j
                if results:
                    raw_entries.extend(results)
            except Exception as e:
                print(f"    skip {t}: {e}")
    return raw_entries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY-MM-DD (default: 2024-02-08)")
    ap.add_argument("--end", help="YYYY-MM-DD (default: yesterday UTC)")
    ap.add_argument("--limit", type=int, help="Max dates to process this run")
    ap.add_argument("--no-skip-loaded", action="store_true",
                    help="Re-ingest dates already in DB (default skips them)")
    args = ap.parse_args()

    start = date.fromisoformat(args.start) if args.start else EARLIEST
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    end = date.fromisoformat(args.end) if args.end else yesterday

    if start > end:
        sys.exit(f"start {start} is after end {end} — nothing to do.")

    load_dotenv()
    sb = Supabase()

    print(f"Backfill range: {start} .. {end}")
    skip: set[date] = set() if args.no_skip_loaded else already_loaded_dates(sb)
    print(f"Already-loaded dates in DB: {len(skip)}")

    to_do = [d for d in daterange(start, end) if d not in skip]
    if args.limit:
        to_do = to_do[: args.limit]
    print(f"Dates to process this run: {len(to_do)}")

    if not to_do:
        print("Nothing to do.")
        return

    processed = 0
    skipped_empty = 0
    failed = 0
    total_rows = 0
    t0 = time.time()

    for d in to_do:
        print(f"\n[{d.isoformat()}]  ({processed + 1}/{len(to_do)})")
        try:
            archive = download_archive(d)
            if archive is None:
                print("  no archive (404), skipping")
                processed += 1
                continue
            size_mb = archive.stat().st_size / (1024 * 1024)
            print(f"  archive: {size_mb:.1f} MB")
            raw = extract_lorcana_prices(archive, d)
            if not raw:
                print("  no Lorcana data in this archive")
                skipped_empty += 1
                processed += 1
                continue
            rows = transform_price_rows(raw, d)
            print(f"  {len(raw)} raw entries -> {len(rows)} price rows")
            if rows:
                sb.upsert(
                    "prices_daily",
                    rows,
                    on_conflict="tcgplayer_product_id,date,printing,source,grade",
                )
                total_rows += len(rows)
            processed += 1
        except Exception as e:
            print(f"  !! FAILED on {d}: {e}")
            failed += 1
            processed += 1
            # keep going — one bad day shouldn't kill an 800-day run
            continue

        # Progress summary every 10 dates
        if processed % 10 == 0:
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = len(to_do) - processed
            eta_sec = remaining / rate if rate > 0 else 0
            print(f"  ... {processed}/{len(to_do)} done, {total_rows} rows total, "
                  f"{failed} failed, ETA {eta_sec / 60:.1f} min")

    elapsed = time.time() - t0
    print(f"\nDone. Processed {processed} dates ({skipped_empty} empty, "
          f"{failed} failed), {total_rows} total rows in {elapsed / 60:.1f} min.")
    if failed:
        print("Re-run the script to retry failed dates (they'll be detected as missing).")


if __name__ == "__main__":
    main()
