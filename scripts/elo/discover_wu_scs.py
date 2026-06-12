"""Discover ALL upcoming Set Championships for a given Lorcana set on RPH
(Ravensburger Play, tcg.ravensburgerplay.com) and upsert them into the Supabase
`set_championships` table.

The old per-event hydraproxy API (api.cloudflare.ravensburgerplay.com/hydraproxy)
was retired. The live public events API is:

    https://api.ravensburgerplay.com/api/v2/events/?<filters>

Useful filters (snake_case query params; camelCase ones are silently ignored):
  game_slug=disney-lorcana
  display_statuses=upcoming        # only future events
  name=<text>                      # FUZZY RELEVANCE search — see warning below
  ordering=start_datetime|id|-id   # soonest first / stable keyset
  page / page_size                 # pagination (page_size up to ~250)

⚠️  DO NOT trust the `name=` filter as the collection gate. It is a scored
relevance search with a cutoff, NOT a substring/token filter. Asking for
name="Wilds Unknown Set Championship" silently DROPS clean matches whose
title doesn't closely hug that exact phrase — hyphens ("Wilds Unknown -
Set Championship"), reversed word order ("Set Championship Wilds Unknown"),
store prefixes, quotes, or non-English titles all score below the threshold
and vanish. Measured 2026-06-11: the name filter returned ~2203 WU SCs while
an unfiltered pull found 2269 (~96 real events dropped, incl. event 646568).

So we pull ALL upcoming Lorcana events with NO name filter and decide what's
an SC locally in `is_target_sc`. A second hazard: deep offset pagination over
the live ~15k-row index drifts (rows get skipped when events are inserted
mid-scan), so we union several passes with different orderings — dedup-by-id
makes the union free.

Each result carries name, store{name,city,state,country,lat,lng,website},
full_address, start/end_datetime, timezone, registered_user_count, capacity,
cost_in_cents, currency, gameplay_format{name}, display_status.

Re-runnable: upserts on event_id (merge-duplicates), so running it again just
refreshes registration counts / new events.

Usage:
    python discover_wu_scs.py                          # Wilds Unknown, all countries -> Supabase
    python discover_wu_scs.py --set "Wilds Unknown"
    python discover_wu_scs.py --country US             # client-side country filter
    python discover_wu_scs.py --dry-run --json out.json
"""
from __future__ import annotations
import argparse, json, os, sys, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlencode

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

API = "https://api.ravensburgerplay.com/api/v2/events/"
EVENT_URL = "https://tcg.ravensburgerplay.com/events/{id}"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")


def http_json(url: str, retries: int = 4) -> dict:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            last = e
            time.sleep(0.6 * (i + 1))
    raise last


def fetch_pages(extra: dict, into: dict[int, dict]) -> int:
    """Page through one upcoming-Lorcana query, merging rows into `into` (keyed
    by event id). Returns how many unique ids this pass contributed."""
    before = len(into)
    page = 1
    base = {
        "game_slug": "disney-lorcana",
        "display_statuses": "upcoming",
        "page_size": 250,
    }
    while True:
        params = dict(base, **extra, page=page)
        d = http_json(API + "?" + urlencode(params))
        results = d.get("results") or []
        if not results:
            break
        for ev in results:
            into[ev["id"]] = ev
        total = d.get("count")
        sys.stdout.write(
            f"\r  pass {extra.get('ordering') or extra.get('name') or '?'}: "
            f"page {page}, {len(into)} unique so far (api count={total})   ")
        sys.stdout.flush()
        if not d.get("next"):
            break
        page += 1
        time.sleep(0.12)
    print()
    return len(into) - before


def fetch_all(set_name: str) -> list[dict]:
    """Collect EVERY upcoming Lorcana event (not just `set_name`), robustly.

    We deliberately do not filter by name on the server (see the module
    docstring) — `is_target_sc` does the gating locally. We union several full
    passes with different orderings so pagination drift on the live index can't
    silently skip events; a name-relevance pass for `set_name` is folded in as a
    cheap high-recall safety net for the current set. Dedup is by event id."""
    union: dict[int, dict] = {}
    passes = [
        {"ordering": "id"},               # stable ascending keyset
        {"ordering": "-id"},              # opposite direction — different drift
        {"ordering": "start_datetime"},   # soonest-first ordering
        # cheap relevance net for the requested set (a few pages):
        {"ordering": "start_datetime", "name": f"{set_name} Set Championship"},
    ]
    for p in passes:
        added = fetch_pages(p, union)
        print(f"    +{added} new from this pass — {len(union)} total unique")
    return list(union.values())


