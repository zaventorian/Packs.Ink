"""
terapeak_match.py — feasibility harness for attributing scraped Terapeak
graded-sale rows to catalog cards by parsing the listing title.

Reads a *.jsonl produced by terapeak_scrape.py, parses each title into
(grader, grade, collector#, name tokens, printing), and matches it against the
`cards` catalog (pulled live from Supabase). Prints a match-rate report plus
sample matches and misses so we can judge whether title-attribution is viable
before building the real loader.

Usage:
    python scripts/terapeak_match.py scripts/terapeak_output/lorcana_psa_*.jsonl
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

GRADERS = ("PSA", "CGC", "BGS", "SGC", "TAG", "BECKETT")

# Tokens that carry no identifying signal — stripped before name matching.
STOP = {
    "disney", "lorcana", "ravensburger", "the", "of", "a", "an", "and", "en",
    "card", "tcg", "trading", "game", "psa", "cgc", "bgs", "sgc", "tag",
    "beckett", "gem", "mint", "graded", "grade", "foil", "nonfoil", "non",
    "holo", "holofoil", "cold", "enchanted", "fabled", "iconic", "epic",
    "legendary", "rare", "super", "uncommon", "common", "promo", "first",
    "edition", "ed", "new", "near", "english", "eng", "set", "chapter",
}


def fetch_catalog() -> list[dict]:
    cards: list[dict] = []
    step = 1000
    for off in range(0, 8000, step):
        r = requests.get(
            f"{SB_URL}/rest/v1/cards", headers=HEAD, timeout=30,
            params={
                "select": "id,set_id,name,version,collector_number,rarity,"
                          "tcgplayer_product_id",
                "offset": off, "limit": step, "order": "id",
            },
        )
        r.raise_for_status()
        batch = r.json()
        cards.extend(batch)
        if len(batch) < step:
            break
    return cards


def fetch_sets() -> dict[str, str]:
    r = requests.get(f"{SB_URL}/rest/v1/sets", headers=HEAD, timeout=30,
                     params={"select": "id,name"})
    r.raise_for_status()
    return {s["id"]: s["name"] for s in r.json()}


def toks(s: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if w in STOP or len(w) < 2 or w.isdigit():
            continue
        out.add(w)
    return out


def norm_cn(cn: str) -> str:
    cn = (cn or "").strip()
    m = re.match(r"^0*(\d+)$", cn)
    return m.group(1) if m else cn.upper()


def parse_grade(title: str):
    t = title.upper()
    for g in GRADERS:
        m = re.search(rf"\b{g}\b\s*([0-9]{{1,2}}(?:\.5)?)", t)
        if m:
            return ("BGS" if g == "BECKETT" else g), m.group(1)
    # grader named without an adjacent number
    for g in GRADERS:
        if re.search(rf"\b{g}\b", t):
            return ("BGS" if g == "BECKETT" else g), None
    return None, None


def parse_collectors(title: str) -> set[str]:
    """Candidate collector numbers pulled from the title."""
    nums: set[str] = set()
    # "207/204", "42/204", "14/P2", "12/C1"
    for m in re.finditer(r"(?<![\d./])(\d{1,3})\s*/\s*(?:\d{1,3}|[A-Z]\d+)", title):
        nums.add(norm_cn(m.group(1)))
    # "#207", "#7", "#P1"
    for m in re.finditer(r"#\s*([A-Za-z]?\d{1,3})", title):
        nums.add(norm_cn(re.sub(r"^[A-Za-z]", "", m.group(1))))
    return {n for n in nums if n}


def main() -> None:
    patterns = sys.argv[1:] or ["scripts/terapeak_output/lorcana_psa_*.jsonl"]
    files: list[str] = []
    for p in patterns:
        files.extend(glob.glob(p))
    if not files:
        sys.exit(f"No files matched: {patterns}")
    newest = max(files, key=os.path.getmtime)
    rows = [json.loads(l) for l in open(newest, encoding="utf-8")]
    print(f"Loaded {len(rows)} rows from {Path(newest).name}\n")

    print("Fetching catalog from Supabase ...")
    cat = fetch_catalog()
    sets = fetch_sets()
    by_cn: dict[str, list[dict]] = defaultdict(list)
    for c in cat:
        c["_tok"] = toks(c.get("name")) | toks(c.get("version"))
        c["_setname"] = sets.get(c.get("set_id"), "")
        by_cn[norm_cn(c.get("collector_number"))].append(c)
    print(f"Catalog: {len(cat)} cards across {len(sets)} sets\n")

    n_graded = n_nograder = 0
    n_match = n_ambig = n_miss = 0
    matches, misses = [], []

    for r in rows:
        title = r.get("title") or ""
        grader, grade = parse_grade(title)
        if not grader:
            n_nograder += 1
            continue
        n_graded += 1

        cns = parse_collectors(title)
        ttok = toks(title)
        cands: list[dict] = []
        for cn in cns:
            cands.extend(by_cn.get(cn, []))

        best, best_score = None, 0.0
        for c in cands:
            ct = c["_tok"]
            if not ct:
                continue
            overlap = len(ttok & ct)
            score = overlap / len(ct)
            # nudge when the set name appears in the title
            if c["_setname"] and toks(c["_setname"]) & ttok:
                score += 0.25
            if score > best_score:
                best, best_score = c, score

        if best and best_score >= 0.5:
            n_match += 1
            if len(matches) < 18:
                matches.append((title, grader, grade, best))
        elif cands:
            n_ambig += 1
            if len(misses) < 18:
                misses.append(("AMBIG", title, [f"{c['name']} - {c.get('version')}" for c in cands[:3]]))
        else:
            n_miss += 1
            if len(misses) < 18:
                misses.append(("NO-CN ", title, []))

    print("=" * 70)
    print(f"ROWS                 {len(rows)}")
    print(f"  no grader (raw/acc) {n_nograder}")
    print(f"  graded              {n_graded}")
    print(f"    matched           {n_match}  ({n_match/max(n_graded,1)*100:.1f}% of graded)")
    print(f"    ambiguous         {n_ambig}")
    print(f"    unmatched         {n_miss}")
    print("=" * 70)

    print("\n--- sample MATCHES ---")
    for title, gr, gd, c in matches:
        print(f"  [{gr} {gd}] {c['name']} - {c.get('version')}  ({c['_setname']} #{c.get('collector_number')})")
        print(f"        <- {title}")

    print("\n--- sample MISSES (graded but unmatched) ---")
    for tag, title, cand in misses:
        print(f"  {tag}  {title}")
        if cand:
            print(f"        cands: {cand}")


if __name__ == "__main__":
    main()
