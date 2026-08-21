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

Event Tickets and Unique Fans both come from public.rph_event_attendance
(scrape_event_attendance.py) — one row per person per event — filtered to people
who actually PLAYED, since both of RPH's metrics are about players. Tickets is
that row count; Fans is the distinct people behind it, so a regular who turns up
weekly is many tickets and one fan.

⚠️  registered_user_count is deliberately NOT used. It is pre-registration,
    frozen at the last time the upcoming feed listed the event, so it misses
    walk-ins and counts no-shows.

⚠️  Events whose roster hasn't been scraped yet are reported in a "gap" column
    rather than counted as zero-attendance. A store with a large gap is
    under-reported, not quiet.
"""
from __future__ import annotations
import argparse, datetime, json, sys, urllib.request
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from discover_wu_scs import SUPABASE_URL, SERVICE_KEY, FALLBACK_SETS  # noqa: E402

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


def window_start(n_sets: int, skip_current: bool = True) -> tuple[str, str | None, list[str]]:
    """The window for N set seasons: (start, end-exclusive, set names).

    The `sets` table also holds promo and special sets — "Format Coconut",
    "PD1", "Attack of the Vine! Promos" — which are not set seasons. Taking the
    newest N rows unfiltered collapsed the window from ~a year to ~a month and
    made every store look like it had failed. RPH's "four most recent set
    seasons" means the mainline releases, so filter to those.

    ⚠️ Skipping the current set has to move BOTH ends. Returning only a start
    and letting the query run to today counted the four complete seasons PLUS
    however much of the in-progress one has happened — so this report read 104
    fans for a store the tab showed 92 for, with both claiming the same window.
    The end bound is the skipped set's release date, which is exactly where the
    tab's season bucketing cuts.
    """
    today = datetime.date.today().isoformat()
    rows = _get(f"sets?select=name,released_at&released_at=lte.{today}"
                f"&order=released_at.desc&limit=200")
    mainline = [r for r in rows if r.get("name") in set(FALLBACK_SETS)]
    # Skip the set currently running unless asked not to: its season is still
    # filling up, so counting it drags every store down against bars written for
    # finished seasons. Matches the Stores tab's default window.
    until = None
    if skip_current and len(mainline) > n_sets:
        until = mainline[0]["released_at"]
        mainline = mainline[1:]
    mainline = mainline[:n_sets]
    if not mainline:
        raise SystemExit("couldn't read released mainline sets from the `sets` table")
    return mainline[-1]["released_at"], until, [r["name"] for r in mainline]


def tracked_store_ids() -> set[int]:
    """The stores we actually track. lorcana_events_history also holds every
    store worldwide (the archive step keeps whatever the global upcoming feed
    listed), so without this the report answers for ~3,000 shops instead of the
    ~100 in this scene."""
    rows = _get("elo_tracked_stores?select=store_id")
    return {r["store_id"] for r in rows if r.get("store_id") is not None}


def fetch_events(since: str, until: str | None = None) -> list[dict]:
    end = f"&start_datetime=lt.{quote(until)}" if until else ""
    out, offset = [], 0
    while True:
        page = _get(f"lorcana_events_history?select=event_id,store_id,store_name,city,state,kind,"
                    f"set_name,start_datetime"
                    f"&start_datetime=gte.{quote(since)}{end}"
                    f"&order=event_id.asc&limit=1000&offset={offset}")
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


# Who sat down, as opposed to who registered. Kept identical to the client's
# RPH_PLAYED_FILTER and to played() in scrape_event_attendance.py. The standing
# test is gte.0 rather than a not-null because PostgREST spells negation inside
# an or() group as a `not.` prefix on the column — a standing is a positive
# integer or absent, so this is the same set with no syntax to get wrong.
PLAYED = ("or=(final_place_in_standings.gte.0,matches_won.gt.0,"
          "matches_lost.gt.0,matches_drawn.gt.0)")


def _page_all(path: str) -> list[dict]:
    out, offset = [], 0
    while True:
        page = _get(f"{path}&limit=1000&offset={offset}")
        out.extend(page)
        if len(page) < 1000:
            return out
        offset += 1000


def fetch_fallback(event_ids: list[int]) -> list[dict]:
    """Every stored registration for events with no recorded result. Not every
    store runs pairings through RPH — Seven Out Cards took 19 registrations
    across 5 events and entered results for none — and the strict rule scores
    those shops 0 for a season they demonstrably ran. Kept identical to the
    client's second pass in fetchEloStoreActivity."""
    out: list[dict] = []
    for i in range(0, len(event_ids), 150):
        chunk = ",".join(str(x) for x in event_ids[i:i + 150])
        out += _page_all(f"rph_event_attendance?select=event_id,rph_user_id,best_identifier,"
                         f"registration_status&event_id=in.({chunk})"
                         f"&order=event_id.asc,best_identifier.asc")
    return out


