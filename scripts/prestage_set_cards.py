"""
prestage_set_cards.py — pre-stage newly-revealed cards Lorcast hasn't indexed
yet, using a local image folder + TCGCSV extendedData, so they show on the site
the moment we have art for them.

The catalog renders any row in `cards` even with no price / no TCGPlayer link
(the no-price branch in transformSupabaseData synthesizes a $— row). So all we
have to do to make a revealed card appear is insert a `cards` row. This script:

  1. Reads an image folder named `<seq>_<cn>-<setcode>_<slug>.png` (the format
     of the Lorcana official-gallery batch download).
  2. Pulls TCGCSV extendedData for the set's TCGPlayer group — a COMPLETE,
     already-trusted card-data source (ink, cost, rarity, type, classification,
     text, stats, version, inkable) that is often ahead of Lorcast on pre-order
     products. Cards TCGCSV lists get full data + their pid (so pre-order prices
     flow); cards it doesn't list yet get name (de-slugged) + collector number,
     which auto-upgrade once TCGCSV/Lorcast catch up.
  3. Optimizes each PNG (~1 MB) to a ~734 px JPEG and uploads it to the public
     Supabase Storage bucket `card-art`, then points the row's image at it.
  4. Upserts a `cards` row id `crd_prestage_<setcode>_<cn>`.

These rows are RETIRED automatically by scripts/retire_prestaged.py (wired into
the daily metadata job) the moment Lorcast publishes the real card for that
(set, collector number) — so the site switches to Lorcast's image/data with zero
manual work. Re-run this script with a fresh folder each reveal batch.

Usage:
    python scripts/prestage_set_cards.py --folder "Art Assets/Set13_Cards" \
        --set-id set_57c6817823c14dda8eccbca4b555d858 --setcode 207 --group 24666
    # add --commit to upload images + write rows (default is a dry run)
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer/71"
USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests"
BUCKET = "card-art"
IMG_WIDTH = 734  # Lorcast 'large' width; tiles downscale via CSS

_RARITY_CANONICAL = {
    "common": "Common", "uncommon": "Uncommon", "rare": "Rare",
    "super rare": "Super Rare", "super_rare": "Super Rare",
    "legendary": "Legendary", "enchanted": "Enchanted", "epic": "Epic",
    "iconic": "Iconic", "promo": "Promo",
}


def norm_rarity(r):
    return _RARITY_CANONICAL.get(str(r or "").strip().lower(), r or None)


def get_json(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def strip_html(s):
    if not s:
        return None
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip() or None


def deslug(slug):
    """Best-effort name from a filename slug. Imperfect (apostrophes lost,
    'and'->'&'); only used for cards with no TCGCSV/Lorcast data yet, which
    overwrite this with the real name the moment either source lists them."""
    out = []
    for p in slug.split("-"):
        if p.lower() == "and":
            out.append("&")
        elif p.isdigit():
            out.append(p)
        else:
            out.append(p[:1].upper() + p[1:])
    return " ".join(out)


def ext_map(prod):
    return {e.get("name"): e.get("value") for e in (prod.get("extendedData") or [])}


def build_tcgcsv_by_cn(group_id):
    """collector_number(int) -> {pid, full extendedData dict, product name}."""
    prods = get_json(f"{TCGCSV_BASE}/{group_id}/products")
    prods = prods.get("results") if isinstance(prods, dict) and "results" in prods else prods
    out = {}
    for p in prods or []:
        ed = ext_map(p)
        num = ed.get("Number")
        if not num:
            continue
        try:
            cn = int(str(num).split("/")[0])
        except ValueError:
            continue
        out[cn] = {"pid": p.get("productId"), "ed": ed, "name": p.get("name") or ""}
    return out


def to_int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def card_row_from_tcgcsv(set_id, cn, tp, image_url):
    ed = tp["ed"]
    version = ed.get("Character Version") or None
    # TCGCSV appends " (Iconic)" / " (Enchanted)" / " (Epic)" to chase product
    # names — strip it before peeling off the version suffix.
    base_name = re.sub(r"\s*\((?:Iconic|Enchanted|Epic)\)\s*$", "", tp["name"])
    if version and base_name.endswith(" - " + version):
        base_name = base_name[: -(len(version) + 3)]
    ink = ed.get("InkType") or None
    inks = re.split(r"\s*[-/]\s*", ink) if ink else None  # dual-ink "Amber-Steel"
    classifications = [c.strip() for c in (ed.get("Classification") or "").split(";") if c.strip()] or None
    return {
        "id": f"crd_prestage_{set_id_tag}_{cn}",
        "set_id": set_id,
        "name": base_name,
        "version": version,
        "collector_number": str(cn),
        "rarity": norm_rarity(ed.get("Rarity")),
        "ink": (inks[0] if inks else None),
        "inks": inks,
        "cost": to_int(ed.get("Cost Ink")),
        "inkable": (str(ed.get("InkwellIcononCard") or "").strip().lower() == "yes"),
        "card_type": ed.get("CardType") or None,
        "strength": to_int(ed.get("Strength")),
        "willpower": to_int(ed.get("Willpower")),
        "lore": to_int(ed.get("Lore Value")),
        "move_cost": to_int(ed.get("Move Cost")),
        "classifications": classifications,
        "text": strip_html(ed.get("Description")),
        "flavor_text": strip_html(ed.get("Flavor Text")),
        "tcgplayer_product_id": tp["pid"],
        "image_small": image_url,
        "image_normal": image_url,
        "image_large": image_url,
    }


def card_row_image_only(set_id, cn, slug, image_url):
    return {
        "id": f"crd_prestage_{set_id_tag}_{cn}",
        "set_id": set_id,
        "name": deslug(slug),
        "version": None,
        "collector_number": str(cn),
        "rarity": None, "ink": None, "inks": None, "cost": None,
        "inkable": None, "card_type": None,
        "strength": None, "willpower": None, "lore": None, "move_cost": None,
        "classifications": None, "text": None, "flavor_text": None,
        "tcgplayer_product_id": None,
        "image_small": image_url, "image_normal": image_url, "image_large": image_url,
    }


def optimize_image(path):
    from PIL import Image
    import io
    im = Image.open(path).convert("RGB")
    if im.width > IMG_WIDTH:
        h = round(im.height * IMG_WIDTH / im.width)
        im = im.resize((IMG_WIDTH, h), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()


def upload_image(sb, set_id_tag, cn, data):
    path = f"{set_id_tag}/{cn}.jpg"
    url = f"{sb.url}/storage/v1/object/{BUCKET}/{path}"
    r = requests.post(url, headers={
        "apikey": sb.key, "Authorization": f"Bearer {sb.key}",
        "Content-Type": "image/jpeg", "x-upsert": "true",
    }, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"upload {path} failed ({r.status_code}): {r.text[:300]}")
    return f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"


set_id_tag = "set13"  # storage subfolder + id tag; set in main()


def main():
    global set_id_tag
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", required=True)
    ap.add_argument("--set-id", required=True)
    ap.add_argument("--setcode", required=True, help="filename set code, e.g. 207 or PD1")
    ap.add_argument("--group", type=int, required=True, help="TCGCSV group id")
    ap.add_argument("--tag", default="set13", help="id/storage tag (default set13)")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    set_id_tag = args.tag

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase() if args.commit else None

    # Parse the image folder for this setcode.
    files = {}
    for f in os.listdir(args.folder):
        m = re.match(r"^\d+_(\d+)-" + re.escape(args.setcode) + r"_(.+)\.png$", f)
        if m:
            files[int(m.group(1))] = {"slug": m.group(2), "file": os.path.join(args.folder, f)}
    print(f"Folder cards for setcode {args.setcode}: {len(files)}")

    # Which collector numbers are already real (non-prestage) cards in this set?
    existing = set()
    if args.commit or True:
        try:
            rows = Supabase().select("cards", columns="id,collector_number",
                                     filters={"set_id": f"eq.{args.set_id}"})
            for r in rows:
                if not str(r.get("id", "")).startswith("crd_prestage_"):
                    existing.add(to_int(r.get("collector_number")))
        except SystemExit:
            print("  (no DB creds — dry run will treat all folder cards as holes)")

    tcg = build_tcgcsv_by_cn(args.group)
    print(f"TCGCSV cards in group {args.group}: {len(tcg)}\n")

    rows, full, imageonly, skipped = [], 0, 0, 0
    for cn in sorted(files):
        if cn in existing:
            skipped += 1
            continue
        slug = files[cn]["slug"]
        img_url = f"{sb.url if sb else 'https://<supabase>'}/storage/v1/object/public/{BUCKET}/{set_id_tag}/{cn}.jpg"
        if cn in tcg:
            row = card_row_from_tcgcsv(args.set_id, cn, tcg[cn], img_url)
            src = "TCGCSV"
            full += 1
        else:
            row = card_row_image_only(args.set_id, cn, slug, img_url)
            src = "image "
            imageonly += 1
        rows.append((cn, files[cn]["file"], row))
        print(f"  #{cn:>3} [{src}] {row['name']}"
              + (f" - {row['version']}" if row.get('version') else "")
              + f"  | {row.get('rarity') or '—'} | {row.get('ink') or '—'}"
              + f" | cost {row.get('cost') if row.get('cost') is not None else '—'}"
              + (f" | pid {row['tcgplayer_product_id']}" if row.get('tcgplayer_product_id') else ""))

    print(f"\n{'COMMIT' if args.commit else 'DRY RUN'}: {len(rows)} to prestage "
          f"({full} full from TCGCSV, {imageonly} image+name), {skipped} already real.")

    if not args.commit:
        print("\nDry run — no images uploaded, no rows written. Re-run with --commit.")
        return

    print("\nUploading images + upserting rows...")
    final_rows = []
    for cn, fpath, row in rows:
        try:
            data = optimize_image(fpath)
            row["image_small"] = row["image_normal"] = row["image_large"] = upload_image(sb, set_id_tag, cn, data)
            final_rows.append(row)
            print(f"  uploaded #{cn} ({len(data)//1024} KB)")
        except Exception as e:
            print(f"  ERR image #{cn}: {repr(e)[:200]}")
    if final_rows:
        sb.upsert("cards", final_rows, on_conflict="id")
        print(f"\nUpserted {len(final_rows)} prestage card(s).")
        try:
            sb.rpc("refresh_card_prices_latest")
            print("Refreshed card_prices_latest.")
        except Exception as e:
            print(f"matview refresh failed: {e}")
    print("\nDone.")


if __name__ == "__main__":
    main()
