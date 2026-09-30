"""Guard for import_official_set.parse_card - offline, no network, no database.

The official gallery is the second-best source for a revealed card, and its
import OVERWRITES a hand-made stand-in in place. So a parser that misreads a
field does not add a wrong card, it replaces a right one. Both bugs pinned here
did exactly that on a Hyperia City dry run (2026-09-30), and neither errors:

  * a card's fields were read from a flat 2,800-character window that runs on
    into the next cards, so an uninkable card followed by an inkable one came
    back inkable (three of 39), and an action could take a neighbour's stats;
  * ability names came through in the gallery's Title Case with a blank line
    between abilities, where every other card says `NAME rule` on one line each.

The fixture is cut from the live page, field order kept.
"""
import os
import sys

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))
import import_official_set as ios  # noqa: E402

IMG = "https://ravensburger.cloud/ci/lorcana_en_set14_%s_abc/"


def card(cn, author, body, tail, ctype):
    return ('{abilities:$R[1]=[],author:"%s",card_identifier:"%s/204 EN 14",'
            'card_sets:$R[2]=[$R[3]={id:"set14",name:"Hyperia City"}],%s,'
            'variants:$R[8]=[$R[9]={detail_image_url:"%s",variant_id:"Regular"}],'
            '%ssearch_terms:"x",card_type:"%s"},' % (author, cn, body, IMG % cn, tail, ctype))


HTML = "".join([
    # an uninkable action with no stats, directly before an inkable character
    card(162, "Monica Catalano / Kristen Breshears",
         r'flavor_text:"\"What strange rocks!\"",ink_convertible:!1,ink_cost:3,'
         r'magic_ink_colors:$R[4]=["SAPPHIRE"],name:"A Dark Age No More",rarity:"RARE",'
         r'rules_text:"Put the top card of your deck into your inkwell facedown and exerted.",'
         r'searchable_keywords:$R[5]=["Sword in the Stone"],sort_number:-3429,subtypes:$R[6]=[]',
         "", "action"),
    card(24, "Noukah",
         r'flavor_text:"",ink_convertible:!0,ink_cost:4,magic_ink_colors:$R[4]=["AMBER"],'
         r'name:"Judy Hopps",quest_value:1,rarity:"RARE",'
         r'rules_text:"\x3CShift> 2 {I} (You may pay 2 {I} to play this on top of one of your '
         r'characters named Judy Hopps.)\n\n\\Got You Now\\ When you play this character, you '
         r'can’t lose.\n\n\\Today' + "'" + r's the Day\\ Draw a card.",'
         r'searchable_keywords:$R[5]=["Zootopia"],sort_number:-3567,strength:4,'
         r'subtitle:"Always Vigilant",subtypes:$R[6]=["Dreamborn","Hero","Detective"]',
         "willpower:5,", "character"),
    card(30, "Maxine Vee",
         r'flavor_text:"\"If I go 6#% faster with \x3Cone> ink drop?\"",ink_convertible:!0,ink_cost:5,'
         r'magic_ink_colors:$R[4]=["AMBER"],name:"Never Gonna Let You Cry",rarity:"UNCOMMON",'
         r'rules_text:"\x3CSing Together> 5 (Any number of your characters may {E} to sing this '
         r'song for free.)\n\nReturn up to 2 character cards from your discard to your hand.",'
         r'searchable_keywords:$R[5]=["Turning Red"],sort_number:-3561,subtypes:$R[6]=["Song"]',
         "", "action"),
])

fails = []


def check(label, got, want):
    if got != want:
        fails.append("%s\n    got  %r\n    want %r" % (label, got, want))


a = ios.parse_card(HTML, 162, 14)
check("an uninkable card stays uninkable when an inkable one follows", a["inkable"], False)
check("an action takes no strength from the next card", a["strength"], None)
check("an action takes no willpower from the next card", a["willpower"], None)
check("an action takes no lore from the next card", a["lore"], None)
check("name", a["name"], "A Dark Age No More")
check("two illustrators split", a["illustrators"], ["Monica Catalano", "Kristen Breshears"])
check("a card with no classifications has none", a["classifications"], None)
check("art url", a["img"], IMG % 162 + "card")

j = ios.parse_card(HTML, 24, 14)
check("an inkable card is inkable", j["inkable"], True)
check("own stats", (j["cost"], j["strength"], j["willpower"], j["lore"]), (4, 4, 5, 1))
check("version", j["version"], "Always Vigilant")
check("ability names in caps, one line per ability, straight apostrophes", j["text"],
      "Shift 2 {I} (You may pay 2 {I} to play this on top of one of your characters named "
      "Judy Hopps.)\nGOT YOU NOW When you play this character, you can't lose.\n"
      "TODAY'S THE DAY Draw a card.")
check("classifications", j["classifications"], ["Dreamborn", "Hero", "Detective"])

s = ios.parse_card(HTML, 30, 14)
check("a song's type", s["card_type"], "Action - Song")
check("Song is the type, not a classification", s["classifications"], None)
check("keyword line kept plain", s["text"].split("\n")[0][:16], "Sing Together 5 ")
check("flavor text: tags stripped, percent unescaped", s["flavor_text"],
      '"If I go 6% faster with one ink drop?"')

check("a card the gallery lacks", ios.parse_card(HTML, 99, 14), None)
check("no inkable flag reads as unknown, not uninkable",
      ios.parse_card(HTML.replace("ink_convertible:!1,", ""), 162, 14)["inkable"], None)

if fails:
    print("FAIL test_import_official_set (%d)" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("OK test_import_official_set: 19 checks")
