"""Scrape who actually PLAYED in each past event, for the tracked stores.

    python scripts/elo/scrape_event_attendance.py
    python scripts/elo/scrape_event_attendance.py --recheck-days 3   # the daily run
    python scripts/elo/scrape_event_attendance.py --limit 200        # a slice
    python scripts/elo/scrape_event_attendance.py --refresh          # re-scrape
    python scripts/elo/scrape_event_attendance.py --dry-run

Fills public.rph_event_attendance from /api/v2/events/{id}/registrations/.

Why: RPH's Event Tickets is "the total number of players across all events" and
Unique Fans is "individuals that have played in at least 1 event". Both are
about PLAYERS. The two things we had were neither:

  * lorcana_events.registered_user_count — pre-registrations, frozen at the last
    listing before the event. Misses walk-ins (a store showing ~1 ticket per
    event is a walk-in scene, not an empty one) and counts no-shows.
  * elo_matches — only the SC-shaped slice the Elo pipeline ingested, so most of
    a store's events contributed nobody at all.

The registrations endpoint has both, per event, for past events (confirmed by
probe_rph_history.py). Each row carries the user, their final standing and their
match record — enough to tell a registrant from someone who actually sat down.

Scope: events in lorcana_events_history belonging to elo_tracked_stores. The
first full run was ~4,200 events at one request each; writes are batched
FLUSH_EVERY events, and the scans table makes every later run incremental, so an
interrupted run resumes where it stopped rather than starting over.

Cadence: discover_scs.yml runs this on its daily schedule with --recheck-days 3.
It used to be reachable only from a manual dispatch; it ran around 2026-08-19 and
never again, so by 2026-09-10, 212 of the 216 events played at tracked stores
since then had no roster, and the Stores tab counted each one as an event nobody
attended while every workflow stayed green.

Idempotent: upserts on (event_id, best_identifier), and skips events already in
rph_event_attendance_scans unless --refresh, or they started inside
--recheck-days. An event that genuinely had nobody still gets a scan row, so "no
attendance" and "never scraped" stay distinct.
"""
from __future__ import annotations
import argparse, datetime, json, sys, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlencode, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_wu_scs import SUPABASE_URL, SERVICE_KEY, HDR  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REG = "https://api.ravensburgerplay.com/api/v2/events/{eid}/registrations/"
PAGE = 100
FLUSH_EVERY = 50        # events per write batch — see flush() in main()


def _hdr(extra: dict | None = None) -> dict:
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
         "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def _get(path: str):
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr())
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "[]")


def _post(table: str, rows: list[dict], conflict: str) -> None:
    if not rows:
        return
    endpoint = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={conflict}"
    headers = _hdr({"Prefer": "resolution=merge-duplicates,return=minimal"})
    for i in range(0, len(rows), 200):
        batch = rows[i:i + 200]
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    endpoint, data=json.dumps(batch).encode(), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=90) as r:
                    _ = r.read()
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:300]
                if e.code in (400, 404) and ("rph_event_attendance" in detail or "PGRST205" in detail):
                    raise SystemExit("rph_event_attendance missing — apply "
                                     "supabase/122_rph_event_attendance.sql first.")
                raise SystemExit(f"upsert {table} failed [{e.code}]: {detail}")
            except Exception as e:
                if attempt == 4:
                    raise SystemExit(f"upsert {table} failed after retries: {e}")
                time.sleep(1.5 * (attempt + 1))


