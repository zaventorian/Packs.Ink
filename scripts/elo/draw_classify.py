"""Which recorded draws were agreed, and which were actually played?

The single source of truth for that question. `analyze_draws.py` reports it and
`flag_intentional_draws.py` writes it to the DB; both import from here so a
tweak can't leave one of them classifying differently from the other.

RPH records no intent flag, and the game score does not reliably supply one:
an ID is sometimes entered as 1-1-1 (a game each plus a drawn game), which is
byte-identical to a Bo3 that ran out of time at one game each — `matches` has
no games_drawn column, so both store as games_won 1/1. Whether 0-0 vs 1-1
actually separates the two is an empirical question about a given data set;
`analyze_draws.py` cross-tabulates score against position to answer it.

Two rules, hence:
  score-only  0-0 is an ID, anything else is real. The literal reading. It will
              call a round-1 0-0 draw an ID, which no competitive player does.
  position    0-0 AND in the closing rounds of Swiss AND both players in cut
              contention entering the round. The default, because the cost of
              the two errors is not symmetric: wrongly flagging a real draw
              deletes genuine evidence from a rating, while missing an ID only
              leaves today's behaviour in place.
"""
from collections import Counter, defaultdict

WIN_PTS, DRAW_PTS = 3, 1
RULES = ("position", "score-only")

MATCH_COLS = """m.match_id, m.event_id, m.round_number, m.table_number, m.is_bye,
                m.player1_id, m.player2_id, m.winner_id,
                m.games_won_p1, m.games_won_p2"""


def cut_rounds(round_sizes):
    """Round numbers belonging to the single-elimination top cut.

    phase_type ('SWISS' / 'RANKED_SINGLE_ELIMINATION') is only stored for GAP
    rounds, so it has to be inferred: elimination rounds strictly halve toward a
    single final, Swiss rounds hold roughly the same count. Walk back from the
    end expecting 1, 2, 4, 8 ... and stop as soon as a round repeats its
    predecessor's size, which is Swiss and never elimination.
    """
    nums = sorted(round_sizes)
    cut, want = set(), 1
    for i in range(len(nums) - 1, -1, -1):
        rn = nums[i]
        if round_sizes[rn] != want:
            break
        if i > 0 and round_sizes[nums[i - 1]] == want:
            break
        cut.add(rn); want *= 2
    return cut


def points_entering(matches, swiss_rounds):
    """{(player_id, round_number): match points held going into that round}."""
    pts, out = defaultdict(int), {}
    for rn in sorted(swiss_rounds):
        rnd = [m for m in matches if m["round_number"] == rn]
        for m in rnd:
            for p in (m["player1_id"], m["player2_id"]):
                if p is not None:
                    out[(p, rn)] = pts[p]
        for m in rnd:
            p1, p2, w = m["player1_id"], m["player2_id"], m["winner_id"]
            if m["is_bye"]:
                pts[p1] += WIN_PTS
            elif w is not None:
                pts[w] += WIN_PTS
            elif p1 is not None and p2 is not None:
                pts[p1] += DRAW_PTS; pts[p2] += DRAW_PTS
    return out


def load(conn, season=None):
    """(match rows, {(event_id, player_id): final place})."""
    where, params = "e.is_ignored = 0 AND m.source != 'forfeit'", []
    if season:
        where += " AND e.season = ?"; params.append(season)
    rows = [dict(r) for r in conn.execute(
        f"""SELECT {MATCH_COLS}, e.name AS event_name, e.event_date
            FROM matches m JOIN events e ON e.event_id = m.event_id
            WHERE {where}
            ORDER BY e.event_date, m.event_id, m.round_number, m.table_number""", params)]
    places = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                    " AND name='event_standings_official'").fetchone():
        places = {(r["event_id"], r["player_id"]): r["place"] for r in conn.execute(
            "SELECT event_id, player_id, place FROM event_standings_official")}
    return rows, places


def agreed_score(m):
    """No game was finished — nobody sat down. games_won can be NULL on old rows."""
    return (m["games_won_p1"] or 0) == 0 and (m["games_won_p2"] or 0) == 0


