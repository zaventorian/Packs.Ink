"""
import_quest_cards.py: load the Illumineer's Quest scenario cards that Lorcast
never indexed (Q1 Deep Trouble, Q2 Palace Heist) into `cards`.

Source is LorcanaJSON (lorcanajson.org), which parses the official Lorcana app:
every quest card with its number, text, stats, artist, the official card image
and the TCGplayer product id. TCGplayer sells these singles (groups 23528 and
24257), and the daily ETL already prices them, so a `cards` row with the pid is
all it takes for a price to show.

  * Rows are `crd_quest_<q1|q2>_<n>` in `set_quest_q1` / `set_quest_q2`
    (migration 179), rarity "Quest". Lorcast's own Q3 rows are left alone.
  * Art is copied from the official image host into the public `card-art`
    bucket (quests/<q1|q2>/<n>.jpg, 734px JPEG). The site never hotlinks it.
  * Idempotent: re-running refreshes data and art in place, same ids.

Usage:
  python scripts/import_quest_cards.py            # dry run
  python scripts/import_quest_cards.py --commit   # upload art + upsert rows
"""
from __future__ import annotations

import argparse, io, json, os, sys, zipfile

import requests
from dotenv import load_dotenv
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

LJSON_ZIP = "https://lorcanajson.org/files/current/en/allCards.json.zip"
BUCKET = "card-art"
IMG_WIDTH = 734
QUESTS = {"Q1": "set_quest_q1", "Q2": "set_quest_q2"}
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
    rows = []
    for c in cards:
        set_id = QUESTS[c["setCode"]]
        label = f"{c['setCode']} #{c['number']} {c.get('fullName') or c['name']}"
        if not args.commit:
            r = build_row(c, set_id, None)
            print(f"  {label} | {r['card_type']} | pid {r['tcgplayer_product_id']}")
            continue
        src = (c.get("images") or {}).get("full")
        url = None
        if src:
            try:
                jpg = optimize(requests.get(src, headers=UA, timeout=45).content)
                path = f"quests/{c['setCode'].lower()}/{int(c['number'])}.jpg"
                up = requests.post(f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
                                   headers={**sb.auth_headers(), "Content-Type": "image/jpeg", "x-upsert": "true"},
                                   data=jpg, timeout=60)
                if up.ok:
                    url = f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"
                else:
                    print(f"  {label} UPLOAD FAIL {up.status_code}")
            except Exception as e:
                print(f"  {label} IMAGE ERR {repr(e)[:120]}")
        rows.append(build_row(c, set_id, url))
        print(f"  {label} {'ok' if url else 'NO ART'}")

    if not args.commit:
        print(f"\nDRY RUN: {len(cards)} card(s). Add --commit to load.")
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
