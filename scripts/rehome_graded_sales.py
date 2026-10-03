r"""rehome_graded_sales.py - move graded sales that were attributed to the wrong card.

    python scripts/rehome_graded_sales.py            # DRY RUN: prints every move
    python scripts/rehome_graded_sales.py --commit   # writes (backup JSON first)

Every ruling below was made by reading the slab itself, not the title: the top of the
PSA/CGC label prints the set, the collector number and the variety ("2024 DISNEY LORCANA
EN 5 #208 / ARCHIMEDES / ENCHANTED"), which is the one thing a seller's auto-title drops.
Where the label was unreadable the title or the release date decided and the rule says so.
This is NOT reattribute_graded_sales.py (which walks every row and must not be run): it
touches only the item_ids / source cards named here, and a row whose card_id has already
moved is skipped, so a re-run is a no-op.

A hand edit to card_id survives the daily scrape because terapeak_load.py --new-only is
ON CONFLICT DO NOTHING on item_id.

After a commit, refresh the rollup:  select public.refresh_graded_sales_rollup();
"""
import argparse, json, re, sys, urllib.parse, urllib.request
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

HERE = Path(__file__).resolve().parent

# card ids (looked up 2026-10-01)
TFC_LET_IT_GO = "crd_cb6a73f229b646c8bf57adbb4356dbd4"
WS_LET_IT_GO = "crd_7e294ae586f24eddae3b7d1263c73ee7"        # Winterspell reprint, released 2026-02-13
FABLED_BRUNO_0 = "crd_2cbda843e29c4e6392ccddd6858eeb7d"      # starter-deck foil "#0"
D23_BRUNO_4 = "crd_8d986fbd95984691b7fe1a27a5e110bc"
UR_BRUNO_39 = "crd_a7a6c097879443db9bb5299c7017fd20"
SS_ARCH_47 = "crd_14a6c9cb57b54a889bad8a3e1f62e8ba"          # Uncommon
SS_ARCH_208 = "crd_cb38cec5fa8e49139bb0377111d6d048"         # Enchanted
WITW_ELSA_45 = "crd_df577add2294407d8594959234177041"        # Common
WITW_ELSA_208 = "crd_04d59c2ff0e648eb9dad622fa82ce49b"       # Epic
SS_HEXWELL_65 = "crd_721b1a5a766441a382bd8975b7b7a7ea"       # Rare
SS_HEXWELL_223 = "crd_cbd6fc9596f14329af2f0c237a7be6a2"      # Deep Trouble Victory Prize
AS_SAIL_163 = "crd_049739e69c034e898c3c48abd37544cc"

RULES = [
    dict(why="Let It Go: every slab label reads 'EN 1 #163' (The First Chapter); the Winterspell "
             "reprint did not exist before 2026-02-13 and the two later sales read 'EN 1 #163' too",
         src=WS_LET_IT_GO, dst=TFC_LET_IT_GO),
    dict(why="Bruno Undetected Uncle: labels read 'EN D23 #04' (D23 Collection); the Fabled '#0' row is "
             "the starter-deck foil, which is not graded. One slab reads 'EN 4 #39 FOIL' (Ursula's Return)",
         src=FABLED_BRUNO_0, dst=D23_BRUNO_4, override={"167896726039": UR_BRUNO_39}),
    dict(why="Archimedes: labels read 'EN 5 #208 ... ENCHANTED'. Sellers' auto-titles drop the variety, so "
             "the matcher picked the Uncommon #47",
         src=SS_ARCH_47, dst=SS_ARCH_208),
    dict(why="Elsa Exploring the Unknown: labels read 'EN 10 #208 ... EPIC', not the Common #45",
         src=WITW_ELSA_45, dst=WITW_ELSA_208),
    dict(why="Half Hexwell Crown: labels read 'EN 5 #223 ... DEEP TROUBLE VICTORY PRIZE' (the quest "
             "reward), not the booster Rare #65; the PSA 10 pop-1 sale predates Shimmering Skies",
         src=SS_HEXWELL_65, dst=SS_HEXWELL_223),
    dict(why="'Sail the Azurite Sea' is a catch-all: its name is mostly the set's own words, so every title "
             "that said 'Azurite Sea' matched it. Each row below names a different card",
         src=AS_SAIL_163, items={
             "267380043566": "crd_6e88d3615bd94a6fbf2dab003d75287f",   # Minnie P2 #12 PSA 9
             "267380042936": "crd_6e88d3615bd94a6fbf2dab003d75287f",   # Minnie P2 #12 PSA 10
             "267380044916": "crd_61fa338e64c749f4b236deeade5bf433",   # Wasabi P2 #13
             "187605193777": "crd_3c803ea6602c49e0869da110c5d31d42",   # Aladdin P2 #9 (x4)
             "286705448074": "crd_3c803ea6602c49e0869da110c5d31d42",
             "286597269616": "crd_3c803ea6602c49e0869da110c5d31d42",
             "256898288383": "crd_3c803ea6602c49e0869da110c5d31d42",
             "356677361178": "crd_c01f3a4124be48dbb77aaa45281e74ba",   # Tiana - Restaurant Owner #16 (x2)
             "356677355928": "crd_c01f3a4124be48dbb77aaa45281e74ba",
             "356677336512": "crd_a94b5e02de4a43bdba60303fffe3d20f",   # Simba - Pride Protector #20
             "297812893909": "crd_aace3808bd9f445195dceec7b4fe87e9",   # Hades - Strong Arm (CGC)
             "117156389664": "crd_10eefc9e8b2943c0a29f6e19a1c114a0",   # John Silver - Stern Captain (CGC)
             "177794801440": "crd_5123478a...",                         # Maui - Half-Shark (CGC) -- id set below
             "376242900868": "crd_6df56dd3dbb5471589800f12bba4eb46",   # Kakamora - Long-Range Specialist
         },
         # no card can be named from these: a bare "Tiana" TAG slab, and a $5,750 ungraded
         # cruise-line exclusive. Detached and excluded, the loader's own convention.
         unmatched=["256920483214", "398052354126"]),
]
# Maui's id is filled from the catalog at run time (Azurite Sea #124); keeping a literal
# truncated id above would be a silent wrong move, so it is resolved and checked here.
MAUI_PLACEHOLDER = "crd_5123478a..."


