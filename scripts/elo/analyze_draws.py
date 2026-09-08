"""Report on recorded draws: which look agreed, which look played, and whether
the game score is telling you anything at all.

Read-only, no network. Classification lives in draw_classify.py; this only
prints. Section 2 is the one that settles the open question — it cross-tabulates
the game score against position, so:

  * if 0-0 draws cluster in the closing rounds and 1-1 draws are spread evenly
    across every round, then "1-1 is a real draw, otherwise an ID" holds;
  * if 1-1 draws ALSO cluster in the closing rounds at the top tables, then IDs
    are being entered 1-1-1 as well and that rule silently keeps them in.

    python scripts/elo/analyze_draws.py [--db PATH] [--season "..."]
                                        [--id-window 2] [--rule position]
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


def score_key(m):
    a, b = m["games_won_p1"], m["games_won_p2"]
    return "0-0" if dc.agreed_score(m) else f"{a}-{b}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--season", default=None)
    ap.add_argument("--id-window", type=int, default=2,
                    help="how many closing Swiss rounds can hold an ID (default 2)")
    ap.add_argument("--rule", choices=dc.RULES, default="position")
    ap.add_argument("--player", default=None,
                    help="dump this player's draws individually (substring, case-insensitive)")
    ap.add_argument("--since", default=None, help="with --player: only events on/after YYYY-MM-DD")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows, places = dc.load(conn, args.season)
    conn.close()
    if not rows:
        print("no matches — wrong --db path, or the season label doesn't exist"); return

    draws, meta = dc.classify(rows, places, args.id_window, args.rule)
    n_all = sum(1 for r in rows if not r["is_bye"])
    print(f"{n_all} matches over {meta['events']} events · {len(draws)} draws "
          f"({100*len(draws)/n_all:.2f}%) · rule={args.rule}\n")

    tiers = Counter(m["_tier"] for m in draws)
    print(f"1. TIERS  (closing window = last {args.id_window} Swiss rounds)")
    for t in ("ID-strong", "ID-likely", "unclear", "real", "in-cut"):
        print(f"   {t:<10} {tiers[t]:5d}")
    missed = sum(1 for m in draws if dc.is_intentional(m) and not m["_made_cut"])
    print(f"   {missed} ID-tier draws involve a player who ultimately MISSED the cut")
    print("   — judging by the final cut instead of contention would lose those")
    if meta["no_cut"]:
        blind = sum(1 for m in draws if m["event_id"] in meta["no_cut"] and m["_closing"])
        print(f"   {len(meta['no_cut'])} of {meta['events']} events recorded no cut "
              f"({blind} closing draws there can only ever be unclear)")

    print("\n2. SCORE vs POSITION — does '1-1 means real' hold?")
    print("   Read the 0-0 row against the 1-1 row. If 1-1 is genuinely time")
    print("   running out, it should NOT lean on the closing rounds.")
    shapes = Counter(score_key(m) for m in draws)
    print(f"   {'score':<8}{'n':>6}{'closing':>9}{'%':>6}{'contested':>11}{'%':>6}   med.table")
    for shape, n in shapes.most_common(6):
        sel = [m for m in draws if score_key(m) == shape]
        cl = sum(1 for m in sel if m["_closing"] and not m["_cut_rd"])
        cn = sum(1 for m in sel if m["_made_cut"])
        tt = sorted(m["table_number"] for m in sel if m["table_number"] is not None)
        med = tt[len(tt) // 2] if tt else "-"
        print(f"   {shape:<8}{n:>6}{cl:>9}{100*cl/n:>5.0f}%{cn:>11}{100*cn/n:>5.0f}%{med:>12}")
    print("   -> a 1-1 row with closing% near the 0-0 row's means IDs are entered")
    print("      1-1-1 too, and score-only would silently keep them in the ratings")

    print("\n3. POSITION")
    off = Counter()
    for m in draws:
        if m["_last"] is not None and not m["_cut_rd"]:
            off[m["_last"] - m["round_number"]] += 1
    print("   rounds before the last Swiss round: " +
          ", ".join(f"-{k}:{v}" for k, v in sorted(off.items())))
    print("   -> a fat tail at -3/-4 is unintentional draws; they cannot be IDs")

    if args.player:
        # A named false negative is the most informative bug report this can get,
        # so print the gates rather than the verdict: which one rejected it is
        # the whole answer.
        needle = args.player.lower()
        hits = [m for m in draws
                if needle in (m.get("p1_name") or "").lower()
                or needle in (m.get("p2_name") or "").lower()]
        if args.since:
            hits = [m for m in hits if (m["event_date"] or "") >= args.since]
        print(f"\n5. DRAWS FOR {args.player!r}"
              + (f" SINCE {args.since}" if args.since else "") + f" — {len(hits)}")
        for m in hits:
            e, rn = m["event_id"], m["round_number"]
            a = meta["entering"].get((e, m["player1_id"], rn))
            b = meta["entering"].get((e, m["player2_id"], rn))
            print(f"   {m['event_date']} e{e} R{rn} t{m['table_number']} "
                  f"{m['p1_name']} vs {m['p2_name']}")
            print(f"      score={score_key(m)}  closing={m['_closing']}  "
                  f"cut_round={m['_cut_rd']}  pts={a} vs {b}  "
                  f"both_made_cut={m['_made_cut']}  -> {m['_tier']}")

    print("\n4. SAMPLE — intentional, with match points held entering the round")
    for m in [d for d in draws if d["_tier"] == "ID-strong"][:10]:
        e, rn = m["event_id"], m["round_number"]
        a = meta["entering"].get((e, m["player1_id"], rn))
        b = meta["entering"].get((e, m["player2_id"], rn))
        print(f"   e{e} R{rn} t{m['table_number']} {a}pts vs {b}pts "
              f"({score_key(m)})  {m['event_name'][:40]}")


if __name__ == "__main__":
    main()
