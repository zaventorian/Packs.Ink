"""
terapeak_match.py — Stage 2: map classified GRADED sales to catalog cards.

Builds on terapeak_clean (Stage 1 classification + global dedup). For every
GRADED row it parses collector number + set hint + name/version tokens from the
title and matches against the `cards` catalog (pulled from Supabase via
scripts/.env). Reports the match rate with samples of matched / ambiguous /
unmatched so we can keep tuning.

    python scripts/terapeak_match.py
    python scripts/terapeak_match.py --samples 15
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_clean import load_all_dedup, classify

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

# EN <n> in a title maps to the nth mainline set. Strongest set signal.
MAINLINE = [
    "The First Chapter", "Rise of the Floodborn", "Into the Inklands",
    "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
    "Reign of Jafar", "Fabled", "Whispers in the Well",
]
# extra set-name aliases -> exact set name in the catalog
SET_ALIASES = {
    "first chapter": "The First Chapter", "1st chapter": "The First Chapter",
    "floodborn": "Rise of the Floodborn",
    "inklands": "Into the Inklands", "ursulas return": "Ursula's Return",
    "shimmering skies": "Shimmering Skies", "azurite": "Azurite Sea",
    "archazia": "Archazia's Island", "reign of jafar": "Reign of Jafar",
    "fabled": "Fabled", "whispers in the well": "Whispers in the Well",
    "wilds unknown": "Wilds Unknown", "winterspell": "Winterspell",
    "epcot": "EPCOT Festival of the Arts",
}
STOP = set("""disney lorcana ravensburger the of a an and en card tcg trading game
psa cgc bgs sgc tag beckett gem mint mt graded grade foil nonfoil non holo holofoil
cold enchanted fabled iconic epic legendary rare super uncommon common promo first
edition ed new near english eng set chapter pristine card slab gemmt""".split())


def norm_cn(cn: str) -> str:
    cn = (cn or "").strip()
    m = re.match(r"^0*(\d+)$", cn)
    return m.group(1) if m else cn.upper()


def toks(s: str):
    out = set()
    for w in re.findall(r"[a-z0-9]+", (s or "").lower()):
        if w in STOP or len(w) < 2 or w.isdigit():
            continue
        out.add(w)
    return out


def fetch_catalog():
    cards = []
    for off in range(0, 9000, 1000):
        r = requests.get(f"{SB_URL}/rest/v1/cards", headers=HEAD, timeout=30, params={
            "select": "id,set_id,name,version,collector_number,rarity,tcgplayer_product_id",
            "offset": off, "limit": 1000, "order": "id"})
        r.raise_for_status()
        b = r.json()
        cards.extend(b)
        if len(b) < 1000:
            break
    return cards


def fetch_sets():
    r = requests.get(f"{SB_URL}/rest/v1/sets", headers=HEAD, timeout=30,
                     params={"select": "id,name"})
    r.raise_for_status()
    return {s["id"]: s["name"] for s in r.json()}


def set_hint(title: str):
    """Best guess at the set name from the title, or None."""
    t = title.lower()
    # promo collector-number suffix is the cleanest signal: "11/P1", "1/P3"
    m = re.search(r"\b\d{1,3}\s*/\s*p([123])\b", t)
    if m:
        return {"1": "Promo Set 1", "2": "Promo Set 2", "3": "Promo Set 3"}[m.group(1)]
    # 2024 D23 Collection vs 2022 D23 Expo (= Promo Set 1, confirmed from catalog)
    if re.search(r"\bd23\b", t):
        if "collection" in t or re.search(r"\b202[45]\b", t):
            return "D23 Collection"
        return "Promo Set 1"
    if re.search(r"\bp1\b|p1[-\s]promo|gencon|gamescom|disney\s?100|\bd100\b", t):
        return "Promo Set 1"
    if re.search(r"\bp2\b|p2[-\s]promo", t):
        return "Promo Set 2"
    if re.search(r"\bp3\b|p3[-\s]promo", t):
        return "Promo Set 3"
    if "challenge" in t:
        return "Challenge Promo"
    # EN <n> -> nth mainline set
    m = re.search(r"\ben[\s-]?(\d{1,2})\b", t)
    if m:
        i = int(m.group(1))
        if 1 <= i <= len(MAINLINE):
            return MAINLINE[i - 1]
    for alias, name in SET_ALIASES.items():
        if alias in t:
            return name
    return None


def strong_collectors(title: str):
    """Unambiguous collector#s only: '#207', '207/204', '11/P1', '10/C1'. The
    denominator must be a set total (>=100) or a promo code (P1/C1/D23) — NOT a
    grade subgrade like '10/10/9.5'. The '#' form takes digits only, so the set
    code in '#D23' isn't read as collector 23."""
    nums = set()
    for m in re.finditer(r"(?<![\d./])(\d{1,3})\s*/\s*(\d{1,3}|[A-Za-z]\d+)", title):
        num, den = m.group(1), m.group(2)
        if den[0].isalpha() or int(den) >= 100:
            nums.add(norm_cn(num))
    for m in re.finditer(r"#\s*(\d{1,3})\b", title):
        nums.add(norm_cn(m.group(1)))
    return {n for n in nums if n}


