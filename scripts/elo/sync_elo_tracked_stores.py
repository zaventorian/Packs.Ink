"""Sync public.elo_tracked_stores — the RPH store_ids whose Set Championships
should appear on the ELO section's "Upcoming SCs" tab.

A store qualifies if ANY of:
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

The allowlist of "stores we track" is read from Supabase `public.elo_events`
(the cloud mirror of lorcana_elo.db, kept current by the weekly ELO refresh) —
NOT the local SQLite file, which is gitignored and absent in CI. That lets this
script run in the daily discover workflow on its own.

The site reads the view public.elo_upcoming_scs = set_championships ⋈
elo_tracked_stores, so adding a store_id here makes ALL its future SCs (already
in set_championships) show up on the tab.

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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
REGION = {"IL", "IN", "WI", "MI"}  # broad state gate (paired with history match)
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


def _page(table: str, select: str) -> list[dict]:
    """Page through a PostgREST table (default cap 1000 rows/response)."""
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    out, offset, page = [], 0, 1000
    while True:
        url = f"{SUPABASE_URL}/rest/v1/{table}?select={select}&limit={page}&offset={offset}"
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
    lorcana_elo.db). This is the allowlist that defines "a store we track"."""
    return {norm(r.get("store")) for r in _page("elo_events", "store") if r.get("store")}


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    elo_names = fetch_tracked_store_names()
    scs = fetch_set_championships()
    matched: dict[int, str] = {}
    reason: dict[int, str] = {}
    for r in scs:
        sid = r.get("store_id")
        if not sid:
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

    geo_only = [s for s, rs in reason.items() if "geo" in rs and "history" not in rs]
    man_only = [s for s, rs in reason.items() if rs == "manual"]
    print(f"{len(scs)} set_championships rows scanned → {len(matched)} tracked stores "
          f"({len(geo_only)} via ≤{RADIUS_MI:.0f}mi geo-rule w/o history, {len(man_only)} curated)")
    rows = [{"store_id": sid, "store_name": nm} for sid, nm in sorted(matched.items(), key=lambda kv: kv[1])]
    for r in rows:
        tag = reason.get(r["store_id"], "")
        flag = "  ← geo/curated" if r["store_id"] in geo_only or r["store_id"] in man_only else ""
        print(f"  {r['store_id']:>6}  {r['store_name']}{flag}")
    if args.dry_run:
        print("  (dry run — not writing)")
        return
    upsert(rows)
    print(f"\nupserted {len(rows)} store_ids into public.elo_tracked_stores")


if __name__ == "__main__":
    main()
