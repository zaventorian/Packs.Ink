"""Report events with missing cut/top-bracket rounds and emit a fill-in template.

For each event that has gap rounds (API says round is COMPLETE but exposes no
matches), this prints:
  - Final standings (so the inferred seeding is visible)
  - Any cut matches we DO have
  - A blank template for missing matches

It also writes `manual_results_template.csv` you can hand to a TO to fill in.
Once filled, run `python apply_manual.py manual_results.csv` to import.

Usage:
    python gaps.py
"""
import csv, json, sqlite3, urllib.request
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"
TEMPLATE = Path(__file__).parent / "manual_results_template.csv"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def fetch_phase_boundaries(event_id):
    """Return dict round_number -> phase_type ('SWISS', 'RANKED_SINGLE_ELIMINATION', ...)."""
    url = f"https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{event_id}/tv/"
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as r:
        tv = json.load(r)
    out = {}
    for ph in tv.get("tournament_phases", []):
        ph_type = ph.get("round_type")
        for rnd in ph.get("rounds", []):
            out[rnd["round_number"]] = ph_type
    return out


def fetch_event_context(conn, event_id):
    """Return (event_row, swiss_standings, recorded_cut_matches) for an event.
    Phase boundaries come from a fresh API call so we correctly separate Swiss
    from cut rounds even when the cut's first round was recorded in our DB."""
    ev = conn.execute(
        "SELECT * FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()

    boundaries = fetch_phase_boundaries(event_id)
    cut_rounds = sorted(
        rn for rn, pt in boundaries.items() if pt and "ELIMINATION" in pt
    )
    first_cut_rnum = cut_rounds[0] if cut_rounds else 999

    swiss = conn.execute("""
        WITH pe AS (
            SELECT p.player_id, p.display_name,
                   SUM(CASE WHEN m.winner_id = p.player_id THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN m.winner_id IS NOT NULL AND m.winner_id != p.player_id
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS losses,
                   SUM(CASE WHEN m.winner_id IS NULL AND m.is_bye = 0
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS draws,
                   SUM(CASE WHEN m.is_bye = 1 THEN 1 ELSE 0 END) AS byes
            FROM players p
            JOIN matches m ON (m.player1_id = p.player_id OR m.player2_id = p.player_id)
            WHERE m.event_id = ? AND m.round_number < ?
            GROUP BY p.player_id
        )
        SELECT * FROM pe ORDER BY (wins*3 + draws) DESC, wins DESC, display_name
    """, (event_id, first_cut_rnum)).fetchall()

    cut_matches = conn.execute("""
        SELECT m.round_number, m.table_number,
               p1.display_name AS p1, p2.display_name AS p2,
               pw.display_name AS winner,
               m.games_won_p1, m.games_won_p2, m.source
        FROM matches m
        LEFT JOIN players p1 ON p1.player_id = m.player1_id
        LEFT JOIN players p2 ON p2.player_id = m.player2_id
        LEFT JOIN players pw ON pw.player_id = m.winner_id
        WHERE m.event_id = ? AND m.round_number >= ?
        ORDER BY m.round_number, m.table_number
    """, (event_id, first_cut_rnum)).fetchall()

    return ev, swiss, cut_matches


def main():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    gap_events = conn.execute("""
        SELECT DISTINCT e.event_id, e.event_date, e.store, e.location, e.name,
               e.num_players, e.notes,
               COUNT(g.round_id) AS n_gaps
        FROM gap_rounds g JOIN events e ON e.event_id = g.event_id
        WHERE e.is_ignored = 0
        GROUP BY e.event_id ORDER BY e.event_date, e.event_id
    """).fetchall()

    if not gap_events:
        print("no gaps found.")
        return

    template_rows = []
    for ev in gap_events:
        eid = ev["event_id"]
        print("=" * 70)
        print(f"EVENT {eid}  {ev['name']}")
        print(f"  {ev['store']}, {ev['location']}  ({ev['event_date']})  {ev['num_players']} players")
        print(f"  {ev['n_gaps']} gap round(s)")
        if ev["notes"]:
            print(f"  notes: {ev['notes']}")

        event_row, swiss, cut_matches = fetch_event_context(conn, eid)

        print("\n  STANDINGS AFTER SWISS (pre-cut):")
        for i, p in enumerate(swiss, 1):
            byes = f"  ({p['byes']}b)" if p["byes"] else ""
            print(f"    #{i:>2}  {p['display_name']:<26}  {p['wins']}-{p['losses']}-{p['draws']}{byes}")

        if cut_matches:
            print("\n  CUT MATCHES ALREADY RECORDED:")
            for m in cut_matches:
                if m["winner"]:
                    res = f"{m['p1']} > {m['p2']}" if m["winner"] == m["p1"] else f"{m['p1']} < {m['p2']}"
                else:
                    res = f"{m['p1']} vs {m['p2']} (DRAW)"
                score = f"({m['games_won_p1']}-{m['games_won_p2']})" if m["games_won_p1"] is not None else ""
                src = f" [src:{m['source']}]" if m["source"] != "api" else ""
                print(f"    R{m['round_number']} T{m['table_number']:<2}  {res}  {score}{src}")

        gaps = conn.execute("""
            SELECT round_number, phase_type FROM gap_rounds
            WHERE event_id = ? ORDER BY round_number
        """, (eid,)).fetchall()
        print("\n  MISSING ROUNDS (please fill in):")
        for g in gaps:
            print(f"    R{g['round_number']}  ({g['phase_type']})")
            # add a blank template row per missing round; user duplicates rows as needed
            template_rows.append({
                "event_id": eid,
                "event_date": event_row["event_date"],
                "store": event_row["store"],
                "round_number": g["round_number"],
                "table_number": "",
                "player1_display_name": "",
                "player2_display_name": "",
                "winner_display_name": "",
                "games_won_p1": "",
                "games_won_p2": "",
                "notes": f"{g['phase_type']} (e.g. SF/Final). Duplicate this row per match.",
            })
        print()

    # write template
    with open(TEMPLATE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(template_rows[0].keys()))
        w.writeheader()
        for row in template_rows:
            w.writerow(row)
    print(f"\nwrote fill-in template -> {TEMPLATE}")
    print("After editing, run: python apply_manual.py manual_results.csv")


if __name__ == "__main__":
    main()
