"""
Build the TEXT index for OCR-based matching: every card's readable text
(name, version/subtitle, type, classifications, cost, strength, willpower,
lore, collector number, rules text, flavor) + a normalised search blob.

Writes scripts/scanner/data/text_index.json (dev / experiment). If text-OCR
proves out, a slim shippable version goes to repo-root scanner/.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
sys.path.insert(0, str(HERE.parent))
from supabase_client import Supabase  # noqa: E402

def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())

def main():
    load_dotenv(HERE.parent / ".env")
    DATA.mkdir(parents=True, exist_ok=True)
    sb = Supabase()
    # printed set code per set_id ("1".."13", "P1", "D23", ...) — the same code
    # printed on the card's bottom line next to the collector number
    # ("147/204 · EN · 3"), so an OCR'd (set, number) pair keys cnBySet exactly.
    sets = sb.select("sets", columns="id,code")
    set_code = {s["id"]: (s.get("code") or "").strip().upper() or None for s in sets}
    rows = sb.select("cards",
        columns="id,name,version,set_id,card_type,classifications,cost,strength,willpower,lore,inkable,ink,collector_number,text,flavor_text",
        filters={"image_normal": "not.is.null"})
    out = []
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
            "blob": re.sub(r"\s+", " ", blob).strip(),
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
        "s": c["set"], "cn": c["cn"],
    } for c in out]
    (REPO / "scanner" / "text.json").write_text(json.dumps(slim, separators=(",", ":")), encoding="utf-8")
    sz = (REPO / "scanner" / "text.json").stat().st_size
    print(f"wrote scanner/text.json: {len(slim)} cards ({sz/1e6:.2f} MB raw)")

if __name__ == "__main__":
    main()
