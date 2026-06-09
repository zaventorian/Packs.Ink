"""Find Set Championships at orgs we already cover but haven't ingested yet.

For every distinct melee store in our DB:
  1. Extract that store's melee org_id (from one sample tournament page).
  2. Dedupe to unique orgs (multiple store-name variants share an org_id).
  3. POST /Hub/SearchOrganizationTournaments/{orgId} for the full event list.
  4. Filter to Lorcana events with "championship" / "set champ" in the name,
     EXCLUDING release / sealed / draft / league / trove side events.
  5. Drop anything already in our DB.
  6. Drop anything under EXCLUDED_ORGS (currently: Final Round Game Shop).

Output is grouped by org with each candidate's tid, date, player count, and
event name so a human can vet the list before mass-ingesting.

Usage:
    python discover_missing_scs.py
    python discover_missing_scs.py --json out.json
    python discover_missing_scs.py --workers 8
"""
import argparse, json, re, sqlite3, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import ingest_melee

DB = Path(__file__).parent / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000
ORG_URL = "https://melee.gg/Hub/SearchOrganizationTournaments/{org}"
HUB_REFERER = "https://melee.gg/Hub/Organization/{org}"
UA = ingest_melee.UA

# Org IDs to completely skip (user-specified exclusions)
EXCLUDED_ORGS = {
    1614,  # Final Round Game Shop — user request: don't add any more from here
}

# Earliest SC era we care about — Inklands SCs were April 2024
EARLIEST_SC_DATE = "2024-04-01"


def fetch_tournament_html(tid: int) -> str | None:
    try:
        opener = ingest_melee.make_opener()
        return ingest_melee.fetch_html(opener, tid)
    except Exception:
        return None


def extract_org_id(html: str) -> tuple[int, str] | None:
    m = re.search(r'/Hub/Organization/(\d+)[^>]*>\s*([^<]+?)\s*</a>', html)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m2 = re.search(r'/Hub/Organization/(\d+)', html)
    return (int(m2.group(1)), "") if m2 else None


def list_org_tournaments(org_id: int) -> list[dict] | None:
    form = {
        "draw": 1, "start": 0, "length": 500,
        "search[value]": "", "search[regex]": "false",
        "order[0][column]": 0, "order[0][dir]": "desc",
        "columns[0][data]": "StartDate", "columns[0][name]": "",
        "columns[0][searchable]": "true", "columns[0][orderable]": "true",
        "columns[0][search][value]": "", "columns[0][search][regex]": "false",
    }
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "X-Requested-With": "XMLHttpRequest",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": HUB_REFERER.format(org=org_id),
    }
    try:
        req = Request(ORG_URL.format(org=org_id), data=urlencode(form).encode(),
                      method="POST", headers=headers)
        with urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", errors="ignore"))
        return d.get("data") or []
    except Exception as e:
        print(f"  ! list_org_tournaments({org_id}) failed: {e}", file=sys.stderr)
        return None


# Patterns we EXCLUDE — these are side events, not SCs
SIDE_PATTERNS = (
    "prerelease", "pre-release", "release party", "release event", "release day",
    "midnight release", "sunday release", "saturday release",
    "draft", "sealed", "trove party", "launch party",
    "casual", "league night", "weekly league", "win-a-box", "winabox",
    "store pre", "starter deck battle",
    "free play", "scrimmage", "practice", "open play",
    "draft pod", "battle royale", "fnm", "friday night",
    "fat pack", "ticket draft", "showdown",
)
SC_KEYWORDS = ("set championship", "championship", "store champ", "championship!")


