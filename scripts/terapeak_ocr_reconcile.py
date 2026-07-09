"""OCR-reconcile graded_sales against slab labels, and surface red flags.

Go-forward standard (Zaven 2026-07-09): OCR EVERY new card (cheap — we already
have the image URLs), then have Claude audit only the rows that look wrong. Two
independent red-flag detectors:

  1. OCR cn/grade DISAGREES with the title-based attribution — catches slab-vs-
     title mismatches (e.g. an unmatched D23 promo whose label reads "#3").
  2. PRICE-vs-RARITY outlier (no OCR) — a base-rarity card (Common..Legendary)
     sold for a chase-level price. This is the most reliable catch for the
     "no collector-number in title -> matcher defaulted to the cheap base card"
     conflation (Buzz Jungle Ranger #91 vs Iconic #241, Ariel #17 vs #241), and
     it does not depend on OCR reading the slab correctly.

The script does NOT auto-edit the DB — OCR mis-reads, so every change stays
Claude-gated. It writes a red-flag JSON for review + apply.

Usage:
  python terapeak_ocr_reconcile.py                     # rows scraped today
  python terapeak_ocr_reconcile.py --scraped-since 2026-07-01
  python terapeak_ocr_reconcile.py --all-active        # full historical pass (slow)
  python terapeak_ocr_reconcile.py --limit 40          # sample for testing
  python terapeak_ocr_reconcile.py --min-price 100

Output: scripts/terapeak_output/ocr_reconcile_<stamp>.json  (+ printed summary)
Requires: pip install pytesseract pillow requests python-dotenv ; Tesseract binary.
"""
import argparse, json, os, re, sys
from pathlib import Path
from datetime import date
import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
import terapeak_audit_ocr as ocrlib  # reuse ocr_label / fetch_image / CACHE_DIR

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
OUT_DIR = Path(__file__).parent / "terapeak_output"

# A single graded card of these base rarities selling ABOVE the threshold is
# implausible -> almost always a chase-card sale mis-filed onto the base printing
# (or a lot). Chase rarities (Enchanted/Epic/Iconic/Promo) are omitted — high
# prices are normal there. Cold-foil commons/promos can be legit-high, so this
# only FLAGS for Claude; it never auto-edits.
PRICE_CEILING = {
    "Common": 150, "Uncommon": 150, "Rare": 300, "Super Rare": 500, "Legendary": 700,
}
LOT_HINT = re.compile(r"\b(set|lot|bundle|complete|full)\b|[a-z]\s*&\s*[a-z]| and .+ and ", re.I)


def sb_conn():
    load_dotenv(Path(__file__).parent / ".env")
    base = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return base, {"apikey": key, "Authorization": f"Bearer {key}"}


def norm_cn(cn):
    if cn is None:
        return None
    d = re.sub(r"\D", "", str(cn))
    return str(int(d)) if d else None


# Slab collector number prints as "241/204" (num/set-total) or "#241". The
# denominator form is reliable; a bare "#N" is weak (grade/prize/pop counts).
CN_STRONG = re.compile(r"\b(\d{1,3})\s*/\s*(?:204|31|C1|C2|P1|P2|P3|D23|D100)\b")
CN_HASH = re.compile(r"#\s*(\d{1,3})\b")
GRADE_NEAR = re.compile(
    r"(?:GEM\s*MT|GEM\s*MINT|MINT|PRISTINE|PSA|CGC|BGS|SGC|TAG|GRADE)\D{0,6}(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5\.5|5)\b"
)


def ocr_cn_confident(ocr_text):
    m = CN_STRONG.search(ocr_text)
    if m:
        return norm_cn(m.group(1)), "strong"
    m = CN_HASH.search(ocr_text)
    if m:
        return norm_cn(m.group(1)), "hash"
    return None, None


def ocr_grade_confident(ocr_text):
    m = GRADE_NEAR.search(ocr_text)
    return m.group(1) if m else None


def near_miss(a, b):
    """True if a and b look like an OCR digit-drop/partial of each other
    (e.g. '242' vs '42') — used to suppress false cn conflicts."""
    if not a or not b or a == b:
        return False
    return a.endswith(b) or b.endswith(a) or a.startswith(b) or b.startswith(a)


