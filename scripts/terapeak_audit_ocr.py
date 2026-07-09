"""Tesseract slab-label reader for graded_sales conflation audits.

Fetches listing images from eBay, crops the top 30% (where the slab label lives),
upscales 2×, and runs Tesseract OCR to extract: year, set name (D23 EXPO vs
D23 COLLECTION), version/character keywords, collector# (#NNN or NNN/204), grade.

Usage:
  python terapeak_audit_ocr.py --items 305983889186 377290538070 ...
  python terapeak_audit_ocr.py --sql "SELECT item_id, image_url FROM graded_sales WHERE ..."

The --sql form fetches item IDs + image URLs directly from Supabase (needs .env).
Requires: pip install pytesseract pillow requests python-dotenv
Tesseract binary: C:\\Program Files\\Tesseract-OCR\\tesseract.exe (NOT on PATH)
"""
import argparse, re, sys, time, os
from pathlib import Path
import requests
from PIL import Image
import pytesseract
from dotenv import load_dotenv

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CACHE_DIR = Path(__file__).parent / "terapeak_output" / "img_ocr_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (compatible; PacksInkSlabAudit/1.0)"}


def ocr_label(path: Path) -> str:
    """Return combined OCR text from top-30%-crop + full image, uppercased."""
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return ""
    w, h = img.size
    out = []
    for box in [(0, 0, w, int(h * 0.30)), (0, 0, w, h)]:
        crop = img.crop(box)
        if box[3] < h:
            crop = crop.resize((w * 2, box[3] * 2))
        try:
            out.append(pytesseract.image_to_string(crop))
        except Exception:
            pass
    return " ".join(" ".join(t.split()) for t in out).upper()


def extract_fields(ocr_text: str) -> dict:
    """Extract structured fields from raw OCR text."""
    cn_match = re.search(r'#(\d{1,3})\b|(\d{1,3})/(?:204|D23|P1|C1|C2)', ocr_text)
    grade_match = re.search(r'\b(10|9\.5|9|8\.5|8|7\.5|7|6\.5|6|5)\b', ocr_text)
    year_match = re.search(r'\b(20\d\d)\b', ocr_text)

    is_expo = "D23 EXPO" in ocr_text or "2022" in (year_match.group(0) if year_match else "")
    is_collection = "D23 COLLECTION" in ocr_text or "2024" in (year_match.group(0) if year_match else "")

    return {
        "cn": cn_match.group(1) or cn_match.group(2) if cn_match else None,
        "grade": grade_match.group(0) if grade_match else None,
        "year": year_match.group(0) if year_match else None,
        "d23_expo": is_expo,
        "d23_collection": is_collection,
        "wayward": "WAYWARD" in ocr_text,
        "artful": "ARTFUL" in ocr_text,
        "enchanted": "ENCHANTED" in ocr_text,
        "playful": "PLAYFUL" in ocr_text,
        "blt": "BRAVE LITTLE" in ocr_text or "LITTLE TAILOR" in ocr_text,
    }


def fetch_image(item_id: str, image_url: str) -> Path | None:
    # Try to derive the eBay CDN path from the image_url
    if not image_url:
        return None
    ext = ".jpg"
    if ".png" in image_url.lower():
        ext = ".png"
    dest = CACHE_DIR / f"{item_id}{ext}"
    if dest.exists():
        return dest
    # Normalize eBay image URLs to the s-l1200 size for best label resolution
    url = re.sub(r's-l\d+', 's-l1200', image_url)
    try:
        r = requests.get(url, headers=UA, timeout=30)
        r.raise_for_status()
        dest.write_bytes(r.content)
        time.sleep(0.15)
        return dest
    except Exception as e:
        print(f"  DL error {item_id}: {e}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description="OCR slab labels for graded_sales audit")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--items", nargs="+", metavar="ITEM_ID",
                   help="eBay item IDs to audit (fetches image_url from graded_sales)")
    g.add_argument("--image-urls", nargs="+", metavar="ITEM_ID=URL",
                   help="item_id=url pairs (no DB query needed)")
    ap.add_argument("--verbose", action="store_true", help="Print full OCR text")
    args = ap.parse_args()

    rows = []
    if args.items:
        load_dotenv(Path(__file__).parent / ".env")
        sb = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_KEY"]
        h = {"apikey": key, "Authorization": f"Bearer {key}"}
        ids = ",".join(args.items)
        r = requests.get(f"{sb}/rest/v1/graded_sales",
                         headers=h,
                         params={"select": "item_id,image_url", "item_id": f"in.({ids})"},
                         timeout=30)
        rows = r.json()
    elif args.image_urls:
        for pair in args.image_urls:
            iid, url = pair.split("=", 1)
            rows.append({"item_id": iid, "image_url": url})

    print(f"{'item_id':>16}  {'cn':>4}  {'grade':>5}  {'year':>5}  flags")
    print("-" * 70)
    for row in rows:
        iid = row.get("item_id", "?")
        img_url = row.get("image_url") or ""
        path = fetch_image(iid, img_url)
        if not path:
            print(f"{iid:>16}  (no image)")
            continue
        ocr = ocr_label(path)
        fields = extract_fields(ocr)
        flags = []
        if fields["d23_expo"]:     flags.append("D23-EXPO")
        if fields["d23_collection"]: flags.append("D23-COLL")
        if fields["wayward"]:      flags.append("WAYWARD")
        if fields["artful"]:       flags.append("ARTFUL")
        if fields["enchanted"]:    flags.append("ENCH")
        if fields["playful"]:      flags.append("PLAYFUL")
        if fields["blt"]:          flags.append("BLT")
        print(f"{iid:>16}  {fields['cn'] or '?':>4}  "
              f"{fields['grade'] or '?':>5}  "
              f"{fields['year'] or '?':>5}  "
              f"{' '.join(flags) or '—'}")
        if args.verbose:
            print(f"  OCR: {ocr[:120]}")


if __name__ == "__main__":
    main()
