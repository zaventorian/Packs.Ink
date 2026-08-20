"""Backfill public.lorcana_events_history with every PAST event our tracked
stores have run on Ravensburger Play.

    python scripts/elo/scrape_store_history.py                # all tracked stores
    python scripts/elo/scrape_store_history.py --store 2717   # just one
    python scripts/elo/scrape_store_history.py --since 2025-01-01
    python scripts/elo/scrape_store_history.py --dry-run

Why this exists: RPH store tiers are scored on Total Events / Unique Fans /
Event Tickets over the four most recent set seasons, across EVERY event type —
a Tuesday league night counts the same as a Set Championship. Neither existing
source can answer that:

  * elo_events     — the curated Elo ingest. SCs plus whatever locals a season
                     spreadsheet happened to list. Never a complete log.
  * lorcana_events — upcoming only, and swept once events are 30 days past.
                     discover_events.py now archives into the history table
                     before sweeping, but that only helps from today forward.

Measured against the live API (probe run 2026-08-19, ~154k Lorcana events):

  display_statuses=past   133,622 rows.  `ended` / `completed` / `finished` /
                          `archived` / `cancelled` are SILENTLY IGNORED — they
                          return the unfiltered 154,019. Only `past` filters.
  store=<id>              works (server-side).
  store_id=<id>           ALSO works, and DISAGREES with `store` (29 vs 36 rows
                          for store 2717). We don't know which is authoritative,
                          so this script queries BOTH, unions by event id, and
                          then verifies row['store']['id'] locally — the union
                          can't miss what either finds, and the local check
                          throws out anything neither should have returned.
  start_date_after=<date> works (the other four spellings are ignored). Used by
                          --since for cheap incremental re-runs.
  pagination              no cap found — page 400 at page_size=250 still
                          returned full pages, so ~100k rows deep is fine.
  registrations           readable for past events, carrying `user` and
                          `best_identifier` — that's the Unique Fans source, and
                          it's what scrape_rosters.py already consumes.

Idempotent: upserts on event_id, so re-running refreshes rather than duplicates.
"""
from __future__ import annotations
import argparse, datetime, json, sys, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlencode, quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_wu_scs import (  # noqa: E402
    to_row, is_sc, fetch_set_names, build_aliases, detect_set,
    SUPABASE_URL, SERVICE_KEY, API, HDR,
)
from discover_prereleases import (  # noqa: E402
    classify as classify_prerelease, derive_prerelease_templates, fetch_launch_sets,
)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PAGE_SIZE = 250
# Both spellings are queried and unioned — see the module docstring. Ordering by
# id keeps deep paging stable while events are being created elsewhere.
STORE_PARAMS = ("store", "store_id")


def http_json(url: str, retries: int = 4):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            if e.code in (400, 404):
                return None
            last = e
        except Exception as e:
            last = e
        time.sleep(0.6 * (i + 1))
    raise last


def _sb_headers(extra: dict | None = None) -> dict:
    h = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
         "Content-Type": "application/json"}
    h.update(extra or {})
    return h


def tracked_store_ids() -> list[int]:
    """The stores we already count, from the table sync_elo_tracked_stores.py
    maintains. Scoping to these keeps a backfill at ~30 stores instead of 133k
    rows of everyone's events."""
    url = f"{SUPABASE_URL}/rest/v1/elo_tracked_stores?select=store_id,store_name&order=store_id.asc"
    req = urllib.request.Request(url, headers=_sb_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode("utf-8", "ignore") or "[]")
    return [r["store_id"] for r in rows if r.get("store_id") is not None]


def fetch_store_past(store_id: int, since: str | None) -> list[dict]:
    """Every past event for one store, unioned across both store-filter
    spellings and then verified locally against store.id."""
    found: dict[int, dict] = {}
    for param in STORE_PARAMS:
        page = 1
        while True:
            params = {"game_slug": "disney-lorcana", "display_statuses": "past",
                      param: store_id, "page_size": PAGE_SIZE,
                      "ordering": "id", "page": page}
            if since:
                params["start_date_after"] = since
            d = http_json(API + "?" + urlencode(params))
            if not d:
                break
            results = d.get("results") or []
            if not results:
                break
            for ev in results:
                # The server filters disagree, so trust neither blindly: an
                # event counts for this store only if the row says so.
                st = ev.get("store") or {}
                if isinstance(st, dict) and st.get("id") == store_id:
                    found[ev["id"]] = ev
            if not d.get("next"):
                break
            page += 1
            time.sleep(0.12)
    return list(found.values())


