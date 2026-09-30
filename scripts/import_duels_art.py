"""
import_duels_art.py - replace hand-cropped stand-in art with duels.ink's clean
renders, and add promos the catalog is missing.

WHY THIS EXISTS (and where it sits in the source precedence)
-------------------------------------------------------------
A card revealed before Lorcast or the official gallery has it reaches the site
as a STAND-IN built from a pasted screenshot (import_pasted_cards.py). Those
crops are the weakest art we carry: tilted, still wearing the yellow backdrop of
the reveal photo, cut off at an edge, or 125px wide. duels.ink publishes every
card as a flat, upright 1101x1536 render, and its public card API says where
each image came from:

  imageSource "reveal"     a clean full-card render of the real print. USE.
  imageSource "generated"  a gold "duels.ink preview" placeholder with NO art.
                           NEVER import one - it is worse than any crop.
  imageSource null         the official gallery's image. Already ours, via
                           import_official_set.py; this script leaves it alone.

Precedence stays Lorcast > official gallery > pasted screenshots. This script
only ever touches rows that are ALREADY prestage stand-ins (id crd_prestage_*),
so it cannot sit on top of a Lorcast card, and it skips any stand-in that is
already exactly 734x1024 (a clean import from the gallery or an earlier run).

WHAT IT WRITES
--------------
* Art: same storage path the stand-in already uses (that shared id/path is the
  overwrite mechanism - see import_pasted_cards.py), resized to 734 wide. The
  stored URL gains ?v=<hash> because packsink-img-v1 survives deploys and keys on
  the URL, so an in-place overwrite would otherwise keep serving the old crop.
* Rows: ONLY the image columns of existing rows. Names, stats and text are NOT
  touched - duels' names for a Japan-only reveal are its own translations
  (see the set-14 provenance note in CLAUDE.md), and a stand-in's data was
  reconciled separately.
* --add-missing: a promo duels lists and we do not have becomes a new stand-in.
  Mainline numbers are never added this way (Lorcast / the gallery own those).
  Illustrators are not in the API, so they are left NULL unless you pass
  --illustrators <json {"PD1|11": ["Name"]}>.

Dry run by default. Usage:
    python scripts/import_duels_art.py --setnum 14 --tag set14
    python scripts/import_duels_art.py --setnum 14 --tag set14 --add-missing --commit
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys

import requests

sys.path.insert(0, os.path.dirname(__file__))

API = "https://duels.ink/api/cards"
UA = {"User-Agent": "Mozilla/5.0 (packs.ink art import)"}
BUCKET = "card-art"
IMG_WIDTH = 734
OFFICIAL_SIZE = (734, 1024)
MAINLINE_TOTAL = re.compile(r"^(\d+)/\d+ [A-Z]{2} (\d+)$")
PROMO = re.compile(r"^(\d+)/([A-Z0-9]+) ([A-Z]{2}) (\d+)$")


def parse_full_id(full_id: str):
    """'167/204 EN 14' -> ('14', '167', 'EN'); '11/PD1 EN 14' -> ('PD1', '11', 'EN').
    The first element is the set code we file the card under: the set number for
    a mainline card, the promo code for a promo. None when it is neither."""
    m = PROMO.match(full_id)
    if m and not re.fullmatch(r"\d+", m.group(2)):
        return m.group(2), m.group(1), m.group(3)
    m = MAINLINE_TOTAL.match(full_id)
    if m:
        return m.group(2), m.group(1), re.search(r" ([A-Z]{2}) \d+$", full_id).group(1)
    return None


def cards_for_setnum(all_cards: list[dict], setnum: str) -> dict[str, dict]:
    """Every duels card printed for this set number, keyed 'CODE|cn'."""
    out = {}
    for c in all_cards:
        if not c.get("fullId", "").endswith(" " + str(setnum)):
            continue
        p = parse_full_id(c["fullId"])
        if p:
            out["%s|%s" % (p[0], p[1])] = c
    return out


def usable(card: dict) -> bool:
    """Only a real render. 'generated' is a placeholder; null is the gallery's."""
    return card.get("imageSource") == "reveal"


def needs_upgrade(size) -> bool:
    return tuple(size or ()) != OFFICIAL_SIZE


def clean_rules(t: str) -> str:
    """duels markup -> the {I}/{E}/{S}/{L}/{W} form our rows use, one ability per line."""
    for a, b in (("[INKCOST]", "{I}"), ("[EXERT]", "{E}"), ("[STRENGTH]", "{S}"),
                 ("[LORE]", "{L}"), ("[WILLPOWER]", "{W}")):
        t = t.replace(a, b)
    return re.sub(r"\n\s*\n", "\n", t).strip()


def card_type_of(c: dict) -> tuple[str, list[str] | None]:
    """A song is 'Action - Song' with NULL classifications (what the official
    rows carry); everything else keeps its subtypes."""
    kind = (c.get("type") or "").capitalize()
    subs = c.get("subtypes") or []
    if kind == "Action" and "Song" in subs:
        return "Action - Song", None
    return kind, subs or None


def to_jpeg(webp_bytes: bytes) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(webp_bytes)).convert("RGB")
    im = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue()


