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

ALL-SETS MODE (`--all-sets`, what the daily workflow runs): instead of scoping
to one set, capture EVERY upcoming Set Championship and auto-detect which set
each belongs to by matching its title against the canonical Lorcana set names —
pulled live from the Supabase `sets` table (kept current by the Lorcast loader).
So a new set is picked up automatically once it lands in `sets`; no edit here.
SCs whose title matches no known set are skipped and logged (so the displayed
`<set> Set Championship` label never goes blank/garbled) and get swept up on a
later run once the set is in the DB.

Usage:
    python discover_wu_scs.py --all-sets               # every set -> Supabase (daily job)
    python discover_wu_scs.py                          # Wilds Unknown, all countries
    python discover_wu_scs.py --set "Reign of Jafar"
    python discover_wu_scs.py --country US             # client-side country filter
    python discover_wu_scs.py --all-sets --dry-run --json out.json
"""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.request, urllib.error
from pathlib import Path
from urllib.parse import urlencode

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

# Windows consoles default to cp1252, which can't encode some of our progress
# glyphs (—, …) and would crash on print(). Force UTF-8 (no-op on Linux CI).
try:
    sys.stdout.reconfigure(encoding="utf-8")
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


def fetch_all(name_net: str | None = None) -> list[dict]:
    """Collect EVERY upcoming Lorcana event, robustly.

    We deliberately do not filter by name on the server (see the module
    docstring) — the SC gating happens locally. We union several full passes with
    different orderings so pagination drift on the live index can't silently skip
    events; an optional `name_net` relevance pass is folded in as a cheap
    high-recall safety net (e.g. "<set> Set Championship" for single-set mode, or
    "Set Championship" for all-sets mode). Dedup is by event id."""
    union: dict[int, dict] = {}
    passes = [
        {"ordering": "id"},               # stable ascending keyset
        {"ordering": "-id"},              # opposite direction — different drift
        {"ordering": "start_datetime"},   # soonest-first ordering
    ]
    if name_net:
        # cheap relevance net (a few pages) — drift insurance, not the gate:
        passes.append({"ordering": "start_datetime", "name": name_net})
    for p in passes:
        added = fetch_pages(p, union)
        print(f"    +{added} new from this pass — {len(union)} total unique")
    return list(union.values())


# Side events that share "set championship" wording but aren't the main SC.
SIDE_PATTERNS = ("prerelease", "pre-release", "release party",
                 "draft", "sealed", "trove", "league night")

# Resilience-only fallback if the Supabase `sets` query fails or a brand-new
# set's SCs appear before Lorcast adds it to `sets`. The DB is the source of
# truth — this list need not be exhaustive or perfectly maintained; unmatched
# sets are skipped+logged, not silently mis-stored. "Attack of the Vines" is
# pre-seeded as the known-next set so its SCs are caught the moment they post.
FALLBACK_SETS = (
    "The First Chapter", "Rise of the Floodborn", "Into the Inklands",
    "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
    "Reign of Jafar", "Fabled", "Whispers in the Well", "Winterspell",
    "Wilds Unknown", "Attack of the Vines",
)


def is_sc(ev: dict) -> bool:
    """True if this looks like a real Set Championship (any set), not a side event."""
    name = (ev.get("name") or "").lower()
    if "set championship" not in name:
        return False
    if any(k in name for k in SIDE_PATTERNS):
        return False
    return True


def is_target_sc(ev: dict, set_name: str) -> bool:
    # scope to the requested set (the API name filter is loose; pin it here)
    return is_sc(ev) and set_name.lower() in (ev.get("name") or "").lower()


def _norm(s: str) -> str:
    """Lowercase, unify apostrophes->none, collapse whitespace — so 'Ursula's
    Return' / 'Ursula’s Return' / 'Ursulas Return' all compare equal."""
    s = (s or "").lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    s = s.replace("'", "")
    return re.sub(r"\s+", " ", s).strip()


