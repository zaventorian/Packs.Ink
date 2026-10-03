"""
import_quest_cards.py: load the Illumineer's Quest cards that Lorcast never
indexed into `cards`.

  * The numbered scenario cards of Q1 Deep Trouble (31) and Q2 Palace Heist
    (35) come from LorcanaJSON (lorcanajson.org), which parses the official
    Lorcana app: number, text, stats, artist, the official card image and the
    TCGplayer product id. Rows are `crd_quest_<q1|q2>_<n>` in `set_quest_q1` /
    `set_quest_q2` (migration 179). Lorcast's own Q3 rows are left alone.
  * The OVERSIZED cards of all three quests (the boss card, the Reforged
    Crown, the double-sided battlegrounds) are in no LorcanaJSON list and carry
    no collector number. They come from TCGplayer's own listing (TCGCSV):
    `crd_quest_<q>_os<k>`, empty collector number, "(Oversized)" in the
    version, TCGplayer's photo.
  * TCGplayer sells all of them, and the daily ETL already prices them, so the
    pid on the row is all it takes for a price to show.
  * Art is copied into the public `card-art` bucket (quests/<q>/<slot>.jpg,
    734px JPEG). The site never hotlinks it.
  * Idempotent: re-running refreshes data and art in place, same ids.

Usage:
  python scripts/import_quest_cards.py            # dry run
  python scripts/import_quest_cards.py --commit   # upload art + upsert rows
"""
from __future__ import annotations

import argparse, io, json, os, re, sys, zipfile

import requests
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

LJSON_ZIP = "https://lorcanajson.org/files/current/en/allCards.json.zip"
TCGCSV = "https://tcgcsv.com/tcgplayer/71/{gid}/products"
TCG_IMG = "https://tcgplayer-cdn.tcgplayer.com/product/{pid}_in_1000x1000.jpg"
BUCKET = "card-art"
IMG_WIDTH = 734
QUESTS = {"Q1": "set_quest_q1", "Q2": "set_quest_q2"}
# TCGplayer group + our set per quest, for the oversized cards. Q3's set is Lorcast's.
OVERSIZED_GROUPS = {"Q1": (23528, "set_quest_q1"), "Q2": (24257, "set_quest_q2"),
                    "Q3": (24734, "set_5a55ed51fe9144248bc9d1b5656bc6b4")}
UA = {"User-Agent": "packs.ink quest-card import"}


def card_text(c: dict) -> str | None:
    """One line per ability, the way Lorcast stores `text`. LorcanaJSON's
    newlines are wraps from the printed card, not ability breaks."""
    abil = c.get("abilities") or []
    if abil:
        lines = [" ".join((a.get("fullText") or "").split()) for a in abil]
        return "\n".join(l for l in lines if l) or None
    t = c.get("fullText") or ""
    return " ".join(t.split()) or None


def build_row(c: dict, set_id: str, img_url: str | None) -> dict:
    n = int(c["number"])
    ink = (c.get("color") or "").strip() or None
    t = c.get("type")
    subtypes = c.get("subtypes") or None
    if t == "Action" and subtypes and "Song" in subtypes:
        t = "Action - Song"
        subtypes = [s for s in subtypes if s != "Song"] or None
    return {
        "id": f"crd_quest_{c['setCode'].lower()}_{n}",
        "set_id": set_id,
        "collector_number": str(n),
        "name": c["name"],
        "version": c.get("version"),
        "rarity": "Quest",
        "ink": ink,
        "inks": [ink] if ink else None,
        "cost": c.get("cost"),
        "inkable": c.get("inkwell"),
        "card_type": t,
        "classifications": subtypes,
        "strength": c.get("strength"),
        "willpower": c.get("willpower"),
        "lore": c.get("lore"),
        "move_cost": c.get("moveCost"),
        "text": card_text(c),
        "flavor_text": " ".join((c.get("flavorText") or "").split()) or None,
        "illustrators": c.get("artists") or None,
        "tcgplayer_product_id": (c.get("externalLinks") or {}).get("tcgPlayerId"),
        "image_small": img_url, "image_normal": img_url, "image_large": img_url,
    }


def strip_html(t: str | None) -> str | None:
    """TCGplayer's Description: <br> line breaks, inline tags, \\r\\n."""
    if not t:
        return None
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t).replace("\r", "")
    lines = [" ".join(l.split()) for l in t.split("\n")]
    return "\n".join(l for l in lines if l) or None


def split_oversized(product_name: str) -> tuple[str, str]:
    """'Ursula - Ruler of Lorcana (Oversized)' -> ('Ursula', 'Ruler of Lorcana
    (Oversized)'); 'The Reforged Crown (Oversized)' -> ('The Reforged Crown',
    'Oversized'); 'The Lair // Infinite Wrath - Battleground (Oversized)' ->
    ('The Lair // Infinite Wrath', 'Battleground (Oversized)')."""
    base = re.sub(r"\s*\(Oversized\)\s*$", "", product_name).strip()
    if " - " in base:
        name, ver = base.rsplit(" - ", 1)
        return name.strip(), f"{ver.strip()} (Oversized)"
    return base, "Oversized"


