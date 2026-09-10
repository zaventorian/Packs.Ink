"""Find Set Championships at stores we ALREADY count but haven't ingested for a
given set — so a store with a track record never silently drops off the board
because a hand-curated season spreadsheet missed it.

Why this exists: the RPH Elo ingest is spreadsheet-driven (ingest.py --xlsx).
When a season sheet omits a store that ran an SC, that store vanishes from the
board for that set. Coverage regressed badly for Winterspell (77 stores) and
Wilds Unknown (57) vs Whispers (82). This script makes ingestion store-driven:

  1. Derive the set of RPH store_ids we've EVER counted, from the events already
     in our local DB (each rph event -> its store.id via the events meta API).
     A physical store has a stable store_id, so this is its durable identity.
  2. For each target set, pull that set's SCs two ways and union them by id:
     the name-relevance "net" (the only tractable filter over the 115k-row past
     index) across a few spellings + orderings, and each tracked store's OWN
     event feed across that set's season. The nets can't see an SC whose title
     never says "Set Championship" or names no set; a store's feed can. Gate on
     is_sc + sc_set_for locally.
  3. Keep SCs whose store.id is in our tracked set and whose event_id we haven't
     already ingested. Those are real SCs at stores we count, currently missing.

Reads Supabase only for set names and release dates. Without --ingest it is
read-only: it prints the candidates and (optionally) a JSON + the ingest.py
command to pull them by hand. With --ingest (how the weekly refresh runs it) it
writes them to the local DB. Scope is never widened either way — a candidate has
to sit at a store_id we already count (minus EXCLUDED_STORE_IDS, and not counting
the hand-added one-offs in ONE_OFF_EVENT_IDS), so a store legitimately skipping a
set is still a real outcome.

Usage:
    python discover_store_scs.py --sets "Winterspell" "Wilds Unknown"
    python discover_store_scs.py --sets "Wilds Unknown" --json wu_missing.json
    python discover_store_scs.py --sets "Winterspell" --refresh-store-ids
    python discover_store_scs.py --ingest --season-label "Attack of the Vine! Fall 2026"
"""
from __future__ import annotations
import argparse, datetime, json, sqlite3, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode

import discover_wu_scs as d  # reuse http_json, is_sc, detect_set, set-name loading
import ingest as ing         # reuse ingest_event for --ingest mode

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent
DB = HERE / "lorcana_elo.db"
STORE_ID_CACHE = HERE / "_store_id_cache.json"
META = "https://api.ravensburgerplay.com/api/v2/events/{eid}/"
API = d.API

# RPH store_ids that are OUT OF SCOPE for this (Chicagoland) board and must never
# be ingested — past, present, or future — even though they ran Lorcana SCs.
# These are central-Indiana stores, not Chicagoland. Their existing events are
# flagged is_ignored=1 (so the leaderboard/standings/summary already exclude
# them); this set stops the store-driven discovery from re-adding NEW events for
# them on a future set. (tracked_store_ids also derives only from non-ignored
# events, so a fully-dropped store falls out of scope on its own — this is the
# explicit belt-and-suspenders guard + the documented record of the decision.)
EXCLUDED_STORE_IDS = {
    2237,   # Good Games - Indianapolis (Indianapolis, IN)
    28480,  # Storming Good Games (Greencastle, IN)
}

# Hand-added one-offs: the event counts, its store does not become one we track.
# Shared with sync_elo_tracked_stores, which derives the SAME scope from the
# Supabase mirror — see elo_scope.py for why it has to be one list.
from elo_scope import ONE_OFF_EVENT_IDS  # noqa: E402