def fetch_all_cards() -> list[dict]:
    out, off = [], 0
    while True:
        j = requests.get(API, params={"limit": 200, "offset": off}, headers=UA, timeout=60).json()
        out += j["cards"]
        if not j["meta"].get("hasMore"):
            return out
        off += 200


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setnum", required=True, help='the set number, e.g. 14 (the "EN <n>" in a card id)')
    ap.add_argument("--tag", required=True, help="storage/id tag for MAINLINE stand-ins, e.g. set14")
    ap.add_argument("--add-missing", action="store_true", help="add promos duels has and we do not")
    ap.add_argument("--illustrators", help='JSON file {"PD1|11": ["Name"]} for --add-missing rows')
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    from dotenv import load_dotenv
    from PIL import Image
    from supabase_client import Supabase
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    sets = sb.select("sets", columns="id,code,name")
    set_by_code = {s["code"]: s["id"] for s in sets if s.get("code")}
    duels = cards_for_setnum(fetch_all_cards(), args.setnum)
    print("duels.ink has %d card(s) printed for set %s" % (len(duels), args.setnum))
    ill = json.load(open(args.illustrators, encoding="utf-8")) if args.illustrators else {}

    base = "%s/storage/v1/object/public/%s/" % (sb.url, BUCKET)
    upgrades, skipped_generated = [], []
    have = set()
    for code in {k.split("|")[0] for k in duels}:
        sid = set_by_code.get(code)
        if not sid:
            continue
        for r in sb.select("cards", columns="id,collector_number,image_normal",
                           filters={"set_id": "eq.%s" % sid}):
            key = "%s|%s" % (code, r.get("collector_number"))
            have.add(key)
            if not r["id"].startswith("crd_prestage_"):
                continue            # Lorcast owns it
            dc = duels.get(key)
            if not dc:
                continue
            if not usable(dc):
                if dc.get("imageSource") == "generated":
                    skipped_generated.append(key)
                continue
            old = requests.get(r["image_normal"].split("?")[0], timeout=60).content
            size = Image.open(io.BytesIO(old)).size
            if needs_upgrade(size):
                upgrades.append((key, r, dc, old, size))

    print("\nstand-ins to upgrade: %d" % len(upgrades))
    for key, r, dc, _old, size in sorted(upgrades, key=lambda t: t[0]):
        print("  %-9s %-28s %s -> %dx%d" % (key, r["id"], size, *OFFICIAL_SIZE))
    if skipped_generated:
        print("\nleft alone - duels only has a PLACEHOLDER (%d): %s"
              % (len(skipped_generated), ", ".join(sorted(skipped_generated))))

    missing = []
    if args.add_missing:
        for key, dc in sorted(duels.items()):
            code, cn = key.split("|")
            if key in have or not usable(dc) or code == str(args.setnum):
                continue            # mainline numbers belong to Lorcast / the gallery
            if code not in set_by_code:
                print("  !! no sets row for code %s - skipping %s" % (code, dc["fullName"]))
                continue
            missing.append((key, dc))
        print("\npromos to add: %d" % len(missing))
        for key, dc in missing:
            print("  %-9s %s" % (key, dc["fullName"]))

    if not args.commit:
        print("\nDRY. Re-run with --commit to upload and write.")
        return 0

    def upload(path: str, data: bytes) -> None:
        up = requests.post("%s/storage/v1/object/%s/%s" % (sb.url, BUCKET, path),
                           headers={**sb.auth_headers(), "Content-Type": "image/jpeg", "x-upsert": "true"},
                           data=data, timeout=90)
        if not up.ok:
            raise SystemExit("upload failed %s %s %s" % (path, up.status_code, up.text[:120]))

    def render(dc: dict) -> bytes:
        return to_jpeg(requests.get(dc["imageUrl"], headers=UA, timeout=90).content)

    backup = os.path.join(os.path.dirname(__file__), "scanner", "data", "duels_art_backup")
    os.makedirs(backup, exist_ok=True)
    for key, r, dc, old, size in upgrades:
        path = r["image_normal"].split("/%s/" % BUCKET)[1].split("?")[0]
        open(os.path.join(backup, "%s_%dx%d.jpg" % (key.replace("|", "_"), *size)), "wb").write(old)
        new = render(dc)
        upload(path, new)
        url = "%s%s?v=%s" % (base, path, hashlib.md5(new).hexdigest()[:8])
        sb.update("cards", {"id": "eq.%s" % r["id"]},
                  {"image_small": url, "image_normal": url, "image_large": url})
        print("  upgraded %s" % r["id"])

    rows = []
    for key, dc in missing:
        code, cn = key.split("|")
        tag = code.lower()
        new = render(dc)
        path = "%s/%s.jpg" % (tag, cn)
        upload(path, new)
        url = "%s%s?v=%s" % (base, path, hashlib.md5(new).hexdigest()[:8])
        inks = [x.capitalize() for x in dc["colors"]]
        ctype, cls = card_type_of(dc)
        rows.append({
            "id": "crd_prestage_%s_%s" % (tag, cn), "set_id": set_by_code[code],
            "collector_number": cn, "name": dc["name"], "version": dc.get("title") or None,
            "rarity": "Promo", "ink": inks[0] if inks else None, "inks": inks or None,
            "cost": dc.get("cost"), "inkable": dc.get("inkable"), "card_type": ctype,
            "classifications": cls, "strength": dc.get("strength"), "willpower": dc.get("willpower"),
            "lore": dc.get("lore"), "move_cost": dc.get("moveCost"),
            "text": clean_rules(dc.get("rulesText") or ""), "flavor_text": dc.get("flavorText") or None,
            "illustrators": ill.get(key), "image_small": url, "image_normal": url, "image_large": url,
        })
        print("  added %s %s%s" % (key, dc["fullName"], "" if ill.get(key) else "  (no illustrator)"))
    if rows:
        sb.upsert("cards", rows, on_conflict="id")
    try:
        sb.rpc("refresh_card_prices_latest")
    except Exception as e:  # noqa: BLE001
        print("matview refresh failed:", e)
    print("\nupgraded %d, added %d" % (len(upgrades), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
