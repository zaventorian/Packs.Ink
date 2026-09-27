"""
test_playmats.py - guards the playmat catalog: the loader's classification, its
overrides file, the ETL wiring, and the client/migration contract.

    python scripts/test_playmats.py

Offline by construction (guards.yml runs it with no network and no secrets):
the classifier runs over a frozen copy of TCGplayer's playmat group
(scripts/fixtures/playmats_tcgcsv_2026-09-27.json).

Every failure here is SILENT in production. A mis-parsed Set Championship
description files a Champion mat under no set; a lost override moves a Disney-
park exclusive into the regular retail pair; a drifted id band makes owned mats
count as sealed product. None of it errors - the tab just says something false.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "http://stub.invalid")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import load_playmats as lp  # noqa: E402
import tcgcsv_common as tc  # noqa: E402

FIXTURE = json.loads((HERE / "fixtures" / "playmats_tcgcsv_2026-09-27.json").read_text(encoding="utf-8"))
SETS = FIXTURE["sets"]
SET_ID = {s["name"]: s["id"] for s in SETS}
ROOT = HERE.parent

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f"FAIL  {label}")


rows = lp.build_rows(FIXTURE["products"], SETS, lp.load_overrides())
by_pid = {r["tcgplayer_product_id"]: r for r in rows}

# ── 1. The whole group, section by section ──────────────────────────────────
counts: dict[str, int] = {}
for r in rows:
    counts[r["section"]] = counts.get(r["section"], 0) + 1
check(len(rows) == 63, f"63 Lorcana playmats in the fixture (got {len(rows)})")
check(counts == {"retail": 29, "disney": 4, "ravensburger": 3, "set_champ": 15, "dlc": 7, "event": 5},
      f"section counts (got {counts})")
check(all(r["section"] in lp.SECTIONS for r in rows), "every section is a known one")
check(not [r for r in rows if r["section"] == "other"], "nothing falls through to 'other'")
unplaced = [r["tcgplayer_product_id"] for r in rows
            if r["section"] in ("retail", "set_champ") and not r["set_id"]]
check(not unplaced, f"every retail and Set Championship mat has a set (unplaced: {unplaced})")
check(all(r["tier"] in ("Champion", "Participant") for r in rows if r["section"] == "set_champ"),
      "every Set Championship mat names its tier")
# TCGplayer never says Top Prize or Prize Wall, so every Challenge mat in the
# fixture carries a ruling - a new one shows up in the loader's report instead.
check(all(r["tier"] in lp.DLC_TIERS for r in rows if r["section"] == "dlc"),
      "every Challenge mat is ruled Top Prize or Prize Wall")
check(sorted(r["tcgplayer_product_id"] for r in rows if r.get("tier") == "Prize Wall")
      == [555946, 655975, 655976], "the Prize Wall mats are Cinderella, Mulan and Simba")
check(all(r["tier"] is None for r in rows if r["section"] not in ("set_champ", "dlc", "event")),
      "only prize and event mats carry a tier")
check(not [r for r in rows if r["section"] == "retail" and r["source"]],
      "no shop exclusive is left in Retail")

# ── 2. The cases that break a naive parser ──────────────────────────────────
def expect(pid, **want):
    r = by_pid.get(pid)
    if r is None:
        check(False, f"{pid} missing")
        return
    for k, v in want.items():
        if k == "set":
            check(r["set_id"] == SET_ID.get(v), f"{pid} set -> {v} (got {r['set_id']})")
        else:
            check(r.get(k) == v, f"{pid} {k} -> {v!r} (got {r.get(k)!r})")

# TCGplayer writes "Archazia�s Island" - the apostrophe is mojibake.
expect(622934, section="set_champ", set="Archazia's Island", tier="Champion", year=2025)
# ... and "Reign of Jafarl" - a trailing typo.
expect(680933, section="set_champ", set="Reign of Jafar", tier="Champion", year=2025)
expect(547672, section="set_champ", set="Into the Inklands", tier="Participant", year=2024,
       name="Stitch - Rock Star")
expect(705523, section="set_champ", set="Attack of the Vine!", name="If I Didn't Have You")
# DLC: the year is stated only on the newest two; the tier is always a ruling.
expect(712028, section="dlc", finish="Foil", year=2026, tier="Top Prize", name="Down in New Orleans")
expect(555944, section="dlc", finish="Foil", year=None, tier="Top Prize", name="Rapunzel - Gifted with Healing")
expect(555946, section="dlc", tier="Prize Wall", name="Cinderella - Stouthearted")
# Listed by TCGplayer as a Challenge mat; it is the Season 3 CCQ Top 8 prize.
expect(711521, section="event", finish=None, tier="Top 8 prize", source="Season 3 CCQ",
       name="Mother Knows Best")
# Conventions.
expect(555950, section="event", year=2024, source="2024 conventions", name="2024 Convention")
# The D23 Show Bundle mat - an OVERRIDE, TCGplayer's own copy reads like retail;
# it files with the Disney-location mats.
expect(711435, section="disney", source="D23 2026", year=2026, finish="Premium Foil",
       released_on="2026-08-15", name="Winnie the Pooh - Hunny Wizard")
# Exclusives the DESCRIPTION names ...
expect(664842, section="ravensburger", set="Winterspell", source="Ravensburger online store")
expect(664843, section="disney", set="Winterspell", source="Disney locations", finish="Foil")
# ... and the ones only an override knows.
expect(691140, section="ravensburger", set="Wilds Unknown", source="Ravensburger online store")
expect(691137, section="disney", set="Wilds Unknown", source="Disney locations", finish="Foil")
expect(690392, section="disney", set="Attack of the Vine!", source="Disney locations")
expect(696531, section="ravensburger", set="Attack of the Vine!", source="Ravensburger online store")
# Retail placed by street date, including a presale one.
expect(543891, section="retail", set="Ursula's Return", source=None)   # +14 days
# TCGplayer's photo of these two is the BOX alone; ours is the mat.
expect(543891, image_url="Logos/playmats/ursulas-return-tinker-bell.webp")
expect(543892, image_url="Logos/playmats/ursulas-return-rapunzel-gifted-artist.webp")
expect(510085, image_url="https://tcgplayer-cdn.tcgplayer.com/product/510085_200w.jpg")
expect(706248, section="retail", set="Hyperia City", presale=True)
# Retail placed by override (no release date on TCGplayer).
expect(510088, section="retail", set="The First Chapter", name="Maui")
expect(625034, section="retail", set="Reign of Jafar", name="Hades - Double Dealer")

# ── 3. display_name ─────────────────────────────────────────────────────────
for raw, want in [
    ("Disney Lorcana: Stitch - Rock Star Playmat (Champion)", ("Stitch - Rock Star", None)),
    ("Disney Lorcana: Rapunzel - Gifted with Healing Foil Playmat (Disney Lorcana Challenge)",
     ("Rapunzel - Gifted with Healing", "Foil")),
    ("Disney Lorcana: Winnie the Pooh - Hunny Wizard Premium Foil Playmat",
     ("Winnie the Pooh - Hunny Wizard", "Premium Foil")),
    ("Disney Lorcana: Hades - Double Dealer", ("Hades - Double Dealer", None)),
    ("Disney Lorcana: 2024 Convention Playmat", ("2024 Convention", None)),
    # "Foil" inside a card NAME is not a finish; only "<...> Foil Playmat" is.
    ("Disney Lorcana: Foil Test Card Playmat", ("Foil Test Card", None)),
]:
    got = lp.display_name(raw)
    check(got == want, f"display_name({raw!r}) -> {want} (got {got})")

# ── 4. Set matching ─────────────────────────────────────────────────────────
check(lp.match_set_name("Archazia�s Island", SETS) == SET_ID["Archazia's Island"], "mojibake apostrophe")
check(lp.match_set_name("Reign of Jafarl", SETS) == SET_ID["Reign of Jafar"], "one-letter trailing typo")
check(lp.match_set_name("Reign of Jafarlxyz", SETS) is None, "a long tail is NOT a typo")
check(lp.match_set_name("Promo Set 1", SETS) is None, "a promo set is never a playmat's set")
check(lp.match_set_name("", SETS) is None, "empty text matches nothing")
check(lp.set_by_release("2024-05-31", SETS) == SET_ID["Ursula's Return"], "+14 days attaches")
check(lp.set_by_release("2026-10-23", SETS) == SET_ID["Hyperia City"], "presale street date attaches")
check(lp.set_by_release("2023-08-01", SETS) is None, "a date before any set attaches to none")
check(lp.set_by_release("2024-04-20", SETS) is None,
      f"57 days after a set, past the {lp.RETAIL_RELEASE_WINDOW_DAYS}-day window, attaches to none")
check(lp.set_by_release(None, SETS) is None, "no date, no set")

# ── 5. The overrides file is a decision record ──────────────────────────────
raw = json.loads(lp.OVERRIDES_PATH.read_text(encoding="utf-8"))
allowed = {"section", "tier", "finish", "source", "year", "name", "set", "released_on", "image", "why"}
for key, entry in raw["overrides"].items():
    check(key.isdigit(), f"override key {key} is a product id")
    check(bool((entry.get("why") or "").strip()), f"override {key} carries a why")
    check(set(entry) <= allowed, f"override {key} uses only known fields ({set(entry) - allowed})")
    if "set" in entry and entry["set"] is not None:
        check(entry["set"] in SET_ID, f"override {key} names a real set ({entry['set']!r})")
    if "section" in entry:
        check(entry["section"] in lp.SECTIONS, f"override {key} section is known")
    # A photo that is not on disk renders as the glyph with no error anywhere.
    if "image" in entry:
        img = str(entry["image"])
        check(img.startswith("Logos/playmats/"), f"override {key} photo lives under Logos/playmats/ ({img})")
        check((ROOT / img).is_file(), f"override {key} photo exists on disk ({img})")
    if "released_on" in entry:
        check(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(entry["released_on"]))),
              f"override {key} released_on is a YYYY-MM-DD date")
try:
    lp.apply_override(dict(by_pid[510088]), {"set": "The Fist Chapter", "why": "typo"}, SETS)
    check(False, "an override naming an unknown set must raise, not null the set")
except ValueError:
    check(True, "unknown override set raises")

# ── 6. Only Lorcana products load ───────────────────────────────────────────
check(lp.is_lorcana({"name": "Disney Lorcana: Moana Playmat"}), "Lorcana name accepted")
check(not lp.is_lorcana({"name": "Ravensburger Labyrinth Playmat"}), "a non-Lorcana mat is skipped")

# ── 7. ETL wiring ───────────────────────────────────────────────────────────
check((tc.PLAYMATS_CATEGORY_ID, tc.PLAYMATS_GROUP_ID) == (35, 23280), "playmat group ids")
check(any(g[:2] == (35, 23280) for g in tc.EXTRA_PRICE_GROUPS), "daily ETL is told about the group")
etl = (HERE / "etl_tcgcsv_daily.py").read_text(encoding="utf-8")
check("EXTRA_PRICE_GROUPS" in etl and "for cat_id, gid, label in EXTRA_PRICE_GROUPS" in etl,
      "etl_tcgcsv_daily.py loops the extra groups")
# A playmat failure must never cost the day's CARD prices.
m = re.search(r"for cat_id, gid, label in EXTRA_PRICE_GROUPS:(.*?)print\(f\"\\nTotal", etl, re.S)
check(bool(m) and "except Exception" in m.group(1) and "continue" in m.group(1),
      "the extra-group fetch is wrapped so it cannot fail the card ETL")

# ── 8. Migration <-> loader <-> client contract ─────────────────────────────
mig = (ROOT / "supabase" / "170_playmats.sql").read_text(encoding="utf-8")
# The NEWEST migration that sets the section CHECK is the one the database has.
chk_migs = sorted((p for p in (ROOT / "supabase").glob("[0-9]*_*.sql")
                   if "playmats_section_chk" in p.read_text(encoding="utf-8")),
                  key=lambda p: int(p.name.split("_", 1)[0]))
latest = chk_migs[-1].read_text(encoding="utf-8") if chk_migs else ""
sec_m = re.search(r"check \(section in \(([^)]*)\)\)", latest)
mig_sections = tuple(x.strip().strip("'") for x in sec_m.group(1).split(",")) if sec_m else ()
check(mig_sections == lp.SECTIONS,
      f"newest section CHECK ({chk_migs[-1].name if chk_migs else '-'}) matches the loader ({mig_sections})")
check("security_invoker = on" in mig, "the view is security_invoker")
check("grant select on public.playmat_prices_latest to anon" in mig, "the view is granted to anon")
check("prices_daily" in mig and "p.printing = 'Normal'" in mig, "the view reads Normal prices")

html = (ROOT / "Index.html").read_text(encoding="utf-8")
band = re.search(r"const PLAYMAT_PID_BASE = (\d+);", html)
check(bool(band) and int(band.group(1)) == 980000000, "Index.html PLAYMAT_PID_BASE is 980000000")
check("980000000" in mig, "the migration documents the same id band")
# The band must clear every synthetic band already in use: puzzles 900M+SKU,
# exclusives 930M+n, pins 950M+n, counters 960M+n (isCollectiblePid: 950-970M).
check(re.search(r"const isCollectiblePid = \(pid\) => \{ const n = Number\(pid\); "
                r"return n >= 950000000 && n < 970000000; \};", html) is not None,
      "pins/counters band unchanged, so 980M cannot collide with it")
client_sections = re.search(r"const PLAYMAT_SECTIONS = \[(.*?)\];", html, re.S)
keys = tuple(re.findall(r'key:\s*"(\w+)"', client_sections.group(1))) if client_sections else ()
check(set(keys) == set(lp.SECTIONS), f"client PLAYMAT_SECTIONS cover the loader's ({keys})")
check(keys == lp.SECTIONS, f"client PLAYMAT_SECTIONS list the sections in the loader's order ({keys})")
client_tiers = re.search(r"const PLAYMAT_DLC_TIERS = \[([^\]]*)\]", html)
check(bool(client_tiers) and tuple(re.findall(r'"([^"]+)"', client_tiers.group(1))) == lp.DLC_TIERS,
      "client PLAYMAT_DLC_TIERS match the loader's DLC_TIERS")

# ── 9. A playmat's value counts toward SEALED value (Zaven, 2026-09-27) ─────
# Owned under its band id, priced under its TCGplayer id: every surface that
# turns the sealed collection into money has to translate one into the other,
# or an owned mat silently adds $0 again.
def component(decl: str) -> str:
    """One top-level declaration's text: from its line to the next line that
    starts another top-level const/function."""
    start = html.find("\n" + decl)
    if start < 0:
        return ""
    nxt = re.search(r"\n(?:const |function |async function )", html[start + 1:])
    return html[start:start + 1 + nxt.start()] if nxt else html[start:]


check("const sealedPricePid = (pid) =>" in html, "sealedPricePid exists")
for decl, fetches in (("const SealedValueChart", False), ("const CollectionPanel", True),
                      ("function SealedCollectionView", True)):
    body = component(decl)
    name = decl.split()[-1]
    check(len(body) > 2000, f"{name} found")
    check("sealedPricePid(" in body, f"{name} prices a mat under its TCGplayer id")
    if fetches:   # the chart values from price HISTORY; these two need today's price
        check("useOwnedPlaymatPrices(" in body, f"{name} fetches the owned mats' prices")
# The mats' record has a hole, so a chart that fetched plain history drew them
# arriving from nothing inside short windows ("+324% past 3M"). Both value
# charts go through the seeded fetch.
for decl in ("const SealedValueChart", "const CollectionPanel"):
    body = component(decl)
    check("fetchSealedValueHistory(" in body, f"{decl.split()[-1]} seeds the mats' history")
seeder = component("async function fetchSealedValueHistory")
check("lt(\"date\", sinceDate)" in seeder and "date: sinceDate" in seeder,
      "the seed is the newest price BEFORE the window, re-dated to its first day")
pm = component("const PlaymatsView")
check("playmat-value-note" in pm, "the Playmats tab explains where its value is counted")
check("playmat-ast" in pm, "the Playmats tab's value carries the asterisk")
check(re.search(r'PLAYMAT_CACHE_KEY = "packsink:playmatPrices:v(\d+)"', html) is not None
      and int(re.search(r'PLAYMAT_CACHE_KEY = "packsink:playmatPrices:v(\d+)"', html).group(1)) >= 2,
      "the playmat price cache is v2+ (rows cached before the section split must not replay)")
check('"playmats"' in re.search(r"const COLLECTION_SECTIONS = \[([^\]]*)\]", html).group(1),
      "Collection has a playmats tab")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
