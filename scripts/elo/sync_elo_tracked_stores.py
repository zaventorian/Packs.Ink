"""Sync public.elo_tracked_stores — the RPH store_ids whose Set Championships
should appear on the ELO section's "Upcoming SCs" tab.

A store qualifies if its name matches a store we already track (i.e. we've
counted its SCs before) AND it sits in the Chicagoland region (IL/IN/WI/MI) —
the region guard drops same-name collisions like the Victoria-BC "Gauntlet
Games" vs our Bradley-IL one. New LOCATIONS of a chain we track count too: a
fresh store_id like "Chupacabra Games Joliet" matches because its name is
already in our event history — that is exactly how event 586841 should have been
picked up.

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
import argparse, json, os, re, sys, urllib.request, urllib.error
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
REGION = {"IL", "IN", "WI", "MI"}  # Chicagoland orbit
norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower())


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
    return _page("set_championships", "store_id,store_name,state,country")


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
    for r in scs:
        if (r.get("country") == "US" and r.get("state") in REGION
                and r.get("store_id") and norm(r.get("store_name")) in elo_names):
            matched[r["store_id"]] = r["store_name"]

    print(f"{len(scs)} set_championships rows scanned → {len(matched)} tracked stores in region")
    rows = [{"store_id": sid, "store_name": nm} for sid, nm in sorted(matched.items(), key=lambda kv: kv[1])]
    for r in rows:
        print(f"  {r['store_id']:>6}  {r['store_name']}")
    if args.dry_run:
        print("  (dry run — not writing)")
        return
    upsert(rows)
    print(f"\nupserted {len(rows)} store_ids into public.elo_tracked_stores")


if __name__ == "__main__":
    main()
