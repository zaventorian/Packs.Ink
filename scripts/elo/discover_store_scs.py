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
  2. For each target set, pull that set's SCs from RPH via the name-relevance
     "net" (the only tractable filter over the 115k-row past index) across a few
     spellings + orderings, union by id, and gate on is_sc + detect_set locally.
  3. Keep SCs whose store.id is in our tracked set and whose event_id we haven't
     already ingested. Those are real SCs at stores we count, currently missing.

Read-only: writes NO DB rows and never calls Supabase. It prints the candidates
and (optionally) a JSON + the ingest.py command to actually pull them. Vetting
stays a human step — a store legitimately skipping a set is a real outcome.

Usage:
    python discover_store_scs.py --sets "Winterspell" "Wilds Unknown"
    python discover_store_scs.py --sets "Wilds Unknown" --json wu_missing.json
    python discover_store_scs.py --sets "Winterspell" --refresh-store-ids
"""
from __future__ import annotations
import argparse, json, sqlite3, sys, time
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


def tracked_store_ids(refresh: bool) -> tuple[set[int], dict[int, set[str]]]:
    """Map every rph event we've ingested -> its RPH store.id. Returns the set of
    store_ids we count + a store_id -> {our store names} map for labeling.
    Cached to disk (event_id -> store_id) so re-runs don't re-fetch ~600 events."""
    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT event_id, store FROM events WHERE platform='rph'").fetchall()
    conn.close()
    cache: dict[str, int | None] = {}
    if STORE_ID_CACHE.exists() and not refresh:
        cache = json.loads(STORE_ID_CACHE.read_text())

    todo = [r["event_id"] for r in rows if str(r["event_id"]) not in cache]
    if todo:
        print(f"  resolving store_id for {len(todo)} rph events (cached {len(cache)})...")

        def fetch(eid):
            try:
                m = d.http_json(META.format(eid=eid))
                return eid, (m.get("store") or {}).get("id")
            except Exception:
                return eid, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            for i, (eid, sid) in enumerate(
                    (f.result() for f in as_completed([ex.submit(fetch, e) for e in todo])), 1):
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
    Unknown' -> 'Wilds Unknown Summer 2026'). We backfill EXISTING sets, so the
    label is already present on that set's other events. None if the set has no
    events yet (a brand-new set is seeded via the spreadsheet, not here)."""
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT season FROM events WHERE season LIKE ? AND season IS NOT NULL "
        "GROUP BY season ORDER BY COUNT(*) DESC LIMIT 1", (set_name + "%",)).fetchone()
    conn.close()
    return row[0] if row else None


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


def pull_set_scs(set_name: str, name_nets: list[str], sets_sorted, aliases) -> dict[int, dict]:
    """Union name-net pulls (past + upcoming) across orderings; keep SC events
    whose detected set == set_name. Keyed by event id."""
    union: dict[int, dict] = {}
    base = {"game_slug": "disney-lorcana", "page_size": 250}
    combos = []
    for status in ("past", "upcoming"):
        for net in name_nets:
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
                if d.detect_set(ev.get("name") or "", sets_sorted, aliases) != set_name:
                    continue
                union[ev["id"]] = ev
            if not doc.get("next") or page >= 15:  # name net is small; cap pages
                break
            page += 1
            time.sleep(0.1)
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
    # extra spellings improve name-net recall (the relevance filter drops ~4%)
    NETS = {
        "Wilds Unknown": ["Wilds Unknown Set Championship", "Wilds Unknown - Set Championship",
                          "Set Championship Wilds Unknown"],
        "Winterspell": ["Winterspell Set Championship", "Winterspell - Set Championship",
                        "Set Championship Winterspell"],
    }

    all_candidates = []
    for set_name in args.sets:
        nets = NETS.get(set_name, [f"{set_name} Set Championship"])
        print(f"Pulling '{set_name}' SCs from RPH (name nets: {len(nets)})...")
        scs = pull_set_scs(set_name, nets, sets_sorted, aliases)
        cands = []
        for ev in scs.values():
            sid = (ev.get("store") or {}).get("id")
            if sid not in tracked:
                continue
            if ev["id"] in have:
                continue
            cands.append(ev)
        cands.sort(key=lambda e: (e.get("start_datetime") or ""))
        print(f"  {len(scs)} {set_name} SCs found; {len(cands)} at tracked stores & not yet ingested:\n")
        label = season_label_for(set_name) if args.ingest else None
        if args.ingest and not label:
            print(f"  ! no existing season label for {set_name!r} in the DB — "
                  f"SKIPPING ingest for this set (seed its first event via the spreadsheet first)")
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
