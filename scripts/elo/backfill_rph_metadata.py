"""Backfill date + store + location for RPH events by scraping the public
Play Hub event page. The /tv/ API doesn't expose any of these, but the
Next.js-rendered event page embeds the full event JSON server-side with:

  start_datetime              -> event_date
  store.name                  -> store
  store.administrative_area_level_1_short + city in full_address -> location

Idempotent: only updates rows whose date/store is NULL or '?'. Safe to re-run.

Usage:
    python backfill_rph_metadata.py                    # all RPH events
    python backfill_rph_metadata.py --season "Winterspell Spring 2026"
    python backfill_rph_metadata.py --event 437414
"""
from __future__ import annotations
import argparse, re, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

DB = Path(__file__).parent / "lorcana_elo.db"
HDR = {"User-Agent": "Mozilla/5.0"}

DT_RE  = re.compile(r'\\"(\w+)\\":\\"(20\d\d-\d\d-\d\dT\d\d:\d\d:\d\d[+\-]\d\d:\d\d)')
STORE_NAME_RE = re.compile(r'\\"store\\":\{\\"id\\":\d+,\\"name\\":\\"([^"\\]+)')
ADDR_RE  = re.compile(r'\\"full_address\\":\\"([^"\\]+)\\"')

def fetch_page(eid: int, retries: int = 3) -> str | None:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(f"https://tcg.ravensburgerplay.com/events/{eid}", headers=HDR)
            with urllib.request.urlopen(req, timeout=25) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last = e; time.sleep(0.5 * (i + 1))
    print(f"  e{eid}: fetch failed ({last})")
    return None


def parse_event(html: str) -> dict:
    """Pull start_datetime, store name, and a city-level location string."""
    out = {"event_date": None, "store": None, "location": None}
    # start_datetime — pick the first occurrence (top-level event field)
    for m in DT_RE.finditer(html):
        if m.group(1) == "start_datetime":
            out["event_date"] = m.group(2)[:10]
            break
    # store.name — first match is the top-level store
    sm = STORE_NAME_RE.search(html)
    if sm:
        out["store"] = sm.group(1)
    # full_address — parse the city, state from "Street, City, ST, ZIP, Country"
    am = ADDR_RE.search(html)
    if am:
        parts = [p.strip() for p in am.group(1).split(",")]
        # Typical: "Street", "City", "ST", "ZIP", "Country"
        if len(parts) >= 3:
            city, state = parts[-4], parts[-3]
            out["location"] = f"{city}, {state}"
        elif len(parts) >= 2:
            out["location"] = parts[-2]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None)
    ap.add_argument("--event", type=int, default=None)
    ap.add_argument("--force", action="store_true",
                    help="overwrite metadata even when already present")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    q = "SELECT event_id, event_date, store, location FROM events WHERE platform='rph'"
    params: list = []
    if args.season:
        q += " AND season=?"; params.append(args.season)
    if args.event:
        q += " AND event_id=?"; params.append(args.event)
    rows = conn.execute(q, params).fetchall()
    if not args.force:
        rows = [r for r in rows if r["event_date"] is None or r["store"] is None]
    print(f"scanning {len(rows)} events with {args.workers} workers...")

    updates: list[tuple] = []
    def work(eid: int):
        html = fetch_page(eid)
        if not html: return eid, None
        return eid, parse_event(html)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, r["event_id"]): r["event_id"] for r in rows}
        done = 0
        for f in as_completed(futs):
            eid, info = f.result()
            done += 1
            if info is None:
                continue
            updates.append((info["event_date"], info["store"], info["location"], eid))
            if done % 10 == 0:
                print(f"  ...{done}/{len(rows)}")

    # COALESCE the new values with existing (so partial extracts don't blank existing data)
    for d, s, loc, eid in updates:
        conn.execute(
            """UPDATE events SET
                 event_date = COALESCE(?, event_date),
                 store      = COALESCE(?, store),
                 location   = COALESCE(?, location)
               WHERE event_id = ?""",
            (d, s, loc, eid),
        )
    conn.commit()
    print(f"\nupdated {len(updates)} events")

    # Show a sample for sanity
    if updates:
        print("\nsample:")
        for d, s, loc, eid in updates[:5]:
            print(f"  e{eid}  date={d}  store='{s}'  loc='{loc}'")


if __name__ == "__main__":
    main()
