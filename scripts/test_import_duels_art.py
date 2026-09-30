"""Offline guard for scripts/import_duels_art.py - no network, no .env.

Every way this importer goes wrong is silent: a placeholder image written over a
real crop looks like a normal card tile, and a wrong set code files a promo under
the wrong set with nothing erroring.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import import_duels_art as m  # noqa: E402

fails = 0


def check(name, cond):
    global fails
    if not cond:
        fails += 1
        print("FAIL", name)


# ---- ids -> (set code, collector number, language)
check("mainline id", m.parse_full_id("167/204 EN 14") == ("14", "167", "EN"))
check("promo id", m.parse_full_id("11/PD1 EN 14") == ("PD1", "11", "EN"))
check("rph id", m.parse_full_id("6/RPH EN 14") == ("RPH", "6", "EN"))
check("d23 id", m.parse_full_id("13/D23 EN 14") == ("D23", "13", "EN"))
check("japanese mainline keeps its language", m.parse_full_id("15/204 JA 14")[2] == "JA")
check("garbage is None", m.parse_full_id("nonsense") is None)

cards = [
    {"fullId": "90/204 EN 14", "imageSource": "reveal"},
    {"fullId": "14/204 EN 14", "imageSource": "generated"},
    {"fullId": "1/204 EN 13", "imageSource": None},
    {"fullId": "11/PD1 EN 14", "imageSource": "reveal"},
]
got = m.cards_for_setnum(cards, "14")
check("only the asked set", set(got) == {"14|90", "14|14", "PD1|11"})
check("set 1 is not set 14 (suffix match is whole-token)", "14|1" not in got)

# ---- the rule the whole script exists for
check("a reveal render is usable", m.usable({"imageSource": "reveal"}))
check("a PLACEHOLDER is never usable", not m.usable({"imageSource": "generated"}))
check("the gallery's own image is left to import_official_set", not m.usable({"imageSource": None}))
check("missing source is not usable", not m.usable({}))

check("an exact 734x1024 stand-in is left alone", not m.needs_upgrade((734, 1024)))
check("a 125px thumb is upgraded", m.needs_upgrade((125, 175)))
check("734x1026 (a resized paste) is upgraded", m.needs_upgrade((734, 1026)))
check("unreadable size is upgraded", m.needs_upgrade(None))

# ---- card data for a newly added promo
check("rules markup", m.clean_rules("Pay 1 [INKCOST].\n\nTap [EXERT] for +2 [STRENGTH] [LORE]")
      == "Pay 1 {I}.\nTap {E} for +2 {S} {L}")
check("song is Action - Song with no classifications",
      m.card_type_of({"type": "action", "subtypes": ["Song"]}) == ("Action - Song", None))
check("character keeps subtypes",
      m.card_type_of({"type": "character", "subtypes": ["Storyborn", "Hero"]}) == ("Character", ["Storyborn", "Hero"]))
check("plain action", m.card_type_of({"type": "action", "subtypes": []}) == ("Action", None))

# ---- image output: 734 wide, JPEG
from PIL import Image  # noqa: E402
buf = io.BytesIO()
Image.new("RGB", (1101, 1536), (200, 160, 40)).save(buf, "WEBP")
out = Image.open(io.BytesIO(m.to_jpeg(buf.getvalue())))
check("resized to the catalog's size", out.size == (734, 1024))
check("is a JPEG", out.format == "JPEG")

# ---- source-level guards
src = open(os.path.join(os.path.dirname(__file__), "import_duels_art.py"), encoding="utf-8").read()
check("upgrade loop skips non-prestage (Lorcast) rows", 'startswith("crd_prestage_")' in src)
check("the image URL is cache-busted", "?v=" in src)
check("illustrators are never guessed", '"illustrators": ill.get(key)' in src)
check("mainline numbers are never added", "code == str(args.setnum)" in src)

print("FAILED %d" % fails if fails else "ok - import_duels_art")
sys.exit(1 if fails else 0)
