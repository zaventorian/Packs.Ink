"""Sync public.elo_tracked_stores — the RPH store_ids whose Set Championships
should appear on the ELO section's "Upcoming SCs" tab.

A store is EXCLUDED outright if it is in elo_scope.EXCLUDED_STORE_IDS — a
geographic ruling that beats every rule below, and one this script also ENFORCES
by deleting the row (see prune_excluded). Otherwise it qualifies if ANY of:
  1. HISTORY: its name matches a store in our results history (Supabase
     elo_events) AND it's in the broad region (IL/IN/WI/MI). The region guard
     drops same-name collisions (Victoria-BC "Gauntlet Games" vs our Bradley-IL
     one). New LOCATIONS of a tracked chain count too ("Chupacabra Games Joliet"
     matches because its name is already in our history — that's event 586841).
  2. GEOGRAPHY: it's a US store with an upcoming SC within RADIUS_MI of downtown
     Chicago, regardless of history. The state+history gate alone tracked stores
     165-170 mi out (Green Bay, Indianapolis) yet missed central stores we'd
     never ingested (Amazing Fantasy, Frankfort IL, 27 mi — 94% of its roster was
     already-ranked players). The geo rule guarantees the core bubble is covered.
  3. CURATED: it's in MANUAL_TRACKED (cross-metro/chain calls the rules can't
     infer, e.g. Game Universe Mequon in the Milwaukee ring).
  4. HISTORY w/ NO UPCOMING SC: an in-region store we've ingested results for but
     that has no SC currently in set_championships. Pass 1 only sees stores listed
     in set_championships (upcoming), so a store whose SCs we added by event_id
     (the season sheet) but that isn't running one right now stayed untracked —
     even though it's part of the scene. (The 14 I&L-circuit stores were exactly
     this: all IL/IN, 1-72 mi out, fully counted in ELO, just off the tab.) We
     resolve those stores' store_id from a sample event and track the in-region
     ones. Skipped-by-name once tracked, so it stays cheap after the first run.

The allowlist of "stores we track" is read from Supabase `public.elo_events`
(the cloud mirror of lorcana_elo.db, kept current by the weekly ELO refresh) —
NOT the local SQLite file, which is gitignored and absent in CI. That lets this
script run in the daily discover workflow on its own.

The site reads the view public.elo_upcoming_scs = set_championships ⋈
elo_tracked_stores, so adding a store_id here makes ALL its future SCs (already
in set_championships) show up on the tab. The same table also gates the Scout
tab, whether a scouting sheet opens at all, the roster scrape and the Stores
tab's history backfill — so a store wrongly listed here is visible in four
places, not one.

⚠ The upsert ADDS and never removes, so tightening a rule cannot take effect on
its own: a store that qualified once stays tracked forever. That is how Good
Games - Indianapolis (excluded as out-of-region) was still on the Scout tab
months later (reported 2026-09-12). prune_excluded() closes it for the explicit
ruling; drift from the inferred rules is REPORTED, not deleted — pass 2 resolves
store_ids over the live RPH API, so a 404 or a timeout makes a perfectly good
store look unmatched, and deleting on that would take a real shop off four
surfaces because a network call blipped.

Run AFTER discover_wu_scs.py refreshes set_championships:
    python sync_elo_tracked_stores.py
    python sync_elo_tracked_stores.py --dry-run
"""
from __future__ import annotations
import argparse, json, math, os, re, sys, urllib.request, urllib.error
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

# Windows consoles default to cp1252 and choke on the → / — glyphs below.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from elo_scope import EXCLUDED_STORE_IDS, ONE_OFF_EVENT_IDS

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
REGION = {"IL", "IN", "WI", "MI"}  # broad state gate (paired with history match)
RPH_HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())

# Geographic auto-track: any US store with an upcoming SC inside this radius of
# downtown Chicago is tracked regardless of history. The state+history gate alone
# was a poor proxy for "Chicagoland" — it tracked stores 165-170 mi out (Green
# Bay, Indianapolis) yet missed central stores we'd never ingested (e.g. Amazing
# Fantasy, Frankfort IL, 27 mi, whose roster was 94% already-ranked players). 75
# mi = city + collar counties + NW Indiana + Kenosha/Racine WI; the next untracked
# store sits at ~94 mi (Milwaukee ring), so this cleanly covers the core bubble.
CHICAGO = (41.8781, -87.6298)
RADIUS_MI = 75.0

# Curated additions the rules above can't infer: clearly community stores (high
# board roster-overlap) that have no results history AND fall outside the core
# radius. Keep short + justified; each is a deliberate cross-metro/chain call.
MANUAL_TRACKED = {
    2039: "Game Universe Mequon — Milwaukee-ring (94 mi) location of a tracked "
          "chain (Game Universe Brookfield/Franklin); 100% roster overlap",
}


