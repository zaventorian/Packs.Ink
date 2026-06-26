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
    rows = sb.select("cards",
        columns="id,name,version,card_type,classifications,cost,strength,willpower,lore,inkable,ink,collector_number,text,flavor_text",
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
            "cost": r.get("cost"), "strength": r.get("strength"),
            "willpower": r.get("willpower"), "lore": r.get("lore"),
            "cn": (r.get("collector_number") or ""),
            "blob": re.sub(r"\s+", " ", blob).strip(),
        })
    (DATA / "text_index.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"wrote text_index.json: {len(out)} cards")

    # slim SHIPPABLE version the PWA loads: id + name + version + blob (+ exact-
    # match fields cost/strength/willpower/cn for boosting). ~150KB gzipped.
    REPO = HERE.parent.parent
    slim = [{
        "id": c["id"], "n": c["name"], "v": c["version"], "b": c["blob"],
        "c": c["cost"], "s": c["strength"], "w": c["willpower"], "cn": c["cn"],
    } for c in out]
    (REPO / "scanner" / "text.json").write_text(json.dumps(slim, separators=(",", ":")), encoding="utf-8")
    sz = (REPO / "scanner" / "text.json").stat().st_size
    print(f"wrote scanner/text.json: {len(slim)} cards ({sz/1e6:.2f} MB raw)")

if __name__ == "__main__":
    main()