def collectors(title: str):
    nums = set(strong_collectors(title))
    # bare 1-3 digit numbers as weak collector#s (e.g. "Elsa 207"), AFTER
    # stripping "GRADER N" (the grade) and 4-digit years so they aren't mistaken
    # for collector numbers. These only ADD candidates; scoring still gates.
    t2 = re.sub(r"\b(?:PSA|CGC|BGS|SGC|TAG|BECKETT|CSG|HGA|ACE)\b[\s.:#-]*\d+(?:\.\d)?",
                " ", title, flags=re.I)
    t2 = re.sub(r"\b(?:19|20)\d{2}\b", " ", t2)
    t2 = re.sub(r"\b\d+(?:st|nd|rd|th)\b", " ", t2, flags=re.I)   # ordinals: "1st edition"
    t2 = re.sub(r"\bpop\s*\d+\b", " ", t2, flags=re.I)            # BGS population
    for m in re.finditer(r"(?<![\d/#.])(\d{1,3})(?![\d/.])", t2):
        if int(m.group(1)) >= 100:   # bare numbers <100 are too often ordinals/grades; require # for those
            nums.add(norm_cn(m.group(1)))
    return {n for n in nums if n}


def build_index():
    """Fetch the catalog and build the collector#/token indexes the matcher uses.
    Returns (by_cn, inv, n_cards, n_sets)."""
    cat = fetch_catalog()
    sets = fetch_sets()
    by_cn = collections.defaultdict(list)
    inv = collections.defaultdict(list)       # name/version token -> [card]
    for c in cat:
        c["_tok"] = toks(c.get("name")) | toks(c.get("version"))
        c["_set"] = sets.get(c.get("set_id"), "")
        c["_cn"] = norm_cn(c.get("collector_number"))
        c["_rarity"] = c.get("rarity") or ""
        by_cn[c["_cn"]].append(c)
        for tk in c["_tok"]:
            inv[tk].append(c)
    return by_cn, inv, len(cat), len(sets)


# The 2022 D23 Expo Collector's Set is catalogued as Promo Set 1 #1-7. When a
# title is 2022-D23 but carries NO collector#, the character name alone collides
# with the OTHER same-name promos in Promo Set 1 (e.g. Robin Hood #6 vs the
# unrelated #17 "Capable Fighter"). Bias such titles to the #1-7 D23 cards.
D23_2022_CNS = {"1", "2", "3", "4", "5", "6", "7"}
CHASE_RARITIES = {"Enchanted", "Iconic", "Epic"}


def title_rarity(title: str):
    """The chase rarity named in the title, else None. Enchanted/Iconic/Epic are
    distinct cards (different card_id + collector#) from the base — a title that
    says one should never match the base, and a plain title should never match a
    chase card."""
    t = title.lower()
    if re.search(r"\benchanted\b", t):
        return "Enchanted"
    if re.search(r"\biconic\b", t):
        return "Iconic"
    if re.search(r"\bepic\b", t):
        return "Epic"
    return None