def tracked_store_ids(refresh: bool) -> tuple[set[int], dict[int, set[str]]]:
    """Map every rph event we've ingested -> its RPH store.id. Returns the set of
    store_ids we count + a store_id -> {our store names} map for labeling.
    Cached to disk (event_id -> store_id) so re-runs don't re-fetch ~600 events."""
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    # Only NON-ignored events define "stores we count". A store whose every event
    # is is_ignored=1 (dropped from scope) falls out of the tracked set, so we
    # never re-discover SCs for it. is_ignored is the single source of truth for
    # scope; this keeps discovery honoring it automatically.
    rows = conn.execute(
        "SELECT event_id, store FROM events WHERE platform='rph' AND is_ignored=0").fetchall()
    conn.close()
    # A hand-added one-off confers no scope on its store (see ONE_OFF_EVENT_IDS).
    rows = [r for r in rows if r["event_id"] not in ONE_OFF_EVENT_IDS]
    cache: dict[str, int | None] = {}
    if STORE_ID_CACHE.exists() and not refresh:
        cache = json.loads(STORE_ID_CACHE.read_text())

    todo = [r["event_id"] for r in rows if str(r["event_id"]) not in cache]
    if todo:
        print(f"  resolving store_id for {len(todo)} rph events (cached {len(cache)})...")

        def fetch(eid):
            # ok=False means a transient fetch error — do NOT cache it, or the
            # event is never retried and its store silently drops off the board.
            try:
                m = d.http_json(META.format(eid=eid))
                return eid, (m.get("store") or {}).get("id"), True
            except Exception:
                return eid, None, False

        with ThreadPoolExecutor(max_workers=8) as ex:
            for i, (eid, sid, ok) in enumerate(
                    (f.result() for f in as_completed([ex.submit(fetch, e) for e in todo])), 1):
                if ok:
                    cache[str(eid)] = sid
                if i % 100 == 0:
                    print(f"    {i}/{len(todo)}")
        STORE_ID_CACHE.write_text(json.dumps(cache))

    ids: set[int] = set()
    names: dict[int, set[str]] = {}
    by_event = {r["event_id"]: r["store"] for r in rows}
    for eid, store in by_event.items():
        sid = cache.get(str(eid))
        if sid is None:
            continue
        ids.add(sid)
        names.setdefault(sid, set()).add(store or "?")
    return ids, names


def ingested_event_ids() -> set[int]:
    conn = sqlite3.connect(DB)
    ids = {r[0] for r in conn.execute(
        "SELECT event_id FROM events WHERE platform='rph'")}
    conn.close()
    return ids


def season_label_for(set_name: str) -> str | None:
    """The full season label this set already uses in our DB (e.g. set 'Wilds
    Unknown' -> 'Wilds Unknown Summer 2026'). None if the set has no events yet,
    in which case the caller seeds one with season_label_from_date()."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT season FROM events WHERE season LIKE ? AND season IS NOT NULL "
        "GROUP BY season ORDER BY COUNT(*) DESC LIMIT 1", (set_name + "%",)).fetchone()
    conn.close()
    return row[0] if row else None


def season_label_from_date(set_name: str, iso_date: str) -> str:
    """Name a brand-new set's season from the first SC we're about to ingest —
    "<set> <northern-hemisphere season> <year>", the shape every existing label
    already has (Fabled Fall 2025, Wilds Unknown Summer 2026).

    Only the SET half is load-bearing: the UI's eloSeasonSetLabel() longest-prefix
    matches it against MAINLINE_SETS to head the Stores columns, and the stores
    tab assigns seasons by DATE rather than by this string. The tag is display
    text on the season chip, so deriving it is safe — and deriving beats the old
    behaviour of refusing to ingest a whole set for want of a display string.
    Pass --season-label to name it by hand."""
    d0 = datetime.date.fromisoformat(iso_date[:10])
    m = d0.month
    if m in (3, 4, 5):
        tag = f"Spring {d0.year}"
    elif m in (6, 7, 8):
        tag = f"Summer {d0.year}"
    elif m in (9, 10, 11):
        tag = f"Fall {d0.year}"
    else:
        # A December window belongs to the winter that ENDS the next year, which
        # is how the existing "Azurite Sea Winter 2025" label reads.
        tag = f"Winter {d0.year + 1 if m == 12 else d0.year}"
    return f"{set_name} {tag}"


def sibling_location(store_name: str) -> str | None:
    """Most-common location among that store's existing events, for nicer display
    (RPH store records frequently have null city/state)."""
    if not store_name:
        return None
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT location FROM events WHERE store=? AND location IS NOT NULL "
        "GROUP BY location ORDER BY COUNT(*) DESC LIMIT 1", (store_name,)).fetchone()
    conn.close()
    return row[0] if row else None


def name_nets(set_name: str) -> list[str]:
    """Spellings to throw at RPH's name-relevance filter, which drops ~4% on any
    single phrasing — and a dropped SC is a store falling off the board. Derived
    per set rather than kept in a map, so a set rotation needs no edit here."""
    return [f"{set_name} Set Championship",
            f"{set_name} - Set Championship",
            f"Set Championship {set_name}"]


def fetch_set_releases() -> list[tuple[str, datetime.date]]:
    """Booster sets with a release date, oldest first. A promo set's code isn't
    numeric, and it has no Set Championship season of its own."""
    if not (d.SUPABASE_URL and d.SERVICE_KEY):
        return []
    try:
        req = urllib.request.Request(
            f"{d.SUPABASE_URL}/rest/v1/sets?select=name,code,released_at"
            f"&order=released_at.asc.nullslast",
            headers={"apikey": d.SERVICE_KEY, "Authorization": f"Bearer {d.SERVICE_KEY}",
                     "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            rows = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"  ! couldn't read set release dates ({e}); store feeds won't be pulled")
        return []
    out: list[tuple[str, datetime.date]] = []
    for row in rows:
        released = (row.get("released_at") or "")[:10]
        if not (str(row.get("code") or "").isdigit() and row.get("name") and released):
            continue
        try:
            out.append((row["name"], datetime.date.fromisoformat(released)))
        except ValueError:
            continue
    return out


def set_window(set_name: str, releases) -> tuple[datetime.date, datetime.date | None] | None:
    """[this set's release, the next booster set's release) — the only dates a Set
    Championship for it can fall in. None if the set isn't dated."""
    for i, (name, released) in enumerate(releases):
        if name == set_name:
            return released, (releases[i + 1][1] if i + 1 < len(releases) else None)
    return None


