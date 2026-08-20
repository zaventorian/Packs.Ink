"""Read-only: show exactly who the Fans number is counting for one store.

    python scripts/elo/diagnose_store_fans.py --store "Dice Dojo"
    python scripts/elo/diagnose_store_fans.py --store "Dice Dojo" --sets 4 --list 40

Fans is "distinct people who played at this store in the window". If that number
looks too high, the ways it can be wrong are all visible here:

  * identity split — the same person counted twice because their rows carry no
    rph_user_id and their display name varies (or differs only by case/spacing).
  * guest noise — walk-in entries like "Guest 1"/"Guest 2" that are really the
    store's own placeholder rows, each becoming its own "person".
  * one-and-done tail — a large share of fans who appear at exactly one event is
    not itself a bug (a prerelease draws strangers), but it is what a bad key
    looks like, so it is broken out rather than buried in the total.

Prints the same person key the client uses (rphPersonKey), so what you see here
is what the tab counts.
"""
from __future__ import annotations
import argparse, json, sys, urllib.error, urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_wu_scs import SUPABASE_URL, SERVICE_KEY, FALLBACK_SETS  # noqa: E402
from report_store_tiers import window_start, PLAYED  # noqa: E402
from scrape_event_attendance import REG  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _get(path: str):
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/{path}",
        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "[]")


def _page(path: str):
    out, off = [], 0
    while True:
        page = _get(f"{path}&limit=1000&offset={off}")
        out.extend(page)
        if len(page) < 1000:
            return out
        off += 1000


def probe_event(eid: int) -> str:
    """Live RPH read for one event, reporting what actually came back. The
    scraper collapses every failure to an empty list, so this is the only way to
    tell an event nobody registered for from one whose roster we could not
    read — they are the same row in the scans table."""
    url = REG.format(eid=eid) + "?page_size=100&page=1"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0",
                                                   "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=45) as r:
            d = json.loads(r.read().decode("utf-8", "ignore"))
        n = len(d.get("results") or [])
        return f"HTTP 200, {n} registration(s){' MORE PAGES' if d.get('next') else ''}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} <- NOT readable"
    except Exception as e:
        return f"{type(e).__name__}: {e} <- NOT readable"


def person_key(a: dict) -> str:
    if a.get("rph_user_id") is not None:
        return "u:%s" % a["rph_user_id"]
    return "n:" + (a.get("best_identifier") or "").strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True, help="substring of the store name")
    ap.add_argument("--sets", type=int, default=4)
    ap.add_argument("--list", type=int, default=25, help="how many fans to print")
    ap.add_argument("--include-current", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="re-fetch each event's roster from RPH and print the HTTP status, "
                         "to tell 'genuinely empty' from 'we could not read it'")
    args = ap.parse_args()
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")

    since, until, set_names = window_start(args.sets, not args.include_current)
    print(f"Window: {since} -> {until or 'today'}  ({', '.join(set_names)})\n")

    end = f"&start_datetime=lt.{quote(until)}" if until else ""
    evs = _page(f"lorcana_events_history?select=event_id,store_id,store_name,kind,start_datetime"
                f"&start_datetime=gte.{quote(since)}{end}&order=event_id.asc")
    want = args.store.lower()
    mine = [e for e in evs if want in (e.get("store_name") or "").lower()]
    if not mine:
        raise SystemExit(f"no events matched a store containing {args.store!r}")
    by_store = defaultdict(list)
    for e in mine:
        by_store[(e.get("store_id"), e.get("store_name"))].append(e)

    for (sid, name), rows in sorted(by_store.items(), key=lambda kv: -len(kv[1])):
        ids = {e["event_id"] for e in rows}
        kinds = Counter(e.get("kind") for e in rows)
        print(f"=== {name}  (store_id {sid}) — {len(rows)} events  {dict(kinds)}")

        # Pull attendance for just this store's events, in chunks the URL can hold.
        played = []
        idlist = sorted(ids)
        for i in range(0, len(idlist), 150):
            chunk = ",".join(str(x) for x in idlist[i:i + 150])
            played += _page(f"rph_event_attendance?select=event_id,rph_user_id,best_identifier,is_guest"
                            f"&event_id=in.({chunk})&{PLAYED}&order=event_id.asc,best_identifier.asc")

        keys = Counter(person_key(a) for a in played)
        named = {}
        for a in played:
            named.setdefault(person_key(a), a.get("best_identifier"))
        n_null = sum(1 for a in played if a.get("rph_user_id") is None)
        n_guest = sum(1 for a in played if a.get("is_guest"))
        by_id = {a["rph_user_id"] for a in played if a.get("rph_user_id") is not None}
        by_name = {person_key(a) for a in played if a.get("rph_user_id") is None}
        once = sum(1 for k, c in keys.items() if c == 1)

        print(f"  tickets (played rows): {len(played)}")
        print(f"  FANS (distinct keys):  {len(keys)}")
        print(f"    ...of which keyed by account id: {len(by_id)}")
        print(f"    ...of which keyed by name only:  {len(by_name)}  "
              f"({n_null} rows have no rph_user_id, {n_guest} rows flagged is_guest)")
        print(f"  fans who played exactly ONE event: {once} of {len(keys)}"
              f" ({round(100*once/max(1,len(keys)))}%)")
        print(f"  fans who played 5+ events:         {sum(1 for c in keys.values() if c >= 5)}")

        # Near-duplicate names are what an identity split looks like.
        norm = defaultdict(set)
        for k, disp in named.items():
            n = "".join(ch for ch in (disp or "").lower() if ch.isalnum())
            if n:
                norm[n].add(k)
        dupes = {n: ks for n, ks in norm.items() if len(ks) > 1}
        print(f"  display names mapping to >1 person key: {len(dupes)}"
              + (f"  e.g. {list(dupes)[:5]}" if dupes else ""))

        if args.probe:
            scans = {}
            for i in range(0, len(idlist), 150):
                chunk = ",".join(str(x) for x in idlist[i:i + 150])
                for r in _page(f"rph_event_attendance_scans?select=event_id,row_count,player_count"
                               f"&event_id=in.({chunk})&order=event_id.asc"):
                    scans[r["event_id"]] = r
            print(f"\n  per-event probe (stored scan vs a live RPH read):")
            for e in sorted(rows, key=lambda x: x.get("start_datetime") or ""):
                sc = scans.get(e["event_id"])
                stored = (f"reg={sc['row_count']} played={sc['player_count']}"
                          if sc else "NEVER SCANNED")
                print(f"    {str(e.get('start_datetime') or '')[:10]}  {e['event_id']:>8}  "
                      f"{(e.get('kind') or '?'):<11} stored[{stored:<22}]  live[{probe_event(e['event_id'])}]")

        print(f"\n  top {args.list} by events played:")
        for k, c in keys.most_common(args.list):
            print(f"    {c:>3}  {named.get(k) or '?':<34} {k}")
        print()


if __name__ == "__main__":
    main()
