"""Guards the draw classifier in analyze_draws.py.

    python scripts/elo/test_analyze_draws.py

No network. Builds a real SQLite event in a temp file and runs the script.
Three pieces of arithmetic here drift silently — nothing throws, the tiers just
quietly become wrong:

  1. CUT DETECTION. phase_type is only stored for gap rounds, so Swiss vs top
     cut is inferred from round sizes. Get it wrong and the "closing rounds"
     window points at elimination rounds, where a draw cannot happen.
  2. POINTS ENTERING THE ROUND. Off by one round and every contention test is
     answered with the standings AFTER the draw it is judging.
  3. CONTENTION, NOT OUTCOME. A player can intentionally draw in the
     second-to-last round, lose the last one and miss the cut. Judging by who
     finally made it calls that draw real, which is backwards — the agreement
     happened while both were playing for the same slot.
"""
from __future__ import annotations
import sqlite3, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import analyze_draws as ad  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


print("cut detection")
check("top-8 cut split off a 6-round Swiss",
      sorted(ad.cut_rounds({1: 32, 2: 32, 3: 32, 4: 32, 5: 32, 6: 32, 7: 4, 8: 2, 9: 1})),
      [7, 8, 9])
# a 32-player Swiss round holds 16 matches and a Top-16 opener holds 8, so the
# halving walk would swallow the last Swiss round without the repeat guard
check("32-player Swiss not eaten by a Top-16 cut",
      sorted(ad.cut_rounds({1: 16, 2: 16, 3: 16, 4: 16, 5: 8, 6: 4, 7: 2, 8: 1})),
      [5, 6, 7, 8])
check("a league night with no cut", sorted(ad.cut_rounds({1: 8, 2: 8, 3: 8})), [])

print("points entering the round")
ms = [
    {"round_number": 1, "player1_id": 1, "player2_id": 2, "winner_id": 1, "is_bye": 0},
    {"round_number": 1, "player1_id": 3, "player2_id": None, "winner_id": None, "is_bye": 1},
    {"round_number": 2, "player1_id": 1, "player2_id": 3, "winner_id": None, "is_bye": 0},
    {"round_number": 3, "player1_id": 1, "player2_id": 3, "winner_id": 1, "is_bye": 0},
]
pts = ad.points_entering(ms, [1, 2, 3])
check("round 1 starts everyone at zero", pts[(1, 1)], 0)
check("a win is worth 3", pts[(1, 2)], 3)
check("a bye is worth 3", pts[(3, 2)], 3)
check("a draw is worth 1 to each", (pts[(1, 3)], pts[(3, 3)]), (4, 4))
check("a player who sits a round gets no entry for it", (2, 3) in pts, False)

print("bubble event end to end")
# 16 players, 4 Swiss rounds, top 4. Players 1-4 all hold 6 points entering R3
# and the top two tables draw; 2 and 3 then lose R4 and are passed on points, so
# both agreed draws involve someone who missed the cut.
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "t.db"
    c = sqlite3.connect(db)
    c.executescript((HERE / "schema.sql").read_text())
    c.execute("INSERT INTO events (event_id,name,event_date,season,is_ignored)"
              " VALUES (3,'SC Bubble','2026-08-03','X',0)")
    for i in range(1, 17):
        c.execute("INSERT INTO players (player_id,display_name) VALUES (?,?)", (i, f"P{i}"))
    mid = 0

    def add(rn, t, p1, p2, w, g1=2, g2=1):
        global mid
        mid += 1
        c.execute("INSERT INTO matches (match_id,event_id,round_id,round_number,table_number,"
                  "player1_id,player2_id,winner_id,games_won_p1,games_won_p2,is_bye)"
                  " VALUES (?,3,?,?,?,?,?,?,?,?,0)", (mid, rn, rn, t, p1, p2, w, g1, g2))

    for t, (a, b) in enumerate([(1, 9), (2, 10), (3, 11), (4, 12),
                                (5, 13), (6, 14), (7, 15), (8, 16)], 1):
        # table 8 is an isolated real draw, recorded 1-1 exactly like an ID
        add(1, t, a, b, None if t == 8 else a, *((1, 1) if t == 8 else (2, 1)))
    for t, (a, b) in enumerate([(1, 5), (2, 6), (3, 7), (4, 8),
                                (9, 13), (10, 14), (11, 15), (12, 16)], 1):
        add(2, t, a, b, a)
    add(3, 1, 1, 2, None, 1, 1)
    add(3, 2, 3, 4, None, 1, 1)
    for t, (a, b) in enumerate([(9, 10), (11, 12), (5, 6), (7, 8), (13, 14), (15, 16)], 3):
        add(3, t, a, b, a)
    for t, (a, b, w) in enumerate([(1, 3, 1), (4, 2, 4), (9, 11, 9), (10, 12, 10),
                                   (5, 7, 5), (6, 8, 6), (13, 15, 13), (14, 16, 14)], 1):
        add(4, t, a, b, w)
    for t, (a, b) in enumerate([(1, 10), (4, 9)], 1):
        add(5, t, a, b, a)
    add(6, 1, 1, 4, 1)
    c.commit(); c.close()

    out = subprocess.run([sys.executable, str(HERE / "analyze_draws.py"), "--db", str(db)],
                         capture_output=True, text=True).stdout

    def tier_count(name):
        for line in out.splitlines():
            if line.strip().startswith(name + " "):
                return int(line.split()[-1])
        return None

    check("both agreed draws land ID-strong", tier_count("ID-strong"), 2)
    check("the isolated round-1 draw stays real", tier_count("real"), 1)
    check("nothing lands in an elimination round", tier_count("in-cut"), 0)
    check("the cut-outcome gate would have lost both",
          "2 ID-tier draws involve a player who ultimately MISSED" in out, True)
    check("entering points are reported at the draw, not after",
          "6pts vs 6pts" in out, True)

print()
print(f"{len(failures)} failure(s)" if failures else "all passed")
sys.exit(1 if failures else 0)