def best_match(title, by_cn, inv):
    ttok = toks(title)
    hint = set_hint(title)
    cns = collectors(title)
    tl = title.lower()
    d23_2022 = bool(re.search(r"\bd23\b", tl)) and not (
        "collection" in tl or re.search(r"\b202[45]\b", tl))
    trar = title_rarity(title)
    cand = {}
    for cn in cns:
        for c in by_cn.get(cn, []):
            cand[id(c)] = c
    for tk in ttok:
        for c in inv.get(tk, []):
            cand[id(c)] = c
    scored = []
    for c in cand.values():
        if not c["_tok"]:
            continue
        nmatch = len(ttok & c["_tok"])
        ov = nmatch / len(c["_tok"])          # how much of the card's name the title covers
        cn_hit = c["_cn"] in cns
        set_hit = bool(hint) and c["_set"] == hint
        set_miss = bool(hint) and c["_set"] != hint
        d23_pref = d23_2022 and c["_set"] == "Promo Set 1" and c["_cn"] in D23_2022_CNS
        crar = c.get("_rarity") or ""
        # Rarity gate: title names a chase rarity → prefer that exact rarity, push
        # away the base + other chases. Plain title → push away chase cards.
        # EXCEPTION: a collector# hit is a STRONGER rarity signal than the keyword.
        # Enchanted/Iconic/Epic each carry their own collector# (e.g. "215/204"),
        # so a title bearing that number points squarely at the chase card even
        # with no rarity word ("Simba Returned King 215/204" → the #215 Enchanted,
        # not the #189 base). When cn_hit, trust the number, don't penalize rarity.
        if trar:
            rarity_ok = (crar == trar)
            if rarity_ok or cn_hit:
                rarity_pref = 0.7 if rarity_ok else 0.0
            else:
                rarity_pref = -0.6 if crar in CHASE_RARITIES else -0.45
        elif cn_hit:
            rarity_ok = True
            rarity_pref = 0.0
        else:
            rarity_ok = (crar not in CHASE_RARITIES)
            rarity_pref = 0.0 if rarity_ok else -0.5
        sc = ov + (0.4 if cn_hit else 0.0) + (0.4 if set_hit else 0.0) \
            + (0.6 if d23_pref else 0.0) + rarity_pref
        if set_miss and ov < 0.9:
            sc -= 0.3
        scored.append((c, ov, cn_hit, set_hit, sc, nmatch, d23_pref, rarity_ok))
    if not scored:
        return None, 0.0, 0.0, False, False
    # Tier 1: the title contains the card's FULL name+version (>=0.85 overlap, >=2
    # tokens). rarity match > d23-2022 pref > collector# > set hint > overlap
    # break ties in the full-name tier.
    strong = [s for s in scored if s[1] >= 0.85 and s[5] >= 2]
    if strong:
        c, ov, cn_hit, set_hit = max(strong, key=lambda s: (s[7], s[6], s[2], s[3], s[1]))[:4]
        sc = next(s[4] for s in strong if s[0] is c)
    else:
        c, ov, cn_hit, set_hit, sc, _, _, _ = max(scored, key=lambda s: s[4])
    return c, sc, ov, cn_hit, set_hit