def is_set_championship(row: dict) -> bool:
    """Heuristic: Lorcana + 'championship' in name + not a known side-event pattern."""
    if (row.get("Game") or "").lower() != "lorcana":
        return False
    name_lower = (row.get("Name") or "").lower()
    if not any(k in name_lower for k in SC_KEYWORDS):
        return False
    if any(k in name_lower for k in SIDE_PATTERNS):
        return False
    # Cut anything too small to be a real SC. None / 0 are common for unstarted events.
    pcount = row.get("ParticipatingCount") or 0
    if pcount < 6:
        return False
    # Drop anything before the SC era
    sd = (row.get("StartDate") or "")[:10]
    if sd and sd < EARLIEST_SC_DATE:
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="dump structured results to this path")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    conn = sqlite3.connect(DB); conn.row_factory = sqlite3.Row
    stores = conn.execute("""
        SELECT store, MIN(event_date) earliest, COUNT(*) n_events,
               (SELECT event_id FROM events e2
                 WHERE e2.store=e.store AND e2.platform='melee'
                 ORDER BY event_date LIMIT 1) sample_eid
        FROM events e
        WHERE platform='melee' AND store IS NOT NULL
        GROUP BY store
    """).fetchall()
    # Set of existing melee event_ids (with offset) for fast lookup
    existing_eids = {r[0] for r in conn.execute(
        "SELECT event_id FROM events WHERE platform='melee'"
    )}
    existing_tids = {eid - MELEE_OFFSET for eid in existing_eids}

    print(f"Step 1: fetching org_id for each of {len(stores)} distinct melee stores...")

    orgs: dict[int, dict] = {}
    failed: list[str] = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_tournament_html,
                           row["sample_eid"] - MELEE_OFFSET): row for row in stores}
        for f in as_completed(futs):
            row = futs[f]
            html = f.result()
            if not html:
                failed.append(row["store"]); continue
            res = extract_org_id(html)
            if not res:
                failed.append(row["store"]); continue
            org_id, org_name = res
            entry = orgs.setdefault(org_id, {"name": org_name, "stores": set()})
            entry["stores"].add(row["store"])
            if not entry["name"] and org_name:
                entry["name"] = org_name

    # Filter excluded orgs
    excluded_count = sum(1 for oid in orgs if oid in EXCLUDED_ORGS)
    orgs = {oid: v for oid, v in orgs.items() if oid not in EXCLUDED_ORGS}
    print(f"  → {len(orgs)} unique orgs to scan ({excluded_count} explicitly excluded, {len(failed)} stores failed)")
    if failed:
        print(f"  failed stores: {failed[:8]}{' ...' if len(failed)>8 else ''}")

    print(f"\nStep 2: querying tournament list for each org...")
    missing_by_org: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(list_org_tournaments, oid): oid for oid in orgs}
        done = 0
        for f in as_completed(futs):
            oid = futs[f]
            rows = f.result()
            done += 1
            if rows is None: continue
            missing = []
            for r in rows:
                if not is_set_championship(r): continue
                tid = r.get("ID")
                if tid is None or tid in existing_tids: continue
                missing.append(r)
            if missing:
                missing_by_org[oid] = missing
            if done % 20 == 0:
                print(f"  scanned {done}/{len(orgs)} orgs...")

    total = sum(len(v) for v in missing_by_org.values())
    print(f"\n=== {total} candidate missing SCs across {len(missing_by_org)} orgs ===\n")

    structured = []
    sorted_orgs = sorted(missing_by_org.items(),
                         key=lambda kv: -len(orgs[kv[0]]["stores"]))
    for oid, hits in sorted_orgs:
        org = orgs[oid]
        store_label = " / ".join(sorted(org["stores"])[:3])
        if len(org["stores"]) > 3:
            store_label += f" (+{len(org['stores'])-3} more)"
        # Entity-decode the org name for display
        oname = re.sub(r'&#39;', "'", re.sub(r'&amp;', '&', org["name"]))
        print(f"  Org {oid}  '{oname}'  [{store_label}]")
        for r in sorted(hits, key=lambda r: r.get("StartDate") or ""):
            date = (r.get("StartDate") or "")[:10]
            tid = r.get("ID")
            name = r.get("Name") or ""
            pcount = r.get("ParticipatingCount") or "?"
            print(f"    tid={tid:<8} {date}  {name[:60]}  ({pcount} players)")
            structured.append({
                "org_id": oid, "org_name": oname,
                "stores": sorted(org["stores"]),
                "tid": tid, "date": date, "name": name,
                "participating": r.get("ParticipatingCount"),
            })

    if args.json:
        Path(args.json).write_text(json.dumps(structured, indent=2))
        print(f"\nwrote {len(structured)} candidates to {args.json}")


if __name__ == "__main__":
    main()
