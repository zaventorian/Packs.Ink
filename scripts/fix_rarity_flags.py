"""
fix_rarity_flags.py — re-attribute the "rarity" mismatches the slab-OCR audit
flagged (scripts/_ocr_mismatches.csv, issue=rarity). These are sales where the
title matcher landed an expensive chase sale (Enchanted/Iconic/Epic) on the cheap
BASE card because the chase printing is a separate card_id with no same-set sibling
the OCR reconcile() could move to. The slab read the real rarity + collector#, so
we resolve the correct card here.

Resolution tiers (per flag):
  1. SAME character (cur card's name) + slab rarity + slab collector#  → high confidence
  2. SAME character + slab rarity (when slab cn is blank), if unique     → high confidence
  3. GLOBAL by slab rarity + slab collector#, if unique                  → review (cross-character)
Anything ambiguous is printed and skipped (resolve by hand).

    python scripts/fix_rarity_flags.py            # dry-run (default)
    python scripts/fix_rarity_flags.py --commit   # apply + refresh rollup
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import requests
from pathlib import Path

from ocr_slab_audit import fetch_cards, norm_cn, patch_one, refresh_rollup, SB_URL, HEAD

HERE = Path(__file__).resolve().parent
CSV = HERE / "_ocr_mismatches.csv"
CHASE = {"Enchanted", "Iconic", "Epic"}


def nkey(s):
    """Case/space-insensitive name key — cards.name capitalization is inconsistent
    between base and chase printings ('Can't Hold It' vs 'Can't Hold it')."""
    return " ".join((s or "").lower().split())


def fetch_set_names():
    r = requests.get(f"{SB_URL}/rest/v1/sets", headers=HEAD, timeout=30,
                     params={"select": "id,name"})
    r.raise_for_status()
    return {s["id"]: s["name"] for s in r.json()}


# Abbreviations sellers use that won't substring-match the full set name.
_SET_ALIASES = {
    "rise of the floodborn": ["rotf"],
    "the first chapter": ["first chapter", "1st chapter", "tfc"],
    "into the inklands": ["inklands"],
}


def set_in_title(set_name, title):
    t = (title or "").lower()
    base = re.sub(r"^the ", "", (set_name or "").lower())
    if base and base in t:
        return True
    return any(a in t for a in _SET_ALIASES.get((set_name or "").lower(), []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    cards = fetch_cards()
    by_id = {c["id"]: c for c in cards}
    set_names = fetch_set_names()
    by_name = {}
    for c in cards:
        by_name.setdefault(nkey(c["name"]), []).append(c)

    rows = []
    with open(CSV, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue"] == "rarity":
                rows.append(r)

    print(f"rarity flags: {len(rows)}\n")
    fixes, ambiguous = [], []
    for r in rows:
        cur = by_id.get(r["cur_card_id"])
        if not cur:
            ambiguous.append((r, "cur card not in catalog"))
            continue
        rar, cn, title = r["slab_rarity"], (r["slab_cn"] or "").strip(), r["title"]
        tier, hits = None, []
        if cn:
            cand = [c for c in cards if c["rarity"] == rar and norm_cn(c["collector_number"]) == cn]
            if len(cand) == 1:
                hits, tier = cand, "cn+rarity"
            else:
                # disambiguate the cross-set cn collision by the set named in the title
                by_set = [c for c in cand if set_in_title(set_names.get(c["set_id"]), title)]
                if len(by_set) == 1:
                    hits, tier = by_set, "cn+rarity+set"
                else:
                    # fall back to same character (case-insensitive name)
                    same = [c for c in cand if nkey(c["name"]) == nkey(cur["name"])]
                    if len(same) == 1:
                        hits, tier = same, "cn+rarity+name"
        else:
            same = [c for c in by_name.get(nkey(cur["name"]), []) if c["rarity"] == rar]
            if len(same) == 1:
                hits, tier = same, "name+rarity"
        if len(hits) == 1 and hits[0]["id"] != cur["id"]:
            fixes.append((r, cur, hits[0], tier))
        else:
            ambiguous.append((r, f"{len(hits)} candidates (rar={rar} cn={cn or '—'})"))

    def risk(r, tier):
        t = r["title"] or ""
        if tier == "name+rarity":  # cn blank → slab-rarity OCR only, low confidence
            return "low-confidence (no collector#)"
        if re.search(r"[äöüßÄÖÜ]|domäne|dschafar|\bsusi\b", t, re.I):
            return "looks German (exclude instead)"
        return None

    safe = [(r, cur, tgt, tier) for (r, cur, tgt, tier) in fixes if not risk(r, tier)]
    held = [(r, cur, tgt, tier, risk(r, tier)) for (r, cur, tgt, tier) in fixes if risk(r, tier)]

    for r, cur, tgt, tier in sorted(safe, key=lambda x: -float(x[0]["sale_price"] or 0)):
        print(f"  ${float(r['sale_price']):>8.2f}  {cur['name']} {cur['rarity']} #{cur['collector_number']}"
              f"  ->  {tgt['rarity']} #{tgt['collector_number']}  [{tier}]")
        print(f"            {(r['title'] or '')[:80]}")
    print(f"\n  {len(safe)} will APPLY, {len(held)} held for review, {len(ambiguous)} ambiguous:")
    for r, cur, tgt, tier, why in held:
        print(f"    HOLD  ${float(r['sale_price'] or 0):>8.2f}  {r['cur_card']}  -> {tgt['rarity']} #{tgt['collector_number']}  — {why}")
    for r, why in ambiguous:
        print(f"    SKIP  ${float(r['sale_price'] or 0):>8.2f}  {r['cur_card']}  — {why}")

    if args.commit and safe:
        n = 0
        for r, cur, tgt, tier in safe:
            if patch_one(r["item_id"], tgt["id"]):
                n += 1
        print(f"\ncommitted {n}/{len(safe)} re-attributions")
        refresh_rollup()
        print("rollup refreshed.")
    elif safe:
        print("\ndry-run — re-run with --commit to apply.")


if __name__ == "__main__":
    main()
