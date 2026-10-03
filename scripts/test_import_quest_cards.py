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

ok("boss card split", Q.split_oversized("Ursula - Ruler of Lorcana (Oversized)"), ("Ursula", "Ruler of Lorcana (Oversized)"))
ok("item with no version", Q.split_oversized("The Reforged Crown (Oversized)"), ("The Reforged Crown", "Oversized"))
ok("battleground keeps its // name", Q.split_oversized("The Lair // Infinite Wrath - Battleground (Oversized)"),
   ("The Lair // Infinite Wrath", "Battleground (Oversized)"))
prods = [
    {"productId": 552745, "name": "The Lair // Infinite Wrath - Battleground (Oversized)",
     "extendedData": [{"name": "Description", "value": "Difficulty: Hard\r\n<br>Ursula draws 1 more card each turn."}]},
    {"productId": 552741, "name": "Ursula - Ruler of Lorcana (Oversized)", "extendedData": []},
    {"productId": 552746, "name": "Anna - Ensnared Sister", "extendedData": [{"name": "Number", "value": "1/31"}]},
]
over = Q.oversized_rows("Q1", prods, lambda q, slot, pid: f"img/{q}/{slot}/{pid}")
ok("only the oversized products", [r["tcgplayer_product_id"] for r in over], [552741, 552745])
ok("numbered os1.. in product-id order", [r["id"] for r in over], ["crd_quest_q1_os1", "crd_quest_q1_os2"])
ok("no collector number on an oversized card", over[0]["collector_number"], None)
ok("boss is a Character, battleground a Battleground", [r["card_type"] for r in over], ["Character", "Battleground"])
ok("rarity Quest", {r["rarity"] for r in over}, {"Quest"})
ok("description becomes text", over[1]["text"], "Difficulty: Hard\nUrsula draws 1 more card each turn.")
ok("art slot", over[0]["image_normal"], "img/Q1/os1/552741")
ok("Q3 oversized go to Lorcast's Q3 set", Q.OVERSIZED_GROUPS["Q3"][1], "set_5a55ed51fe9144248bc9d1b5656bc6b4")

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
