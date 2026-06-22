"""Detect RPH display-name renames by re-pulling every event from the API.

Idea: RPH has no stable user_id — only `tv_display_name`. If someone renames
their account, the API will denormalize the NEW name onto historical matches.
So for any match in our DB, if the API now returns a different name at the
same (event_id, round_id, table_number, player_order), that's a rename signal
for that player_id.

Output: `rename_candidates.csv`. Review, set approve=y on real renames, then
run `python apply_renames.py rename_candidates.csv`.

Run monthly or whenever you suspect a rename. Read-only against the DB.

Usage:
    python detect_renames.py                      # scan all RPH events
    python detect_renames.py --season "Fabled..." # scan one season only
    python detect_renames.py --workers 8
"""
import argparse, csv, json, sqlite3, sys, urllib.request, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Player names contain emoji / mathematical-bold glyphs (🦁, 𝙎𝙃𝙄𝙁𝙏). Windows
# consoles default to cp1252 and crash on print(); force UTF-8 (no-op on Linux CI).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).parent
DB_PATH = HERE / "lorcana_elo.db"
API = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def http_get(url, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            last = e; time.sleep(0.5 * (i + 1))
    raise last


def scan_event(event_id, db_path):
    """Returns list of (player_id, db_name, api_name) tuples for any mismatches
    found in this event's matches. One row per mismatched match-side."""
    conn = sqlite3.connect(db_path); conn.row_factory = sqlite3.Row
    out = []
    try:
        tv = http_get(API.format(eid=event_id) + "/tv/")
        round_ids = [r["id"] for ph in tv.get("tournament_phases", []) for r in ph.get("rounds", [])]
        for rid in round_ids:
            try:
                payload = http_get(API.format(eid=event_id) + f"/tv/matches/?round_id={rid}")
            except Exception:
                continue
            for m in payload.get("results", []):
                table_num = m.get("table_number")
                players = m.get("players", [])
                if not players:
                    continue
                # Map API player by player_order. Byes have only 1 player, no player_order.
                api_by_order = {}
                for p in players:
                    order = p.get("player_order")
                    if order is None and m.get("match_is_bye"):
                        order = 1  # byes get treated as player_order 1
                    if order is not None:
                        api_by_order[int(order)] = p.get("tv_display_name")

                # Pull our DB record for this exact match. Use IS for nullable
                # table_number so byes match correctly.
                db = conn.execute("""
                    SELECT m.match_id, m.is_bye,
                           p1.player_id AS p1_id, p1.display_name AS p1_name,
                           p2.player_id AS p2_id, p2.display_name AS p2_name
                    FROM matches m
                    LEFT JOIN players p1 ON p1.player_id = m.player1_id
                    LEFT JOIN players p2 ON p2.player_id = m.player2_id
                    WHERE m.event_id = ? AND m.round_id = ?
                      AND COALESCE(m.table_number, -999) = COALESCE(?, -999)
                """, (event_id, rid, table_num)).fetchone()
                if not db:
                    continue

                # Compare per slot
                for order, pid, db_name in [(1, db["p1_id"], db["p1_name"]),
                                            (2, db["p2_id"], db["p2_name"])]:
                    if pid is None or db_name is None:
                        continue
                    api_name = api_by_order.get(order)
                    if api_name is None:
                        continue
                    if api_name != db_name:
                        out.append((pid, db_name, api_name, event_id, rid, table_num))
    finally:
        conn.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None, help="filter to one season")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--min-evidence", type=int, default=2,
                    help="surface a (player, new_name) pair only when it shows up in this many matches")
    ap.add_argument("--auto-approve", action="store_true",
                    help="mark approve=y on high-confidence renames so apply_renames.py runs headless "
                         "(used by the weekly refresh). Off by default — manual runs stay review-only.")
    ap.add_argument("--auto-approve-min-ratio", type=float, default=0.9,
                    help="auto-approve only when the new name covers this fraction of the player's matches "
                         "(RPH denormalizes a rename onto ALL of a player's history, so a true rename → ~1.0)")
    ap.add_argument("--auto-approve-min-evidence", type=int, default=3,
                    help="absolute floor on confirming matches before a rename can auto-apply")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    # Only RPH events (melee uses stable Usernames — not subject to this drift)
    q = "SELECT event_id, season, store, event_date FROM events WHERE platform='rph' AND is_ignored=0"
    params = ()
    if args.season:
        q += " AND season=?"; params = (args.season,)
    events = conn.execute(q, params).fetchall()
    print(f"scanning {len(events)} RPH events with {args.workers} workers...")

    all_diffs = []  # (pid, db_name, api_name, event_id, round_id, table_num)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(scan_event, e["event_id"], str(DB_PATH)): e["event_id"] for e in events}
        done = 0
        for f in as_completed(futs):
            try:
                diffs = f.result()
                all_diffs.extend(diffs)
            except Exception as e:
                print(f"  e{futs[f]}: scan err {e}")
            done += 1
            if done % 50 == 0: print(f"  ...{done}/{len(events)}")

    print(f"\ntotal name mismatches found: {len(all_diffs)}")

    # Aggregate: per (player_id, api_name) → count of matches
    by_pair = defaultdict(lambda: {"count": 0, "evidence": []})
    for pid, db_name, api_name, eid, rid, tn in all_diffs:
        key = (pid, db_name, api_name)
        by_pair[key]["count"] += 1
        if len(by_pair[key]["evidence"]) < 3:
            by_pair[key]["evidence"].append(f"e{eid}/R{rid}/T{tn}")

    # Per-player totals (for context column)
    total_matches_per_pid = dict(conn.execute("""
        SELECT p.player_id, COUNT(*) AS n
        FROM players p
        JOIN matches m ON (m.player1_id = p.player_id OR m.player2_id = p.player_id)
        WHERE p.platform='rph'
        GROUP BY p.player_id
    """).fetchall())

    # Filter to candidates with >= min-evidence matches
    candidates = []
    for (pid, db_name, api_name), info in by_pair.items():
        if info["count"] < args.min_evidence:
            continue
        candidates.append({
            "db_player_id": pid,
            "current_db_name": db_name,
            "candidate_new_name": api_name,
            "evidence_count": info["count"],
            "total_db_matches": total_matches_per_pid.get(pid, 0),
            "evidence_events": "; ".join(info["evidence"]),
            "approve": "",
        })

    if args.auto_approve:
        # A new name claimed by >1 db player is ambiguous (two people sharing a
        # handle, or a data glitch) — auto-applying both would collapse distinct
        # players. Only auto-approve names claimed by exactly ONE keeper; leave
        # the rest blank for manual review.
        claimants = defaultdict(set)
        for c in candidates:
            claimants[c["candidate_new_name"]].add(c["db_player_id"])
        auto_n = 0
        for c in candidates:
            total = c["total_db_matches"]
            cover = (c["evidence_count"] / total) if total else 0
            if (len(claimants[c["candidate_new_name"]]) == 1
                    and c["evidence_count"] >= args.auto_approve_min_evidence
                    and cover >= args.auto_approve_min_ratio):
                c["approve"] = "y"
                auto_n += 1
        print(f"auto-approved {auto_n} high-confidence rename(s) "
              f"(cover >= {args.auto_approve_min_ratio}, evidence >= {args.auto_approve_min_evidence})")

    candidates.sort(key=lambda r: (-r["evidence_count"], r["current_db_name"]))

    out_path = HERE / "rename_candidates.csv"
    if not candidates:
        print(f"no renames detected at evidence threshold >= {args.min_evidence}.")
        # Still write an empty file with headers
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=[
                "db_player_id","current_db_name","candidate_new_name",
                "evidence_count","total_db_matches","evidence_events","approve"])
            w.writeheader()
        return

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
        w.writeheader()
        for r in candidates: w.writerow(r)

    print(f"\n=== {len(candidates)} rename candidates (evidence >= {args.min_evidence}) ===\n")
    for r in candidates[:20]:
        pct = (100 * r["evidence_count"] / r["total_db_matches"]) if r["total_db_matches"] else 0
        print(f"  '{r['current_db_name']}' -> '{r['candidate_new_name']}'  "
              f"({r['evidence_count']}/{r['total_db_matches']} matches confirm, {pct:.0f}%)")
    if len(candidates) > 20:
        print(f"  ... and {len(candidates) - 20} more")
    print(f"\nwrote {out_path}")
    print("Review, set approve=y on real renames, then:")
    print("  python apply_renames.py rename_candidates.csv")


if __name__ == "__main__":
    main()
