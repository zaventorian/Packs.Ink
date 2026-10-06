"""Offline guard: retire_prestaged re-points ENCRYPTED deck rows (and version snapshots).
Run: python scripts/test_retire_prestaged_decks.py"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))
import retire_prestaged as r

class FakeSB:
    def __init__(s):
        s.deck = [
            {"deck_id": "d1", "card_id": r.deck_enc("crd_prestage_x_1"), "printing": "Normal", "quantity": 2},
            {"deck_id": "d1", "card_id": r.deck_enc("crd_real_1"), "printing": "Normal", "quantity": 1},
            {"deck_id": "d2", "card_id": r.deck_enc("crd_prestage_x_1"), "printing": "Normal", "quantity": 4},
            {"deck_id": "d2", "card_id": r.deck_enc("crd_other"), "printing": "Normal", "quantity": 4},
        ]
        s.ver = [{"deck_id": "d2", "version": 1, "cards": [{"card_id": r.deck_enc("crd_prestage_x_1"), "quantity": 4}]}]
    def select(s, t, columns=None, filters=None, order=None, **kw): return s.deck if t == "deck_cards" else s.ver
    def update(s, t, match, patch):
        rows = s.deck if t == "deck_cards" else s.ver
        for x in rows:
            if all(x[k] == v for k, v in match.items()): x.update(patch)
    def delete(s, t, f):
        s.deck[:] = [x for x in s.deck if not (x["deck_id"] == f["deck_id"][3:] and x["card_id"] == f["card_id"][3:])]

sb = FakeSB(); m = {"crd_prestage_x_1": "crd_real_1"}
assert r.repoint_decks(sb, m, True) == {"crd_prestage_x_1": 2}
got = {(x["deck_id"], r.deck_dec(x["card_id"])): x["quantity"] for x in sb.deck}
assert got == {("d1", "crd_real_1"): 3, ("d2", "crd_real_1"): 4, ("d2", "crd_other"): 4}, got  # merged + moved
assert r.repoint_versions(sb, m, True) == 1
assert r.deck_dec(sb.ver[0]["cards"][0]["card_id"]) == "crd_real_1"
# dry run changes nothing
sb2 = FakeSB(); r.repoint_decks(sb2, m, False)
assert r.deck_dec(sb2.deck[0]["card_id"]) == "crd_prestage_x_1"
print("ok")
