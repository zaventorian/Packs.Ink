"""Generate a community-friendly report of events with missing match data.

Outputs:
  - gaps_report.md   : human-readable per-event sections (paste into Discord, etc.)
  - gaps_to_fill.csv : flat list, one row per missing round (for tracking)

Each event entry includes the original tournament URL, the missing rounds, and
the Swiss standings we already have, so a TO or player who was there can fill
in the bracket from memory.
"""
import csv, re, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000


def event_url(event_id, platform):
    if platform == "melee":
        return f"https://melee.gg/Tournament/View/{event_id - MELEE_OFFSET}"
    return f"https://tcg.ravensburgerplay.com/events/{event_id}"


def swiss_record(conn, event_id, first_cut_round):
    """Return list of player records BEFORE the cut, ordered by wins desc."""
    rows = conn.execute("""
        WITH plays AS (
            SELECT p.display_name,
                   SUM(CASE WHEN m.winner_id = p.player_id THEN 1 ELSE 0 END) AS w,
                   SUM(CASE WHEN m.winner_id IS NOT NULL AND m.winner_id != p.player_id
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS l,
                   SUM(CASE WHEN m.winner_id IS NULL AND m.is_bye = 0
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS d,
                   SUM(CASE WHEN m.is_bye = 1 THEN 1 ELSE 0 END) AS byes
            FROM players p
            JOIN matches m ON (m.player1_id = p.player_id OR m.player2_id = p.player_id)
            WHERE m.event_id = ? AND m.round_number < ?
            GROUP BY p.player_id
        )
        SELECT * FROM plays
        ORDER BY (w*3 + d) DESC, w DESC, display_name
    """, (event_id, first_cut_round)).fetchall()
    return rows


def main():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    events_with_gaps = conn.execute("""
        SELECT e.event_id, e.platform, e.event_date, e.store, e.location, e.name,
               e.num_players, e.season,
               COUNT(g.round_id) AS n_gaps,
               GROUP_CONCAT(g.round_number || ':' || g.phase_type, '|') AS gaps
        FROM gap_rounds g JOIN events e ON e.event_id = g.event_id
        WHERE e.is_ignored = 0 AND g.filled_matches = 0
        GROUP BY e.event_id ORDER BY e.event_date, e.event_id
    """).fetchall()

    md_path = Path(__file__).parent / "gaps_report.md"
    csv_path = Path(__file__).parent / "gaps_to_fill.csv"

    md_lines = []
    md_lines.append("# Chicagoland Lorcana ELO — Events Missing Results\n")
    md_lines.append(f"As of the latest ingest, {len(events_with_gaps)} events have at least one round whose results aren't on the platform (the round shows as COMPLETE but no pairings or winners are exposed). If anyone played in or ran these, please reach out so we can fill them in.\n")
    md_lines.append("---\n")

    csv_rows = []
    for ev in events_with_gaps:
        gap_specs = [g.split(":") for g in (ev["gaps"] or "").split("|") if g]
        gap_rnums = sorted(set(int(g[0]) for g in gap_specs))
        first_cut = min(gap_rnums)
        url = event_url(ev["event_id"], ev["platform"])

        # if the gap is round 1, we have nothing to show as Swiss standings
        standings = []
        if first_cut > 1:
            standings = swiss_record(conn, ev["event_id"], first_cut)

        md_lines.append(f"## {ev['store']}, {ev['location']} — {ev['event_date']}")
        md_lines.append(f"**Season:** {ev['season']}  ")
        md_lines.append(f"**Event:** {ev['name']}  ")
        md_lines.append(f"**Players:** {ev['num_players'] or '?'}  ")
        md_lines.append(f"**Link:** {url}")
        md_lines.append("")
        md_lines.append(f"**Missing rounds:** " + ", ".join(f"R{n}" for n in gap_rnums))
        md_lines.append("")
        if standings:
            md_lines.append(f"**Standings before missing round{'s' if len(gap_rnums)>1 else ''} (R{first_cut}):**\n")
            md_lines.append("```")
            for i, s in enumerate(standings, 1):
                byes = f"  ({s['byes']}b)" if s["byes"] else ""
                md_lines.append(f"  #{i:>2}  {s['display_name']:<26}  {s['w']}-{s['l']}-{s['d']}{byes}")
            md_lines.append("```")
        else:
            md_lines.append(f"_(No prior-round data available — entire event needs results filled in.)_")
        md_lines.append("")
        md_lines.append("---\n")

        for rnum in gap_rnums:
            csv_rows.append({
                "event_id": ev["event_id"],
                "platform": ev["platform"],
                "season": ev["season"],
                "event_date": ev["event_date"],
                "store": ev["store"],
                "location": ev["location"],
                "event_name": ev["name"],
                "url": url,
                "round_number": rnum,
                "phase_type": next((g[1] for g in gap_specs if int(g[0]) == rnum), ""),
            })

    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()))
        w.writeheader()
        for r in csv_rows: w.writerow(r)

    print(f"events with gaps: {len(events_with_gaps)}")
    print(f"total missing rounds: {len(csv_rows)}")
    print(f"\nwrote:")
    print(f"  {md_path.name}    (paste into Discord/forum)")
    print(f"  {csv_path.name}   (tracking spreadsheet)")


if __name__ == "__main__":
    main()