def sc_set_for(ev: dict, window, set_name: str, sets_sorted, aliases) -> str | None:
    """The set an SC belongs to. A title that names a set decides it. A title that
    names none ("Twisted - Lorcana Set Champs") is placed by DATE inside the set's
    season window — the rule the Stores tab applies to every event, and the one
    discover_events.py already applies to an upcoming SC."""
    named = d.detect_set(ev.get("name") or "", sets_sorted, aliases)
    if named or not window:
        return named
    day = (ev.get("start_datetime") or "")[:10]
    start, end = window
    if day and start.isoformat() <= day and (end is None or day < end.isoformat()):
        return set_name
    return None


def pull_set_scs(set_name: str, nets: list[str], sets_sorted, aliases,
                 window=None) -> dict[int, dict]:
    """Union name-net pulls (past + upcoming) across orderings; keep SC events
    that belong to set_name. Keyed by event id."""
    union: dict[int, dict] = {}
    base = {"game_slug": "disney-lorcana", "page_size": 250}
    combos = []
    for status in ("past", "upcoming"):
        for net in nets:
            for ordering in ("-start_datetime", "start_datetime"):
                combos.append({"display_statuses": status, "name": net, "ordering": ordering})
    for extra in combos:
        page = 1
        while True:
            params = dict(base, **extra, page=page)
            try:
                doc = d.http_json(API + "?" + urlencode(params))
            except Exception as e:
                print(f"  ! pull failed ({extra.get('name')}/{extra.get('display_statuses')} p{page}): {e}")
                break
            results = doc.get("results") or []
            for ev in results:
                if ev["id"] in union:
                    continue
                if not d.is_sc(ev):
                    continue
                if sc_set_for(ev, window, set_name, sets_sorted, aliases) != set_name:
                    continue
                union[ev["id"]] = ev
            if not doc.get("next") or page >= 15:  # name net is small; cap pages
                break
            page += 1
            time.sleep(0.1)
    return union


