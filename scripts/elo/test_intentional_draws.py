"""Guards intentional-draw classification and its effect on ratings.

    python scripts/elo/test_intentional_draws.py

No network. Builds a real SQLite event in a temp file and runs the script.
Three pieces of arithmetic here drift silently — nothing throws, the tiers just
quietly become wrong:

  1. CUT DETECTION. phase_type is only stored for gap rounds, so Swiss vs top
     cut is inferred from round sizes. Get it wrong and the "closing rounds"
     window points at elimination rounds, where a draw cannot happen.
  2. POINTS ENTERING THE ROUND. Off by one round and every contention test is
     answered with the standings AFTER the draw it is judging.
  3. RATINGS. A flagged ID must hold both ratings FLAT while still scoring
     0.5. Skipping the row instead would delete the draw from the player's
     record and from mw_pct, since every W/L/D count in the Supabase views is
     derived from elo_ratings.score.
  4. CONTENTION, NOT OUTCOME. A player can intentionally draw in the
     second-to-last round, lose the last one and miss the cut. Judging by who
     finally made it calls that draw real, which is backwards — the agreement
     happened while both were playing for the same slot.
"""
from __future__ import annotations
import sqlite3, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import draw_classify as ad  # noqa: E402

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
# ...and counting ALONE cannot tell that apart from a Swiss round that landed on
# the expected count once players dropped. A drawn match is the tiebreaker:
# single elimination has to produce a winner, so a round holding a draw is Swiss.
_shrunk = {1: 11, 2: 11, 3: 11, 4: 11, 5: 8, 6: 4, 7: 2, 8: 1}
check("a shrunken last Swiss round IS swallowed on counts alone",
      sorted(ad.cut_rounds(_shrunk)), [5, 6, 7, 8])
check("a draw in it stops the walk (e200747 R5)",
      sorted(ad.cut_rounds(_shrunk, {5})), [6, 7, 8])
check("a bogus draw inside a real cut costs only its own round",
      sorted(ad.cut_rounds(_shrunk, {7})), [8])
check("a draw in the final leaves no cut at all",
      sorted(ad.cut_rounds(_shrunk, {8})), [])

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
        # t8 played out to 1-1; t7 is an early 0-0, which no competitive player
        # agrees in round 1 — it is where the two rules disagree
        res = {7: (None, 0, 0), 8: (None, 1, 1)}.get(t, (a, 2, 1))
        add(1, t, a, b, *res)
    for t, (a, b) in enumerate([(1, 9), (2, 10), (3, 11), (4, 12),
                                (5, 13), (6, 14), (7, 15), (8, 16)], 1):
        add(2, t, a, b, a)
    # two top tables agree at 0-0; the table beside them plays out to 1-1, with
    # the same round and the same standing, so the score is the only difference
    add(3, 1, 1, 2, None, 0, 0)
    add(3, 2, 3, 4, None, 0, 0)
    # the Zaven case: an agreed draw entered 1-1-1, same round and same six
    # points as the two above. `position` requires 0-0 and so calls it real;
    # `position-only` ignores the score and catches it.
    add(3, 3, 5, 6, None, 1, 1)
    for t, (a, b) in enumerate([(7, 8), (9, 10), (11, 12), (13, 14), (15, 16)], 4):
        add(3, t, a, b, a)
    for t, (a, b, w) in enumerate([(1, 3, 1), (4, 2, 4), (5, 7, 5), (6, 8, 6),
                                   (9, 11, 9), (10, 12, 10), (13, 15, 13), (14, 16, 14)], 1):
        add(4, t, a, b, w)
    for t, (a, b) in enumerate([(1, 4), (5, 6)], 1):
        add(5, t, a, b, a)
    add(6, 1, 1, 5, 1)
    c.commit(); c.close()

    def run_rule(rule):
        return subprocess.run(
            [sys.executable, str(HERE / "analyze_draws.py"), "--db", str(db), "--rule", rule],
            capture_output=True, text=True).stdout

    out = run_rule("position")

    def tier_count(name, text=None):
        for line in (text or out).splitlines():
            if line.strip().startswith(name + " "):
                return int(line.split()[-1])
        return None

    check("both agreed draws land ID-strong", tier_count("ID-strong"), 2)
    check("a played-out 1-1 is real even in the same round, at the same points",
          tier_count("real"), 3)
    check("nothing lands in an elimination round", tier_count("in-cut"), 0)
    check("the cut-outcome gate would have lost both",
          "2 ID-tier draws involve a player who ultimately MISSED" in out, True)
    po = run_rule("position-only")
    check("position-only catches the 1-1 agreed draw position misses",
          tier_count("ID-strong", po), 3)
    check("...and still leaves the early draws alone", tier_count("real", po), 2)

    so = run_rule("score-only")
    check("score-only flags the round-1 0-0 that position rejects",
          tier_count("ID-likely", so), 3)
    check("...and both rules agree 1-1 is played out", tier_count("real", so), 2)
    check("entering points are reported at the draw, not after",
          "6pts vs 6pts" in out, True)