def match_one(title, by_cn, inv):
    """Resolve one title -> (card_or_None, confidence, cn_conflict)."""
    best, sc, ov, cn_hit, set_hit = best_match(title, by_cn, inv)
    matched = best is not None and (
        (cn_hit and set_hit)
        or (ov >= 0.5 and (cn_hit or set_hit))
        or (cn_hit and ov >= 0.25)
        or (ov >= 0.85)
    )
    if not matched:
        return None, round(sc, 3), False
    scn = strong_collectors(title)
    return best, round(sc, 3), bool(scn and best["_cn"] not in scn)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=12)
    args = ap.parse_args()

    print("Loading scraped sales + classifying ...")
    rows, _, _ = load_all_dedup()
    graded = []
    for r in rows:
        cat, grader, grade = classify(r.get("title", ""), r["_file_grader"])
        if cat == "GRADED":
            r["_grader"], r["_grade"] = grader, grade
            graded.append(r)
    print(f"GRADED rows to match: {len(graded)}")

    print("Fetching catalog ...")
    by_cn, inv, ncards, nsets = build_index()
    print(f"catalog: {ncards} cards, {nsets} sets\n")

    n_match = 0
    unmatched = []
    matched_samp = []
    cn_conflict = []
    for i, r in enumerate(graded):
        best, sc, ov, cn_hit, set_hit = best_match(r.get("title", ""), by_cn, inv)
        # collector# + set both agree -> high confidence (any name overlap);
        # otherwise need a good name + one signal, or an overwhelming name alone
        matched = best is not None and (
            (cn_hit and set_hit)
            or (ov >= 0.5 and (cn_hit or set_hit))
            or (cn_hit and ov >= 0.25)      # exact collector# + partial name (e.g. "Elsa 207")
            or (ov >= 0.85)
        )
        if matched:
            n_match += 1
            r["_card"] = best
            scn = strong_collectors(r.get("title", ""))
            if scn and best["_cn"] not in scn:
                cn_conflict.append((r, best, scn))
            if i % 1500 == 0:
                matched_samp.append((r, best))
        else:
            unmatched.append((r, best, sc, ov))
    n_unmatch = len(unmatched)
    tot = len(graded)
    print("=" * 64)
    print(f"  matched     {n_match:6}  ({n_match/tot*100:4.1f}%)")
    print(f"  unmatched   {n_unmatch:6}  ({n_unmatch/tot*100:4.1f}%)")
    print("=" * 64)

    print(f"\nCN-CONSISTENCY AUDIT (likely wrong matches): {len(cn_conflict)} "
          f"({len(cn_conflict)/max(n_match,1)*100:.2f}% of matches) where the "
          f"title's collector# != the matched card's #")
    for r, c, scn in cn_conflict[:18]:
        print(f"  title#{sorted(scn)} != card#{c['_cn']}  {c['name']} - "
              f"{c.get('version')} ({c['_set']})")
        print(f"     <- {(r.get('title') or '')[:66]}")

    FOREIGN = re.compile(
        r"\b(jap|japan\w*|chinese|china|korea\w*|french|german|italian|spanish|portug\w*)\b", re.I)
    cats = collections.Counter()
    samp = collections.defaultdict(list)
    for r, best, sc, ov in unmatched:
        t = r.get("title", "")
        hint = set_hint(t)
        d23 = bool(re.search(r"\bd23\b", t, re.I))
        promo = bool(re.search(r"\bp[123]\b|promo|gencon|gamescom|disney\s?100|d100", t, re.I))
        if FOREIGN.search(t):
            cat = "foreign / regional"
        elif best and ov >= 0.5 and (d23 or promo or not hint):
            cat = "promo/D23 collision (name matched, no set hint)"
        elif best and ov >= 0.5:
            cat = "near-miss (just under threshold)"
        elif len(toks(t)) <= 2:
            cat = "generic / too few name tokens"
        elif best and ov > 0.2:
            cat = "weak name overlap (abbreviated/odd title)"
        else:
            cat = "no candidate (not in catalog / unparseable)"
        cats[cat] += 1
        if len(samp[cat]) < (60 if "foreign" in cat else 7):
            samp[cat].append((r, best, ov))

    print("\n--- MATCHED audit (spread sample) ---")
    for r, c in matched_samp:
        print(f"  [{r['_grader']} {r['_grade']}] {c['name']} - {c.get('version')} "
              f"({c['_set']} #{c.get('collector_number')})")
        print(f"        <- {(r.get('title') or '')[:72]}")

    print(f"\nUNMATCHED breakdown ({n_unmatch}):")
    for cat, n in cats.most_common():
        print(f"  {n:6} ({n/n_unmatch*100:4.1f}%)  {cat}")
    for cat, _ in cats.most_common():
        print(f"\n  ## {cat} ##")
        for r, best, ov in samp[cat]:
            bc = (f"   => closest: {best['name']} - {best.get('version')} "
                  f"({best['_set']} #{best.get('collector_number')}) ov={ov:.2f}") if best else ""
            print(f"    {(r.get('title') or '')[:66]}{bc}")


if __name__ == "__main__":
    main()
