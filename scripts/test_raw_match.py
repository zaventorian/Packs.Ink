"""Guard for raw_match's gates. No network, no .env, synthetic catalog.

Run: python scripts/test_raw_match.py

Every failure this protects against is SILENT -- a bad gate does not raise, it
publishes a wrong price on a card whose price nobody can check, which is the one
thing this pipeline exists not to do. Three classes, and each is pinned in BOTH
directions, because over-tightening a gate costs real sales just as quietly:

  * gate 1 leaks put a SLAB's price on a raw card. Every pattern asserted here
    was found leaking in the live corpus, up to a $17,500 "Gem Mint 10" with no
    grader name in the title. Tightened too far it eats "Near Mint", which is
    what most raw listings actually say about themselves.
  * pins and merch wear the card's NAME, so they satisfy every identity gate
    there is -- a $8 D23 pin and a $34 poster both attribute cleanly to cards
    worth four figures. Tightened too far, `print` eats "1st Print" (367 corpus
    hits) and `custom` eats "Picky Customer".
  * gate 2 is the one that cannot be re-derived from the data: with no collector
    number and no set hint, same-named cards TIE on name tokens and the winner is
    arbitrary. The corpus puts $1.75 on a $1,350 promo that way.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# terapeak_match reads Supabase credentials at import time (it owns the catalog
# fetch). Neutralised so this guard runs anywhere, including CI.
os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")

import terapeak_clean as tc   # noqa: E402
import terapeak_match as tm   # noqa: E402
import raw_match as rm        # noqa: E402
from raw_watchlist import WATCHLIST, queries  # noqa: E402

# A slice of the real catalog: each watchlist card here is paired with the
# same-named sibling that actually competes with it in the live data.
# (id, name, version, cn, rarity, set)
CARDS = [
    ("p1_1",    "Mickey Mouse", "Brave Little Tailor", "1",   "Promo", "Promo Set 1"),
    ("d23_1",   "Mickey Mouse", "Brave Little Tailor", "1",   "Promo", "D23 Collection"),
    ("tfc115",  "Mickey Mouse", "Brave Little Tailor", "115", "Rare",  "The First Chapter"),
    ("chal43",  "Rapunzel", "Gifted with Healing", "43", "Promo", "Challenge Promo"),
    ("tfc18",   "Rapunzel", "Gifted with Healing", "18", "Rare",  "The First Chapter"),
    ("chal41",  "Let It Go", None, "41", "Promo", "Challenge Promo"),
    ("tfc163",  "Let It Go", None, "163", "Rare", "The First Chapter"),
    ("p1_3",    "Elsa", "Snow Queen", "3",  "Promo", "Promo Set 1"),
    ("tfc41",   "Elsa", "Snow Queen", "41", "Rare",  "The First Chapter"),
]


def build():
    by_cn = collections.defaultdict(list)
    inv = collections.defaultdict(list)
    for cid, name, version, cn, rarity, setname in CARDS:
        c = {"id": cid, "name": name, "version": version, "collector_number": cn,
             "rarity": rarity, "_set": setname, "_rarity": rarity,
             "_cn": tm.norm_cn(cn), "_tok": tm.toks(name) | tm.toks(version)}
        by_cn[c["_cn"]].append(c)
        for tk in c["_tok"]:
            inv[tk].append(c)
    return by_cn, inv


# (title, expected_reason_or_None, note). None means "counts as a raw price".
CASES = [
    # ---- gate 1: a slab is not a raw sale. All seen leaking in the corpus. ----
    ("Disney Lorcana Rapunzel Gifted with Healing 4/C1 Foil PSA 10", "graded", "grader+grade"),
    ("Disney Lorcana: A Whole New World Foil Gem Mint 10 - 10/C1 World Champ Promo",
     "graded", "$17,500 slab, NO grader name in the title"),
    ("Disney Lorcana D23 Expo 2022 Mickey Mouse Brave Little Tailor #1 PSA Authentic Pop8",
     "graded", "grader name, no number"),
    ("2022 D23 Expo Disney Lorcana Mickey Mouse Brave Little Tailor #1 graded PSA rare",
     "graded", "bare 'graded'"),
    ("DISNEY LORCANA D23 2022 EXPO #1 MICKEY MOUSE BRAVE LITTLE TAILOR GRADED MINT 9",
     "graded", "'GRADED MINT 9', no grader"),
    ("Lorcana D23 Expo | Mickey Mouse - Brave Little Tailor #1 - Grade 9",
     "graded", "bare 'Grade 9'"),
    ("2025 Disney Lorcana EN 6 #13 Mickey Mouse Pirate Captain TAG Score 968 GEM MT 10",
     "graded", "grade-then-grader plus GEM MT"),
    ("DISNEY LORCANA D23 01 MICKEY MOUSE BRAVE LITTLE TAILOR 10 PRISTINE FOIL - POP 90",
     "graded", "'PRISTINE' and a population report"),
    # ...and the over-tightening trap: ordinary raw condition language.
    ("Disney Lorcana D23 Expo 2022 Mickey Mouse Brave Little Tailor 1/P1 Near Mint",
     None, "'Near Mint' is raw condition language, NOT a grade"),
    ("Disney Lorcana Mickey Mouse Brave Little Tailor 1/P1 NM ungraded raw card",
     None, "'ungraded'/'raw card' is this pipeline's TARGET, not an exclusion"),

    # ---- pins and merch wear the card's name ----
    ("Disney D23 Expo 2022 Lorcana Mickey Mouse Brave Little Tailor 1/P1 Promo Pin",
     "accessory", "$8 pin vs a four-figure card"),
    ("2023 DISNEY D23 LORCANA CARD 13X19 POSTER ELSA SNOW QUEEN 3/P1", "merch", "poster"),
    ("Disney Lorcana Elsa Snow Queen 3/P1 custom proxy", "merch", "counterfeit"),
    ("Lorcana D23 Expo Mickey Mouse - Brave Little Tailor 1/P1 Extended Art",
     "variant", "Extended Art is the 2024 D23 Collection card, not this one"),

    # ---- gate 2: no collector# and no set hint is undecidable ----
    ("Disney Lorcana Mickey Mouse Brave Little Tailor", "ambiguous",
     "three same-named cards tie on name tokens"),
    ("Disney Lorcana Let It Go foil", "ambiguous", "same, and 'foil' is not identity"),

    # ---- gate 3: TCGplayer owns any card it actually prices ----
    ("Disney Lorcana Mickey Mouse Brave Little Tailor 115/204 The First Chapter",
     "off-watchlist", "a real sale of a card with a live TCGplayer price"),

    # ---- the including verdicts ----
    ("Disney Lorcana Mickey Mouse Brave Little Tailor D23 Expo 2022 1/P1", None, "P1 #1"),
    ("Disney Lorcana Rapunzel - Gifted with Healing 4/C1 Foil Promo Card", None, "C1 foil"),
    ("Lorcana D23 Promo #3 Elsa, Snow Queen", None, "P1 #3"),
]


def main():
    by_cn, inv = build()
    wl = rm.build_watchlist_index(by_cn, inv)
    fails = []

    for title, want, note in CASES:
        _card, _conf, _cc, got = rm.raw_verdict(title, by_cn, inv, wl,
                                                skip_title_reasons=True)
        if got != want:
            fails.append(f"  reason want={want!r} got={got!r}  [{note}]\n      {title}")

    # The two verdicts that must land on a SPECIFIC card, not merely be included:
    # the same title shape resolves to a $1,900 promo or a $2 rare depending only
    # on the number in it.
    for title, want_id in [
        ("Disney Lorcana Mickey Mouse Brave Little Tailor D23 Expo 2022 1/P1", "p1_1"),
        ("Disney Lorcana Rapunzel - Gifted with Healing 4/C1 Foil Promo Card", "chal43"),
    ]:
        card, _c, _cc, reason = rm.raw_verdict(title, by_cn, inv, wl, skip_title_reasons=True)
        if reason is not None or not card or card["id"] != want_id:
            fails.append(f"  want card {want_id}, got {card and card['id']} "
                         f"(reason={reason})\n      {title}")

    # ---- structural: the gates cannot be quietly widened ----

    # Price must never reach the attribution decision. If raw_verdict ever grows a
    # price argument, the pipeline can start deciding which sales count by whether
    # they already agree with the price it wants to publish.
    import inspect
    params = set(inspect.signature(rm.raw_verdict).parameters)
    for banned in ("price", "sale_price", "amount"):
        if banned in params:
            fails.append(f"  raw_verdict takes a {banned!r} argument — price must never "
                         f"attribute a sale (see raw_match's module docstring)")

    # The broad pin rule belongs to RAW ONLY. If it ever migrates into the shared
    # ACC_RE it would start dropping ~30 genuine graded card sales that merely
    # mention a bundled pin (one of them $8,500).
    if tc.ACC_RE.search("Mickey Mouse Brave Little Tailor D23 Promo Pin"):
        fails.append("  terapeak_clean.ACC_RE now matches a bare 'Promo Pin' — that "
                     "breadth belongs in raw_match.RAW_PIN_RE only (it costs the graded "
                     "pipeline ~30 real card sales, one of them $8,500)")
    if not rm.RAW_PIN_RE.search("Mickey Mouse Brave Little Tailor D23 Promo Pin"):
        fails.append("  raw_match.RAW_PIN_RE stopped matching a bare 'Promo Pin'")

    # Merch words that were measured against the live catalog and must not creep.
    for t, should in [("Donald Duck Musketeer FOIL Lorcana 1st Print", False),
                      ("Kuzco - Picky Customer 2/P1", False),
                      ("Lorcana Jumbo Pop 3/P1", False),
                      ("Lorcana Elsa Snow Queen 3/P1 art print", True)]:
        if bool(rm.RAW_MERCH_RE.search(t)) != should:
            fails.append(f"  RAW_MERCH_RE match={not should} (want {should}) for: {t}")

    # Gate 1's own words, checked against the card names they were cleared against.
    for t, should in [("Gazelle - Pop Star 5/P1", False),
                      ("Detective's Badge 7/P1", False),
                      ("Vision Slab 9/P1", False),
                      ("Elsa Snow Queen 3/P1 Pop 90", True)]:
        if rm.is_graded_listing(t) != should:
            fails.append(f"  is_graded_listing={not should} (want {should}) for: {t}")

    # Every watchlist card must be reachable by some query, or it is on a list
    # that nothing ever searches for.
    qs = [q.lower() for q in queries()]
    for st, cn, name, ver, q, _pr in WATCHLIST:
        token = (ver or name).lower()
        if not any(token in qq for qq in qs):
            fails.append(f"  {st} #{cn}: no query covers token {token!r}")

    # The output directory contamination guard. A raw JSONL under
    # scripts/terapeak_output/ is loaded into graded_sales by the graded loader's
    # glob, silently, under a grader invented from the filename.
    here = os.path.dirname(os.path.abspath(__file__))
    for fname in ("raw_topup.py", "raw_load.py"):
        src = open(os.path.join(here, fname), encoding="utf-8").read()
        if 'RAW_OUT = HERE / "raw_output"' not in src:
            fails.append(f"  {fname}: raw output must live in scripts/raw_output/, "
                         f"never scripts/terapeak_output/ (the graded loader globs that dir)")

    if fails:
        print(f"FAIL ({len(fails)})")
        print("\n".join(fails))
        return 1
    print(f"ok - {len(CASES)} verdict cases + attribution, gate-width and wiring checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