print("the default rule")
# The default is the whole finding: an ID entered 1-1-1 is invisible to any rule
# that requires 0-0, and that is how Zaven was told to enter one. A silent revert
# to `position` would quietly stop flagging that entire convention again.
check("draw_classify names score-or-position", ad.DEFAULT_RULE, "score-or-position")
check("...and it is a real rule", ad.DEFAULT_RULE in ad.RULES, True)
for mod in ("analyze_draws", "flag_intentional_draws"):
    src = (HERE / f"{mod}.py").read_text()
    check(f"{mod} defers to it", 'default=dc.DEFAULT_RULE' in src, True)
refresh = (HERE.parent / "refresh_elo.py").read_text()
check("refresh_elo defers to it", "default=_dc.DEFAULT_RULE" in refresh, True)
# the choices list here was stale once already — it never gained position-only
check("...and takes its choices from the same place", "choices=list(_dc.RULES)" in refresh, True)

print("ratings")
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "r.db"
    c = sqlite3.connect(db)
    c.executescript((HERE / "schema.sql").read_text())
    c.execute("INSERT INTO events (event_id,name,event_date,season,is_ignored)"
              " VALUES (1,'E','2026-08-01','X',0)")
    for i in (1, 2, 3, 4):
        c.execute("INSERT INTO players (player_id,display_name) VALUES (?,?)", (i, f"P{i}"))
    rows = [  # round 1 opens a rating gap, round 2 draws it two different ways
        (1, 1, 1, 1, 2, 1, 2, 0, 0), (2, 1, 2, 3, 4, 3, 2, 0, 0),
        (3, 2, 1, 1, 2, None, 0, 0, 1), (4, 2, 2, 3, 4, None, 1, 1, 0)]
    for mid, rn, t, p1, p2, w, g1, g2, idf in rows:
        c.execute("INSERT INTO matches (match_id,event_id,round_id,round_number,table_number,"
                  "player1_id,player2_id,winner_id,games_won_p1,games_won_p2,is_bye,"
                  "is_intentional_draw) VALUES (?,1,?,?,?,?,?,?,?,?,0,?)",
                  (mid, rn, rn, t, p1, p2, w, g1, g2, idf))
    c.commit(); c.close()

    import elo  # noqa: E402
    elo.DB_PATH = db
    elo.compute()
    c = sqlite3.connect(db)
    got = {(r[0], r[1]): (round(r[3] - r[2], 4), r[4]) for r in c.execute(
        "SELECT player_id, match_id, rating_before, rating_after, score FROM ratings")}
    c.close()
    check("a flagged ID moves neither rating",
          (got[(1, 3)][0], got[(2, 3)][0]), (0.0, 0.0))
    check("...but is still scored 0.5, so the record still says D",
          (got[(1, 3)][1], got[(2, 3)][1]), (0.5, 0.5))
    check("an unflagged draw still moves ratings",
          got[(3, 4)][0] != 0.0 and got[(4, 4)][0] != 0.0, True)
    check("the two are equal and opposite",
          round(got[(3, 4)][0] + got[(4, 4)][0], 6), 0.0)

print()

print("manual overrides")
_rows = [
    {"event_id": 9, "round_number": 2, "table_number": 0, "_tier": "real"},
    {"event_id": 9, "round_number": 5, "table_number": 1, "_tier": "ID-strong"},
    {"event_id": 9, "round_number": 3, "table_number": 2, "_tier": "in-cut"},
]
_miss = ad.apply_overrides(_rows, force_id={(9, 2, 0): "why", (9, 3, 2): "why"},
                           force_real={(9, 5, 1): "why"})
check("an override forces a draw the rule called real", _rows[0]["_tier"], "ID-manual")
check("...and can force one back to real", _rows[1]["_tier"], "real-manual")
check("...and outranks in-cut", _rows[2]["_tier"], "ID-manual")
check("a forced ID still counts as intentional", ad.is_intentional(_rows[0]), True)
check("a forced real does not", ad.is_intentional(_rows[1]), False)
check("everything matched, so nothing is reported stale", _miss, [])
# the failure that matters: a key that stopped matching is a ruling that
# silently reverted, so it has to be reported rather than shrugged off
check("a dead key is reported",
      ad.apply_overrides([], force_id={(1, 1, 1): "gone"}, force_real={}),
      [(1, 1, 1)])
check("every shipped override carries a reason",
      all(str(v).strip() for v in
          {**ad.draw_overrides.FORCE_ID, **ad.draw_overrides.FORCE_REAL}.values()), True)
check("manual tiers are in the printed list",
      ("ID-manual" in ad.TIERS and "real-manual" in ad.TIERS), True)

