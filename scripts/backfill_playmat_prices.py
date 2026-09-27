"""
backfill_playmat_prices.py - daily price history for the Lorcana playmats,
from TCGCSV's archive (2024-02-08 onward) into prices_daily.

The daily ETL only started asking for the playmat group (category 35, group
23280 - see tcgcsv_common.EXTRA_PRICE_GROUPS) on the day playmats shipped, so
every earlier day is missing. TCGCSV's daily archives carry EVERY category, so
the history is all there: this extracts that one group from each day's archive.

- Uses the local archive cache the Lorcana backfill left behind
  (scripts/backfill_cache/, ~2.5 GB, 2024-02-08..2026-05-11) wherever it can.
- A day missing from the cache is downloaded to a TEMP directory and deleted
  after extraction, so the cache (inside OneDrive) does not grow by ~400 MB.
- Skips days that already hold a playmat row, so it is resumable.
- Idempotent upsert on prices_daily's own key.

!! TCGCSV TOOK ITS PUBLIC ARCHIVE OFFLINE (found 2026-09-27). Every
   /archive/tcgplayer/prices-<date>.ppmd.7z now answers 403 with a notice from
   its operator ("temporarily removed due to rising server costs"). So the
   LOCAL CACHE IS THE ONLY COPY of those days anywhere we can reach: do not
   delete scripts/backfill_cache/. A 403 is reported as "archive offline", not
   as a failure, so a full run over the cache still exits 0.

--live loads the CURRENT publish instead (TCGCSV's /prices endpoint, which is
still up), dated by its own last-updated stamp. It is the gap-filler for the
days between this script's run and the day the daily ETL starts carrying the
playmat group; once that ETL is live it does this itself, every day.

Usage:
    python scripts/backfill_playmat_prices.py --dry-run      # count, write nothing
    python scripts/backfill_playmat_prices.py                # load everything missing
    python scripts/backfill_playmat_prices.py --start 2026-05-12 --end 2026-09-26
    python scripts/backfill_playmat_prices.py --cache-dir <path to backfill_cache>
    python scripts/backfill_playmat_prices.py --live [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import py7zr
import requests
from dotenv import load_dotenv

from supabase_client import Supabase
from tcgcsv_common import PLAYMATS_CATEGORY_ID, PLAYMATS_GROUP_ID, TCGCSV_BASE, transform_price_rows

ARCHIVE_URL = "https://tcgcsv.com/archive/tcgplayer/prices-{d}.ppmd.7z"
LAST_UPDATED_URL = "https://tcgcsv.com/last-updated.txt"
USER_AGENT = "PacksInk/1.0 (+https://packs.ink) playmat-backfill"


class ArchiveOffline(Exception):
    """TCGCSV answered the archive URL with 403 - it has taken the archive down."""
EARLIEST = date(2024, 2, 8)
DEFAULT_CACHE = Path(__file__).parent / "backfill_cache"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _download(d: date, dest: Path) -> Path | None:
    url = ARCHIVE_URL.format(d=d.isoformat())
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, stream=True, timeout=120)
            if r.status_code == 404:
                return None
            if r.status_code == 403:
                raise ArchiveOffline(d.isoformat())
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 16):
                    if chunk:
                        f.write(chunk)
            return dest
        except requests.RequestException:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"download failed for {d}")


def extract_day(d_iso: str, cache_dir: str) -> tuple[str, list[dict] | None, str]:
    """Worker: this day's raw playmat price entries. (date, entries|None, note).
    None = no archive for the day (404); [] = archive without the group."""
    d = date.fromisoformat(d_iso)
    target = f"{d_iso}/{PLAYMATS_CATEGORY_ID}/{PLAYMATS_GROUP_ID}/prices"
    cached = Path(cache_dir) / f"prices-{d_iso}.ppmd.7z"
    with tempfile.TemporaryDirectory() as td:
        archive = cached if cached.exists() and cached.stat().st_size > 0 else None
        note = "cache"
        if archive is None:
            try:
                archive = _download(d, Path(td) / f"prices-{d_iso}.ppmd.7z")
            except ArchiveOffline:
                return d_iso, None, "archive offline"
            note = "downloaded"
            if archive is None:
                return d_iso, None, "no archive"
        with py7zr.SevenZipFile(archive, "r") as a:
            if target not in a.getnames():
                return d_iso, [], note + ", group absent"
            a.extract(path=td, targets=[target])
        with open(Path(td) / target, "rb") as f:
            j = json.load(f)
    entries = j.get("results") if isinstance(j, dict) else j
    return d_iso, entries or [], note


def playmat_pids() -> list[int]:
    """Every product in the group today - the ids whose history we backfill."""
    url = f"{TCGCSV_BASE}/{PLAYMATS_CATEGORY_ID}/{PLAYMATS_GROUP_ID}/products"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    data = r.json()
    rows = data.get("results") if isinstance(data, dict) else data
    return sorted({int(p["productId"]) for p in rows if p.get("productId") is not None})


def loaded_days(sb: Supabase, pids: list[int]) -> set[str]:
    """Days that already carry a playmat price row (the resume point)."""
    days: set[str] = set()
    for i in range(0, len(pids), 40):
        chunk = pids[i:i + 40]
        rows = sb.select(
            "prices_daily", columns="tcgplayer_product_id,date",
            filters={"tcgplayer_product_id": f"in.({','.join(map(str, chunk))})",
                     "source": "eq.tcgcsv", "grade": "eq.raw"},
            order="tcgplayer_product_id.asc,date.asc")
        days.update(r["date"] for r in rows)
    return days


def publish_date() -> date:
    """The UTC day of TCGCSV's newest publish, from its own last-updated stamp.
    That is the date the daily ETL files the same file under."""
    r = requests.get(LAST_UPDATED_URL, headers={"User-Agent": USER_AGENT}, timeout=30)
    r.raise_for_status()
    s = r.text.strip()
    s = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", s)   # "+0000" -> "+00:00"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc).date()


def latest_card_snapshot(sb: Supabase) -> str | None:
    rows = sb.select("card_prices_latest", columns="price_date", limit=1, order="price_date.desc")
    return rows[0]["price_date"] if rows else None


def run_live(sb: Supabase, dry_run: bool) -> int:
    """Load TCGCSV's CURRENT playmat prices under the day they were published.

    ⚠ Refuses when the daily ETL has not loaded that day yet. Its idempotency
    probe asks "is there ANY tcgcsv/raw row for today, written after the
    publish window?" - so a playmat row written first would make it skip the
    whole day's CARD prices. Only ever add to a day the ETL already holds."""
    snap = publish_date()
    have = latest_card_snapshot(sb)
    if not have or have < snap.isoformat():
        print(f"TCGCSV's newest publish is {snap}, but the daily ETL has only loaded "
              f"{have or 'nothing'} so far. Writing a playmat row first would make it "
              "skip that day's card prices - run this again after the ETL has run.")
        return 0
    url = f"{TCGCSV_BASE}/{PLAYMATS_CATEGORY_ID}/{PLAYMATS_GROUP_ID}/prices"
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
    r.raise_for_status()
    data = r.json()
    entries = data.get("results") if isinstance(data, dict) and "results" in data else data
    rows = transform_price_rows(entries or [], snap)
    written_at = datetime.now(timezone.utc).isoformat()
    for row in rows:
        row["inserted_at"] = written_at
    print(f"Live publish {snap}: {len(entries or [])} entries -> {len(rows)} price rows")
    if dry_run:
        print("(dry run - nothing written)")
        return 0
    if rows:
        sb.upsert("prices_daily", rows,
                  on_conflict="tcgplayer_product_id,date,printing,source,grade", batch=500)
    print(f"Wrote {len(rows)} rows under {snap}.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", help="YYYY-MM-DD (default 2024-02-08)")
    ap.add_argument("--end", help="YYYY-MM-DD (default yesterday UTC)")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    ap.add_argument("--workers", type=int, default=max(2, min(6, (os.cpu_count() or 4) - 1)))
    ap.add_argument("--dry-run", action="store_true", help="extract and count, write nothing")
    ap.add_argument("--no-skip-loaded", action="store_true", help="re-load days already present")
    ap.add_argument("--live", action="store_true",
                    help="load TCGCSV's current publish instead of the archive")
    args = ap.parse_args()

    if args.live:
        load_dotenv()
        return run_live(Supabase(), args.dry_run)

    start = date.fromisoformat(args.start) if args.start else EARLIEST
    end = (date.fromisoformat(args.end) if args.end
           else (datetime.now(timezone.utc) - timedelta(days=1)).date())
    if start > end:
        print(f"start {start} is after end {end} - nothing to do")
        return 0

    load_dotenv()
    sb = Supabase()
    pids = playmat_pids()
    print(f"{len(pids)} products in the playmat group; range {start}..{end}")
    skip = set() if args.no_skip_loaded else loaded_days(sb, pids)
    todo = [d.isoformat() for d in daterange(start, end) if d.isoformat() not in skip]
    print(f"{len(skip)} days already loaded; {len(todo)} to extract with {args.workers} workers"
          f" (cache: {args.cache_dir})")
    if not todo:
        return 0

    pending: list[dict] = []
    total = done = empty = missing = offline = failed = 0
    t0 = time.time()

    def flush(force: bool = False) -> None:
        nonlocal pending, total
        if pending and (force or len(pending) >= 2000):
            if not args.dry_run:
                sb.upsert("prices_daily", pending,
                          on_conflict="tcgplayer_product_id,date,printing,source,grade", batch=500)
            total += len(pending)
            pending = []

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(extract_day, d, args.cache_dir): d for d in todo}
        for fut in as_completed(futs):
            d_iso = futs[fut]
            try:
                d_iso, entries, note = fut.result()
            except Exception as e:
                failed += 1
                print(f"  !! {d_iso}: {e}")
                continue
            done += 1
            if entries is None and note == "archive offline":
                offline += 1
            elif entries is None:
                missing += 1
            elif not entries:
                empty += 1
            else:
                pending.extend(transform_price_rows(entries, date.fromisoformat(d_iso)))
                flush()
            if done % 50 == 0:
                rate = done / max(1e-6, time.time() - t0)
                print(f"  {done}/{len(todo)} days, {total + len(pending)} rows"
                      f" ({rate:.1f} days/s, ETA {(len(todo) - done) / max(rate, 1e-6) / 60:.1f} min)")
    flush(force=True)
    verb = "would write" if args.dry_run else "wrote"
    print(f"\nDone in {(time.time() - t0) / 60:.1f} min: {verb} {total} rows across {done} days"
          f" ({empty} without the group, {missing} with no archive, {failed} failed).")
    if offline:
        print(f"{offline} days are not in the local cache and TCGCSV's archive is offline (403),"
              " so they cannot be loaded from anywhere right now. --live covers today onward.")
    if failed:
        print("Re-run to retry the failed days - loaded days are skipped.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
