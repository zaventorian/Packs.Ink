"""Print the Ravensburger Play Hub tier metrics per store, from real data.

    python scripts/elo/report_store_tiers.py
    python scripts/elo/report_store_tiers.py --sets 4 --csv

Reads public.lorcana_events_history (populated by scrape_store_history.py and
kept current by discover_events.py's archive step). Read-only.

RPH scores tiers over "the four (4) most recent set seasons":

    Metric          Standard   Legendary
    Total Events        25         50
    Unique Fans         25         50
    Event Tickets      250        500
    Prerelease Events   all available sets

⚠️  The window is by DATE, not by set_name. Most events carry no set_name at all
    — a Tuesday league night belongs to no set — so grouping by set_name would
    silently drop the ~80% of activity that is exactly what these tiers reward.
    The window runs from the release date of the 4th-most-recent set to now, and
    every event inside it counts regardless of what set it names.

⚠️  Unique Fans is NOT computed here. It needs a per-event roster (distinct
    registrants), and we only scrape rosters for upcoming tracked SCs. Reporting
    a partial count as if it were the metric would show stores failing a bar they
    actually clear, so it prints n/a. `registered_user_count` gives Event Tickets
    honestly; Unique Fans needs the roster backfill.

⚠️  Event Tickets is a FLOOR. registered_user_count is frozen at the last time
    the upcoming feed listed the event — roughly the day before it ran — so
    day-of signups are missing.
"""
from __future__ import annotations
import argparse, datetime, json, sys, urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_wu_scs import SUPABASE_URL, SERVICE_KEY  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TIERS = [("Legendary", 50, 50, 500), ("Standard", 25, 25, 250)]


def _hdr():
    return {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
            "Accept": "application/json"}


def _get(path: str):
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", headers=_hdr())
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "[]")


def window_start(n_sets: int) -> tuple[str, list[str]]:
    """Release date of the Nth-most-recent already-released set."""
    today = datetime.date.today().isoformat()
    rows = _get(f"sets?select=name,released_at&released_at=lte.{today}"
                f"&order=released_at.desc&limit={n_sets}")
    if not rows:
        raise SystemExit("couldn't read released sets from the `sets` table")
    return rows[-1]["released_at"], [r["name"] for r in rows]


def fetch_events(since: str) -> list[dict]:
    out, offset = [], 0
    while True:
        page = _get(f"lorcana_events_history?select=event_id,store_id,store_name,kind,"
                    f"set_name,start_datetime,registered_user_count"
                    f"&start_datetime=gte.{quote(since)}"
                    f"&order=event_id.asc&limit=1000&offset={offset}")
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=4, help="how many recent set seasons (default 4)")
    ap.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    args = ap.parse_args()
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")

    since, set_names = window_start(args.sets)
    print(f"Window: {since} → today  ({args.sets} most recent sets: {', '.join(set_names)})\n")

    evs = fetch_events(since)
    stores: dict[int, dict] = {}
    for e in evs:
        sid = e.get("store_id")
        if sid is None:
            continue
        s = stores.setdefault(sid, {"name": e.get("store_name") or f"store {sid}",
                                    "events": 0, "tickets": 0, "pre": set(), "kinds": {}})
        s["events"] += 1
        s["tickets"] += e.get("registered_user_count") or 0
        s["kinds"][e.get("kind")] = s["kinds"].get(e.get("kind"), 0) + 1
        if e.get("kind") == "prerelease":
            s["pre"].add(e.get("set_name") or "?")

    def tier(s):
        for label, ev, _fans, tk in TIERS:
            # Unique Fans is unavailable, so this is an EVENTS+TICKETS verdict
            # only — flagged in the header so nobody reads it as the full bar.
            if s["events"] >= ev and s["tickets"] >= tk:
                return label
        return "Welcome"

    rows = sorted(stores.values(), key=lambda s: (-s["events"], -s["tickets"]))
    if args.csv:
        print("store,events,tickets,prerelease_sets,tier_partial")
        for s in rows:
            print(f'"{s["name"]}",{s["events"]},{s["tickets"]},{len(s["pre"])},{tier(s)}')
    else:
        print(f"{'Store':<44}{'Events':>7}{'Tickets':>9}{'Fans':>7}{'Pre':>5}  Tier*")
        print("-" * 82)
        for s in rows:
            print(f"{s['name'][:43]:<44}{s['events']:>7}{s['tickets']:>9}"
                  f"{'n/a':>7}{len(s['pre']):>5}  {tier(s)}")
        print("-" * 82)
        tot_e = sum(s["events"] for s in rows)
        tot_t = sum(s["tickets"] for s in rows)
        print(f"{len(rows)} stores{'':<36}{tot_e:>7}{tot_t:>9}")
        counts = {}
        for s in rows:
            counts[tier(s)] = counts.get(tier(s), 0) + 1
        print(f"\n  Tier* spread (events+tickets only): {counts}")
        print("  * Unique Fans is NOT in this verdict — see the module docstring.")
        print("    A store shown Legendary here still has to clear 50 unique fans")
        print("    and every available Prerelease.")


if __name__ == "__main__":
    main()