def _dist_mi(lat, lng):
    """Great-circle miles from downtown Chicago, or None if no coordinates."""
    if lat is None or lng is None:
        return None
    p1, p2 = math.radians(CHICAGO[0]), math.radians(lat)
    dphi = math.radians(lat - CHICAGO[0])
    dl = math.radians(lng - CHICAGO[1])
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def _page(table: str, select: str, where: str = "") -> list[dict]:
    """Page through a PostgREST table (default cap 1000 rows/response).
    `where` is an optional raw PostgREST filter appended to each request."""
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    out, offset, page = [], 0, 1000
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}&limit={page}&offset={offset}"
        if where:
            url += f"&{where}"
        req = urllib.request.Request(url, headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"})
        batch = json.loads(urllib.request.urlopen(req, timeout=60).read())
        out.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return out


def fetch_set_championships() -> list[dict]:
    return _page("set_championships",
                 "store_id,store_name,state,country,latitude,longitude")


def fetch_tracked_store_names() -> set[str]:
    """Normalized names of every store in our ELO history (Supabase mirror of
    lorcana_elo.db). This is the allowlist that defines "a store we track".
    Ignored events (is_ignored=true) are NOT history — a store whose events are
    all ignored (e.g. an out-of-scope store we dropped) must not re-qualify.
    Neither are hand-added one-offs: those count for Elo but confer no scope, so
    a single guest event must not put its shop on the Upcoming SCs tab."""
    return {norm(r.get("store"))
            for r in _page("elo_events", "event_id,store", "is_ignored=eq.false")
            if r.get("store") and r.get("event_id") not in ONE_OFF_EVENT_IDS}


MELEE_OFFSET = 100_000_000  # melee event_ids are stored +100M; only RPH ids resolve via the RPH API

def history_store_samples(per: int = 3) -> dict[str, list[int]]:
    """{normalized store name -> up to `per` sample *RPH* event_ids} over our ELO
    history, so a store with no upcoming SC can still be resolved to its store_id.
    Keeps several events per store so one deleted/404 event doesn't skip it, and
    skips melee event_ids (≥100M) which can't be resolved via the RPH events API."""
    out: dict[str, list[int]] = {}
    for r in _page("elo_events", "event_id,store", "is_ignored=eq.false"):
        nm = norm(r.get("store"))
        eid = r.get("event_id")
        if eid in ONE_OFF_EVENT_IDS:
            continue  # counts for Elo, but its store is not one we track
        if nm and eid and eid < MELEE_OFFSET:
            lst = out.setdefault(nm, [])
            if len(lst) < per:
                lst.append(eid)
    return out


def rph_store_of(event_id: int) -> dict | None:
    """Resolve {id, name, state} of the store that ran an RPH event. The event
    detail endpoint exposes the state as `administrative_area_level_1_short`
    (NOT `state`, which only the list endpoint returns); fall back to parsing it
    out of full_address ("…, City, ST, ZIP, US")."""
    url = f"https://api.ravensburgerplay.com/api/v2/events/{event_id}/"
    try:
        d = json.loads(urllib.request.urlopen(
            urllib.request.Request(url, headers=RPH_HDR), timeout=30).read())
    except Exception:
        return None
    st = d.get("store") or {}
    if not st:
        return None
    state = st.get("administrative_area_level_1_short") or st.get("state")
    if not state:
        parts = [p.strip() for p in (st.get("full_address") or "").split(",")]
        if len(parts) >= 3:
            state = parts[-3]  # …, City, ST, ZIP, Country
    return {"id": st.get("id"), "name": st.get("name"), "state": state}


def upsert(rows: list[dict]) -> None:
    endpoint = f"{SUPABASE_URL}/rest/v1/elo_tracked_stores"
    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
               "Content-Type": "application/json",
               "Prefer": "resolution=merge-duplicates,return=minimal"}
    req = urllib.request.Request(endpoint, data=json.dumps(rows).encode(), headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"upsert failed [{e.code}]: {e.read().decode('utf-8','ignore')[:400]}")


def fetch_tracked() -> list[dict]:
    """What elo_tracked_stores holds right now."""
    return _page("elo_tracked_stores", "store_id,store_name")


def _delete_ids(ids: str) -> None:
    """DELETE elo_tracked_stores rows by a PostgREST in.(…) id list."""
    endpoint = f"{SUPABASE_URL}/rest/v1/elo_tracked_stores?store_id=in.({ids})"
    headers = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
               "Prefer": "return=minimal"}
    req = urllib.request.Request(endpoint, headers=headers, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=60).read()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"delete failed [{e.code}]: {e.read().decode('utf-8','ignore')[:400]}")


