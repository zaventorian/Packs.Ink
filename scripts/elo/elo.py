"""Compute ELO ratings from ingested matches.

Iterates matches chronologically (event_date, round_number, table_number) and
applies standard ELO. Wipes and rewrites the `ratings` table on each run, so the
ELO formula can be tweaked without re-ingesting.

Usage:
    python elo.py                       # default K=32, start=1500
    python elo.py --k 24 --start 1500   # tweak
    python elo.py --top 20              # show top N leaderboard
"""
import argparse, sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def expected(my_rating, opp_rating):
    return 1.0 / (1.0 + 10 ** ((opp_rating - my_rating) / 400.0))


def build_resolver(conn):
    """Return {player_id: canonical_player_id} by following merged_into_id chains."""
    raw = dict(conn.execute("SELECT player_id, merged_into_id FROM players"))
    resolver = {}
    for pid in raw:
        seen, cur = set(), pid
        while raw.get(cur) and cur not in seen:
            seen.add(cur); cur = raw[cur]
        resolver[pid] = cur
    return resolver


def compute(k_factor=32.0, start=1500.0):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    resolver = build_resolver(conn)

    matches = conn.execute(
        """
        SELECT m.match_id, m.event_id, m.round_number, m.table_number,
               m.player1_id, m.player2_id, m.winner_id, m.is_bye,
               e.event_date
        FROM matches m
        JOIN events  e ON e.event_id = m.event_id
        WHERE e.is_ignored = 0
        ORDER BY e.event_date ASC,
                 m.event_id ASC,         -- keep each event's matches contiguous
                                         -- so multi-event days (or placeholder
                                         -- shared dates) don't interleave a
                                         -- player's chain across events.
                 m.round_number ASC,
                 m.table_number ASC,
                 m.match_id ASC
        """
    ).fetchall()

    ratings = {}  # player_id -> current rating
    history_rows = []

    for m in matches:
        if m["is_bye"]:
            continue
        raw_p1, raw_p2, raw_w = m["player1_id"], m["player2_id"], m["winner_id"]
        if raw_p1 is None or raw_p2 is None:
            continue
        # resolve through merged_into_id so aliased melee/rph accounts share a curve
        p1 = resolver.get(raw_p1, raw_p1)
        p2 = resolver.get(raw_p2, raw_p2)
        if p1 == p2:
            continue  # self-match after merge — skip
        winner = resolver.get(raw_w, raw_w) if raw_w is not None else None

        r1 = ratings.get(p1, start)
        r2 = ratings.get(p2, start)

        if winner == p1:
            s1, s2 = 1.0, 0.0
        elif winner == p2:
            s1, s2 = 0.0, 1.0
        else:
            s1, s2 = 0.5, 0.5

        e1 = expected(r1, r2)
        new_r1 = r1 + k_factor * (s1 - e1)
        new_r2 = r2 + k_factor * (s2 - (1.0 - e1))

        history_rows.append((p1, m["match_id"], r1, new_r1, p2, r2, k_factor, s1))
        history_rows.append((p2, m["match_id"], r2, new_r2, p1, r1, k_factor, s2))

        ratings[p1] = new_r1
        ratings[p2] = new_r2

    with conn:
        conn.execute("DELETE FROM ratings")
        conn.executemany(
            """INSERT INTO ratings
               (player_id, match_id, rating_before, rating_after,
                opponent_id, opponent_rating, k_factor, score)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            history_rows,
        )

    conn.close()
    return ratings


def leaderboard(top=25, min_matches=3):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """
        WITH last_rating AS (
            SELECT player_id,
                   rating_after AS rating,
                   COUNT(*) OVER (PARTITION BY player_id) AS n_matches,
                   ROW_NUMBER() OVER (PARTITION BY player_id ORDER BY rating_id DESC) AS rn
            FROM ratings
        ),
        peak AS (
            SELECT player_id, MAX(rating_after) AS peak_rating FROM ratings GROUP BY player_id
        ),
        wins AS (
            SELECT player_id,
                   SUM(CASE WHEN score = 1.0 THEN 1 ELSE 0 END) AS w,
                   SUM(CASE WHEN score = 0.0 THEN 1 ELSE 0 END) AS l,
                   SUM(CASE WHEN score = 0.5 THEN 1 ELSE 0 END) AS d
            FROM ratings GROUP BY player_id
        )
        SELECT p.display_name, lr.rating, lr.n_matches, pk.peak_rating,
               w.w, w.l, w.d
        FROM last_rating lr
        JOIN players p ON p.player_id = lr.player_id
        JOIN peak pk   ON pk.player_id = lr.player_id
        JOIN wins w    ON w.player_id  = lr.player_id
        WHERE lr.rn = 1 AND lr.n_matches >= ?
        ORDER BY lr.rating DESC
        LIMIT ?
        """,
        (min_matches, top),
    ).fetchall()
    conn.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=float, default=32.0)
    ap.add_argument("--start", type=float, default=1500.0)
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--min-matches", type=int, default=3,
                    help="hide players with fewer matches (default 3)")
    args = ap.parse_args()

    print(f"computing ELO (K={args.k}, start={args.start})...")
    ratings = compute(k_factor=args.k, start=args.start)
    print(f"  rated {len(ratings)} players\n")

    rows = leaderboard(top=args.top, min_matches=args.min_matches)
    print(f"TOP {len(rows)} (min {args.min_matches} matches)")
    print(f"{'#':>3}  {'rating':>6}  {'peak':>6}  {'W-L-D':>9}  player")
    print("-" * 60)
    for i, r in enumerate(rows, 1):
        wld = f"{r['w']}-{r['l']}-{r['d']}"
        print(f"{i:>3}  {r['rating']:>6.0f}  {r['peak_rating']:>6.0f}  {wld:>9}  {r['display_name']}")


if __name__ == "__main__":
    main()
