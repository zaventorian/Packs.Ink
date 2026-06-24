"""
terapeak_clean.py — clean + classify scraped Terapeak graded sales.

Stage 1: for every raw sale row decide what it IS before matching to a card:
  - EXCLUDE_LOT        multi-card listing (lot / pick-your-card / set / bundle)
  - EXCLUDE_SEALED     sealed product (booster box/pack, trove, gift set)
  - EXCLUDE_ACCESSORY  not a card (toploader, sleeve, stand, tool, ...)
  - EXCLUDE_RAW        explicitly ungraded ("gradeable", "raw", "ungraded")
  - GRADED             single graded card, grader + grade parsed from title
  - NEEDS_GRADE        single graded card but no grade token in the title
                       (read grade off the slab thumbnail in a later stage)

Global dedup by item_id first (a sale can appear in >1 grader file). Card
matching is a later stage. Run:
    python scripts/terapeak_clean.py
    python scripts/terapeak_clean.py --samples 12
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
OUT = HERE / "terapeak_output"

GRADERS = ("PSA", "CGC", "BGS", "SGC", "TAG", "BECKETT", "CSG", "HGA", "ACE")
GR = r"(?:PSA|CGC|BGS|SGC|TAG|BECKETT|CSG|HGA|ACE)"
GVAL = r"(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5|4\.5|4|3\.5|3|2\.5|2|1\.5|1)"

# grader then grade, allowing NO separator ("CGC9.5") or qualifiers ("PSA GEM MINT 10")
GRADE_RE = re.compile(
    r"\b(" + GR + r")[\s.:#-]*"
    r"(?:GRADE[\sD]*|GEM[\s-]*MINT\s*|GEM[\s-]*MT\s*|MINT\s*|PRISTINE\s*)?" + GVAL + r"\b",
    re.I,
)
# grade then grader ("GEM MINT 10 PSA", "9.5 BGS")
GRADE_RE_REV = re.compile(GVAL + r"\s*(" + GR + r")\b", re.I)

LOT_RE = re.compile(
    r"\b(lot|lots|bundle|bundles|playset|joblot|job lot|wholesale|bulk|"
    r"complete set|master set|full set|base set|set of \d|\d+\s*card set|"
    r"pick your|you pick|your pick|pick a|pick \d|you choose|choose your|"
    r"choose a|multi[- ]?buy|[2-9]\d*\s+cards\b|x\s?\d{2,}|\d{2,}\s?x)\b",
    re.I,
)
# sealed product (not a graded single)
SEALED_RE = re.compile(
    r"\b(booster box|booster pack|sleeved booster|illumineer'?s? trove|trove|"
    r"gift set|starter deck|sealed|prerelease|pre-release|booster bundle|"
    r"display box|booster case)\b",
    re.I,
)
# true accessories — NO bare "box" (gift/collector box promos are single cards),
# NO "protector" (Kida - Protector of Atlantis is a card name)
ACC_RE = re.compile(
    r"\b(toploaders?|top loader|sleeves?|st[aä]nder|screw\s?down|"
    r"magnetic (?:holder|case)|card saver|deck box|binder|playmat|"
    r"centering tool|slab case|graded card case|acrylic (?:case|stand|display))\b",
    re.I,
)
RAW_RE = re.compile(r"\b(gradeable|ungraded|un-graded|raw card|not graded|no grade)\b", re.I)
# other-TCG / non-Lorcana cards that leaked into the grader searches
OTHER_TCG_RE = re.compile(
    r"\b(kingdom hearts|weiss schwarz|one piece|pok[eé]mon|yugioh|yu-gi-oh|"
    r"magic the gathering|topps|panini)\b", re.I)


def parse_grade(title: str):
    m = GRADE_RE.search(title)
    if m:
        g = m.group(1).upper()
        return ("BGS" if g == "BECKETT" else g), m.group(2)
    m = GRADE_RE_REV.search(title)
    if m:
        g = m.group(2).upper()
        return ("BGS" if g == "BECKETT" else g), m.group(1)
    return None, None


def grader_present(title: str):
    t = title.upper()
    for g in GRADERS:
        if re.search(r"\b" + g + r"\b", t):
            return "BGS" if g == "BECKETT" else g
    return None


def classify(title: str, file_grader: str):
    t = title or ""
    if OTHER_TCG_RE.search(t):
        return "EXCLUDE_OTHER_TCG", None, None
    if LOT_RE.search(t):
        return "EXCLUDE_LOT", None, None
    if SEALED_RE.search(t):
        return "EXCLUDE_SEALED", None, None
    if ACC_RE.search(t):
        return "EXCLUDE_ACCESSORY", None, None
    if RAW_RE.search(t):
        return "EXCLUDE_RAW", None, None
    grader, grade = parse_grade(t)
    if grade:
        return "GRADED", grader or file_grader, grade
    return "NEEDS_GRADE", grader_present(t) or file_grader, None


def load_all_dedup():
    """All rows across the 6 grader files, deduped by item_id (global). Returns
    (rows, n_total_lines, n_cross_file_dupes)."""
    seen = {}
    total = dupes = 0
    for f in sorted(glob.glob(str(OUT / "lorcana_*.jsonl"))):
        name = os.path.basename(f)
        if any(ch.isdigit() for ch in name.split("_")[-1][:4]):
            continue
        fg = name.replace("lorcana_", "").replace(".jsonl", "").upper()
        if fg == "BECKETT":
            fg = "BGS"
        for line in open(f, encoding="utf-8"):
            if not line.strip():
                continue
            r = json.loads(line)
            total += 1
            k = r.get("item_id") or f"{r.get('title')}|{r.get('avg_sold_price')}|{r.get('date_last_sold_text')}"
            if k in seen:
                dupes += 1
                continue
            r["_file_grader"] = fg
            seen[k] = r
    return list(seen.values()), total, dupes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=10)
    args = ap.parse_args()

    rows, total_lines, dupes = load_all_dedup()
    print(f"raw lines: {total_lines}   cross-file dupes removed: {dupes}   "
          f"unique sales: {len(rows)}\n")

    buckets = collections.defaultdict(list)
    grader_counts = collections.Counter()
    for r in rows:
        cat, grader, grade = classify(r.get("title", ""), r["_file_grader"])
        buckets[cat].append((r, grader, grade))
        if cat == "GRADED":
            grader_counts[grader] += 1

    print("CLASSIFICATION:")
    order = ("GRADED", "NEEDS_GRADE", "EXCLUDE_LOT", "EXCLUDE_SEALED",
             "EXCLUDE_ACCESSORY", "EXCLUDE_RAW")
    for cat in order:
        n = len(buckets[cat])
        print(f"  {cat:18} {n:6}  ({n/len(rows)*100:4.1f}%)")
    print("\nGRADER (GRADED):",
          ", ".join(f"{g}:{c}" for g, c in grader_counts.most_common()))

    for cat in ("EXCLUDE_LOT", "EXCLUDE_SEALED", "EXCLUDE_ACCESSORY",
                "EXCLUDE_RAW", "NEEDS_GRADE"):
        b = buckets[cat]
        if not b:
            continue
        print(f"\n--- {cat} ({len(b)}) samples ---")
        step = max(1, len(b) // args.samples)
        for r, grader, grade in b[::step][:args.samples]:
            print(f"  {(r.get('title') or '')[:80]}")


if __name__ == "__main__":
    main()