def prune_excluded(dry: bool) -> list[dict]:
    """DELETE every EXCLUDED_STORE_IDS row from elo_tracked_stores.

    ⚠ The upsert above only ever ADDS, so before this existed a ruling could not
    be enforced retroactively: Good Games - Indianapolis was excluded as
    out-of-region and still sat on the Scout tab months later, because nothing in
    the pipeline could take a row back out. An exclusion has to be able to REMOVE.

    Deliberately narrow — only the explicit list, never "whatever this run did not
    match". Pass 2 resolves store_ids over the live RPH API, so a 404 or a timeout
    makes a perfectly good store look unmatched, and deleting on that would drop a
    real shop off the Upcoming SCs tab, the Scout tab, its scouting sheets and the
    Stores tab's history because one network call blipped. Drift from the inferred
    rules is REPORTED by main() instead.
    """
    doomed = [r for r in fetch_tracked() if r.get("store_id") in EXCLUDED_STORE_IDS]
    if not doomed:
        return []
    ids = ",".join(str(r["store_id"]) for r in doomed)
    for r in doomed:
        print(f"  - {r['store_id']:>6}  {r.get('store_name') or '?'}  ← excluded, removing")
    if dry:
        print("  (dry run — not deleting)")
        return doomed
    _delete_ids(ids)
    return doomed


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-history", action="store_true",
                    help="skip pass 2 (in-region history stores with no upcoming SC)")
    args = ap.parse_args()

    elo_names = fetch_tracked_store_names()
    scs = fetch_set_championships()
    matched: dict[int, str] = {}
    reason: dict[int, str] = {}
    for r in scs:
        sid = r.get("store_id")
        if not sid or sid in EXCLUDED_STORE_IDS:
            continue
        name = r.get("store_name")
        us = r.get("country") == "US"
        hist = us and r.get("state") in REGION and norm(name) in elo_names
        near = us and (lambda d: d is not None and d <= RADIUS_MI)(
            _dist_mi(r.get("latitude"), r.get("longitude")))
        man = sid in MANUAL_TRACKED
        if hist or near or man:
            matched[sid] = name
            reason[sid] = "+".join(t for t, on in
                                   (("history", hist), ("geo", near), ("manual", man)) if on)

    # Pass 2 — in-region stores from ELO history that have NO upcoming SC (so pass
    # 1, which only walks set_championships, never sees them). Resolve store_id
    # from a sample event; track the IL/IN/WI/MI ones. Already-tracked names are
    # skipped (no RPH call) so this stays cheap after the first run.
    if not args.no_history:
        tracked_norm = {norm(n) for n in matched.values()}
        n_pass2 = 0
        for nname, eids in history_store_samples().items():
            if nname in tracked_norm:
                continue
            # try several of the store's events; some may be deleted (404)
            st = next((s for s in (rph_store_of(e) for e in eids) if s and s.get("id")), None)
            if not st:
                continue
            sid = st.get("id")
            if sid in EXCLUDED_STORE_IDS:
                continue
            if sid and sid not in matched and st.get("state") in REGION:
                matched[sid] = st.get("name") or "?"
                reason[sid] = "history-no-upcoming"
                n_pass2 += 1
        print(f"pass 2: +{n_pass2} in-region history stores with no upcoming SC")

    geo_only = [s for s, rs in reason.items() if "geo" in rs and "history" not in rs]
    man_only = [s for s, rs in reason.items() if rs == "manual"]
    hist_noup = [s for s, rs in reason.items() if rs == "history-no-upcoming"]
    print(f"{len(scs)} set_championships rows scanned → {len(matched)} tracked stores "
          f"({len(geo_only)} via ≤{RADIUS_MI:.0f}mi geo-rule w/o history, "
          f"{len(hist_noup)} in-region history w/o upcoming SC, {len(man_only)} curated)")
    rows = [{"store_id": sid, "store_name": nm} for sid, nm in sorted(matched.items(), key=lambda kv: kv[1])]
    for r in rows:
        sid = r["store_id"]
        flag = {"history-no-upcoming": "  ← history (no upcoming)"}.get(reason.get(sid, ""), "")
        if not flag and (sid in geo_only or sid in man_only):
            flag = "  ← geo/curated"
        print(f"  {sid:>6}  {r['store_name']}{flag}")
    if args.dry_run:
        print("  (dry run — not writing)")
    else:
        upsert(rows)
        print(f"\nupserted {len(rows)} store_ids into public.elo_tracked_stores")

    # An exclusion is a RULING, so it is enforced rather than merely not re-added.
    print("\nexclusions:")
    removed = prune_excluded(args.dry_run)
    if not removed:
        print(f"  none of the {len(EXCLUDED_STORE_IDS)} excluded stores is tracked")

    # Drift: tracked stores no rule matched this run. REPORTED, NEVER DELETED —
    # pass 2 asks the live RPH API, so one 404 would otherwise drop a real shop
    # off four surfaces. If an entry here is genuinely out of scope, the fix is to
    # add it to EXCLUDED_STORE_IDS, which the pass above then enforces.
    gone = [r for r in fetch_tracked()
            if r.get("store_id") not in matched
            and r.get("store_id") not in EXCLUDED_STORE_IDS]
    if gone:
        print(f"\n{len(gone)} tracked store(s) matched no rule this run "
              f"(left alone — add to EXCLUDED_STORE_IDS to remove):")
        for r in sorted(gone, key=lambda r: r.get("store_name") or ""):
            print(f"  ? {r['store_id']:>6}  {r.get('store_name') or '?'}")


if __name__ == "__main__":
    main()