print("0-0 needs no position support")
# Zaven's 2025-05-11 e100267947 R3, minimised: an 8-player, 3-round event where
# the 0-0 sits in the closing window but neither player clears the cut line, so
# position-only calls it `unclear`. It is an ID; nobody finished a game.
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "score.db"
    c = sqlite3.connect(db)
    c.executescript((HERE / "schema.sql").read_text())
    c.execute("INSERT INTO events (event_id,name,event_date,season,is_ignored)"
              " VALUES (5,'SC Small','2026-08-17','X',0)")
    for i in range(1, 9):
        c.execute("INSERT INTO players (player_id,display_name) VALUES (?,?)", (i, f"R{i}"))
    k = [0]

    def addm(rn, t, p1, p2, w, g1=2, g2=1):
        k[0] += 1
        c.execute("INSERT INTO matches (match_id,event_id,round_id,round_number,table_number,"
                  "player1_id,player2_id,winner_id,games_won_p1,games_won_p2,is_bye)"
                  " VALUES (?,5,?,?,?,?,?,?,?,?,0)", (k[0], rn, rn, t, p1, p2, w, g1, g2))

    # R1: the 0-0 is at table 4, between two players who go on to finish 1-1-1
    addm(1, 4, 7, 8, None, 0, 0)
    for t, (a, b) in enumerate([(1, 5), (2, 6), (3, 4)], 1):
        addm(1, t, a, b, a)
    for t, (a, b) in enumerate([(1, 2), (3, 5), (4, 6), (7, 8)], 1):
        addm(2, t, a, b, a)
    for t, (a, b) in enumerate([(1, 3), (2, 4), (5, 7), (6, 8)], 1):
        addm(3, t, a, b, a)
    c.commit(); c.close()

    def rule_out(rule):
        return subprocess.run(
            [sys.executable, str(HERE / "analyze_draws.py"), "--db", str(db), "--rule", rule],
            capture_output=True, text=True).stdout

    po = rule_out("position-only")
    check("position-only leaves an unsupported 0-0 on the table",
          (tier_count("ID-strong", po) or 0) + (tier_count("ID-likely", po) or 0), 0)
    sp = rule_out("score-or-position")
    check("score-or-position flags it",
          (tier_count("ID-strong", sp) or 0) + (tier_count("ID-likely", sp) or 0), 1)

print("a swallowed last Swiss round still yields its ID")
# The e200747 shape, minimised: R3 holds 4 matches sitting above a 2/1 cut, so
# the halving walk reads it as the top-4 opener and the draw in it disappears as
# `in-cut` — losing a confirmed ID. R2 holds 5, so the repeat guard cannot help.
with tempfile.TemporaryDirectory() as td:
    db = Path(td) / "swallow.db"
    c = sqlite3.connect(db)
    c.executescript((HERE / "schema.sql").read_text())
    c.execute("INSERT INTO events (event_id,name,event_date,season,is_ignored)"
              " VALUES (4,'SC Shrunk','2026-08-10','X',0)")
    for i in range(1, 11):
        c.execute("INSERT INTO players (player_id,display_name) VALUES (?,?)", (i, f"Q{i}"))
    n = [0]

    def addm(rn, t, p1, p2, w, g1=2, g2=1):
        n[0] += 1
        c.execute("INSERT INTO matches (match_id,event_id,round_id,round_number,table_number,"
                  "player1_id,player2_id,winner_id,games_won_p1,games_won_p2,is_bye)"
                  " VALUES (?,4,?,?,?,?,?,?,?,?,0)", (n[0], rn, rn, t, p1, p2, w, g1, g2))

    for t, (a, b) in enumerate([(1, 6), (2, 7), (3, 8), (4, 9), (5, 10)], 1):
        addm(1, t, a, b, a)
    for t, (a, b) in enumerate([(1, 2), (3, 4), (5, 6), (7, 8), (9, 10)], 1):
        addm(2, t, a, b, a)
    # R3: two players dropped, so 4 matches — the count the walk is expecting.
    # Table 1 is the agreed draw, both sides on 6 points at the top of the field.
    addm(3, 1, 1, 3, None, 0, 0)
    for t, (a, b) in enumerate([(5, 2), (4, 7), (6, 9)], 2):
        addm(3, t, a, b, a)
    for t, (a, b) in enumerate([(1, 5), (3, 4)], 1):   # cut: semis
        addm(4, t, a, b, a)
    addm(5, 1, 1, 3, 1)                                 # cut: final
    c.commit(); c.close()

    out2 = subprocess.run(
        [sys.executable, str(HERE / "analyze_draws.py"), "--db", str(db)],
        capture_output=True, text=True).stdout
    check("the draw is no longer discarded as in-cut", tier_count("in-cut", out2), 0)
    check("it classifies as intentional",
          (tier_count("ID-strong", out2) or 0) + (tier_count("ID-likely", out2) or 0), 1)


print(f"{len(failures)} failure(s)" if failures else "all passed")
sys.exit(1 if failures else 0)
