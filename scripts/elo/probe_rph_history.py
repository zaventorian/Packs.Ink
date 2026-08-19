"""Probe the RPH events API for what it will tell us about PAST events.

    python scripts/elo/probe_rph_history.py

Read-only. Writes nothing, touches no database. ~20 requests, ~30 seconds.

Why this exists: tier tracking (Ravensburger Play Hub store tiers — Total
Events / Unique Fans / Event Tickets over the 4 most recent set seasons) needs
EVERY event a store has run, not the Set-Championship-shaped slice the Elo
pipeline ingests. Our two existing sources can't answer it:

  * elo_events        — curated Elo ingest. SCs plus whatever locals a season
                        spreadsheet happened to include. Not a complete log.
  * lorcana_events    — UPCOMING only, and pruned 30 days after the fact.

The discovery scripts only ever pull `display_statuses=upcoming`, and
discover_store_scs.py calls the name-relevance net "the only tractable filter
over the 115k-row past index" — which reads like a bare full sweep was tried
and found wanting, but doesn't say why. Everything below is the set of
questions whose answers decide whether the scraper is a 460-request nightly
sweep, a per-store query, or a date-sharded crawl.

Answer these, and the real scraper stops being guesswork.
"""
from __future__ import annotations
import json, sys, time, urllib.request, urllib.error
from urllib.parse import urlencode

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

API = "https://api.ravensburgerplay.com/api/v2/events/"
REG = "https://api.ravensburgerplay.com/api/v2/events/{eid}/registrations/"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
BASE = {"game_slug": "disney-lorcana", "display_statuses": "past"}


def get(url: str, timeout: int = 40):
    """Returns (json|None, status|None, error|None). Never raises — a probe that
    dies on the first 400 tells you nothing about the other twelve questions."""
    try:
        req = urllib.request.Request(url, headers=HDR)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "ignore"))
            return body, r.status, round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return None, e.code, None
    except Exception as e:
        return None, None, str(e)


def q(**extra):
    return API + "?" + urlencode(dict(BASE, **extra))


findings = {}
print("=" * 72)
print("RPH past-events probe")
print("=" * 72)

# 1 ─ Does the bare past index answer at all, and how big is it?
print("\n[1] Bare past index (no name filter)")
d, st, el = get(q(page_size=1))
if not d:
    print(f"    FAILED  status={st}  {el}")
    print("    Everything below depends on this. Stop here and report the status.")
    sys.exit(1)
total = d.get("count")
findings["total_past"] = total
print(f"    status={st}  elapsed={el}s  count={total:,}" if isinstance(total, int)
      else f"    status={st}  count={total!r}")

# 2 ─ Do list rows carry store + headcount, so a sweep needs no per-event fetch?
print("\n[2] Shape of a past-event list row")
d, st, el = get(q(page_size=1, ordering="-start_datetime"))
row = (d or {}).get("results") or []
if row:
    r0 = row[0]
    store = r0.get("store") or {}
    print(f"    keys: {', '.join(sorted(r0.keys()))}")
    print(f"    store.id={store.get('id')!r}  store.name={store.get('name')!r}")
    print(f"    registered_user_count={r0.get('registered_user_count')!r}  "
          f"capacity={r0.get('capacity')!r}")
    print(f"    start_datetime={r0.get('start_datetime')!r}  "
          f"gameplay_format={r0.get('gameplay_format')!r}")
    findings["row_has_store"] = store.get("id") is not None
    findings["row_has_count"] = r0.get("registered_user_count") is not None
    findings["sample_store_id"] = store.get("id")
    findings["sample_event_id"] = r0.get("id")
else:
    print("    no results returned — ordering param may be rejected")