SC_SET_HINTS = ("set championship",)


def is_target_sc(ev: dict, set_name: str) -> bool:
    name = (ev.get("name") or "").lower()
    if "set championship" not in name:
        return False
    # scope to the requested set (the API name filter is loose; pin it here)
    if set_name.lower() not in name:
        return False
    # belt-and-suspenders: drop obvious side events that slipped in
    if any(k in name for k in ("prerelease", "pre-release", "release party",
                               "draft", "sealed", "trove", "league night")):
        return False
    return True


def to_row(ev: dict, set_name: str) -> dict:
    st = ev.get("store") or {}
    if not isinstance(st, dict):
        st = {}
    gpf = ev.get("gameplay_format")
    gpf_name = gpf.get("name") if isinstance(gpf, dict) else (gpf or None)
    return {
        "event_id": ev["id"],
        "name": ev.get("name"),
        "set_name": set_name,
        "store_id": st.get("id"),
        "store_name": st.get("name"),
        "store_website": st.get("website"),
        "start_datetime": ev.get("start_datetime"),
        "end_datetime": ev.get("end_datetime"),
        "timezone": ev.get("timezone"),
        "full_address": ev.get("full_address") or st.get("full_address"),
        "city": st.get("city"),
        "state": st.get("state"),
        "country": st.get("country"),
        "latitude": ev.get("latitude") if ev.get("latitude") is not None else st.get("latitude"),
        "longitude": ev.get("longitude") if ev.get("longitude") is not None else st.get("longitude"),
        "registered_user_count": ev.get("registered_user_count"),
        "capacity": ev.get("capacity"),
        "cost_cents": ev.get("cost_in_cents"),
        "currency": ev.get("currency"),
        "gameplay_format": gpf_name,
        "display_status": ev.get("display_status"),
        "url": EVENT_URL.format(id=ev["id"]),
    }


def upsert(rows: list[dict], chunk: int = 200) -> None:
    # Smaller batches + retries: the Supabase TLS endpoint intermittently throws
    # SSLV3_ALERT_BAD_RECORD_MAC on large/back-to-back POSTs.
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    endpoint = f"{SUPABASE_URL}/rest/v1/set_championships"
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    done = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        body = json.dumps(batch).encode()
        for attempt in range(5):
            try:
                req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=60) as r:
                    _ = r.read()
                break
            except urllib.error.HTTPError as e:
                raise SystemExit(f"upsert failed [{e.code}]: {e.read().decode('utf-8','ignore')[:400]}")
            except Exception as e:
                if attempt == 4:
                    raise SystemExit(f"upsert batch failed after retries: {e}")
                time.sleep(1.5 * (attempt + 1))
        done += len(batch)
        print(f"  upserted {done}/{len(rows)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="Wilds Unknown", help="set name to scope SCs to")
    ap.add_argument("--country", default=None, help="optional client-side ISO country filter, e.g. US")
    ap.add_argument("--json", default=None, help="also dump the rows to this path")
    ap.add_argument("--dry-run", action="store_true", help="don't write to Supabase")
    args = ap.parse_args()

    print(f"Pulling ALL upcoming Lorcana events from RPH (no name filter) "
          f"to find '{args.set}' Set Championships locally...")
    raw = fetch_all(args.set)
    kept = [ev for ev in raw if is_target_sc(ev, args.set)]
    rows = [to_row(ev, args.set) for ev in kept]
    if args.country:
        rows = [r for r in rows if (r.get("country") or "").upper() == args.country.upper()]
    rows.sort(key=lambda r: (r.get("start_datetime") or "", r.get("country") or ""))

    # country breakdown
    from collections import Counter
    by_country = Counter((r.get("country") or "?") for r in rows)
    print(f"\n{len(rows)} {args.set} Set Championships "
          f"({len(raw)} upcoming Lorcana events scanned, {len(kept)} matched the local SC filter)")
    print("  by country:", dict(sorted(by_country.items(), key=lambda kv: -kv[1])))

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"  wrote {len(rows)} rows to {args.json}")

    if args.dry_run:
        print("  (dry run — not writing to Supabase)")
        for r in rows[:8]:
            print(f"    {r['start_datetime'][:10] if r['start_datetime'] else '????-??-??'}  "
                  f"{(r['name'] or '')[:42]:44}  {(r['store_name'] or '')[:22]:24}  {r.get('country')}")
        return

    upsert(rows)
    print(f"\nDone — {len(rows)} events in public.set_championships")


if __name__ == "__main__":
    main()
