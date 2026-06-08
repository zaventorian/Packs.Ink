"""Suggest melee → RPH aliases by name similarity.

Outputs two CSVs:
  - aliases_auto.csv       : exact + normalized matches (very high confidence;
                             review then apply directly)
  - alias_suggestions.csv  : fuzzy matches (review, copy good ones into aliases.csv)

Tiers:
  exact      melee Username == RPH display_name (confidence 1.00)
  normalized lower(alnum-only) matches            (confidence 0.95)
  fuzzy      difflib ratio >= 0.85 on either raw or token-sort   (0.70-0.94)

Use apply_aliases.py to import a confirmed CSV.

Usage:
    python suggest_aliases.py
    python suggest_aliases.py --min-ratio 0.80   # widen the fuzzy net
"""
import argparse, csv, re, sqlite3
from difflib import SequenceMatcher
from pathlib import Path

DB_PATH = Path(__file__).parent / "lorcana_elo.db"


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def token_sort(s):
    """Lowercase, alphanum tokens, sorted — for matching reordered words."""
    toks = re.findall(r"[a-z0-9]+", s.lower())
    return "".join(sorted(toks))


def ratio(a, b):
    return SequenceMatcher(None, a, b).ratio()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-ratio", type=float, default=0.85,
                    help="minimum fuzzy ratio to surface (default 0.85)")
    ap.add_argument("--top-k", type=int, default=3,
                    help="max candidates per melee player in suggestions file")
    args = ap.parse_args()

    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row

    melee = conn.execute(
        "SELECT player_id, display_name, external_username FROM players WHERE platform='melee' AND merged_into_id IS NULL"
    ).fetchall()
    rph = conn.execute(
        "SELECT player_id, display_name FROM players WHERE platform='rph' AND merged_into_id IS NULL"
    ).fetchall()

    # Pre-index RPH names
    rph_by_norm = {}
    for r in rph:
        rph_by_norm.setdefault(norm(r["display_name"]), []).append(r)
    rph_by_tok = {}
    for r in rph:
        rph_by_tok.setdefault(token_sort(r["display_name"]), []).append(r)

    # Pre-compute melee match counts (for prioritization)
    play_counts = dict(conn.execute("""
        SELECT p.player_id, COUNT(*) FROM players p
        JOIN matches m ON (m.player1_id=p.player_id OR m.player2_id=p.player_id)
        WHERE p.platform='melee' GROUP BY p.player_id
    """).fetchall())

    auto_rows = []        # exact + normalized -> high confidence
    suggest_rows = []     # fuzzy -> needs review

    for mp in melee:
        m_name = mp["display_name"]
        m_norm = norm(m_name)
        m_tok = token_sort(m_name)
        n_matches = play_counts.get(mp["player_id"], 0)

        # tier 1 + 2: normalized match (covers exact)
        if m_norm in rph_by_norm:
            for r in rph_by_norm[m_norm]:
                confidence = 1.00 if m_name == r["display_name"] else 0.95
                evidence = "exact" if confidence == 1.00 else "normalized"
                auto_rows.append({
                    "melee_player_id": mp["player_id"],
                    "melee_name": m_name,
                    "rph_player_id": r["player_id"],
                    "rph_name": r["display_name"],
                    "confidence": confidence,
                    "evidence": evidence,
                    "melee_matches_played": n_matches,
                    "approve": "y",
                })
            continue

        # tier 3: fuzzy. Compute ratio against all RPH names but skip wildly different lengths
        candidates = []
        m_len = max(len(m_norm), 1)
        for r in rph:
            r_norm = norm(r["display_name"])
            if not r_norm: continue
            r_len = max(len(r_norm), 1)
            if min(m_len, r_len) / max(m_len, r_len) < 0.5:
                continue  # length differs too much
            # token-sort ratio (catches "Last First" vs "First Last")
            r_tok = token_sort(r["display_name"])
            raw_r = ratio(m_norm, r_norm)
            tok_r = ratio(m_tok, r_tok) if r_tok != r_norm else raw_r
            best = max(raw_r, tok_r)
            if best >= args.min_ratio:
                candidates.append((best, r))

        candidates.sort(key=lambda x: -x[0])
        for score, r in candidates[:args.top_k]:
            suggest_rows.append({
                "melee_player_id": mp["player_id"],
                "melee_name": m_name,
                "rph_player_id": r["player_id"],
                "rph_name": r["display_name"],
                "confidence": round(score, 3),
                "evidence": f"fuzzy:{score:.2f}",
                "melee_matches_played": n_matches,
                "approve": "",  # blank — user fills 'y' to confirm
            })

    auto_path = Path(__file__).parent / "aliases_auto.csv"
    sug_path  = Path(__file__).parent / "alias_suggestions.csv"
    cols = ["melee_player_id","melee_name","rph_player_id","rph_name",
            "confidence","evidence","melee_matches_played","approve"]
    for path, rows in [(auto_path, auto_rows), (sug_path, suggest_rows)]:
        rows.sort(key=lambda r: (-r["melee_matches_played"], -float(r["confidence"])))
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            for r in rows: w.writerow(r)

    # summary
    print(f"melee players unmerged: {len(melee)}")
    print(f"  exact + normalized matches: {len(auto_rows)} -> {auto_path.name}")
    print(f"  fuzzy candidates (ratio >= {args.min_ratio}): {len(suggest_rows)} -> {sug_path.name}")
    n_with_any = len({r['melee_player_id'] for r in suggest_rows})
    print(f"  unique melee players with at least one fuzzy candidate: {n_with_any}")
    print(f"  melee players with NO candidate at all: {len(melee) - len({r['melee_player_id'] for r in auto_rows} | {r['melee_player_id'] for r in suggest_rows})}")
    print()
    print(f"Review {auto_path.name} (set approve=n to skip any), then:")
    print(f"  python apply_aliases.py {auto_path.name}")
    print(f"Review {sug_path.name}, set approve=y on confirmed rows, then:")
    print(f"  python apply_aliases.py {sug_path.name}")


if __name__ == "__main__":
    main()
