"""
import_official_set.py — pre-stage a set's cards with OFFICIAL art + full data
straight from the Disney Lorcana card gallery, for the reveal-season window while
Lorcast is still behind. Reusable for any set.

Why / how it works
------------------
`cards.disneylorcana.com/en-US/?set=<slug>` embeds the ENTIRE catalog inline
(RSC `$R[n]=` format) — full data (name, version, ink, cost, rarity, type,
classifications, rules text, stats, illustrator) AND the card art. The art lives
on the ravensburger.cloud CDN, which gates on the `Sec-Fetch-Dest: image` header:
browser JS cannot set Sec-Fetch-* (forbidden headers) so every in-browser path
fails (CORS, canvas taint, hotlink), but a SERVER-SIDE client CAN — that's the
whole unlock. Pillow 11 decodes the AVIF natively.

This inserts a `crd_prestage_<tag>_<cn>` row (official data + 734px JPEG uploaded
to the public `card-art` bucket) for every card NOT already a real Lorcast row,
and leaves Lorcast cards alone. Re-run any time to pick up newly-revealed cards
and refresh data on the stand-ins. The daily ETL's retire_prestaged.py then
swaps each stand-in to Lorcast's version (re-pointing deck/collection refs) the
moment Lorcast publishes it.

Find the set params:
  * --set-id : Lorcast set_id (`select id,code,name from sets`)
  * --slug   : the ?set= value on the gallery (e.g. set13) — also the card_sets
               id and the `lorcana_en_<slug>_` image-URL prefix
  * --setnum : the "EN <n>" number in card_identifier (Set 13 -> 13)
  * --tag    : storage subfolder + prestage-id tag (default = slug)

Usage:
  python scripts/import_official_set.py --set-id set_57c... --slug set13 --setnum 13
  # add --commit to download art + upsert (default is a dry run)
"""
from __future__ import annotations

import argparse, io, os, re, sys, requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase
from PIL import Image

GALLERY = "https://cards.disneylorcana.com/en-US/?set={slug}"
BUCKET = "card-art"
IMG_WIDTH = 734
IMG_HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://cards.disneylorcana.com/", "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site",
}
RARITY = {"common": "Common", "uncommon": "Uncommon", "rare": "Rare", "super": "Super Rare",
          "super_rare": "Super Rare", "legendary": "Legendary", "enchanted": "Enchanted",
          "epic": "Epic", "iconic": "Iconic", "promo": "Promo"}


def clean_text(raw):
    if not raw:
        return None
    t = re.sub(r"\\x([0-9a-fA-F]{2})", lambda m: chr(int(m.group(1), 16)), raw)  # \x3C -> <
    t = t.replace("\\n", "\n").replace("\\", "")  # newlines, then drop bold/keyword backslash markup
    t = t.replace("<", "").replace(">", "")        # strip keyword tag brackets -> plain keyword name
    return re.sub(r"[ \t]+\n", "\n", t).strip() or None


def parse_card(html, cn, setnum):
    i = html.find(f'card_identifier:"{cn}/207 EN {setnum}"')
    # tolerate a non-204/207 total on future sets
    if i < 0:
        m = re.search(r'card_identifier:"' + str(cn) + r'/\d+ EN ' + str(setnum) + r'"', html)
        i = m.start() if m else -1
    if i < 0:
        return None
    w = html[i:i + 2800]
    a = w[w.find("magic_ink_colors"):]

    def q(pat, src=w):
        m = re.search(pat, src); return m.group(1) if m else None

    def num(k):
        m = re.search(k + r":(\d+)", w); return int(m.group(1)) if m else None

    inks = re.search(r"magic_ink_colors:\$R\[\d+\]=\[([^\]]*)\]", w)
    inks = [x.strip().strip('"').title() for x in inks.group(1).split(",")] if inks and inks.group(1) else None
    subt = re.search(r"subtypes:\$R\[\d+\]=\[([^\]]*)\]", w)
    subt = [x.strip().strip('"') for x in subt.group(1).split(",")] if subt and subt.group(1) else None
    ctype = q(r'card_type:"([^"]*)"')
    if subt and "Song" in subt:
        ctype = "Action - Song"
    elif ctype:
        ctype = ctype.title()
    # author sits immediately BEFORE this card's identifier
    am = re.search(r'author:"([^"]*)",card_identifier:"' + str(cn) + r'/\d+ EN ' + str(setnum) + r'"', html)
    ills = [s.strip() for s in re.split(r"\s*/\s*|\s*&\s*", am.group(1)) if s.strip()] if am else None
    rules = re.search(r'rules_text:"(.*?)",(?:searchable_keywords|set_rotation_state|subtypes|sort_number)', w, re.S)
    flav = re.search(r'flavor_text:"(.*?)",(?:ink_convertible|rarity|searchable_keywords|set_rotation_state)', w, re.S)
    img = re.search(r'detail_image_url:"([^"]+)"', w)
    rar = q(r'rarity:"([^"]*)"')
    return dict(
        name=q(r'name:"([^"]*)"', a), version=q(r'subtitle:"([^"]*)"'),
        rarity=RARITY.get((rar or "").lower(), rar), ink=(inks[0] if inks else None), inks=inks,
        cost=num("ink_cost"), inkable=("ink_convertible:!0" in w), card_type=ctype, classifications=subt,
        strength=num("strength"), willpower=num("willpower"), lore=num("quest_value"), move_cost=num("move_cost"),
        text=clean_text(rules.group(1) if rules else None), flavor_text=clean_text(flav.group(1) if flav else None),
        illustrators=ills, img=(img.group(1) + "card") if img else None,
    )