# 3 ─ Is there a server-side store filter? This is the whole ballgame: if one
#     works we query ~30 stores directly instead of sweeping 100k+ rows.
print("\n[3] Server-side store filter (does count drop below the bare total?)")
sid = findings.get("sample_store_id")
if sid:
    for param in ("store", "store_id", "stores", "organization", "store__id", "venue"):
        d, st, el = get(q(page_size=1, **{param: sid}))
        c = (d or {}).get("count")
        if d is None:
            verdict = f"HTTP {st}"
        elif c == total:
            verdict = "ignored (count unchanged)"
        elif isinstance(c, int):
            verdict = f"*** WORKS *** count={c:,}"
            findings.setdefault("store_filter", param)
        else:
            verdict = f"count={c!r}"
        print(f"    {param:14} -> {verdict}")
        time.sleep(0.15)
else:
    print("    skipped — no sample store id from [2]")

# 4 ─ Date filters, so the sweep can be sharded (and re-run incrementally).
print("\n[4] Date-range filters")
for param in ("start_datetime_after", "start_after", "start_datetime__gte",
              "start_date_after", "min_start_datetime"):
    d, st, el = get(q(page_size=1, **{param: "2026-06-01T00:00:00Z"}))
    c = (d or {}).get("count")
    if d is None:
        verdict = f"HTTP {st}"
    elif c == total:
        verdict = "ignored (count unchanged)"
    else:
        verdict = f"*** WORKS *** count={c:,}"
        findings.setdefault("date_filter", param)
    print(f"    {param:22} -> {verdict}")
    time.sleep(0.15)

# 5 ─ How deep can we page? Most DRF-style APIs degrade or cap on deep offsets,
#     and that is the likeliest reason a bare sweep was called intractable.
print("\n[5] Pagination depth (page_size=250, ordering=id)")
for page in (1, 2, 10, 50, 200, 400):
    d, st, el = get(q(page_size=250, ordering="id", page=page), timeout=60)
    n = len((d or {}).get("results") or [])
    if d is None:
        print(f"    page {page:>4}: HTTP {st}  {el if isinstance(el, str) else ''}")
        findings.setdefault("page_cap", page)
        break
    print(f"    page {page:>4}: {n:>3} rows  elapsed={el}s")
    if n == 0:
        findings.setdefault("page_cap", page)
        break
    time.sleep(0.2)

# 6 ─ Unique Fans needs a roster per event. Does it exist for a PAST event?
print("\n[6] Registrations for a past event (the Unique Fans source)")
eid = findings.get("sample_event_id")
if eid:
    d, st, el = get(REG.format(eid=eid) + "?" + urlencode({"page_size": 100}))
    if d is None:
        print(f"    event {eid}: HTTP {st}  {el if isinstance(el, str) else ''}")
    else:
        res = d.get("results") or []
        print(f"    event {eid}: status={st} count={d.get('count')!r} rows={len(res)}")
        if res:
            print(f"    row keys: {', '.join(sorted(res[0].keys()))}")
            findings["registrations_ok"] = True
else:
    print("    skipped — no sample event id from [2]")

# ─ Verdict ────────────────────────────────────────────────────────────────
print("\n" + "=" * 72)
print("VERDICT")
print("=" * 72)
if findings.get("store_filter"):
    print(f"  Query per store via '{findings['store_filter']}=<store_id>'. ~30 stores,")
    print("  a handful of pages each. Cheapest option by far — build this.")
elif findings.get("date_filter"):
    print(f"  No store filter, but '{findings['date_filter']}' shards the sweep.")
    print("  Crawl the 4-set window in date slices, filter to our stores locally,")
    print("  and re-run incrementally from the last scraped date.")
else:
    print("  Neither a store nor a date filter. A full sweep of the past index is")
    print(f"  the only route ({findings.get('total_past', '?')} rows).")
    if findings.get("page_cap"):
        print(f"  ...and pagination stops at page {findings['page_cap']}, so a bare sweep")
        print("  CANNOT reach all of it. Needs another axis (ordering flips, name nets).")
print(f"\n  List rows carry store.id: {findings.get('row_has_store')}")
print(f"  List rows carry headcount: {findings.get('row_has_count')}   "
      "(Event Tickets without a per-event fetch)")
print(f"  Past-event registrations readable: {findings.get('registrations_ok', False)}   "
      "(Unique Fans)")
print("\n  Paste this whole output back and the scraper gets written against facts.")