def classify(rows, places, id_window=2, rule="position"):
    """Annotate every draw in `rows` with `_tier` and return the draws.

    Tiers: ID-strong / ID-likely / unclear / real / in-cut. Only the two ID
    tiers are treated as intentional by the writer.
    """
    if rule not in RULES:
        raise ValueError(f"rule must be one of {RULES}")

    by_event = defaultdict(list)
    for r in rows:
        by_event[r["event_id"]].append(r)

    draws, cut_of, cut_size, entering, no_cut = [], {}, {}, {}, set()
    for eid, ms in by_event.items():
        sizes = Counter(m["round_number"] for m in ms if not m["is_bye"])
        cut = cut_rounds(dict(sizes))
        cut_of[eid] = cut
        swiss = sorted(set(sizes) - cut)
        # the first cut round pairs the whole cut, so 2x its matches is the size
        cut_size[eid] = 2 * sizes[min(cut)] if cut else 0
        if not cut:
            no_cut.add(eid)
        entering.update({(eid,) + k: v for k, v in points_entering(ms, swiss).items()})
        closing = set(swiss[-id_window:])
        for m in ms:
            if m["is_bye"] or m["winner_id"] is not None:
                continue
            m["_closing"] = m["round_number"] in closing
            m["_cut_rd"] = m["round_number"] in cut
            m["_last"] = swiss[-1] if swiss else None
            draws.append(m)

    in_cut_players = defaultdict(set)
    for eid, ms in by_event.items():
        for m in ms:
            if m["round_number"] in cut_of[eid]:
                in_cut_players[eid].update({m["player1_id"], m["player2_id"]})

    # Contention is judged ENTERING the round, not by who finally made the cut.
    # A player can agree a draw in the second-to-last round, lose the last one
    # and miss — an outcome gate calls that real, which is backwards: the
    # agreement happened while both were playing for the same slot. The line is
    # the points held by the player sitting at the cut position going in.
    line = {}
    for (eid, _pid, rn), pts in entering.items():
        line.setdefault((eid, rn), []).append(pts)
    for key, vals in line.items():
        n = cut_size.get(key[0], 0)
        vals.sort(reverse=True)
        line[key] = vals[n - 1] if n and len(vals) >= n else None

    def contending(m, pid):
        ln = line.get((m["event_id"], m["round_number"]))
        pts = entering.get((m["event_id"], pid, m["round_number"]))
        return ln is not None and pts is not None and pts >= ln

    # The cluster signal is several tables agreeing AT ONCE, so only draws that
    # look agreed corroborate each other. A played-out 1-1 sitting in the same
    # round is not evidence that the table beside it shook hands.
    per_round = Counter((m["event_id"], m["round_number"]) for m in draws
                        if agreed_score(m))
    for m in draws:
        m["_made_cut"] = (m["player1_id"] in in_cut_players[m["event_id"]]
                          and m["player2_id"] in in_cut_players[m["event_id"]]) or all(
            (places.get((m["event_id"], p)) or 0) and cut_size.get(m["event_id"], 0)
            and places[(m["event_id"], p)] <= cut_size[m["event_id"]]
            for p in (m["player1_id"], m["player2_id"]))
        if m["_cut_rd"]:
            m["_tier"] = "in-cut"        # elimination cannot draw — a data error
        elif rule == "score-only":
            m["_tier"] = "ID-likely" if agreed_score(m) else "real"
        elif not agreed_score(m) or not m["_closing"]:
            m["_tier"] = "real"
        elif contending(m, m["player1_id"]) and contending(m, m["player2_id"]):
            m["_tier"] = "ID-strong" if per_round[(m["event_id"], m["round_number"])] > 1 \
                else "ID-likely"
        else:
            m["_tier"] = "unclear"

    return draws, {"per_round": per_round, "entering": entering,
                   "no_cut": no_cut, "events": len(by_event)}


def is_intentional(m):
    return m["_tier"].startswith("ID")


COLUMN = "is_intentional_draw"


def has_column(conn):
    return any(r[1] == COLUMN for r in conn.execute("PRAGMA table_info(matches)"))


def ensure_column(conn):
    """schema.sql is CREATE TABLE IF NOT EXISTS, so an existing DB never picks
    up a new column from it. Idempotent ALTER instead."""
    if not has_column(conn):
        conn.execute(f"ALTER TABLE matches ADD COLUMN {COLUMN} INTEGER NOT NULL DEFAULT 0")
        conn.commit()
