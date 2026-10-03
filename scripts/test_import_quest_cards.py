"""test_import_quest_cards.py: the quest-card importer and the Lorcast loader's
Quest rarity. Offline (no network, no .env).

    python scripts/test_import_quest_cards.py
"""
import os, sys

os.environ.setdefault("SUPABASE_URL", "http://stub")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
sys.path.insert(0, os.path.dirname(__file__))

import import_quest_cards as Q
import load_lorcast as L

fails = 0


def ok(name, got, want):
    global fails
    if got == want:
        print("  ok   " + name)
    else:
        fails += 1
        print(f"  FAIL {name}\n        got  {got!r}\n        want {want!r}")


# LorcanaJSON shape (abridged from Q2 #1).
card = {
    "setCode": "Q2", "number": 1, "name": "Metal Scorpion", "version": "Deadly Statue",
    "type": "Character", "color": "", "cost": 7, "inkwell": True, "moveCost": None,
    "strength": 8, "willpower": 5, "lore": 2, "subtypes": ["Colossus"],
    "abilities": [
        {"fullText": "Evasive (Only characters with Evasive can\nchallenge this character.)"},
        {"fullText": "SIMULTANEOUS STRIKE When Jafar plays this\ncharacter, each Illumineer chooses."},
    ],
    "flavorText": None, "artists": ["Carlos Ruiz"],
    "externalLinks": {"tcgPlayerId": 634273},
}
row = Q.build_row(card, "set_quest_q2", "https://x/q2/1.jpg")
ok("stable id", row["id"], "crd_quest_q2_1")
ok("set", row["set_id"], "set_quest_q2")
ok("rarity is Quest, never Promo", row["rarity"], "Quest")
ok("no ink on a quest card", (row["ink"], row["inks"]), (None, None))
ok("pid carried so the price joins", row["tcgplayer_product_id"], 634273)
ok("one line per ability, wraps joined", row["text"],
   "Evasive (Only characters with Evasive can challenge this character.)\n"
   "SIMULTANEOUS STRIKE When Jafar plays this character, each Illumineer chooses.")
ok("image in every size", {row["image_small"], row["image_normal"], row["image_large"]}, {"https://x/q2/1.jpg"})
ok("only Q1 and Q2 are imported (Q3 is Lorcast's)", sorted(Q.QUESTS), ["Q1", "Q2"])

song = Q.build_row({**card, "type": "Action", "subtypes": ["Song"], "abilities": [],
                    "fullText": "Sing it."}, "set_quest_q2", None)
ok("a song is filed the Lorcast way", (song["card_type"], song["classifications"]), ("Action - Song", None))

ok("Q3 is a quest code", L._is_quest_code("Q3"), True)
ok("Q12 is a quest code", L._is_quest_code("q12"), True)
ok("bare Q is not", L._is_quest_code("Q"), False)
ok("a booster set is not", L._is_quest_code("13"), False)
ok("PD1 is not", L._is_quest_code("PD1"), False)
ok("loader writes Quest for a quest set",
   L.transform_card({"id": "x", "name": "n", "rarity": "Promo"}, "s", "Q3")["rarity"], "Quest")
ok("loader leaves other sets alone",
   L.transform_card({"id": "x", "name": "n", "rarity": "Super_rare"}, "s", "5")["rarity"], "Super Rare")

print(f"\n{'FAILED' if fails else 'all passed'}")
sys.exit(1 if fails else 0)