def env():
    e = dict(re.findall(r"^([A-Z_]+)=(.*)$", (HERE.parent / ".env").read_text(encoding="utf-8"), re.M))
    return e["SUPABASE_URL"].rstrip("/"), e["SUPABASE_SERVICE_KEY"]


def call(url, key, method, path, body=None, prefer=None):
    h = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if prefer:
        h["Prefer"] = prefer
    req = urllib.request.Request(f"{url}/rest/v1/{path}", method=method, headers=h,
                                 data=None if body is None else json.dumps(body).encode())
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    url, key = env()

    maui = call(url, key, "GET", "cards?select=id,name,version,collector_number,sets(name)"
                "&name=eq.Maui&collector_number=eq.124")
    maui = [c for c in maui if (c.get("sets") or {}).get("name") == "Azurite Sea"]
    if len(maui) != 1:
        sys.exit("Maui - Half-Shark (Azurite Sea #124) did not resolve to exactly one card")
    maui_id = maui[0]["id"]

    plan, backup = [], []
    for rule in RULES:
        rows = call(url, key, "GET", "graded_sales?select=item_id,card_id,grader,grade,excluded,"
                    f"exclude_reason,title&card_id=eq.{rule['src']}&order=sold_date.desc")
        items = {k: (maui_id if v == MAUI_PLACEHOLDER else v) for k, v in rule.get("items", {}).items()}
        for r in rows:
            iid = r["item_id"]
            if rule.get("items") is not None:
                if iid in rule.get("unmatched", []):
                    plan.append((r, None, rule["why"]))
                elif iid in items:
                    plan.append((r, items[iid], rule["why"]))
                continue
            plan.append((r, rule.get("override", {}).get(iid, rule["dst"]), rule["why"]))

    # Every destination must be a real card, and is printed by NAME so the dry run reads as
    # a ruling a person can check rather than a list of ids.
    names = {}
    for d in sorted({d for _, d, _ in plan if d}):
        c = call(url, key, "GET", f"cards?select=name,version,collector_number,sets(name)&id=eq.{d}")
        if len(c) != 1:
            sys.exit(f"destination {d} is not a card")
        names[d] = f"{c[0]['sets']['name']} #{c[0]['collector_number']} {c[0]['name']}" + \
                   (f" - {c[0]['version']}" if c[0]["version"] else "")
    for r, dst, why in plan:
        print(f"  {r['item_id']}  {r['grader']} {r['grade']}  -> "
              f"{'(detach+exclude)' if dst is None else names[dst]}  | {r['title'][:60]}")
    print(f"\n{len(plan)} row(s) to move")
    if not args.commit:
        print("DRY RUN - nothing written. Re-run with --commit.")
        return 0

    backup = [{"item_id": r["item_id"], "card_id": r["card_id"], "excluded": r["excluded"],
               "exclude_reason": r["exclude_reason"]} for r, _, _ in plan]
    bp = HERE / "rehome_graded_backup_2026-10-01.json"
    bp.write_text(json.dumps(backup, indent=1), encoding="utf-8")
    print("backup ->", bp)
    for r, dst, _ in plan:
        patch = ({"card_id": None, "excluded": True, "exclude_reason": "nomatch"} if dst is None
                 else {"card_id": dst})
        call(url, key, "PATCH", "graded_sales?item_id=eq." + urllib.parse.quote(r["item_id"]), patch,
             prefer="return=minimal")
    print("done; now run: select public.refresh_graded_sales_rollup();")
    return 0


if __name__ == "__main__":
    sys.exit(main())
