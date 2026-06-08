"""Generate ONE short combined message asking for the specific missing match(es) per event.

For each event we infer the most likely missing matchup from the Swiss standings
and any recorded cut data, then phrase a tight one-line ask. The community
member can confirm or correct — but the default ask is concrete (e.g. "was the
final Sean vs METALLICFLARE? who won?") rather than an open "what happened?".

Outputs:
  community_message.md   – one all-in-one Discord post
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"
MELEE_OFFSET = 100_000_000


def event_url(event_id, platform):
    if platform == "melee":
        return f"https://melee.gg/Tournament/View/{event_id - MELEE_OFFSET}"
    return f"https://tcg.ravensburgerplay.com/events/{event_id}"


def swiss_record(conn, event_id, first_cut_round):
    return conn.execute("""
        WITH plays AS (
            SELECT p.display_name,
                   SUM(CASE WHEN m.winner_id = p.player_id THEN 1 ELSE 0 END) AS w,
                   SUM(CASE WHEN m.winner_id IS NOT NULL AND m.winner_id != p.player_id
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS l,
                   SUM(CASE WHEN m.winner_id IS NULL AND m.is_bye = 0
                            AND (m.player1_id = p.player_id OR m.player2_id = p.player_id)
                            THEN 1 ELSE 0 END) AS d
            FROM players p
            JOIN matches m ON (m.player1_id = p.player_id OR m.player2_id = p.player_id)
            WHERE m.event_id = ? AND m.round_number < ?
            GROUP BY p.player_id
        )
        SELECT * FROM plays ORDER BY (w*3 + d) DESC, w DESC, display_name
    """, (event_id, first_cut_round)).fetchall()


def recorded_round(conn, event_id, round_number):
    """Return all matches for a round with their pairings + winner (or None)."""
    return conn.execute("""
        SELECT m.table_number,
               p1.display_name AS p1, p2.display_name AS p2,
               pw.display_name AS winner
        FROM matches m
        LEFT JOIN players p1 ON p1.player_id = m.player1_id
        LEFT JOIN players p2 ON p2.player_id = m.player2_id
        LEFT JOIN players pw ON pw.player_id = m.winner_id
        WHERE m.event_id = ? AND m.round_number = ? AND m.is_bye = 0
        ORDER BY m.table_number
    """, (event_id, round_number)).fetchall()


def round_match_counts(conn, event_id):
    """Return {round_number: match_count} for all recorded rounds."""
    return dict(conn.execute(
        "SELECT round_number, COUNT(*) FROM matches WHERE event_id=? AND is_bye=0 GROUP BY round_number",
        (event_id,),
    ).fetchall())


def swiss_round_count(num_players, fallback=4):
    """Standard Swiss round count for a tournament — ceil(log2(N))."""
    if not num_players or num_players < 2:
        return fallback
    import math
    return max(1, math.ceil(math.log2(num_players)))


def build_ask(conn, ev, gap_rnums):
    """Return a 1-3 line ask tailored to what's missing.

    Strategy: inspect the round JUST BEFORE the first gap.
    - If its match count matches earlier rounds (Swiss pattern), the gap is
      likely the Final between top 2 of standings.
    - If its match count is sharply smaller (cut started), the gap is the next
      bracket round; we use winners or pairings from the prior round."""
    eid = ev["event_id"]
    first_gap = min(gap_rnums)
    last_gap = max(gap_rnums)

    standings = swiss_record(conn, eid, first_gap)
    top = standings[:4]

    prior_rnd = first_gap - 1
    prior = recorded_round(conn, eid, prior_rnd) if prior_rnd >= 1 else []
    prior_winners = [m["winner"] for m in prior if m["winner"]]
    prior_n = len(prior)
    prior_decided = len(prior_winners)

    # Estimate the ACTIVE player count from the largest Swiss round we have
    # (registered count overstates when people drop before R1).
    counts = round_match_counts(conn, eid)
    max_matches_in_a_round = max(counts.values()) if counts else 0
    active_players_est = max_matches_in_a_round * 2
    active_players = max(active_players_est, ev["num_players"] or 0) if active_players_est else (ev["num_players"] or 0)
    expected_swiss = swiss_round_count(active_players_est) if active_players_est else swiss_round_count(ev["num_players"])

    # Total rounds in the event (recorded + missing). If total <= expected_swiss,
    # the event had NO cut — missing rounds are Swiss rounds, not bracket.
    gap_max = max(gap_rnums)
    total_rounds = max(max(counts.keys()) if counts else 0, gap_max)
    has_cut = total_rounds > expected_swiss

    prior_was_swiss = prior_rnd <= expected_swiss

    def fmt_pairing(m, with_score=False):
        if m["winner"]:
            return f"{m['winner']} beat {(m['p2'] if m['winner']==m['p1'] else m['p1'])}"
        return f"{m['p1']} vs {m['p2']}"

    def fmt_pairings(matches):
        return "; ".join(fmt_pairing(m) for m in matches)

    lines = []

    # ---- All-Swiss-missing case (event had no cut, just Swiss rounds) ----
    if not has_cut:
        rng = f"R{first_gap}–R{last_gap}" if (last_gap - first_gap == len(gap_rnums) - 1) and len(gap_rnums) > 1 else ", ".join(f"R{n}" for n in gap_rnums)
        lines.append(f"**Missing {rng} of Swiss.** {active_players or '?'} active players — only R{prior_rnd if prior_rnd>=1 else 1} was entered. Anyone there remember the rest of Swiss?")
        return lines

    # ---- Multiple missing rounds (cut bracket) ----
    if len(gap_rnums) > 1:
        rng = f"R{first_gap}–R{last_gap}" if (last_gap - first_gap == len(gap_rnums) - 1) else ", ".join(f"R{n}" for n in gap_rnums)
        # QF recorded all-decided → SF + Final missing
        if prior_n == 4 and prior_decided == 4 and not prior_was_swiss:
            lines.append(f"**Missing {rng} (top cut SF + Final).** QF winners: {', '.join(prior_winners)}. Who played whom in SF, and who won the Final?")
        elif prior_n == 2 and not prior_was_swiss:
            # SF was recorded; we know pairings — winners may or may not be set
            if prior_decided == 2:
                lines.append(f"**Missing the Final.** SF winners advancing: {', '.join(prior_winners)}. Who won the Final?")
            else:
                lines.append(f"**Missing {rng}.** SF pairings on record but no winners yet ({fmt_pairings(prior)}). Who won each SF and the Final?")
        else:
            names = ", ".join(p["display_name"] for p in top[:4])
            lines.append(f"**Missing {rng} (entire top cut).** Top 4 from Swiss: {names}. Bracket pairings + winners?")
        return lines

    # ---- Single round missing ----
    rgap = gap_rnums[0]

    # Prior was Swiss → missing round is almost certainly a single Top-2 Final
    if prior_was_swiss and len(top) >= 2:
        # Hedge if the runner-up is tied with #3 (and beyond): list the candidates
        tied = [p["display_name"] for p in standings if p["w"] == top[1]["w"] and p["l"] == top[1]["l"] and p["d"] == top[1]["d"]]
        if len(tied) > 1:
            opp = " / ".join(tied)
            lines.append(f"**Missing the Final** — {top[0]['display_name']} played one of: {opp} (all tied {top[1]['w']}-{top[1]['l']}-{top[1]['d']} going in). Who was in the Final and who won?")
        else:
            lines.append(f"**Missing the Final** — was it {top[0]['display_name']} vs {top[1]['display_name']}? Who won (2-0 / 2-1)?")
        return lines

    # Prior was cut SF (2 matches) — gap is the Final
    if prior_n == 2 and not prior_was_swiss:
        if prior_decided == 2:
            lines.append(f"**Missing the Final** — was it {prior_winners[0]} vs {prior_winners[1]}? Who won (2-0 / 2-1)?")
        else:
            lines.append(f"**Missing the Final, and we don't have the SF winners either.** SF pairings: {fmt_pairings(prior)}. Who won each SF and the Final?")
        return lines

    # Prior was cut QF (4 matches) — gap is SF
    if prior_n == 4 and not prior_was_swiss:
        if prior_decided == 4:
            lines.append(f"**Missing R{rgap} (SF).** QF winners advancing: {', '.join(prior_winners)}. Who played whom and who won?")
        else:
            lines.append(f"**Missing R{rgap}.** QF pairings on record but not all results in ({fmt_pairings(prior)}). Who won QF + SF + Final?")
        return lines

    # Fallback
    if len(top) >= 2:
        names = ", ".join(p["display_name"] for p in top[:4])
        lines.append(f"**Missing R{rgap}.** Top of standings going in: {names}. Who played whom and who won?")
    else:
        lines.append(f"**Missing R{rgap}.** Pairings + winners?")
    return lines


def main():
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    events = conn.execute("""
        SELECT e.event_id, e.platform, e.event_date, e.store, e.location, e.name,
               e.num_players, e.season,
               GROUP_CONCAT(g.round_number, ',') AS gap_rnums
        FROM gap_rounds g JOIN events e ON e.event_id = g.event_id
        WHERE e.is_ignored = 0 AND g.filled_matches = 0
        GROUP BY e.event_id ORDER BY e.event_date, e.event_id
    """).fetchall()

    out = []
    out.append("**Hey Chicagoland Lorcana folks 👋**")
    out.append("")
    out.append("Building a season-long ELO leaderboard from all our set champ results, "
               "but a few events have missing rounds — usually just the Final. If you played at any of these, drop the answer in chat (or DM me) and that's it. 🙏")
    out.append("")

    by_season = {}
    for ev in events:
        by_season.setdefault(ev["season"], []).append(ev)

    for season, evs in by_season.items():
        out.append(f"__**{season}**__")
        out.append("")
        for ev in evs:
            rnums = sorted(int(x) for x in ev["gap_rnums"].split(","))
            url = event_url(ev["event_id"], ev["platform"])
            date_short = ev["event_date"][5:]  # MM-DD
            out.append(f"**{date_short} · {ev['store']}, {ev['location']}**  <{url}>")
            for line in build_ask(conn, ev, rnums):
                out.append(f"> {line}")
            out.append("")

    out.append("Thanks!! 🎉")

    p = Path(__file__).parent / "community_message.md"
    p.write_text("\n".join(out), encoding="utf-8")
    print(f"wrote {p.name} ({len(events)} events)")


if __name__ == "__main__":
    main()
