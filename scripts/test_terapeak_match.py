"""Guard for terapeak_match's attribution rules. No network — synthetic catalog.

Run: python scripts/test_terapeak_match.py

The two failure modes this protects against are both silent and expensive:
  * a card whose NAME is its SET's name ("Attack of the Vine!" #202) swallowing every
    no-set-hint title in that set, and the cn-conflict guard then DROPPING the row at
    load (that is how ~$35k of real Iconic sales went missing through 2026-08);
  * over-correcting that, and breaking the community-numbering forgiveness the guard
    was built for (Challenge "3/C1" is Lorcast #42, NOT The First Chapter's #3).
Both directions are asserted here — fixing one by breaking the other is the trap.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import terapeak_match as tm  # noqa: E402

# (id, name, version, collector_number, rarity, set_name)
CARDS = [
    ("aotv202", "Attack of the Vine!", None, "202", "Rare", "Attack of the Vine!"),
    ("aotv245", "Belle & Beast", "Certain as the Sun", "245", "Iconic", "Attack of the Vine!"),
    ("aotv244", "Lilo & Stitch", "Fun-Loving Friends", "244", "Iconic", "Attack of the Vine!"),
    ("aotv228", "Woody & Buzz Lightyear", "Best Buddies", "228", "Enchanted", "Attack of the Vine!"),
    ("wspell199", "Winterspell", None, "199", "Uncommon", "Winterspell"),
    ("wspell242", "Moana", "Curious Explorer", "242", "Iconic", "Winterspell"),
    ("chal42", "Cinderella", "Stouthearted", "42", "Promo", "Challenge Promo"),
    ("tfc3", "Cinderella", "Gentle and Kind", "3", "Rare", "The First Chapter"),
    ("p1_7", "Captain Hook", "Forceful Duelist", "7", "Promo", "Promo Set 1"),
    ("p1_4", "Cruella De Vil", "Miserable As Usual", "4", "Promo", "Promo Set 1"),
    ("p1_1", "Mickey Mouse", "Brave Little Tailor", "1", "Promo", "Promo Set 1"),
    ("p1_25ja", "Mickey Mouse", "True Friend", "25ja", "Promo", "Promo Set 1"),
    ("p1_25zh", "Mickey Mouse", "True Friend", "25zh", "Promo", "Promo Set 1"),
    ("cc1_6", "Tinker Bell", "Giant Fairy", "6", "Promo", "Curator's Collection: Heroines"),
    ("fc18", "Tinker Bell", "Giant Fairy", "18", "Promo", "Format Coconut"),
    ("rotf173", "Beast", "Tragic Hero", "173", "Legendary", "Rise of the Floodborn"),
    ("rotf210", "Beast", "Relentless", "210", "Enchanted", "Rise of the Floodborn"),
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


# (title, expected_card_id_or_None, note)
CASES = [
    # --- the set-name magnet: the printed number must win ---
    ("Disney Lorcana Attack Of The Vine! Belle & Beast 245/207 PSA 10 GEM MT",
     "aotv245", "over-numbered Iconic; was dropped as cn-conflict"),
    ("2026 DISNEY LORCANA EN 13-ATTACK OF THE VINE! ICONIC #244 LILO & STITCH PSA 10",
     "aotv244", "EN 13 must resolve to a set hint"),
    ("2026 DISNEY LORCANA EN 13-ATTACK OF THE VINE! #228 WOODY & BUZZ ENCHANTED PSA 10",
     "aotv228", "same, Enchanted"),
    ("Disney Lorcana Moana Winterspell 242/204 Lore Star Foil CGC 10 Gem Mint",
     "wspell242", "Winterspell is a card name AND a set name"),

    # --- community numbering must STILL be forgiven (the over-correction trap) ---
    ("2024 DISNEY LORCANA EN C1-LORCANA CHALLENGE PROMO #3 CINDERELLA TOP PRIZE PSA 10",
     "chal42", "3/C1 is Lorcast #42, not TFC #3"),
    ("2024 Disney Lorcana EN C1 Top Prize #3 Cinderella PSA 10 GEM MINT",
     "chal42", "same, terser title"),

    # --- a stray number must not beat a card the title actually NAMES ---
    ("Captain Hook Duelist PSA 10 Gem Mint - Lorcana 2022 D23 Expo 1st Edition #4",
     "p1_7", "stray '#4' must not hand the row to Cruella #4"),
    ("Auction #1 2024 Disney Lorcana ZH P1 China Joy #25 Mickey Mouse PSA 10 GEM MINT",
     "p1_25zh", "'Auction #1' must not beat the regional 25zh"),
    ("Disney Lorcana PSA10 Mickey Mouse 2024 25/P1 Tokyo Toy Show Japanese JA1 #1",
     "p1_25ja", "same, Japanese"),

    # --- multi-letter set codes ---
    ("Lorcana Heroines Curator's Collection Tinker Bell Giant Fairy 6/CC1 Promo",
     "cc1_6", "'6/CC1' must parse; was losing to Format Coconut #18"),

    # --- an explicit number beats a contradicting rarity WORD ---
    ("2023 Disney Lorcana EN 2 Enchanted #173 Beast PSA 10 GEM MINT",
     "rotf173", "seller wrote 'Enchanted' but printed #173, the Legendary"),
]


def main():
    by_cn, inv = build()
    fails = []
    for title, want, note in CASES:
        got, _conf, cnc = tm.match_one(title, by_cn, inv)
        gid = got["id"] if got else None
        if gid != want:
            fails.append(f"  {title[:78]}\n     want={want} got={gid} cn_conflict={cnc}  ({note})")
    # set_hint must know every mainline set, or the cn-conflict guard cannot forgive.
    for n, expect in ((11, "Winterspell"), (12, "Wilds Unknown"), (13, "Attack of the Vine!")):
        h = tm.set_hint(f"2026 DISNEY LORCANA EN {n}-SOMETHING PSA 10")
        if h != expect:
            fails.append(f"  set_hint('EN {n}') want={expect} got={h}")
    if len(tm.MAINLINE) < 13:
        fails.append(f"  MAINLINE has {len(tm.MAINLINE)} sets; the index IS the EN number, so a new set must be appended")

    if fails:
        print(f"FAIL ({len(fails)})")
        print("\n".join(fails))
        return 1
    print(f"ok - {len(CASES)} attribution cases + set_hint coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