def fetch_set_names() -> list[dict]:
    """Canonical Lorcana set names, newest-first by normalized length so longer
    names win over any shorter name they contain. Source of truth is the
    Supabase `sets` table (auto-updated by the Lorcast loader); FALLBACK_SETS is
    unioned in for resilience. Returns dicts {canonical, norm}."""
    names: set[str] = set(FALLBACK_SETS)
    if SUPABASE_URL and SERVICE_KEY:
        try:
            url = f"{SUPABASE_URL}/rest/v1/sets?select=name"
            req = urllib.request.Request(url, headers={
                "apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as r:
                for row in json.loads(r.read().decode("utf-8", "ignore")):
                    if row.get("name"):
                        names.add(row["name"])
            print(f"  set list: {len(names)} names (Supabase sets + fallback)")
        except Exception as e:
            print(f"  ! couldn't read `sets` table ({e}); using fallback list only")
    else:
        print("  ! no Supabase creds; using fallback set list only")
    out = [{"canonical": n, "norm": _norm(n)} for n in names if _norm(n)]
    out.sort(key=lambda d: len(d["norm"]), reverse=True)
    return out


def detect_set(ev_name: str, sets_sorted: list[dict]) -> str | None:
    """Which canonical set does this SC title name? Longest-normalized match wins."""
    nt = _norm(ev_name)
    for d in sets_sorted:
        if d["norm"] in nt:
            return d["canonical"]
    return None


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
    from collections import Counter
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-sets", action="store_true",
                    help="capture every set's SCs, auto-detecting the set per event (daily-job mode)")
    ap.add_argument("--set", default="Wilds Unknown", help="set to scope SCs to (ignored with --all-sets)")
    ap.add_argument("--country", default=None, help="optional client-side ISO country filter, e.g. US")
    ap.add_argument("--json", default=None, help="also dump the rows to this path")
    ap.add_argument("--dry-run", action="store_true", help="don't write to Supabase")
    args = ap.parse_args()

    if args.all_sets:
        print("Pulling ALL upcoming Lorcana events from RPH (no name filter), "
              "auto-detecting each Set Championship's set...")
        sets_sorted = fetch_set_names()
        raw = fetch_all(name_net="Set Championship")
        scs = [ev for ev in raw if is_sc(ev)]
        rows, unknown = [], []
        for ev in scs:
            s = detect_set(ev.get("name") or "", sets_sorted)
            (rows.append(to_row(ev, s)) if s else unknown.append(ev))
        label = "all-sets"
        if unknown:
            print(f"\n  [!] {len(unknown)} SC(s) matched no known set - SKIPPED (add the set "
                  f"to the `sets` table / FALLBACK_SETS, or wait for the Lorcast refresh, "
                  f"then re-run):")
            for ev in unknown[:25]:
                print(f"      [{ev.get('id')}] {(ev.get('name') or '')[:72]}")
            if len(unknown) > 25:
                print(f"      ... and {len(unknown) - 25} more")
    else:
        print(f"Pulling ALL upcoming Lorcana events from RPH (no name filter) "
              f"to find '{args.set}' Set Championships locally...")
        raw = fetch_all(name_net=f"{args.set} Set Championship")
        scs = [ev for ev in raw if is_target_sc(ev, args.set)]
        rows = [to_row(ev, args.set) for ev in scs]
        label = args.set

    if args.country:
        rows = [r for r in rows if (r.get("country") or "").upper() == args.country.upper()]
    rows.sort(key=lambda r: (r.get("set_name") or "", r.get("start_datetime") or "", r.get("country") or ""))

    by_country = Counter((r.get("country") or "?") for r in rows)
    print(f"\n{len(rows)} {label} Set Championships "
          f"({len(raw)} upcoming Lorcana events scanned, {len(scs)} SC events found)")
    if args.all_sets:
        by_set = Counter((r.get("set_name") or "?") for r in rows)
        print("  by set:", dict(sorted(by_set.items(), key=lambda kv: -kv[1])))
    print("  by country:", dict(sorted(by_country.items(), key=lambda kv: -kv[1])))

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"  wrote {len(rows)} rows to {args.json}")

    if args.dry_run:
        print("  (dry run — not writing to Supabase)")
        for r in rows[:8]:
            print(f"    {r['start_datetime'][:10] if r['start_datetime'] else '????-??-??'}  "
                  f"{(r.get('set_name') or '')[:18]:20}  {(r['name'] or '')[:38]:40}  "
                  f"{(r['store_name'] or '')[:20]:22}  {r.get('country')}")
        return

    upsert(rows)
    print(f"\nDone — {len(rows)} events in public.set_championships")


if __name__ == "__main__":
    main()
