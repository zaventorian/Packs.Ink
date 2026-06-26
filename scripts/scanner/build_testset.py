"""
Build a REAL-PHOTO benchmark for the scanner from graded_sales (eBay slab
photos). One high-confidence labeled photo per card that also exists in the
shipped scanner index. Downloads images locally (served same-origin for the
in-browser eval harness) and writes test_set.json.

These are slabs (card in a graded case + label), so they're a harder, slightly
different distribution than a raw card — but they're REAL photographs (real
lighting, sensors, glare, plastic, compression, backgrounds), which synthetic
distortion can't replicate. Good for measuring matcher robustness.

  python scripts/scanner/build_testset.py [--n 700] [--minconf 1.0]
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
EBAY = DATA / "ebay"
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE.parent))
from supabase_client import Supabase  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=700)
    ap.add_argument("--minconf", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    load_dotenv(HERE.parent / ".env")
    DATA.mkdir(parents=True, exist_ok=True)
    EBAY.mkdir(parents=True, exist_ok=True)

    idx = json.loads((REPO / "scanner" / "index.json").read_text(encoding="utf-8"))
    art_by_id = {c["id"]: c["art_key"] for c in idx["cards"]}
    in_index = set(art_by_id)
    print(f"scanner index: {len(in_index)} cards")

    sb = Supabase()
    print("pulling usable graded_sales rows ...")
    rows = sb.select(
        "graded_sales",
        columns="card_id,image_url,match_confidence,printing,grader,grade",
        filters={"excluded": "is.false", "cn_conflict": "is.false",
                 "image_url": "not.is.null",
                 "match_confidence": f"gte.{args.minconf}"},
    )
    print(f"  {len(rows)} usable rows")

    best: dict[str, dict] = {}
    for r in rows:
        cid = r.get("card_id")
        if not cid or cid not in in_index:
            continue
        mc = float(r.get("match_confidence") or 0)
        if cid not in best or mc > float(best[cid].get("match_confidence") or 0):
            best[cid] = r
    cards = list(best.values())
    print(f"  {len(cards)} distinct in-index cards with a labeled photo")

    import random
    random.Random(args.seed).shuffle(cards)
    cards = cards[: args.n]
    print(f"  sampling {len(cards)} for the benchmark")

    def dl(r):
        cid = r["card_id"]
        url = (r["image_url"] or "").replace("s-l1200", "s-l1600").replace("s-l500", "s-l1600")
        dest = EBAY / f"{cid}.jpg"
        if dest.exists() and dest.stat().st_size > 1500:
            return cid, True, "cached"
        try:
            resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200 or len(resp.content) < 1500:
                # fall back to the original 1200 size
                resp = requests.get(r["image_url"], timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200 or len(resp.content) < 1500:
                return cid, False, f"http {resp.status_code}"
            dest.write_bytes(resp.content)
            return cid, True, "downloaded"
        except Exception as e:  # noqa: BLE001
            return cid, False, f"{type(e).__name__}"

    ok, fail = 0, 0
    out = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = {ex.submit(dl, r): r for r in cards}
        for i, f in enumerate(as_completed(futs), 1):
            cid, success, _msg = f.result()
            r = futs[f]
            if success:
                ok += 1
                out.append({
                    "card_id": cid, "art_key": art_by_id[cid],
                    "printing": r.get("printing"), "grader": r.get("grader"),
                    "grade": r.get("grade"), "file": f"{cid}.jpg",
                })
            else:
                fail += 1
            if i % 100 == 0:
                print(f"  {i}/{len(cards)} ok={ok} fail={fail}")

    (DATA / "test_set.json").write_text(json.dumps(out, indent=0), encoding="utf-8")
    print(f"done: {ok} images, {fail} failed. wrote data/test_set.json")


if __name__ == "__main__":
    main()
