"""
test_intl_cards.py - offline guard for the localized-card pipeline.

    python scripts/test_intl_cards.py

No network, no database. Pins the parts whose failure is SILENT:

  * matching (intl_cards.py) - a wrong match puts one card's foreign art on
    another card's page and nothing errors. Both directions are pinned: a
    number match whose name disagrees must be REFUSED, and the legitimate
    fallbacks (renumbered promos, Takara's working-title file names) must
    still land.
  * art language - a foreign gallery lists cards never printed in that
    language (shown in English); they must not become 'German' rows.
  * name-only rows never carry art - one printing's picture on another.
  * the gallery extractor (intl_gallery_data.mjs) - it evaluates the page's
    own script, so it is checked against a synthetic page, including one that
    tries to reach `process` from inside the sandbox.
  * the dictionaries - i18n/<lang>.js must match i18n/src, and every
    translation keeps its {placeholders}.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import intl_cards as ic  # noqa: E402

FAILS = 0


def check(cond, msg):
    global FAILS
    if not cond:
        FAILS += 1
        print("FAIL:", msg)


SETS = [
    {"id": "s1", "code": "1", "name": "The First Chapter"},
    {"id": "s3", "code": "3", "name": "Into the Inklands"},
    {"id": "s12", "code": "12", "name": "Wilds Unknown"},
    {"id": "sp1", "code": "P1", "name": "Promo Set 1"},
    {"id": "scp", "code": "cp", "name": "Challenge Promo"},
]
CARDS = [
    {"id": "c_woody", "set_id": "s12", "name": "Woody", "version": "Helping a Friend", "collector_number": "1", "rarity": "Rare",
     "classifications": ["Storyborn", "Hero", "Toy"]},
    {"id": "c_donald", "set_id": "s12", "name": "Donald Duck", "version": "Distracted Traveler", "collector_number": "212", "rarity": "Epic",
     "classifications": ["Storyborn", "Hero"]},
    {"id": "c_donald_base", "set_id": "s12", "name": "Donald Duck", "version": "Distracted Traveler", "collector_number": "70", "rarity": "Common",
     "classifications": ["Storyborn", "Hero"]},
    {"id": "c_smee", "set_id": "s3", "name": "Mr. Smee", "version": "Bumbling Mate", "collector_number": "188", "rarity": "Uncommon",
     "classifications": ["Storyborn", "Ally", "Pirate"]},
    {"id": "c_tk", "set_id": "s1", "name": "Te Kā", "version": "The Burning One", "collector_number": "126", "rarity": "Super Rare",
     "classifications": ["Storyborn", "Villain", "Deity"]},
    {"id": "c_df", "set_id": "scp", "name": "Dragon Fire", "version": None, "collector_number": "25", "rarity": "Promo",
     "classifications": None},
    {"id": "c_ariel_p1", "set_id": "sp1", "name": "Ariel", "version": "Spectacular Singer", "collector_number": "13", "rarity": "Promo",
     "classifications": ["Storyborn", "Hero", "Princess"]},
    {"id": "c_ariel", "set_id": "s1", "name": "Ariel", "version": "Spectacular Singer", "collector_number": "2", "rarity": "Super Rare",
     "classifications": ["Storyborn", "Hero", "Princess"]},
]
cat = ic.Catalog(CARDS, SETS)


def gcard(cid, ident, name, sub, lang, art_lang=None, subtypes=None):
    return {"culture_invariant_id": cid, "card_identifier": ident, "name": name, "subtitle": sub,
            "rules_text": "\\\\Bold\\\\ text%Second line", "flavor_text": "", "subtypes": subtypes or [],
            "variants": [{"variant_id": "Regular",
                          "detail_image_url": f"https://ravensburger.cloud/ci/lorcana_{art_lang or lang}_set1_{cid}_abc/"}]}


# --- identifiers
check(ic.parse_identifier("27/204 DE 14") == {"cn": "27", "code": "14", "lang": "de"}, "mainline identifier")
check(ic.parse_identifier("12/P4 EN 13")["code"] == "P4", "promo identifier keeps its family")
check(ic.parse_identifier("1/C1 EN 1")["code"] == "cp", "C1 maps to our Challenge Promo code")
check(ic.parse_identifier("5/204 EN Q3")["code"] == "Q3", "quest identifier")
check(ic.parse_identifier("1TFC EN 1/P1") is None, "irregular identifier falls to the name match")

# --- English twins
en = [
    gcard(1, "1/204 EN 12", "Woody", "Helping a Friend", "en"),
    gcard(2, "126/204 EN 1", "Te Ka", "The Burning One", "en"),             # accent-insensitive
    gcard(3, "1/C1 EN 1", "Dragon Fire", None, "en"),                        # renumbered: ours is #25
    gcard(4, "2/204 EN 1", "Moana", "Of Motunui", "en"),                     # number hit, WRONG name -> refused
    gcard(5, "13/P1 EN 1", "Ariel", "Spectacular Singer", "en"),
]
m = ic.match_gallery_en(en, cat)
check(m.get(1, {}).get("card_id") == "c_woody" and m[1]["how"] == "number", "set + number + name")
check(m.get(2, {}).get("card_id") == "c_tk", "accents fold (Te Ka / Te Kā)")
check(m.get(3, {}).get("card_id") == "c_df" and m[3]["how"] == "name", "renumbered promo by name inside its set")
check(4 not in m, "a number match whose NAME disagrees is refused, not trusted")
check(m.get(5, {}).get("card_id") == "c_ariel_p1", "promo printing ties to the promo row, not the booster one")

# --- foreign rows: only cards PRINTED in the language
de = [
    gcard(1, "1/204 DE 12", "Woody", "Hilft einem Freund", "de", subtypes=["Traumgestalt", "Held", "Spielzeug"]),
    gcard(3, "1/C1 EN 1", "Dragon Fire", None, "de", art_lang="en"),         # listed, but English art
    gcard(1, "1/204 DE 12", "Woody dup", "x", "de"),                          # duplicate entry
]
rows, st = ic.gallery_rows("de", de, m)
check(st["not_printed"] == 1, "English-art card in the German gallery is skipped")
check(st["duplicate"] == 1 and len(rows) == 1, "first gallery entry wins a duplicate")
r = rows[0]
check(r["_src_image"].endswith("/card") and "lorcana_de_" in r["_src_image"], "art is the 800px `card` variant")
check(r["text"] == "BOLD text\nSecond line", "ability name upper-cased, % becomes a newline")
check(r["_store_key"] == "de/1", "store key is the source id, not our card id")
check(ic.gallery_api_image("https://ravensburger.cloud/ci/lorcana_de_set3_85_95267571bdfe1674e7f7e9d41e43ea88b0ac8af3/")
      == "https://api.lorcana.ravensburger.com/images/de/set3/85_95267571bdfe1674e7f7e9d41e43ea88b0ac8af3.jpg",
      "fallback art path on the app's image host")
check(ic.gallery_api_image("https://example.com/x") is None, "no fallback for an unknown art URL")

# --- name-only rows never carry art
extra = ic.text_only_rows("de", [{**r, "card_id": "c_ariel"}], cat)
check(any(x["card_id"] == "c_ariel_p1" for x in extra), "another printing of the same card borrows the NAME")
check(all(x["image_url"] is None and x["_src_image"] is None and x["match_how"] == "name" for x in extra),
      "a name-only row never carries a picture")

# --- Takara Tomy
p = ic.parse_tt_file("184_DLCS3_UTC_MrSmee_BumblingMate_JA")
check(p and p["code"] == "3" and p["idx"] == "184" and p["slug"].endswith("mrsmeebumblingmate"), "file name parse")
check(ic.parse_tt_file("027_DLCP3_PATX_PuttingitAllTogether_JA")["code"] == "P3", "DLCP<n> is a promo set")
check(ic.parse_tt_file("garbage") is None, "unparseable file name")
jp = [
    {"id": 1, "card_file": "001_DLCS12_Woody_HelpingaFriend_JA", "collector_number": 1, "card_name": "ウッディ",
     "version": "俺が助けるぜ！", "rarity": "レア", "rules_text": "\\つかまれ！\\ 効果%次", "classifications": [{"classification": "ストーリーボーン"}]},
    # Takara files Into the Inklands under its own index (184) but prints 188
    {"id": 2, "card_file": "184_DLCS3_UTC_MrSmee_BumblingMate_JA", "collector_number": 188, "card_name": "ミスター・スミー",
     "version": "マヌケなお仲間", "rarity": "アンコモン", "rules_text": "-", "classifications": []},
    {"id": 3, "card_file": "070_DLCS12_DonaldDuck_DistractedTraveler_JA", "collector_number": 70, "card_name": "ドナルドダック",
     "version": "x", "rarity": "コモン", "rules_text": "", "classifications": []},
    # working title in the FILE name: number + rarity + character must agree
    {"id": 4, "card_file": "212_DLCS12_DonaldDuck_ObliviousTraveler_JA", "collector_number": 212, "card_name": "ドナルドダック",
     "version": "y", "rarity": "エピック", "rules_text": "", "classifications": []},
    # same trick with the WRONG rarity must be refused
    {"id": 5, "card_file": "212_DLCS12_DonaldDuck_SomethingElse_JA", "collector_number": 212, "card_name": "ドナルドダック",
     "version": "z", "rarity": "コモン", "rules_text": "", "classifications": []},
]
rows, st = ic.match_tt(jp, cat)
by = {x["source_id"]: x for x in rows}
check(by.get("1", {}).get("card_id") == "c_woody", "JP by number + slug")
check(by["1"]["text"] == "つかまれ！ 効果\n次", "JP rules text markup stripped")
check(by["1"]["classifications"] == ["ストーリーボーン"], "JP classifications flattened")
check(by.get("2", {}).get("card_id") == "c_smee", "JP printed number used when the file index differs")
check(by.get("4", {}).get("card_id") == "c_donald" and by["4"]["match_how"] == "character", "working-title file accepted on number + rarity + character")
check("5" not in by, "working-title file with a disagreeing rarity is refused")
check(by["1"]["_src_image"].endswith("/001_DLCS12_Woody_HelpingaFriend_JA.png"), "JP art URL")

# --- glossary vote
de_rows = [{"card_id": "c_woody", "classifications": ["Traumgestalt", "Held", "Spielzeug"], "match_how": "number"},
           {"card_id": "c_ariel", "classifications": ["Traumgestalt", "Held", "Prinzessin"], "match_how": "number"},
           {"card_id": "c_tk", "classifications": ["Traumgestalt", "Schurke", "Gottheit"], "match_how": "name"}]
t = ic.derive_terms("de", de_rows, cat, SETS, gallery_set_names={"set1": {"name": "Das erste Kapitel"}})
check(t["class"].get("Storyborn") == "Traumgestalt" and t["class"].get("Hero") == "Held", "classification vote")
check("Toy" not in t["class"], "a word seen once is not guessed")
check("Villain" not in t["class"], "name-only rows do not vote")
check(t["set"].get("The First Chapter") == "Das erste Kapitel", "localized set name")
check(t["ink"]["Amber"] == "Bernstein" and t["rarity"]["Super Rare"] == "Super selten", "official terms")
check(ic.tt_set_title("ＴＨＥ　ＦＩＲＳＴ　ＣＨＡＰＴＥＲ　物語のはじまり") == "物語のはじまり", "Japanese half of a set title")

# --- the gallery extractor, on a synthetic page
node = shutil.which("node")
if not node:
    print("SKIP: node not found - extractor not checked")
else:
    page = """<html><body><script>(self.$R=self.$R||{})["tsr"]=[];self.$_TSR={};
    var leak = (function(){ try { return typeof (this.constructor.constructor("return process")()); } catch(e) { return "blocked"; } })();
    $_TSR.router={matches:[{i:"root"},{i:" ",l:{locale:"de",cardsData:{cards:[{culture_invariant_id:7,name:leak,card_identifier:"1/204 DE 1"}],setNames:{set1:{name:"Das erste Kapitel"}}}}}]};
    document.currentScript.remove();</script></body></html>"""
    tmp = tempfile.mkdtemp()
    try:
        hp, op = os.path.join(tmp, "p.html"), os.path.join(tmp, "o.json")
        open(hp, "w", encoding="utf8").write(page + ("<!-- pad -->" * 10))
        r = subprocess.run([node, os.path.join(HERE, "intl_gallery_data.mjs"), "de-DE", op, hp],
                           capture_output=True, text=True, env={k: os.environ[k] for k in ("PATH", "SYSTEMROOT") if k in os.environ})
        # fewer than 1000 cards is a non-zero exit by design; the file is still written
        out = json.load(open(op, encoding="utf8")) if os.path.exists(op) else None
        check(out is not None and out["cards"][0]["culture_invariant_id"] == 7, "extractor reads cardsData out of the router state")
        check(out is not None and out["cards"][0]["name"] in ("undefined", "blocked"),
              f"sandbox cannot reach process (got {out and out['cards'][0]['name']})")
        check(r.returncode != 0, "a page with under 1000 cards is reported as a failure")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

# --- dictionaries are baked from their sources
r = subprocess.run([sys.executable, os.path.join(HERE, "build_i18n.py"), "--check"], capture_output=True, text=True)
check(r.returncode == 0, "i18n/<lang>.js match i18n/src (run python scripts/build_i18n.py)\n" + r.stdout[-800:])

print(f"\n{'OK' if not FAILS else 'FAILED'}: intl cards guard ({FAILS} failure(s))")
sys.exit(1 if FAILS else 0)
