"""Mark intentional draws in `matches.is_intentional_draw`.

    python scripts/elo/flag_intentional_draws.py            # dry run, prints only
    python scripts/elo/flag_intentional_draws.py --apply
    python scripts/elo/flag_intentional_draws.py --apply --rule score-only

Classification lives in draw_classify.py — this only writes what it decides.
Run it before `elo.py`; the ratings pass reads the column and holds both
players' ratings flat for a flagged match while still scoring it 0.5, so the
draw stays in the player's record and in mw_pct but stops moving the rating.

Dry run is the default because a wrong rule silently deletes real evidence from
every affected rating. `--unflag` clears every flag in one go, so a bad pass is
always reversible — the same reason graded_sales grew exclude_reason.
"""
import argparse, sqlite3, sys
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import draw_classify as dc

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--season", default=None)
    ap.add_argument("--id-window", type=int, default=2)
    ap.add_argument("--rule", choices=dc.RULES, default="position")
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    ap.add_argument("--unflag", action="store_true", help="clear every flag and stop")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    dc.ensure_column(conn)

    if args.unflag:
        n = conn.execute(f"SELECT count(*) FROM matches WHERE {dc.COLUMN}=1").fetchone()[0]
        if args.apply:
            conn.execute(f"UPDATE matches SET {dc.COLUMN}=0"); conn.commit()
            print(f"cleared {n} flags")
        else:
            print(f"would clear {n} flags (add --apply)")
        conn.close(); return

    rows, places = dc.load(conn, args.season)
    if not rows:
        print("no matches — wrong --db path, or the season label doesn't exist")
        conn.close(); return

    draws, meta = dc.classify(rows, places, args.id_window, args.rule)
    ids = [m for m in draws if dc.is_intentional(m)]
    tiers = Counter(m["_tier"] for m in draws)

    print(f"rule={args.rule} window={args.id_window} · {len(draws)} draws · "
          + " ".join(f"{t}={tiers[t]}" for t in
                     ("ID-strong", "ID-likely", "unclear", "real", "in-cut")))

    # Only ever write within the scope just classified: a --season run must not
    # clear flags on events it never looked at.
    scope = {m["match_id"] for m in rows}
    already = {r[0] for r in conn.execute(
        f"SELECT match_id FROM matches WHERE {dc.COLUMN}=1")} & scope
    want = {m["match_id"] for m in ids}
    add, drop = want - already, already - want
    print(f"  {len(add)} to flag, {len(drop)} to unflag, {len(want & already)} unchanged")

    if not args.apply:
        print("dry run — add --apply to write")
        conn.close(); return

    with conn:
        conn.executemany(f"UPDATE matches SET {dc.COLUMN}=1 WHERE match_id=?",
                         [(i,) for i in add])
        conn.executemany(f"UPDATE matches SET {dc.COLUMN}=0 WHERE match_id=?",
                         [(i,) for i in drop])
    print(f"wrote {len(add)} flags, cleared {len(drop)}. Re-run elo.py to recompute.")
    conn.close()


if __name__ == "__main__":
    main()