def fetch_rows(args):
    base, h = sb_conn()
    sel = ("item_id,image_url,title,sale_price,grade,grader,card_id,"
           "cards(name,version,set_id,collector_number,rarity)")
    params = {"select": sel, "excluded": "eq.false", "image_url": "not.is.null",
              "order": "sale_price.desc.nullslast"}
    if not args.all_active:
        params["scraped_at"] = f"gte.{args.scraped_since or date.today().isoformat()}"
    if args.min_price is not None:
        params["sale_price"] = f"gte.{args.min_price}"
    rows, offset, page = [], 0, 1000
    while True:
        r = requests.get(f"{base}/rest/v1/graded_sales",
                         headers={**h, "Range-Unit": "items", "Range": f"{offset}-{offset+page-1}"},
                         params=params, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page or (args.limit and len(rows) >= args.limit):
            break
        offset += page
    return rows[: args.limit] if args.limit else rows


def load_catalog(base, h):
    rows, offset, page = [], 0, 1000
    while True:
        r = requests.get(f"{base}/rest/v1/cards",
                         headers={**h, "Range-Unit": "items", "Range": f"{offset}-{offset+page-1}"},
                         params={"select": "id,name,version,set_id,collector_number,rarity"}, timeout=60)
        r.raise_for_status()
        batch = r.json()
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    by_setcn = {}
    for c in rows:
        by_setcn.setdefault((c["set_id"], norm_cn(c["collector_number"])), []).append(c)
    return by_setcn


def rec(row, ocr_cn=None, cn_conf=None, ocr_grade=None):
    card = row.get("cards")
    r = {"item_id": row["item_id"], "price": row.get("sale_price"), "grader": row.get("grader"),
         "stored_grade": row.get("grade"), "title": (row.get("title") or "")[:110],
         "ocr_cn": ocr_cn, "ocr_cn_conf": cn_conf, "ocr_grade": ocr_grade,
         "image_url": row.get("image_url"),
         "current": ({"card_id": row["card_id"], "name": card.get("name"), "version": card.get("version"),
                      "cn": card.get("collector_number"), "set_id": card.get("set_id"),
                      "rarity": card.get("rarity")} if card else None)}
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scraped-since", dest="scraped_since")
    ap.add_argument("--all-active", action="store_true")
    ap.add_argument("--min-price", type=float)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    base, h = sb_conn()
    rows = fetch_rows(args)
    print(f"reconciling {len(rows)} rows...")
    by_setcn = load_catalog(base, h)

    counts = {"agree": 0, "cn_unread": 0, "no_image": 0, "cn_soft": 0}
    flags = {"price_outlier": [], "cn_conflict": [], "grade_conflict": [], "unmatched": []}

    for i, row in enumerate(rows, 1):
        card = row.get("cards")
        price = row.get("sale_price") or 0

        # Detector 2 (no OCR): base-rarity card at a chase-level price.
        if card:
            ceil = PRICE_CEILING.get(card.get("rarity"))
            if ceil and price >= ceil:
                r = rec(row)
                r["note"] = f"{card.get('rarity')} sold for ${price:g} (ceiling ${ceil})"
                flags["price_outlier"].append(r)

        # Detector 1 (OCR): read the slab label.
        path = ocrlib.fetch_image(row["item_id"], row.get("image_url") or "")
        if not path:
            counts["no_image"] += 1
            continue
        ocr = ocrlib.ocr_label(path)
        ocr_cn, cn_conf = ocr_cn_confident(ocr)
        ocr_grade = ocr_grade_confident(ocr)

        if card:
            card_cn = norm_cn(card.get("collector_number"))
            if ocr_cn and cn_conf:
                if ocr_cn == card_cn:
                    counts["agree"] += 1
                    if ocr_grade and ocr_grade != str(row.get("grade")):
                        r = rec(row, ocr_cn, cn_conf, ocr_grade); r["note"] = "cn ok, grade differs"
                        flags["grade_conflict"].append(r)
                else:
                    sugg = by_setcn.get((card.get("set_id"), ocr_cn), [])
                    # Real conflict only when OCR is STRONG, resolves to a real
                    # card in-set, and isn't a digit-drop near-miss of the cur cn.
                    if cn_conf == "strong" and sugg and not near_miss(card_cn, ocr_cn):
                        r = rec(row, ocr_cn, cn_conf, ocr_grade)
                        r["suggested"] = [{"card_id": s["id"], "name": s["name"], "version": s["version"],
                                           "cn": s["collector_number"], "rarity": s["rarity"]} for s in sugg]
                        flags["cn_conflict"].append(r)
                    else:
                        counts["cn_soft"] += 1  # weak/ambiguous OCR disagreement — ignore
            else:
                counts["cn_unread"] += 1
                if ocr_grade and ocr_grade != str(row.get("grade")):
                    r = rec(row, ocr_cn, cn_conf, ocr_grade); r["note"] = "grade differs (cn unread)"
                    flags["grade_conflict"].append(r)
        else:
            r = rec(row, ocr_cn, cn_conf, ocr_grade)
            r["likely_lot"] = bool(LOT_HINT.search(row.get("title") or ""))
            flags["unmatched"].append(r)

        if args.verbose or i % 100 == 0:
            print(f"  [{i}/{len(rows)}] {row['item_id']} ocr_cn={ocr_cn}/{cn_conf} grade={ocr_grade}")

    for k in flags:
        flags[k].sort(key=lambda r: (r.get("price") or 0), reverse=True)

    stamp = args.scraped_since or ("all" if args.all_active else date.today().isoformat())
    out = OUT_DIR / f"ocr_reconcile_{stamp}.json"
    out.write_text(json.dumps({"counts": counts, **{f"n_{k}": len(v) for k, v in flags.items()},
                               "flags": flags}, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print(f"  agree (cn confirmed):   {counts['agree']}")
    print(f"  cn unread:              {counts['cn_unread']}")
    print(f"  cn soft (weak, ignored):{counts['cn_soft']}")
    print(f"  no image:               {counts['no_image']}")
    for k, v in flags.items():
        print(f"  RED FLAGS -> {k:15s} {len(v)}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
