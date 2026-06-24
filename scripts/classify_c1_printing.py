"""
classify_c1_printing.py — set the `printing` of each Lorcana Challenge Promo (C1)
graded sale from the SLAB LABEL (not the eBay title, which is ~60% silent on the
variant). The PSA/CGC/Beckett label reliably prints the C1 tier:
    PARTICIPATION / SIDE EVENT      -> Prize Wall  (non-foil, cheap)   -> "Non-Foil"
    TOP PRIZE / TOP N PRIZE /       -> Top Prize   (foil, expensive)   -> "Foil"
      CHALLENGE EVENT / CHAMP(S) / SERIALIZED / WORLD CHAMP
C1 cards share ONE card_id across printings (SPLIT_BY_PRINTING_SETS), so the rollup
blends Prize Wall + Top Prize into a misleading middle price. Classifying each sale's
printing here is the prerequisite for splitting them downstream.

    python scripts/classify_c1_printing.py            # dry-run (counts + samples)
    python scripts/classify_c1_printing.py --commit   # write graded_sales.printing
"""
from __future__ import annotations

import argparse
import concurrent.futures
import re
import requests
from datetime import datetime, timezone

from ocr_slab_audit import (SB_URL, HEAD, UA, DELAY, WORKERS, crop_label,
                            ocr_tesseract, refresh_rollup)

C1_SET = "set_e0eb34fc0fbb446886f84c34381d4dce"
FOIL_RE = re.compile(r"top\s*\d*\s*prize|challenge\s*event|champ|seriali[sz]ed|world\s*champ", re.I)
NONFOIL_RE = re.compile(r"participation|side\s*event", re.I)


def classify_text(t):
    if not t:
        return None
    if FOIL_RE.search(t):
        return "Foil"
    if NONFOIL_RE.search(t):
        return "Non-Foil"
    return None


def norm_existing(p):
    """Map the scraper's printing field to the binary C1 split (Foil / Non-Foil)."""
    if not p:
        return None
    p = p.lower()
    if "non" in p:
        return "Non-Foil"
    if "foil" in p or "holo" in p:
        return "Foil"
    return None


def fetch_c1_sales():
    r = requests.get(f"{SB_URL}/rest/v1/cards", headers=HEAD, timeout=30,
                     params={"select": "id", "set_id": f"eq.{C1_SET}"})
    r.raise_for_status()
    ids = "in.(" + ",".join(c["id"] for c in r.json()) + ")"
    rows, off = [], 0
    while True:  # paginate — C1 has >1000 sales, PostgREST caps a page at 1000
        rr = requests.get(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=60, params={
            "select": "item_id,image_url,printing,title", "card_id": ids,
            "excluded": "is.false", "image_url": "not.is.null",
            "order": "item_id.asc", "offset": off, "limit": 1000})
        rr.raise_for_status()
        b = rr.json()
        rows.extend(b)
        if len(b) < 1000:
            break
        off += 1000
    return rows


def save_result(item_id, printing, raw):
    """Persist the raw slab OCR (always) + the classified printing (when known)."""
    body = {"slab_ocr": raw, "slab_ocr_at": datetime.now(timezone.utc).isoformat()}
    if printing:
        body["printing"] = printing
    r = requests.patch(f"{SB_URL}/rest/v1/graded_sales",
                       headers={**HEAD, "Content-Type": "application/json", "Prefer": "return=minimal"},
                       params={"item_id": "eq." + item_id}, json=body, timeout=30)
    return r.status_code < 300


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--workers", type=int, default=WORKERS)
    args = ap.parse_args()

    sales = fetch_c1_sales()
    print(f"C1 sales with images: {len(sales)}", flush=True)

    def work(s):
        try:
            img = requests.get(s["image_url"], headers=UA, timeout=30).content
            raw = " ".join(ocr_tesseract(crop_label(img)).split())
        except Exception:
            return (s, None, "error")
        finally:
            if DELAY:
                __import__("time").sleep(DELAY)
        return (s, raw, "ok")

    foil = nonfoil = unknown = err = ocr_saved = printing_set = 0
    by = {"slab": 0, "title": 0, "field": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for i, (s, raw, status) in enumerate(ex.map(work, sales)):
            if status == "error":
                err += 1
                continue
            # slab label (best) → eBay title → scraper printing field
            cls, src = classify_text(raw), "slab"
            if not cls:
                cls, src = classify_text(s.get("title")), "title"
            if not cls:
                cls, src = norm_existing(s.get("printing")), "field"
            if cls == "Foil":
                foil += 1; by[src] += 1
            elif cls == "Non-Foil":
                nonfoil += 1; by[src] += 1
            else:
                unknown += 1
            if args.commit and save_result(s["item_id"], cls, raw):
                ocr_saved += 1
                if cls:
                    printing_set += 1
            if i and i % 100 == 0:
                print(f"  ... {i}/{len(sales)}  foil {foil} nonfoil {nonfoil} unknown {unknown} err {err}", flush=True)

    print(f"\ndone. FOIL(Top Prize) {foil}, NON-FOIL(Prize Wall) {nonfoil}, unknown {unknown}, err {err}")
    print(f"  classified by: slab {by['slab']}, title {by['title']}, printing-field {by['field']}")
    print(f"  ocr_saved {ocr_saved}, printing_set {printing_set}")
    if args.commit and printing_set:
        refresh_rollup()
        print("rollup refreshed.")
    elif not args.commit:
        print("dry-run — re-run with --commit to write printing + save slab_ocr.")


if __name__ == "__main__":
    main()