def oversized_rows(quest: str, products: list[dict], img_url_for) -> list[dict]:
    """Rows for the "(Oversized)" products in a quest's TCGplayer group,
    numbered os1.. in product-id order (stable: TCGplayer ids only grow)."""
    _, set_id = OVERSIZED_GROUPS[quest]
    over = sorted((p for p in products if "(Oversized)" in (p.get("name") or "")),
                  key=lambda p: p["productId"])
    out = []
    for k, p in enumerate(over, 1):
        ext = {e.get("name"): e.get("value") for e in p.get("extendedData") or []}
        name, ver = split_oversized(p["name"])
        ctype = ext.get("CardType") or ("Battleground" if ver.startswith("Battleground") else "Character")
        url = img_url_for(quest, f"os{k}", p["productId"])
        out.append({
            "id": f"crd_quest_{quest.lower()}_os{k}", "set_id": set_id, "collector_number": None,
            "name": name, "version": ver, "rarity": "Quest",
            "ink": None, "inks": None, "cost": None, "inkable": None, "card_type": ctype,
            "classifications": None, "strength": None, "willpower": None, "lore": None, "move_cost": None,
            "text": strip_html(ext.get("Description")), "flavor_text": None, "illustrators": None,
            "tcgplayer_product_id": p["productId"],
            "image_small": url, "image_normal": url, "image_large": url,
        })
    return out


def optimize(data: bytes) -> bytes:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width > IMG_WIDTH:
        im = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=84, optimize=True); return buf.getvalue()


def load_quest_cards() -> list[dict]:
    z = zipfile.ZipFile(io.BytesIO(requests.get(LJSON_ZIP, headers=UA, timeout=60).content))
    data = json.loads(z.read(z.namelist()[0]))
    return sorted((c for c in data["cards"] if c.get("setCode") in QUESTS),
                  key=lambda c: (c["setCode"], int(c["number"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

    cards = load_quest_cards()
    by_set = {q: sum(1 for c in cards if c["setCode"] == q) for q in QUESTS}
    print(f"LorcanaJSON quest cards: {by_set}")
    if not cards:
        sys.exit("No quest cards found: refusing to continue.")

    sb = Supabase() if args.commit else None

    def store(quest: str, slot, src: str | None) -> str | None:
        if not args.commit or not src:
            return None
        try:
            jpg = optimize(requests.get(src, headers=UA, timeout=45).content)
            path = f"quests/{quest.lower()}/{slot}.jpg"
            up = requests.post(f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
                               headers={**sb.auth_headers(), "Content-Type": "image/jpeg", "x-upsert": "true"},
                               data=jpg, timeout=60)
            if up.ok:
                return f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"
            print(f"  {quest} {slot} UPLOAD FAIL {up.status_code}")
        except Exception as e:
            print(f"  {quest} {slot} IMAGE ERR {repr(e)[:120]}")
        return None

    rows = []
    for c in cards:
        url = store(c["setCode"], int(c["number"]), (c.get("images") or {}).get("full"))
        r = build_row(c, QUESTS[c["setCode"]], url)
        rows.append(r)
        print(f"  {c['setCode']} #{c['number']} {c.get('fullName') or c['name']} | {r['card_type']}"
              f" | pid {r['tcgplayer_product_id']}" + ("" if not args.commit else (" ok" if url else " NO ART")))

    n_over = 0
    for quest, (gid, _) in OVERSIZED_GROUPS.items():
        prods = requests.get(TCGCSV.format(gid=gid), headers=UA, timeout=60).json().get("results") or []
        over = oversized_rows(quest, prods, lambda q, slot, pid: store(q, slot, TCG_IMG.format(pid=pid)))
        for r in over:
            print(f"  {quest} oversized: {r['name']} - {r['version']} | {r['card_type']} | pid {r['tcgplayer_product_id']}"
                  + ("" if not args.commit else (" ok" if r["image_normal"] else " NO ART")))
        rows.extend(over)
        n_over += len(over)

    if not args.commit:
        print(f"\nDRY RUN: {len(cards)} numbered + {n_over} oversized card(s). Add --commit to load.")
        return
    sb.upsert("cards", rows, on_conflict="id")
    print(f"\nUpserted {len(rows)} quest card row(s).")
    for fn in ("refresh_card_prices_latest", "refresh_price_movers"):
        try:
            sb.rpc(fn); print(f"{fn}: ok")
        except Exception as e:
            print(f"{fn} failed: {e}")


if __name__ == "__main__":
    main()