def pull_store_scs(store_ids, set_name: str, window, sets_sorted, aliases) -> dict[int, dict]:
    """Every SC for set_name in each tracked store's own event feed.

    The name nets are a relevance search, and a title like "Twisted - Lorcana Set
    Champs" never comes back from them: it doesn't say "Set Championship" and names
    no set. Those titles are not rare — 26 of the 470 SCs at tracked stores since
    Reign of Jafar read like that, and 5 of the 6 played since Winterspell never
    reached the board. A store's own feed has no such blind spot and is cheap, a
    page or two per store for one season. Both store-filter spellings are unioned
    and store.id is re-checked locally, as in scrape_store_history.py: RPH's two
    store filters disagree."""
    if not window:
        return {}
    start, end = window
    season_over = end is not None and end <= datetime.date.today()

    def one(sid: int) -> dict[int, dict]:
        found: dict[int, dict] = {}
        for status in ("past", "upcoming"):
            if status == "upcoming" and season_over:
                continue
            for param in ("store", "store_id"):
                page = 1
                while True:
                    params = {"game_slug": "disney-lorcana", "display_statuses": status,
                              param: sid, "page_size": 250, "ordering": "id", "page": page}
                    if status == "past":
                        params["start_date_after"] = start.isoformat()
                    try:
                        doc = d.http_json(API + "?" + urlencode(params))
                    except Exception as e:
                        print(f"  ! store {sid} {status} feed failed (p{page}): {e}")
                        break
                    results = doc.get("results") or []
                    for ev in results:
                        st = ev.get("store") or {}
                        if not isinstance(st, dict) or st.get("id") != sid:
                            continue
                        if d.is_sc(ev) and sc_set_for(ev, window, set_name, sets_sorted, aliases) == set_name:
                            found[ev["id"]] = ev
                    if not doc.get("next") or not results or page >= 20:
                        break
                    page += 1
        return found

    union: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for got in ex.map(one, sorted(store_ids)):
            union.update(got)
    return union


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", nargs="+", default=None,
                    help='set names to backfill; defaults to the current set. '
                         'e.g. --sets "Winterspell" "Wilds Unknown"')
    ap.add_argument("--ingest", action="store_true",
                    help="ingest found candidates into the local DB (store-driven backfill). "
                         "Without this, the script is read-only and just reports.")
    ap.add_argument("--json", default=None, help="dump candidate rows to this path")
    ap.add_argument("--refresh-store-ids", action="store_true",
                    help="re-fetch every event's store_id (ignore the disk cache)")
    ap.add_argument("--season-label", default=None,
                    help='name the season for a set we have no events for yet, e.g. '
                         '"Attack of the Vine! Fall 2026". Only used when seeding a '
                         'brand-new set; derived from the first SC date if omitted.')
    args = ap.parse_args()

    if not args.sets:
        args.sets = [d.fetch_current_set()]
        print(f"  no --sets given; defaulting to current set: {args.sets[0]!r}")

    print("Deriving the RPH store_ids we already count...")
    tracked, store_names = tracked_store_ids(args.refresh_store_ids)
    have = ingested_event_ids()
    print(f"  {len(tracked)} distinct tracked store_ids; {len(have)} rph events already ingested\n")

    sets_sorted = d.fetch_set_names()
    aliases = d.build_aliases(sets_sorted)
    releases = fetch_set_releases()
    feed_stores = tracked - EXCLUDED_STORE_IDS

    all_candidates = []
    for set_name in args.sets:
        nets = name_nets(set_name)
        window = set_window(set_name, releases)
        print(f"Pulling '{set_name}' SCs from RPH (name nets: {len(nets)})...")
        scs = pull_set_scs(set_name, nets, sets_sorted, aliases, window=window)
        if window:
            fed = pull_store_scs(feed_stores, set_name, window, sets_sorted, aliases)
            extra = {k: v for k, v in fed.items() if k not in scs}
            scs.update(extra)
            print(f"  +{len(extra)} more from {len(feed_stores)} tracked stores' own feeds "
                  f"(titles the name nets can't match)")
        else:
            print(f"  ! no release date for {set_name!r} in `sets`; store feeds not pulled")
        cands = []
        for ev in scs.values():
            sid = (ev.get("store") or {}).get("id")
            if sid in EXCLUDED_STORE_IDS:
                continue  # out-of-scope store — never ingest (see EXCLUDED_STORE_IDS)
            if sid not in tracked:
                continue
            if ev["id"] in have:
                continue
            cands.append(ev)
        cands.sort(key=lambda e: (e.get("start_datetime") or ""))
        print(f"  {len(scs)} {set_name} SCs found; {len(cands)} at tracked stores & not yet ingested:\n")
        label = season_label_for(set_name) if args.ingest else None
        if args.ingest and not label and cands:
            # First SCs of a new set. This used to skip the whole set for want of
            # a season label, which is how a set rotation silently froze the board:
            # the weekly refresh stayed green while ingesting nothing. Seeding here
            # widens nothing — candidates are already gated on tracked store_ids.
            label = args.season_label or season_label_from_date(
                set_name, cands[0].get("start_datetime") or "")
            print(f"  * no events for {set_name!r} yet — seeding the season as {label!r}"
                  f"{'' if args.season_label else ' (derived; override with --season-label)'}")
        elif args.ingest and args.season_label and label != args.season_label:
            print(f"  ! --season-label {args.season_label!r} ignored; {set_name!r} already "
                  f"uses {label!r} in the DB")
        for ev in cands:
            st = ev.get("store") or {}
            sid = st.get("id")
            ours_name = (sorted(store_names.get(sid, set()))[:1] or [st.get("name")])[0]
            print(f"    eid={ev['id']:<8} {(ev.get('start_datetime') or '')[:10]}  "
                  f"{ev.get('display_status'):9} {(ev.get('name') or '')[:46]:48} "
                  f"[store {sid}: {ours_name}]")
            all_candidates.append({
                "set": set_name, "event_id": ev["id"], "store_id": sid,
                "store_name_rph": st.get("name"),
                "store_name_ours": sorted(store_names.get(sid, set())),
                "date": (ev.get("start_datetime") or "")[:10],
                "name": ev.get("name"), "status": ev.get("display_status"),
                "registered": ev.get("registered_user_count"),
            })
            if args.ingest and label:
                eid, status, msg = ing.ingest_event(
                    ev["id"], store=ours_name,
                    location=sibling_location(ours_name), season=label)
                print(f"        -> {status.upper()}: {msg}")
        print()

    if args.json and all_candidates:
        Path(args.json).write_text(json.dumps(all_candidates, indent=2))
        print(f"wrote {len(all_candidates)} candidates to {args.json}")
    if all_candidates:
        ids = " ".join(str(c["event_id"]) for c in all_candidates)
        print(f"\nTo ingest all candidates:\n  python ingest.py --ids {ids}")


if __name__ == "__main__":
    main()