def complete_reg(a: dict) -> bool:
    st = (a.get("registration_status") or "").upper()
    return not st or st == "COMPLETE"


def fetch_attendance() -> tuple[list[dict], set[int], dict[int, tuple[int, int]]]:
    played = _page_all(f"rph_event_attendance?select=event_id,rph_user_id,best_identifier"
                       f"&{PLAYED}&order=event_id.asc,best_identifier.asc")
    scans = _page_all("rph_event_attendance_scans?select=event_id,row_count,player_count"
                      "&order=event_id.asc")
    # row_count = everyone who registered; player_count = those with a result.
    # An event with registrations and no results at all is one the store never
    # ran through RPH's pairing system, which is NOT the same as a quiet night —
    # see the Dark column.
    counts = {r["event_id"]: (r.get("row_count") or 0, r.get("player_count") or 0)
              for r in scans}
    return played, set(counts), counts


def person_key(a: dict) -> str:
    """rph_user_id is the stable account id and the right thing to count on;
    guests come through without one, so the display name stands in."""
    if a.get("rph_user_id") is not None:
        return "u:%s" % a["rph_user_id"]
    return "n:" + (a.get("best_identifier") or "").strip().lower()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", type=int, default=4, help="how many recent set seasons (default 4)")
    ap.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    ap.add_argument("--include-current", action="store_true",
                    help="also count the set currently running (its season is incomplete)")
    ap.add_argument("--all-stores", action="store_true",
                    help="every store in the archive, not just tracked ones (~3k rows)")
    args = ap.parse_args()
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set")

    since, until, set_names = window_start(args.sets, not args.include_current)
    print(f"Window: {since} → {until or 'today'}  "
          f"({args.sets} most recent sets: {', '.join(set_names)})\n")

    evs = fetch_events(since, until)
    played, scanned, counts = fetch_attendance()
    tracked = None if args.all_stores else tracked_store_ids()
    if tracked is not None:
        print(f"Scoped to {len(tracked)} tracked stores (--all-stores for everything)\n")
    stores: dict[int, dict] = {}
    at_store: dict[int, dict] = {}      # event_id → its store bucket
    for e in evs:
        sid = e.get("store_id")
        if sid is None:
            continue
        if tracked is not None and sid not in tracked:
            continue
        # Keyed on store_id: branches of a chain share a name and are separate
        # stores for tiering, so the location is part of the identity.
        label = e.get("store_name") or f"store {sid}"
        loc = ", ".join(x for x in (e.get("city"), e.get("state")) if x)
        s = stores.setdefault(sid, {"name": f"{label} ({loc})" if loc else label,
                                    "events": 0, "tickets": 0, "gap": 0, "unrecorded": 0,
                                    "regs": 0, "dark": 0,
                                    "fans": set(), "pre": set(), "kinds": {}})
        s["events"] += 1
        if e["event_id"] not in scanned:
            s["gap"] += 1
        n_reg, n_res = counts.get(e["event_id"], (0, 0))
        s["regs"] += n_reg
        if n_reg and not n_res:
            s["dark"] += 1
        at_store[e["event_id"]] = s
        s["kinds"][e.get("kind")] = s["kinds"].get(e.get("kind"), 0) + 1
        if e.get("kind") == "prerelease":
            s["pre"].add(e.get("set_name") or "?")

    # One pass for both metrics: each row is one person at one event, so it is a
    # ticket, and its person key joins the store's fan set.
    with_play = set()
    for a in played:
        with_play.add(a["event_id"])
        s = at_store.get(a["event_id"])
        if s is None:
            continue
        s["tickets"] += 1
        s["fans"].add(person_key(a))

    # Events with no result at all fall back to their registrations, guarded on
    # with_play so a row can never be counted by both passes.
    no_result = [eid for eid in at_store if eid in scanned and eid not in with_play]
    for a in fetch_fallback(no_result):
        if a["event_id"] in with_play or not complete_reg(a):
            continue
        s = at_store.get(a["event_id"])
        if s is None:
            continue
        s["tickets"] += 1
        s["unrecorded"] += 1
        s["fans"].add(person_key(a))

    def tier(s):
        for label, ev, fans, tk in TIERS:
            if s["events"] >= ev and len(s["fans"]) >= fans and s["tickets"] >= tk:
                return label
        return "Welcome"

    rows = sorted(stores.values(), key=lambda s: (-s["events"], -s["tickets"]))
    if args.csv:
        print("store,events,tickets,unique_fans,registrations,dark_events,"
              "unscraped_events,prerelease_sets,tier_partial")
        for s in rows:
            print(f'"{s["name"]}",{s["events"]},{s["tickets"]},{len(s["fans"])},'
                  f'{s["regs"]},{s["dark"]},{s["gap"]},{len(s["pre"])},{tier(s)}')
    else:
        print(f"{'Store':<44}{'Events':>7}{'Tickets':>9}{'Fans':>7}"
              f"{'Reg':>7}{'Dark':>6}{'Gap':>5}{'Pre':>5}  Tier*")
        print("-" * 98)
        for s in rows:
            print(f"{s['name'][:43]:<44}{s['events']:>7}{s['tickets']:>9}"
                  f"{len(s['fans']):>7}{s['regs']:>7}{s['dark']:>6}"
                  f"{s['gap']:>5}{len(s['pre']):>5}  {tier(s)}")
        print("-" * 98)
        tot_e = sum(s["events"] for s in rows)
        tot_t = sum(s["tickets"] for s in rows)
        tot_r = sum(s["regs"] for s in rows)
        tot_d = sum(s["dark"] for s in rows)
        tot_g = sum(s["gap"] for s in rows)
        print(f"{len(rows)} stores{'':<36}{tot_e:>7}{tot_t:>9}{'':>7}"
              f"{tot_r:>7}{tot_d:>6}{tot_g:>5}")
        print(f"\n  Reg  = everyone who registered. Tickets counts only those with a")
        print( "         recorded result, so Reg - Tickets is no-shows PLUS players at")
        print( "         events the store never ran through RPH's pairing system.")
        print(f"  Dark = events with registrations but NO results at all "
              f"({tot_d} of {tot_e}). Those events' registrations ARE")
        print( "         counted toward Tickets and Fans, since the store never recorded who")
        print( "         played and a real event is not an empty one — so they include no-shows.")
        tot_u = sum(s["unrecorded"] for s in rows)
        if tot_u:
            print(f"  {tot_u} of {tot_t} tickets came in that way.")
        counts = {}
        for s in rows:
            counts[tier(s)] = counts.get(tier(s), 0) + 1
        print(f"\n  Tier* spread: {counts}")
        print("  * Events, Fans and Tickets are all scored. The Prerelease requirement")
        print("    is not — Pre counts sets this store ran one for, but not which sets")
        print("    RPH considered available to it.")
        if tot_g:
            print(f"  Gap = events with no roster scraped yet ({tot_g} of {tot_e}); their")
            print("    players are missing from Tickets and Fans.")


if __name__ == "__main__":
    main()