def optimize(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if im.width > IMG_WIDTH:
        im = im.resize((IMG_WIDTH, round(im.height * IMG_WIDTH / im.width)), Image.LANCZOS)
    buf = io.BytesIO(); im.save(buf, "JPEG", quality=84, optimize=True); return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-id", required=True)
    ap.add_argument("--slug", required=True, help="?set= value, e.g. set13")
    ap.add_argument("--setnum", required=True, type=int, help='the "EN <n>" number, e.g. 13')
    ap.add_argument("--tag", default=None, help="storage/id tag (default = slug)")
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()
    tag = args.tag or args.slug

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    html = requests.get(GALLERY.format(slug=args.slug), timeout=60).text
    cns = sorted(set(int(m) for m in re.findall(r'card_identifier:"(\d+)/\d+ EN ' + str(args.setnum) + r'"', html)))
    print(f"Official gallery cards for {args.slug}: {len(cns)}")

    rows = sb.select("cards", columns="id,collector_number", filters={"set_id": f"eq.{args.set_id}"})
    real_cns = {int(r["collector_number"]) for r in rows
                if not r["id"].startswith("crd_prestage_") and (r.get("collector_number") or "").isdigit()}
    todo = [cn for cn in cns if cn not in real_cns]
    print(f"non-Lorcast to import: {len(todo)}\n")

    final = []
    for cn in todo:
        m = parse_card(html, cn, args.setnum)
        if not m or not m["name"] or not m["img"]:
            print(f"  #{cn} SKIP (no data/img)"); continue
        label = f"#{cn} {m['name']}" + (f" - {m['version']}" if m['version'] else "")
        if not args.commit:
            print(f"  {label} | {m['rarity']} | {','.join(m['inks'] or [])} | cost {m['cost']} | {m['card_type']}"); continue
        try:
            data = requests.get(m["img"], headers=IMG_HDRS, timeout=45).content
            jpg = optimize(data)
            path = f"{tag}/{cn}.jpg"
            up = requests.post(f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
                               headers={"apikey": sb.key, "Authorization": f"Bearer {sb.key}",
                                        "Content-Type": "image/jpeg", "x-upsert": "true"}, data=jpg, timeout=60)
            if not up.ok:
                print(f"  {label} UPLOAD FAIL {up.status_code}"); continue
            url = f"{sb.url}/storage/v1/object/public/{BUCKET}/{path}"
            final.append({"id": f"crd_prestage_{tag}_{cn}", "set_id": args.set_id, "collector_number": str(cn),
                          "name": m["name"], "version": m["version"], "rarity": m["rarity"], "ink": m["ink"],
                          "inks": m["inks"], "cost": m["cost"], "inkable": m["inkable"], "card_type": m["card_type"],
                          "classifications": m["classifications"], "strength": m["strength"], "willpower": m["willpower"],
                          "lore": m["lore"], "move_cost": m["move_cost"], "text": m["text"], "flavor_text": m["flavor_text"],
                          "illustrators": m["illustrators"],
                          # tcgplayer_product_id deliberately omitted: link_preorder_pids
                          # fills it on prestage rows, and a refresh re-run sending null
                          # would clobber the link and drop the card to $— for hours.
                          "image_small": url, "image_normal": url, "image_large": url})
            print(f"  {label} -> {len(jpg)//1024}KB")
        except Exception as e:
            print(f"  {label} ERR {repr(e)[:140]}")

    print(f"\n{'COMMIT' if args.commit else 'DRY'}: {len(final) if args.commit else len(todo)} card(s).")
    if args.commit and final:
        sb.upsert("cards", final, on_conflict="id")
        print(f"Upserted {len(final)} prestage row(s).")
        try:
            sb.rpc("refresh_card_prices_latest"); print("matview refreshed.")
        except Exception as e:
            print("refresh fail:", e)


if __name__ == "__main__":
    main()
