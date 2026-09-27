"""
Build the TEXT index for OCR-based matching: every card's readable text
(name, version/subtitle, type, classifications, cost, strength, willpower,
lore, collector number, rules text, flavor) + a normalised search blob.

Writes scripts/scanner/data/text_index.json (dev / experiment). If text-OCR
proves out, a slim shippable version goes to repo-root scanner/.
"""
from __future__ import annotations
import datetime, json, re, sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE.parent))
from supabase_client import Supabase  # noqa: E402
import scanner_scope  # noqa: E402

def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())

def main():
    load_dotenv(HERE.parent / ".env")
    DATA.mkdir(parents=True, exist_ok=True)
    sb = Supabase()
    # printed set code per set_id ("1".."13", "P1", "D23", ...) — the same code
    # printed on the card's bottom line next to the collector number
    # ("147/204 · EN · 3"), so an OCR'd (set, number) pair keys cnBySet exactly.
    sets = sb.select("sets", columns="id,code,released_at")
    set_code = {s["id"]: (s.get("code") or "").strip().upper() or None for s in sets}
    # A set that is not out yet cannot be in anyone's hand, so scanner.js sorts its
    # cards behind every released card and a name-only read ("LEXINGTON") answers
    # with the Lexington that exists. Only emitted for sets still unreleased at build
    # time; the browser compares it to ITS today, so the demotion lapses on release
    # day without a rebuild.
    today = datetime.date.today().isoformat()
    set_upcoming = {s["id"]: s["released_at"] for s in sets
                    if s.get("released_at") and str(s["released_at"])[:10] > today}
    bad_sets, bad_ids = scanner_scope.excluded_set_ids(sets), scanner_scope.suppressed_card_ids()
    rows = sb.select("cards",
        columns="id,name,version,set_id,card_type,classifications,cost,strength,willpower,lore,inkable,ink,collector_number,text,flavor_text,rarity,"
                + ",".join(scanner_scope.IMAGE_COLUMNS))
    # the SAME image predicate as fetch_cards.py, so text.json can never hold an id
    # the colour index lacks (scanner_scope.card_image says why that matters)
    rows = [r for r in rows if scanner_scope.card_image(r)
            and scanner_scope.in_scope(r["id"], r.get("set_id"), bad_sets, bad_ids)]
    out = []
    # single-char rarity code — scanner.js uses it to order same-(name,version)
    # reprint groups base-first (chase = E/I/X/P loses ties without evidence).
    RMAP = {"Common": "C", "Uncommon": "U", "Rare": "R", "Super Rare": "S",
            "Legendary": "L", "Enchanted": "E", "Iconic": "I", "Epic": "X", "Promo": "P"}
    for r in rows:
        cls = r.get("classifications") or []
        blob = " ".join([
            norm(r.get("name")), norm(r.get("version")), norm(r.get("card_type")),
            norm(" ".join(cls)), norm(r.get("text")), norm(r.get("flavor_text")),
        ])
        out.append({
            "id": r["id"],
            "name": r.get("name"), "version": r.get("version"),
            "type": r.get("card_type"), "classifications": cls,
            "set": set_code.get(r.get("set_id")),
            "cost": r.get("cost"), "strength": r.get("strength"),
            "willpower": r.get("willpower"), "lore": r.get("lore"),
            "cn": (r.get("collector_number") or ""),
            "rarity": r.get("rarity"), "r": RMAP.get(r.get("rarity") or "", ""),
            "blob": re.sub(r"\s+", " ", blob).strip(),
            "released": str(set_upcoming[r.get("set_id")])[:10] if r.get("set_id") in set_upcoming else None,
        })
    (DATA / "text_index.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote text_index.json: {len(out)} cards")

    # slim SHIPPABLE version the PWA loads: id + name + version + blob + the
    # exact-match keys (set code + collector number → cnBySet). NOTE: `s` is the
    # PRINTED SET CODE (was strength pre-2026-07-14 — nothing ever consumed it as
    # strength; scanner.js buildNameDB keys cnBySet on it). c/w were dead weight.
    REPO = HERE.parent.parent
    slim = [{
        "id": c["id"], "n": c["name"], "v": c["version"], "b": c["blob"],
        "s": c["set"], "cn": c["cn"], "r": c["r"],
        **({"d": c["released"]} if c["released"] else {}),
    } for c in out]
    (REPO / "scanner" / "text.json").write_text(json.dumps(slim, separators=(",", ":")), encoding="utf-8")
    sz = (REPO / "scanner" / "text.json").stat().st_size
    print(f"wrote scanner/text.json: {len(slim)} cards ({sz/1e6:.2f} MB raw)")

if __name__ == "__main__":
    main()
