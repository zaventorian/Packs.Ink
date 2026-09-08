"""Are intentional draws separable from real draws in what RPH gives us?

Read-only, no network. RPH records no intent flag, so this measures the two
signals that stand in for one: the game score (an ID is agreed before play, a
timed-out match usually is not) and where in the event the draw sits (IDs are a
last-Swiss-round phenomenon and they come in correlated clusters at the top
tables; a real draw is an isolated accident at a random table).

The game-score signal only exists if matches are best-of-three — under Bo1 an
ID and a time draw are both 0-0 and the column says nothing. Section 2 is what
settles that, so read it before trusting section 4.

    python scripts/elo/analyze_draws.py [--db PATH] [--season "Wilds Unknown Summer 2026"]
"""
import argparse, sqlite3, sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--season", default=None, help="restrict to one season label")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    where = "e.is_ignored = 0 AND m.is_bye = 0 AND m.source != 'forfeit'"
    params = []
    if args.season:
        where += " AND e.season = ?"; params.append(args.season)

    rows = [dict(r) for r in conn.execute(f"""
        SELECT m.match_id, m.event_id, m.round_number, m.table_number,
               m.winner_id, m.games_won_p1, m.games_won_p2, m.source,
               e.name AS event_name, e.event_date, e.season
        FROM matches m JOIN events e ON e.event_id = m.event_id
        WHERE {where}
        ORDER BY e.event_date, m.event_id, m.round_number, m.table_number
    """, params)]
    conn.close()

    if not rows:
        print("no matches — wrong --db path, or the season label doesn't exist"); return

    sizes = defaultdict(Counter)
    for r in rows:
        sizes[r["event_id"]][r["round_number"]] += 1
    cuts = {eid: cut_rounds(dict(c)) for eid, c in sizes.items()}
    last_swiss = {eid: max([rn for rn in c if rn not in cuts[eid]], default=None)
                  for eid, c in sizes.items()}

    draws = [r for r in rows if r["winner_id"] is None]
    print(f"{len(rows)} matches over {len(sizes)} events · {len(draws)} draws "
          f"({100*len(draws)/len(rows):.2f}%)\n")

    print("1. WHERE DRAWS SIT")
    in_cut = sum(1 for r in draws if r["round_number"] in cuts[r["event_id"]])
    final = sum(1 for r in draws if r["round_number"] == last_swiss[r["event_id"]])
    print(f"   final Swiss round : {final:5d}  ({100*final/len(draws):.1f}%)")
    print(f"   earlier Swiss     : {len(draws)-final-in_cut:5d}")
    print(f"   inside the cut    : {in_cut:5d}   (elimination can't draw — inspect any)")
    by_off = Counter()
    for r in draws:
        ls = last_swiss[r["event_id"]]
        if ls is not None and r["round_number"] not in cuts[r["event_id"]]:
            by_off[ls - r["round_number"]] += 1
    print("   rounds before the last Swiss round: " +
          ", ".join(f"-{k}:{v}" for k, v in sorted(by_off.items())))

    print("\n2. GAME SCORE — does the format even record one?")
    dec = Counter((r["games_won_p1"], r["games_won_p2"])
                  for r in rows if r["winner_id"] is not None)
    print("   decisive matches: " + ", ".join(f"{a}-{b}:{n}" for (a, b), n in dec.most_common(6)))
    print("   -> Bo3 if 2-0/2-1 dominate; Bo1 if 1-0 does (then section 4 is round-position only)")
    dd = Counter((r["games_won_p1"], r["games_won_p2"]) for r in draws)
    print("   draws:           " + ", ".join(f"{a}-{b}:{n}" for (a, b), n in dd.most_common(6)))
    print("   -> 0-0 = no game finished (agreed, or game 1 timed out); 1-1 = they played it out")

    print("\n3. CLUSTERING — IDs are correlated, accidents are not")
    per_round = Counter((r["event_id"], r["round_number"]) for r in draws)
    solo = sum(n for n in per_round.values() if n == 1)
    print(f"   lone draw in its round : {solo}")
    print(f"   2+ draws in one round  : {len(draws)-solo}")
    tt = [r["table_number"] for r in draws
          if r["table_number"] is not None and r["round_number"] == last_swiss[r["event_id"]]]
    if tt:
        tt.sort()
        print(f"   final-round draw tables: median {tt[len(tt)//2]}, "
              f"{sum(1 for t in tt if t <= 4)}/{len(tt)} at tables 1-4")
        print("   -> IDs concentrate at low table numbers; a time draw is uniform")

    print("\n4. VERDICT under the combined heuristic")
    print("   ID  = final Swiss round AND 0-0 AND (another draw in the same round)")
    ids = [r for r in draws
           if r["round_number"] == last_swiss[r["event_id"]]
           and (r["games_won_p1"], r["games_won_p2"]) in ((0, 0), (0, None), (None, 0), (None, None))
           and per_round[(r["event_id"], r["round_number"])] > 1]
    print(f"   {len(ids)} of {len(draws)} draws classified ID "
          f"({100*len(ids)/len(draws):.1f}%), {len(draws)-len(ids)} left as real")
    for r in ids[:8]:
        print(f"     e{r['event_id']} R{r['round_number']} t{r['table_number']} "
              f"{r['event_date']} {r['event_name'][:44]}")


if __name__ == "__main__":
    main()
