"""Guard for terapeak_load.printing_of. No network — titles are verbatim from
`graded_sales`, plus the false positives the pattern has to keep refusing.

Run: python scripts/test_printing_of.py

This function decides which side of a foil split a sale lands on, and on a
Challenge card both sides share ONE card_id with markets ~50x apart. Its failure
mode is silent AND inverted: a "non-foil" the regex cannot read does not become
NULL, it falls through to the bare `"foil" in t` test and is stored as FOIL.

That is how A Whole New World (C1 #10) read as a $299 card — three of the seven
rows stored as Foil were explicitly non-foil listings, leaving the two REAL foil
sales ($17,500 and $14,100) buried in a median computed mostly from $175-$400
non-foils.

Both directions are asserted. Over-tightening is the mirror trap: "No. 42 Foil"
is a card NUMBER followed by a genuine foil, and reading it as non-foil would
move real foil sales onto the cheap side of the same split.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from terapeak_load import printing_of  # noqa: E402

# (title, expected, why) — every "REAL" title is verbatim from graded_sales.
CASES = [
    # --- the bug: negations the old `non[\s-]?foil` could not read -----------
    ("Disney Lorcana A Whole New World Promo Card 10/C1 No. Foil",
     "Non-Foil", "REAL — stored as Foil, dragged AWNW's foil median to $299"),
    ("2023 Disney Lorcana EN 1 NON - Foil Ariel On Human Legs #1 PSA 10 Gem Mint",
     "Non-Foil", "REAL — space either side of the hyphen"),
    ("2023 Disney Lorcana EN 1 NON- Foil #42 Elsa PSA 10 GEM MINT Sprit of Winter",
     "Non-Foil", "REAL — hyphen then space"),
    ("Disney Lorcana Rapunzel Sunshine 20/204 Non - Foil Floodborn CGC 10",
     "Non-Foil", "REAL"),
    ("Disney Lorcana - Elsa Snow Queen 41/204 - CGC PRISTINE 10 Uncommon *NOT FOIL*",
     "Non-Foil", "REAL — 'not foil'"),
    ("Disney Lorcana Azurblaues Meer Einzelkarten NO FOIL Sleeved NM DE Monatsupdate",
     "Non-Foil", "REAL — 'no foil'"),
    ("Lorcana Promo Goofy PSA 10 Musketier Gamescom 2023 Disney No Foil/no Enchanted",
     "Non-Foil", "REAL"),
    ("Disney Lorcana Floodborn Snow White Well Wisher 25/204 - PSA 9 Mint (not Foil)",
     "Non-Foil", "REAL — parenthesised"),
    ("Lorcana Ursula N/Foil PSA 10", "Non-Foil", "the n/ abbreviation"),

    # --- already worked before the fix; must keep working -------------------
    ("Disney Lorcana - A Whole New World - Non Foil - Promo - 10/C1 - CGC 10 Gem Mint",
     "Non-Foil", "REAL — the plain form"),
    ("Disney Lorcana A Whole New World Infinity Promo Card 10/C1 EN 1 Non Foil CGC 10",
     "Non-Foil", "REAL"),
    ("Lorcana Elsa Non-Foil PSA 10", "Non-Foil", "hyphenated"),
    ("Lorcana Elsa NonFoil PSA 10", "Non-Foil", "no separator"),

    # --- ⚠ FALSE POSITIVES the pattern must refuse --------------------------
    ("Disney Lorcana Mickey Mouse No. 42 Foil PSA 10",
     "Foil", "'No.' is a card NUMBER — a digit breaks the negation"),
    ("Disney Lorcana Elsa No 115 Foil CGC 10",
     "Foil", "same, unpunctuated"),
    ("Disney Lorcana: A Whole New World Foil Gem Mint 10 - 10/C1 World Champ Promo",
     "Foil", "REAL — one of AWNW's two genuine $17,500/$14,100 foils"),
    ("Disney Lorcana TCG CGC 10 Foil A Whole New World Worlds Tournament Promo 10/C1",
     "Foil", "REAL — the other genuine foil"),
    ("Lorcana Cinderella Cold Foil PSA 10", "Cold Foil", "cold foil is its own bucket"),
    ("Lorcana Belle Holofoil PSA 10", "Foil", "holo implies foil"),

    # --- the Challenge prize tiers (untouched by this fix, pinned anyway) ---
    ("Disney Lorcana Simba Pride Protector DLC Top 64 Promo 4/C2 CGC Pristine 10",
     "Foil", "Top N + Challenge context => the foil prize card"),
    ("DISNEY LORCANA EN C2-LORCANA CHALLENGE PROMO PRIZE WALL PEGASUS PSA 10",
     "Non-Foil", "Prize Wall is Challenge-exclusive and stands alone"),
    ("Ursula Set Championship Top Prize Promo 38/P1 PSA 10",
     None, "'Top Prize' WITHOUT Challenge context is a Set Championship promo, not a C1 foil"),
    ("2025 DISNEY LORCANA EN C1-LORCANA CHALLENGE PROMO #10 A WHOLE NEW WORLD PSA 10",
     None, "no finish word and no prize tier — must stay unclassified, never guessed"),
]


def main():
    fails = []
    for title, want, why in CASES:
        got = printing_of(title)
        if got != want:
            fails.append(f"  want={want!r} got={got!r}  ({why})\n     {title[:96]}")

    # The inverted-failure property itself: a title the negation cannot read must
    # never come back as "Foil". This is what makes the bug expensive rather than
    # merely wrong, so assert it directly over every negation case above.
    for title, want, why in CASES:
        if want == "Non-Foil" and printing_of(title) == "Foil":
            fails.append(f"  INVERTED: a non-foil title read as Foil\n     {title[:96]}")

    if fails:
        print(f"FAIL ({len(fails)})")
        print("\n".join(fails))
        return 1
    print(f"ok - {len(CASES)} printing_of cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