def upsert_history(rows: list[dict], chunk: int = 200) -> int:
    endpoint = f"{SUPABASE_URL}/rest/v1/lorcana_events_history"
    headers = _sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    done = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        for attempt in range(5):
            try:
                req = urllib.request.Request(
                    endpoint, data=json.dumps(batch).encode(), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=90) as r:
                    _ = r.read()
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "ignore")[:300]
                if e.code in (400, 404) and ("lorcana_events_history" in detail or "PGRST205" in detail):
                    raise SystemExit(
                        "lorcana_events_history does not exist — apply "
                        "supabase/121_lorcana_events_history.sql first.")
                raise SystemExit(f"upsert failed [{e.code}]: {detail}")
            except Exception as e:
                if attempt == 4:
                    raise SystemExit(f"upsert batch failed after retries: {e}")
                time.sleep(1.5 * (attempt + 1))
        done += len(batch)
        sys.stdout.write(f"\r    upserted {done}/{len(rows)}")
        sys.stdout.flush()
    if rows:
        print()
    return done


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=int, action="append",
                    help="only this store_id (repeatable); default = all tracked")
    ap.add_argument("--since", default=None,
                    help="YYYY-MM-DD; only events starting after this (cheap re-runs)")
    ap.add_argument("--dry-run", action="store_true", help="scrape but don't write")
    args = ap.parse_args()

    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")

    stores = args.store or tracked_store_ids()
    print(f"Backfilling past events for {len(stores)} store(s)"
          + (f" since {args.since}" if args.since else "") + "\n")

    sets_sorted = fetch_set_names()
    aliases_sorted = build_aliases(sets_sorted)
    launch_sets = fetch_launch_sets()
    run_seen = datetime.datetime.now(datetime.timezone.utc).isoformat()

    all_rows: list[dict] = []
    kinds = {"sc": 0, "prerelease": 0, "other": 0}
    for n, sid in enumerate(stores, 1):
        evs = fetch_store_past(sid, args.since)
        name = ((evs[0].get("store") or {}).get("name") if evs else None) or f"store {sid}"
        templates = derive_prerelease_templates(evs)
        for ev in evs:
            if is_sc(ev):
                kind = "sc"
                # No `or current_set` fallback here, unlike the upcoming scan: a
                # PAST event belongs to whatever set was live then, and defaulting
                # it to today's set would mis-file years of history.
                set_name = detect_set(ev.get("name") or "", sets_sorted, aliases_sorted)
            else:
                pre_set, via = classify_prerelease(
                    ev, sets_sorted, aliases_sorted, launch_sets, templates)
                # Gate on `via` (the REASON it matched), not on set_name.
                # classify() returns (None, "name") for "definitely a prerelease,
                # but I can't tell which set" — the normal case outside a launch
                # window. Gating on the name demotes those to 'other'.
                if via:
                    kind, set_name = "prerelease", pre_set
                else:
                    # Regular play. set_name stays NULL unless the title names a
                    # set — a Thursday league night belongs to no set.
                    kind = "other"
                    set_name = detect_set(ev.get("name") or "", sets_sorted, aliases_sorted)
            row = to_row(ev, set_name)
            row["kind"] = kind
            row["last_seen_at"] = run_seen
            all_rows.append(row)
            kinds[kind] += 1
        print(f"  [{n}/{len(stores)}] {name:<38} {len(evs):>5} past events")
        time.sleep(0.1)

    print(f"\n  total {len(all_rows)} events "
          f"({kinds['sc']} SC / {kinds['prerelease']} prerelease / {kinds['other']} other)")
    if args.dry_run:
        print("  --dry-run: nothing written")
        return
    upsert_history(all_rows)
    print(f"  done — {len(all_rows)} rows in lorcana_events_history")


if __name__ == "__main__":
    main()
