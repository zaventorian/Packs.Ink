"""
import_pasted_cards.py — pre-stage a revealed card from a PASTED SCREENSHOT,
for the window where the official gallery does not have it yet.

WHY THIS EXISTS (and when NOT to use it)
----------------------------------------
There are three ways a revealed card reaches the site, and this is the last
resort of the three:

  1. import_official_set.py — the official gallery. Full data AND official art,
     parsed, free and authoritative. ALWAYS prefer it; re-run it as reveals land.
  2. prestage_set_cards.py — TCGCSV extendedData for the set's group. Real card
     data plus a pid, so pre-order prices flow.
  3. THIS — a picture and nothing else. For a card revealed on a stream, a
     podcast slide or a social post, where the gallery has no entry and TCGCSV
     has no product. Measured 2026-09-22 on Hyperia City: the gallery had 11 of
     204, and TCGCSV group 24740 carried 8 sealed products and ZERO cards — so
     for most of that set's reveal season there is no machine-readable source.

Because the only source is a picture, the card DATA is supplied by hand in a
JSON manifest rather than scraped. That is the whole risk of this path: a
misread cost or a wrong stat is a lie the site states confidently, and unlike a
missing card, nothing about it looks wrong. So:

  * it is a DRY RUN by default, and --contact writes a sheet pairing each crop
    with the data claimed for it — look at it, the same rule cut_collectible_bg
    and bake_brand_assets already carry;
  * every field is optional EXCEPT name and collector_number, and an omitted
    field is left NULL rather than guessed. A card with no cost renders fine; a
    card with the WRONG cost is worse than one with none.

⚠ COLLECTOR NUMBER IS MANDATORY, and not for tidiness. retire_prestaged keys on
(set_id, collector_number) — that is how a stand-in is swapped for Lorcast's
real card, with deck/collection refs re-pointed, the day Lorcast publishes it.
A row with no number can never be retired, so it becomes a permanent duplicate
tile the moment the set lands. This is the same rule the set-spoilers review
states: a card with a name but no number is NOT prestageable — wait for the
checklist.

⚠ THE ID AND ART PATH ARE DELIBERATELY THE ONES import_official_set USES
(crd_prestage_<tag>_<cn>, card-art/<tag>/<cn>.jpg). So the moment the gallery
publishes a card we hand-made here, re-running import_official_set OVERWRITES
this row and its art in place — same id, so nobody's collection mark moves, and
no duplicate is created. Keep the tag identical (set14) or that property is lost.

Manifest (a JSON list). crop is [x, y, w, h] in the SOURCE image's pixels, and
is optional — omit it when the paste is already just the card:

  [
    {"image": "1.png", "crop": [120, 64, 500, 700], "collector_number": 21,
     "name": "Miguel Rivera", "version": "Aspiring Musician",
     "rarity": "Rare", "inks": ["Amber"], "cost": 3, "inkable": true,
     "card_type": "Character", "classifications": ["Storyborn", "Hero"],
     "strength": 2, "willpower": 3, "lore": 2,
     "text": "...", "flavor_text": "...", "illustrators": ["..."]}
  ]

Usage:
    python scripts/import_pasted_cards.py --manifest cards.json \
        --images "<session images dir>" --set-id set_hyperia_city --tag set14 \
        --contact sheet.jpg
    # add --commit to upload art + upsert rows (default is a dry run)
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase
from PIL import Image, ImageDraw

BUCKET = "card-art"
IMG_WIDTH = 734
# A Lorcana card is 5:7 portrait; a Location is the same card turned on its side
# and every art source still frames it PORTRAIT (see the landscape-card note in
# CLAUDE.md), so a correct crop is portrait either way. A crop far off that is a
# mis-read box — the commonest failure here, and one that looks deliberate.
ASPECT = 5 / 7
ASPECT_TOL = 0.14
RARITIES = {"Common", "Uncommon", "Rare", "Super Rare", "Legendary",
            "Enchanted", "Epic", "Iconic", "Promo"}
INKS = {"Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"}

# ⚠ A mainline Lorcana set is numbered in six EQUAL INK BLOCKS, in this order.
# That makes the collector number a second, independent witness for the ink —
# which matters because ink is read off a screenshot by eye, and the six frame
# colours are easy to confuse at reveal-image quality (a hue classifier over the
# name band scored only 8/11 on cards whose ink we already knew, confusing
# Amethyst with Ruby and reading Steel's tan rules box as Amber).
# Verified 2026-09-22 against all 11 Hyperia City cards the official gallery had
# published, with their inks taken from the official data: 11/11.
# It is a CROSS-CHECK, never an override — a set with a different base size, or
# a promo/Enchanted numbered past the base set, must not be silently rewritten.
INK_BLOCK_ORDER = ["Amber", "Amethyst", "Emerald", "Ruby", "Sapphire", "Steel"]


def ink_from_collector_number(cn, base_size):
    """The ink a plain base-set collector number implies, or None if it is out
    of range — which is the normal case for an Enchanted/promo number above the
    base size, where the card keeps the ink of the card it enchants."""
    try:
        n = int(cn)
    except (TypeError, ValueError):
        return None
    if not base_size or n < 1 or n > base_size:
        return None
    per = base_size / len(INK_BLOCK_ORDER)
    if per != int(per):
        return None
    return INK_BLOCK_ORDER[int((n - 1) // per)]


def optimize(im):
    im = im.convert("RGB")
    if im.width > IMG_WIDTH:
        im = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=84, optimize=True)
    return buf.getvalue()


def validate(c, idx):
    """Every check refuses rather than repairs: this data was typed by hand."""
    errs = []
    if not c.get("name"):
        errs.append("name is required")
    cn = c.get("collector_number")
    if cn is None or str(cn).strip() == "":
        errs.append("collector_number is required (retire_prestaged keys on it)")
    elif not str(cn).strip().isdigit():
        errs.append("collector_number %r is not a plain number" % (cn,))
    if c.get("rarity") and c["rarity"] not in RARITIES:
        errs.append("rarity %r is not canonical %s" % (c["rarity"], sorted(RARITIES)))
    for ink in (c.get("inks") or []):
        if ink not in INKS:
            errs.append("ink %r is not one of %s" % (ink, sorted(INKS)))
    crop = c.get("crop")
    if crop is not None and (not isinstance(crop, list) or len(crop) != 4):
        errs.append("crop must be [x, y, w, h]")
    if not c.get("image"):
        errs.append("image is required")
    return ["  #%s %s: %s" % (idx, c.get("name") or "?", e) for e in errs]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--images", required=True,
                    help="folder the manifest's image names are relative to")
    ap.add_argument("--set-id", required=True)
    ap.add_argument("--tag", required=True,
                    help="storage/id tag - MUST match import_official_set's (e.g. set14)")
    ap.add_argument("--slug", default=None,
                    help="official-gallery ?set= value (e.g. set14) — used to REFUSE a card "
                         "the gallery already has")
    ap.add_argument("--setnum", type=int, default=None,
                    help='the "EN <n>" number (e.g. 14), with --slug')
    ap.add_argument("--allow-gallery-override", action="store_true",
                    help="import even where the gallery has the card (you will be replacing "
                         "official art with a screenshot — almost never what you want)")
    ap.add_argument("--base-size", type=int, default=204,
                    help="cards in the base set (204 for a mainline set) — used to "
                         "cross-check each ink against its collector number")
    ap.add_argument("--contact", default=None, help="write a verification sheet here")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    cards = json.load(open(args.manifest, encoding="utf-8"))
    if isinstance(cards, dict):
        cards = [cards]

    errs = [e for i, c in enumerate(cards) for e in validate(c, i + 1)]
    if errs:
        print("Manifest is not usable:\n" + "\n".join(errs))
        return 1

    sb = Supabase()
    existing = sb.select("cards", columns="id,collector_number",
                         filters={"set_id": "eq.%s" % args.set_id})
    real = set()
    for r in existing:
        if not r["id"].startswith("crd_prestage_") and r.get("collector_number"):
            real.add(str(r["collector_number"]).strip())

    # ⚠ The Lorcast skip above is NOT enough on its own. This script writes the
    # SAME id and the SAME storage path as import_official_set (that is what lets
    # the gallery supersede us in place), so a card the gallery ALREADY carries
    # would have its official art silently overwritten by a screenshot crop —
    # strictly worse art and possibly worse data, with nothing to show for it,
    # because a prestage row is not a "real" row and so never hits that skip.
    # Verified 2026-09-22: cn 75 was already crd_prestage_set14_75 from the
    # gallery and would have been clobbered. Ask the gallery directly.
    gallery = set()
    if args.slug and args.setnum:
        try:
            import re
            html = requests.get("https://cards.disneylorcana.com/en-US/?set=%s" % args.slug,
                                timeout=60).text
            gallery = set(re.findall(r'card_identifier:"(\d+)/\d+ EN %d"' % args.setnum, html))
            print("official gallery carries %d card(s) for %s\n" % (len(gallery), args.slug))
        except Exception as e:
            print("could not read the gallery (%r) — proceeding without that guard\n" % (e,))
    else:
        print("no --slug/--setnum: NOT checking the official gallery. Pass them, or you may "
              "overwrite official art with a screenshot.\n")

    prepared, sheet = [], []
    for c in cards:
        cn = str(c["collector_number"]).strip()
        label = "#%s %s" % (cn, c["name"]) + (" - %s" % c["version"] if c.get("version") else "")
        if cn in real:
            print("  %s SKIP - Lorcast already has this card" % label)
            continue
        if cn in gallery and not args.allow_gallery_override:
            print("  %s SKIP - the official gallery HAS this card. Run instead:\n"
                  "      python scripts/import_official_set.py --set-id %s --slug %s "
                  "--setnum %s --tag %s --commit\n"
                  "    (--allow-gallery-override forces it, and replaces official art "
                  "with this screenshot)"
                  % (label, args.set_id, args.slug, args.setnum, args.tag))
            continue
        path = os.path.join(args.images, c["image"])
        if not os.path.exists(path):
            print("  %s SKIP - no such image: %s" % (label, path))
            continue
        im = Image.open(path)
        if c.get("crop"):
            x, y, w, h = c["crop"]
            im = im.crop((x, y, x + w, y + h))
        ratio = im.width / im.height if im.height else 0
        warn = ""
        want_ink = ink_from_collector_number(cn, args.base_size)
        got_ink = (c.get("inks") or [None])[0]
        if want_ink and got_ink and want_ink != got_ink:
            warn += ("   ** ink %s disagrees with #%s, which is in the %s block - "
                     "check the card" % (got_ink, cn, want_ink))
        if abs(ratio - ASPECT) > ASPECT_TOL:
            warn += "   ** aspect %.2f is not a card's %.2f - check the crop box" % (ratio, ASPECT)
        if im.width < IMG_WIDTH:
            warn += "   ** only %dpx wide (target %d) - it will be upscaled" % (im.width, IMG_WIDTH)
        jpg = optimize(im)
        prepared.append((c, cn, label, jpg))
        sheet.append((im.copy(), label))
        print("  %s | %s | %s | cost %s | %s | %dKB%s" % (
            label, c.get("rarity") or "-", ",".join(c.get("inks") or []) or "-",
            c.get("cost", "-"), c.get("card_type") or "-", len(jpg) // 1024, warn))

    if args.contact and sheet:
        cw, ch = 260, 364
        cols = min(5, len(sheet))
        rows = (len(sheet) + cols - 1) // cols
        out = Image.new("RGB", (cols * cw, rows * (ch + 24)), "#20182c")
        d = ImageDraw.Draw(out)
        for i, (im, label) in enumerate(sheet):
            t = im.convert("RGB").resize((cw - 12, ch - 12), Image.LANCZOS)
            x, y = (i % cols) * cw + 6, (i // cols) * (ch + 24) + 6
            out.paste(t, (x, y))
            d.text((x, y + ch - 2), label[:38], fill="#e8dcc8")
        out.save(args.contact, "JPEG", quality=88)
        print("\ncontact sheet -> %s  (LOOK AT IT before --commit)" % args.contact)

    if not args.commit:
        print("\nDRY: %d card(s). Re-run with --commit to upload + upsert." % len(prepared))
        return 0

    final = []
    for c, cn, label, jpg in prepared:
        p = "%s/%s.jpg" % (args.tag, cn)
        up = requests.post(
            "%s/storage/v1/object/%s/%s" % (sb.url, BUCKET, p),
            headers={"apikey": sb.key, "Authorization": "Bearer %s" % sb.key,
                     "Content-Type": "image/jpeg", "x-upsert": "true"},
            data=jpg, timeout=60)
        if not up.ok:
            print("  %s UPLOAD FAIL %s %s" % (label, up.status_code, up.text[:120]))
            continue
        url = "%s/storage/v1/object/public/%s/%s" % (sb.url, BUCKET, p)
        inks = c.get("inks") or None
        final.append({
            "id": "crd_prestage_%s_%s" % (args.tag, cn), "set_id": args.set_id,
            "collector_number": cn, "name": c["name"], "version": c.get("version"),
            "rarity": c.get("rarity"), "ink": (inks[0] if inks else None), "inks": inks,
            "cost": c.get("cost"), "inkable": c.get("inkable"),
            "card_type": c.get("card_type"), "classifications": c.get("classifications"),
            "strength": c.get("strength"), "willpower": c.get("willpower"),
            "lore": c.get("lore"), "move_cost": c.get("move_cost"),
            "text": c.get("text"), "flavor_text": c.get("flavor_text"),
            "illustrators": c.get("illustrators"),
            # tcgplayer_product_id deliberately omitted - link_preorder_pids fills
            # it, and sending null on a refresh would clobber that and drop the
            # card to $- for hours. Same reason import_official_set omits it.
            "image_small": url, "image_normal": url, "image_large": url,
        })
        print("  %s -> uploaded" % label)

    if final:
        sb.upsert("cards", final, on_conflict="id")
        print("\nUpserted %d prestage row(s)." % len(final))
        try:
            sb.rpc("refresh_card_prices_latest")
            print("matview refreshed.")
        except Exception as e:
            print("refresh fail:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
