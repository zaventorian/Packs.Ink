"""Discover Inklands-era Set Championships at melee organizers we already cover.

Strategy:
  1. For each distinct (store, sample_tid) in our melee event history, fetch the
     tournament HTML and extract `/Hub/Organization/{orgId}` (the org-of-record
     for that tournament).
  2. Dedupe by orgId — multiple store-name variants ("Nerd Rage Gaming" /
     "Nerd Rage Gaming Store") collapse to the same organizer.
  3. For each unique orgId, POST to /Hub/SearchOrganizationTournaments/{orgId}
     (jQuery DataTables endpoint, returns 500 rows). Filter rows where
     Game == "Lorcana" AND (Name contains "Inklands" OR StartDate is before
     2024-07-06 — covers anything pre-Ursula's-Return).
  4. Print candidates so the human can vet before we ingest.

The endpoint was discovered by reading the inline JS on /Hub/Organization/N and
finding the `/Hub/SearchOrganizationTournaments/${organizerId}` template. POST
form is the standard DataTables shape; GET returns an HTML 404, POST returns
JSON.

Usage:
    python discover_inklands.py                  # full discovery, print summary
    python discover_inklands.py --json out.json  # also dump structured results
"""
import argparse, json, re, sqlite3, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import ingest_melee  # reuse the opener + UA constant

DB = Path(__file__).parent / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000
ORG_URL  = "https://melee.gg/Hub/SearchOrganizationTournaments/{org}"
HUB_REFERER = "https://melee.gg/Hub/Organization/{org}"

# Pre-Ursula's-Return cutoff. Ursula's Return SCs started 2024-07-06 in our
# data — anything before that is in the Inklands SC window (April-June 2024)
# or earlier. We use this as the recency filter on each org's tournament list.
CUTOFF_DATE = "2024-07-06"

UA = ingest_melee.UA


def fetch_tournament_html(tid: int) -> str | None:
    """Fetch a tournament page (sets a fresh cookie jar each time)."""
    try:
        opener = ingest_melee.make_opener()
        return ingest_melee.fetch_html(opener, tid)
    except Exception:
        return None


def extract_org_id(html: str) -> tuple[int, str] | None:
    """Pull (orgId, orgName) from `/Hub/Organization/N">Name</a>`."""
    m = re.search(r'/Hub/Organization/(\d+)[^>]*>\s*([^<]+?)\s*</a>', html)
    if m:
        return int(m.group(1)), m.group(2).strip()
    # Fallback: just the bare ID
    m2 = re.search(r'/Hub/Organization/(\d+)', html)
    return (int(m2.group(1)), "") if m2 else None


def list_org_tournaments(org_id: int) -> list[dict] | None:
    """POST the DataTables endpoint and return every tournament row.

    The form mirrors the page's $.dataTable POST: draw/start/length + at least
    one columns[N] block (the endpoint 500s without it). Length=500 covers
    every TO we've seen (largest is ~150 events for chain organizers).
    """
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


def is_inklands_candidate(row: dict) -> bool:
    """True if this tournament looks like an Inklands-era Set Championship."""
    if (row.get("Game") or "").lower() != "lorcana":
        return False
    name = (row.get("Name") or "").lower()
    # Direct match on Inklands
    if "inkland" in name:
        # exclude prereleases / drafts / casuals — keep championships
        # (also keep Trove Parties? no, those are casual / draft — skip)
        # but keep "Set Championship" / "Championship" with nothing else
        if any(k in name for k in ("prerelease", "draft", "trove party",
                                   "launch party", "release party", "casual",
                                   "league night")):
            return False
        return True
    # Catch-all: pre-cutoff Lorcana events that say "Set Championship"
    start = (row.get("StartDate") or "")[:10]
    if start and start < CUTOFF_DATE:
        if any(k in name for k in ("set championship", "championship",
                                   "store champ")):
            if not any(k in name for k in ("prerelease", "draft", "trove",
                                            "launch", "release party",
                                            "casual", "league")):
                return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write structured results to this path")
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
    print(f"Step 1: fetching org_id for each of {len(stores)} distinct melee stores...")

    # Map: orgId -> {name, stores: set of our store_names}
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

    print(f"  → {len(orgs)} unique orgs covering {sum(len(v['stores']) for v in orgs.values())} stores; {len(failed)} stores failed.")
    if failed:
        print(f"  failed stores: {failed[:8]}{' ...' if len(failed)>8 else ''}")

    # Step 2: query each org's full tournament list
    print(f"\nStep 2: querying tournament list for each of {len(orgs)} orgs...")
    candidates_by_org: dict[int, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(list_org_tournaments, oid): oid for oid in orgs}
        done = 0
        for f in as_completed(futs):
            oid = futs[f]
            rows = f.result()
            done += 1
            if rows is None:
                continue
            hits = [r for r in rows if is_inklands_candidate(r)]
            if hits:
                candidates_by_org[oid] = hits
            if done % 20 == 0:
                print(f"  scanned {done}/{len(orgs)} orgs...")

    # Step 3: print results
    total_candidates = sum(len(v) for v in candidates_by_org.values())
    print(f"\n=== {total_candidates} candidate Inklands-era SCs across {len(candidates_by_org)} orgs ===\n")

    structured = []
    # Sort orgs by store coverage (most-prolific first)
    sorted_orgs = sorted(candidates_by_org.items(),
                         key=lambda kv: -len(orgs[kv[0]]["stores"]))
    for org_id, hits in sorted_orgs:
        org = orgs[org_id]
        store_label = " / ".join(sorted(org["stores"])[:3])
        if len(org["stores"]) > 3:
            store_label += f" (+{len(org['stores'])-3} more)"
        print(f"  Org {org_id}  '{org['name']}'  [{store_label}]")
        for r in sorted(hits, key=lambda r: r.get("StartDate") or ""):
            date = (r.get("StartDate") or "")[:10]
            tid = r.get("ID")
            name = r.get("Name") or ""
            n_players = r.get("ParticipatingCount") or "?"
            print(f"    tid={tid:<8} {date}  {name[:64]}  ({n_players} players)")
            structured.append({
                "org_id": org_id, "org_name": org["name"],
                "stores": sorted(org["stores"]),
                "tid": tid, "date": date, "name": name,
                "participating": r.get("ParticipatingCount"),
            })

    if args.json:
        Path(args.json).write_text(json.dumps(structured, indent=2))
        print(f"\nwrote {len(structured)} candidates to {args.json}")


if __name__ == "__main__":
    main()
