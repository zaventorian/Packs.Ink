"""Guard for import_pasted_cards.validate - offline, no network, no database.

The photo importer writes whatever its manifest says, and that data is typed by
hand off a screenshot, so validate() refuses rather than repairs. On 2026-09-30
three Hyperia City songs were found stored as plain "Action" with "Song" as a
classification, which drops a card out of the site's Song filter without an
error anywhere. This pins the refusals, and that a correct card of every type
still passes: a check that refused good cards would be ignored just as quietly.
"""
import os
import sys

os.environ.setdefault("SUPABASE_URL", "http://localhost")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
sys.path.insert(0, os.path.dirname(__file__))
import import_pasted_cards as ipc  # noqa: E402

fails, checks = [], 0


def check(label, got, want):
    global checks
    checks += 1
    if got != want:
        fails.append("%s\n    got  %r\n    want %r" % (label, got, want))


def card(**kw):
    c = {"image": "163.jpg", "collector_number": 163, "name": "Everything Else Is Obsolete",
         "rarity": "Common", "inks": ["Sapphire"], "cost": 3, "inkable": True,
         "card_type": "Action - Song", "classifications": None,
         "text": "(A character with cost 3 or more can {E} to sing this song for free.)\n"
                 "Look at the top 3 cards of your deck."}
    c.update(kw)
    return c


def refused(c, needle):
    return any(needle in e for e in ipc.validate(c, 1))


check("a correct song passes", ipc.validate(card(), 1), [])
check("a Sing Together song passes", ipc.validate(card(text=(
    "Sing Together 9 (Any number of your or your teammates' characters with total cost 9 or more "
    "may {E} to sing this song for free.)")), 1), [])
check("a character passes", ipc.validate(card(
    card_type="Character", classifications=["Storyborn", "Hero"],
    text="Ward (Opponents can't choose this character except to challenge.)"), 1), [])
check("an item with an empty classification list passes", ipc.validate(card(
    card_type="Item", classifications=[], text="DESTABILIZE {E}, 2 {I} — Banish this item."), 1), [])
check("a location passes", ipc.validate(card(
    card_type="Location", classifications=["Hyperia City"],
    text="OPEN FOR BUSINESS Once during your turn, whenever a character moves here, draw a card."), 1), [])
check("an action that sings nothing passes", ipc.validate(card(card_type="Action", text="Draw 2 cards."), 1), [])

check("Song as a classification is refused",
      refused(card(card_type="Action", classifications=["Song"]), "not a classification"), True)
check("Song as a classification is refused even beside the right type",
      refused(card(classifications=["Song"]), "not a classification"), True)
check("a song typed as plain Action is refused", refused(card(card_type="Action"), "must be 'Action - Song'"), True)
check("a song with no type is refused", refused(card(card_type=None), "must be 'Action - Song'"), True)
check("a type the catalog does not use is refused", refused(card(card_type="Song"), "not canonical"), True)
check("the card's own type-line spelling is refused", refused(card(card_type="Action • Song"), "not canonical"), True)

if fails:
    print("FAIL test_import_pasted_cards (%d)" % len(fails))
    for f in fails:
        print("  - " + f)
    sys.exit(1)
print("OK test_import_pasted_cards: %d checks" % checks)
