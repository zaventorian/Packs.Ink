"""Are intentional draws separable from real draws in what RPH gives us?

Read-only, no network. RPH records no intent flag, and the game score does NOT
supply one either: an ID is commonly entered as 1-1-1 (a game each plus a drawn
game), which is byte-identical to a Bo3 that ran out of time at one game each.
`matches` has no games_drawn column, so both land as games_won 1/1. Section 2
prints the score distribution per tier precisely so that stays visible — if the
strong tier is all 1-1 the score is confirmed dead as a signal, and if some IDs
land 0-0 it is worth a second look.

What is left is position and company:
  - IDs sit in the CLOSING rounds of Swiss (commonly the last two, not just the
    last), where a draw is enough to lock a slot.
  - Both players make the cut. That is the point of the draw.
  - They come in correlated clusters at the top tables; a real draw is an
    isolated accident at a random table.

    python scripts/elo/analyze_draws.py [--db PATH] [--season "..."] [--id-window 2]
"""
import argparse, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB_PATH = Path(__file__).parent / "lorcana_elo.db"
WIN_PTS, DRAW_PTS = 3, 1


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
        for m in matches:
            if m["round_number"] != rn:
                continue
            for p in (m["player1_id"], m["player2_id"]):
                if p is not None:
                    out[(p, rn)] = pts[p]
        for m in matches:
            if m["round_number"] != rn:
                continue
            p1, p2, w = m["player1_id"], m["player2_id"], m["winner_id"]
            if m["is_bye"]:
                pts[p1] += WIN_PTS
            elif w is not None:
                pts[w] += WIN_PTS
            elif p1 is not None and p2 is not None:
                pts[p1] += DRAW_PTS; pts[p2] += DRAW_PTS
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--season", default=None, help="restrict to one season label")
    ap.add_argument("--id-window", type=int, default=2,
                    help="how many closing Swiss rounds can hold an ID (default 2)")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    has_standings = bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='event_standings_official'"
    ).fetchone())

    where = "e.is_ignored = 0 AND m.source != 'forfeit'"
    params = []
    if args.season:
        where += " AND e.season = ?"; params.append(args.season)

    rows = [dict(r) for r in conn.execute(f"""
        SELECT m.match_id, m.event_id, m.round_number, m.table_number, m.is_bye,
               m.player1_id, m.player2_id, m.winner_id,
               m.games_won_p1, m.games_won_p2,
               e.name AS event_name, e.event_date
        FROM matches m JOIN events e ON e.event_id = m.event_id
        WHERE {where}
        ORDER BY e.event_date, m.event_id, m.round_number, m.table_number
    """, params)]
    places = {}
    if has_standings:
        places = {(r["event_id"], r["player_id"]): r["place"] for r in conn.execute(
            "SELECT event_id, player_id, place FROM event_standings_official")}
    conn.close()

    if not rows:
        print("no matches — wrong --db path, or the season label doesn't exist"); return

    by_event = defaultdict(list)
    for r in rows:
        by_event[r["event_id"]].append(r)

    played, cut_of, cut_size, entering = [], {}, {}, {}
    for eid, ms in by_event.items():
        sizes = Counter(m["round_number"] for m in ms if not m["is_bye"])
        cut = cut_rounds(dict(sizes))
        cut_of[eid] = cut
        swiss = sorted(set(sizes) - cut)
        # first cut round pairs the whole cut, so 2x its matches is the cut size
        cut_size[eid] = 2 * sizes[min(cut)] if cut else 0
        entering.update({(eid,) + k: v for k, v in points_entering(ms, swiss).items()})
        closing = set(swiss[-args.id_window:])
        for m in ms:
            if m["is_bye"] or m["winner_id"] is not None:
                continue
            m["_closing"] = m["round_number"] in closing
            m["_cut_rd"] = m["round_number"] in cut
            m["_last"] = swiss[-1] if swiss else None
            played.append(m)

    in_cut_players = defaultdict(set)
    for eid, ms in by_event.items():
        for m in ms:
            if m["round_number"] in cut_of[eid]:
                in_cut_players[eid].update({m["player1_id"], m["player2_id"]})

    def made_cut(eid, pid):
        if pid in in_cut_players[eid]:
            return True
        pl, n = places.get((eid, pid)), cut_size.get(eid, 0)
        return bool(pl and n and pl <= n)

    # Contention is judged ENTERING the round, not by who finally made the cut.
    # A player can ID in the second-to-last round and still lose the last one and
    # miss — an outcome gate calls that real, which is backwards: the draw was
    # agreed while both were playing for the same slot. The cut line is the
    # points held by the player sitting at the cut position going in.
    cut_line = {}
    for (eid, pid, rn), pts in entering.items():
        cut_line.setdefault((eid, rn), []).append(pts)
    for key, vals in cut_line.items():
        n = cut_size.get(key[0], 0)
        vals.sort(reverse=True)
        cut_line[key] = vals[n - 1] if n and len(vals) >= n else None

    def contending(m, pid):
        line = cut_line.get((m["event_id"], m["round_number"]))
        pts = entering.get((m["event_id"], pid, m["round_number"]))
        return line is not None and pts is not None and pts >= line

    draws = played
    per_round = Counter((m["event_id"], m["round_number"]) for m in draws)
    n_all = sum(1 for r in rows if not r["is_bye"])
    print(f"{n_all} matches over {len(by_event)} events · {len(draws)} draws "
          f"({100*len(draws)/n_all:.2f}%)\n")

    def tier(m):
        if m["_cut_rd"]:
            return "in-cut"          # elimination can't draw — data error, inspect
        if not m["_closing"]:
            return "real"            # too early to be worth a draw
        both = contending(m, m["player1_id"]) and contending(m, m["player2_id"])
        if both and per_round[(m["event_id"], m["round_number"])] > 1:
            return "ID-strong"
        return "ID-likely" if both else "unclear"

    for m in draws:
        m["_tier"] = tier(m)
    tiers = Counter(m["_tier"] for m in draws)

    print(f"1. TIERS  (closing window = last {args.id_window} Swiss rounds)")
    for t in ("ID-strong", "ID-likely", "unclear", "real", "in-cut"):
        print(f"   {t:<10} {tiers[t]:5d}")
    print("   ID-strong = closing round + both in cut contention + another draw that round")
    print("   ID-likely = same, but the only draw in its round")
    print("   unclear   = closing round, but at least one player was out of contention")
    missed = sum(1 for m in draws if m["_tier"].startswith("ID")
                 and not (made_cut(m["event_id"], m["player1_id"])
                          and made_cut(m["event_id"], m["player2_id"])))
    print(f"   {missed} ID-tier draws involve a player who ultimately MISSED the cut "
          f"— an outcome gate would wrongly call those real")
    # A league night with no cut has nothing to draw INTO, so "made the cut" is
    # unanswerable there and every closing draw falls to unclear. That is the
    # honest outcome, but it has to be visible or the tier reads as a miss.
    nocut = [e for e in by_event if not cut_of[e]]
    if nocut:
        blind = sum(1 for m in draws if m["event_id"] in nocut and m["_closing"])
        print(f"   {len(nocut)} of {len(by_event)} events recorded no cut "
              f"({blind} closing draws there can only ever be unclear)")

    print("\n2. GAME SCORE PER TIER — is the score worth anything at all?")
    dec = Counter((r["games_won_p1"], r["games_won_p2"])
                  for r in rows if not r["is_bye"] and r["winner_id"] is not None)
    print("   decisive: " + ", ".join(f"{a}-{b}:{n}" for (a, b), n in dec.most_common(5)))
    for t in ("ID-strong", "ID-likely", "unclear", "real"):
        c = Counter((m["games_won_p1"], m["games_won_p2"]) for m in draws if m["_tier"] == t)
        if c:
            print(f"   {t:<10} " + ", ".join(f"{a}-{b}:{n}" for (a, b), n in c.most_common(5)))
    print("   -> 0-0 and 1-1-1 both read as agreed, so expect no split here; a tier that")
    print("      is all one shape is evidence the score is decoration, not signal")

    print("\n3. POSITION")
    off = Counter()
    for m in draws:
        if m["_last"] is not None and not m["_cut_rd"]:
            off[m["_last"] - m["round_number"]] += 1
    print("   rounds before the last Swiss round: " +
          ", ".join(f"-{k}:{v}" for k, v in sorted(off.items())))
    print("   -> if -1 is comparable to -0, the window genuinely needs to be 2")
    tt = sorted(m["table_number"] for m in draws
                if m["_tier"].startswith("ID") and m["table_number"] is not None)
    if tt:
        print(f"   ID-tier draw tables: median {tt[len(tt)//2]}, "
              f"{sum(1 for t in tt if t <= 4)}/{len(tt)} at tables 1-4")

    print("\n4. SAMPLE — ID-strong, with match points held entering the round")
    for m in [d for d in draws if d["_tier"] == "ID-strong"][:10]:
        e, rn = m["event_id"], m["round_number"]
        a = entering.get((e, m["player1_id"], rn)); b = entering.get((e, m["player2_id"], rn))
        print(f"   e{e} R{rn} t{m['table_number']} {a}pts vs {b}pts "
              f"({m['games_won_p1']}-{m['games_won_p2']})  {m['event_name'][:40]}")
    if not has_standings:
        print("\n   note: event_standings_official is missing, so 'made the cut' relies")
        print("   only on players appearing in a recorded cut round.")


if __name__ == "__main__":
    main()