def http_json(url: str, retries: int = 3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None          # event withdrawn / roster not public
        except Exception:
            pass
        time.sleep(0.5 * (i + 1))
    return None


def _started(iso: str | None) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None


def target_events(refresh: bool, limit: int | None, recheck_days: int = 0,
                  now: datetime.datetime | None = None) -> list[dict]:
    """Past events at tracked stores, oldest first so an interrupted run makes
    monotonic progress rather than re-treading the newest slice.

    An already-scanned event is queued again, flagged `_recheck`, when it started
    inside the last `recheck_days`. The scan row is what makes an event skip
    forever, so an event read while it was still being played — the daily job
    lands mid-afternoon Central, halfway through a Sunday SC — or before the store
    entered its results would otherwise keep that half-finished roster for good."""
    now = now or datetime.datetime.now(datetime.timezone.utc)
    recheck_from = now - datetime.timedelta(days=recheck_days) if recheck_days > 0 else None
    tracked = sorted({r["store_id"] for r in _get("elo_tracked_stores?select=store_id")
                      if r.get("store_id") is not None})
    done: set[int] = set()
    if not refresh:
        off = 0
        while True:
            page = _get(f"rph_event_attendance_scans?select=event_id"
                        f"&order=event_id.asc&limit=1000&offset={off}")
            done.update(r["event_id"] for r in page)
            if len(page) < 1000:
                break
            off += 1000
    out = []
    # Filtered on the SERVER: the archive holds every store the global upcoming
    # feed ever listed and grows every day, and this now runs every day. Only
    # events that have started — a row archived and then pushed back isn't
    # attendance yet.
    for i in range(0, len(tracked), 150):
        ids = ",".join(str(s) for s in tracked[i:i + 150])
        off = 0
        while True:
            page = _get(f"lorcana_events_history?select=event_id,store_id,store_name,start_datetime"
                        f"&store_id=in.({ids})&start_datetime=lt.{quote(now.isoformat())}"
                        f"&order=start_datetime.asc,event_id.asc&limit=1000&offset={off}")
            for r in page:
                if r["event_id"] not in done:
                    out.append(r)
                elif recheck_from and (_started(r.get("start_datetime")) or now) >= recheck_from:
                    out.append(dict(r, _recheck=True))
            if len(page) < 1000:
                break
            off += 1000
    out.sort(key=lambda r: (r.get("start_datetime") or "", r["event_id"]))
    return out[:limit] if limit else out


def scrape_one(eid: int) -> list[dict] | None:
    """Every registration for one event, or None if we could not read it.

    None and [] MUST stay distinct. Collapsing a failed read into an empty list
    writes a scan row saying "looked, nobody there" — so a store whose rosters
    404 reads as a store nobody attended, and the Gap column that exists to
    catch exactly that reports 0 because a scan row exists. A partial read (page
    2 fails after page 1 succeeded) is also None: half a roster is a wrong
    number, not a small one.
    """
    rows, page = [], 1
    while True:
        d = http_json(REG.format(eid=eid) + "?" + urlencode({"page_size": PAGE, "page": page}))
        if d is None:
            return None
        for reg in (d.get("results") or []):
            ident = reg.get("best_identifier")
            if not ident:
                continue
            user = reg.get("user") if isinstance(reg.get("user"), dict) else {}
            rows.append({
                "event_id": eid,
                "best_identifier": ident,
                "rph_user_id": user.get("id"),
                "account_name": user.get("best_identifier"),
                "registration_status": reg.get("registration_status"),
                # Participation, stored raw — see the migration's note on why
                # this isn't collapsed to a boolean here.
                "final_place_in_standings": reg.get("final_place_in_standings"),
                "matches_won": reg.get("matches_won"),
                "matches_lost": reg.get("matches_lost"),
                "matches_drawn": reg.get("matches_drawn"),
                "total_match_points": reg.get("total_match_points"),
                "is_guest": reg.get("is_guest"),
            })
        if not d.get("next"):
            break
        page += 1
        time.sleep(0.1)
    return rows


def played(r: dict) -> bool:
    """Sat down and played, as opposed to merely registering. A standing or any
    recorded match counts; registration_status alone does not, since it is about
    the registration rather than the attendance."""
    if r.get("final_place_in_standings") is not None:
        return True
    return any((r.get(k) or 0) > 0 for k in ("matches_won", "matches_lost", "matches_drawn"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only this many events this run")
    ap.add_argument("--refresh", action="store_true", help="re-scrape events already done")
    ap.add_argument("--recheck-days", type=int, default=0,
                    help="also re-scrape events that started within this many days, even "
                         "if already scanned (the daily job uses 3)")
    ap.add_argument("--dry-run", action="store_true", help="scrape but don't write")
    args = ap.parse_args()
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")

    events = target_events(args.refresh, args.limit, args.recheck_days)
    rechecks = sum(1 for e in events if e.get("_recheck"))
    print(f"{len(events)} past event(s) to scrape"
          + (f", {rechecks} of them re-reads from the last {args.recheck_days} days" if rechecks else "")
          + (" (--refresh: including already-scraped)" if args.refresh else "") + "\n")
    if not events:
        print("  nothing to do — every tracked past event is already scraped")
        return

    total_rows = total_played = 0
    unreadable: list[int] = []
    pend_rows: list[dict] = []
    pend_scans: list[dict] = []

    def flush() -> None:
        """Rows BEFORE scans, always. The scan row is what makes a re-run skip an
        event, so recording it first would let an interrupted flush mark an
        event done whose attendance never landed — invisible, and only fixable
        with --refresh over everything."""
        if args.dry_run:
            pend_rows.clear(); pend_scans.clear(); return
        _post("rph_event_attendance", pend_rows, "event_id,best_identifier")
        _post("rph_event_attendance_scans", pend_scans, "event_id")
        pend_rows.clear(); pend_scans.clear()

    for n, ev in enumerate(events, 1):
        eid = ev["event_id"]
        rows = scrape_one(eid)
        if rows is None:
            # No scan row: the event stays "not yet scraped", so it shows up in
            # the Gap column and a later run retries it, instead of being
            # silently booked as an event nobody came to.
            unreadable.append(eid)
            continue
        n_played = sum(1 for r in rows if played(r))
        total_rows += len(rows); total_played += n_played
        pend_rows.extend(rows)
        # Stamped on every read, so a re-read moves it: max(scraped_at) is how to
        # tell at a glance that this is still running.
        pend_scans.append({"event_id": eid, "player_count": n_played, "row_count": len(rows),
                           "scraped_at": datetime.datetime.now(datetime.timezone.utc).isoformat()})
        # Batched because two writes per event made the upserts, not the RPH
        # fetch, the long pole — a full run was overrunning the job timeout. A
        # flush costs at most FLUSH_EVERY events of rework if the run dies.
        if len(pend_scans) >= FLUSH_EVERY:
            flush()
        if n % 50 == 0 or n == len(events):
            sys.stdout.write(f"\r  {n}/{len(events)} events · {total_rows} registrations · "
                             f"{total_played} played")
            sys.stdout.flush()
        time.sleep(0.05)
    flush()
    print()
    print(f"\n  {total_rows} registrations, {total_played} of them played "
          f"({total_rows - total_played} registered without playing)")
    if unreadable:
        print(f"  {len(unreadable)} event(s) could NOT be read and were left unscanned "
              f"(they stay in the Gap column for a later run): "
              f"{', '.join(str(e) for e in unreadable[:20])}"
              + (" ..." if len(unreadable) > 20 else ""))
    if args.dry_run:
        print("  --dry-run: nothing written")


if __name__ == "__main__":
    main()
