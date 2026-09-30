"""
Scanner step 1: pull the card catalog + download every Lorcast card image
into a local cache. Resumable (skips already-downloaded files), threaded.

Outputs:
  scripts/scanner/data/cards.json      — [{id, name, version, set_id, rarity, url, art_key}]
  scripts/scanner/data/img/<id>.avif   — cached source images

`art_key` groups printings that share identical art (same image filename minus
the cache-busting query) so the validator can score "did we identify the art"
rather than penalising a foil/non-foil mismatch.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote_to_bytes

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"

sys.path.insert(0, str(HERE.parent))
from supabase_client import Supabase  # noqa: E402
import scanner_scope  # noqa: E402


def pull_catalog() -> list[dict]:
    sb = Supabase()
    bad_sets = scanner_scope.excluded_set_ids(sb.select("sets", columns="id,code"))
    bad_ids = scanner_scope.suppressed_card_ids()
    rows = sb.select(
        "cards",
        columns="id,name,version,set_id,rarity,card_type," + ",".join(scanner_scope.IMAGE_COLUMNS),
    )
    out = []
    for r in rows:
        url = scanner_scope.card_image(r)
        if not url or not scanner_scope.in_scope(r["id"], r.get("set_id"), bad_sets, bad_ids):
            continue
        # art_key = filename without the ?ts cache-buster (a data: URI has no
        # filename, so it is keyed on its own content instead)
        # A stand-in's art is card-art/<folder>/<n>.jpg and the BARE filename repeats across folders
        # (set14/5.jpg, rph/5.jpg, dis/5.jpg), so three unrelated cards shared the key "5.jpg" - and the
        # scanner treats art_key as a card's identity within a session. Keep the folder. Lorcast's own
        # filenames are unique hashes and are unchanged. Index.html scannerExtraRows uses the same rule.
        art_key = ("data-" + hashlib.sha1(url.encode()).hexdigest()[:16]) if url.startswith("data:") \
            else (url.split("/card-art/")[-1] if "/card-art/" in url else url.split("/")[-1]).split("?")[0]
        out.append({
            "id": r["id"],
            "name": r.get("name"),
            "version": r.get("version"),
            "set_id": r.get("set_id"),
            "rarity": r.get("rarity"),
            # card_type drives the Location upright-rotation in build_index.py —
            # Lorcast serves landscape Locations rotated 90° CCW into a portrait
            # frame, so their descriptors were built sideways.
            "card_type": r.get("card_type"),
            "url": url,
            "art_key": art_key,
        })
    return out


REPO = HERE.parent.parent


def fetch_bytes(url: str) -> bytes:
    # image_normal is not always an https URL: a hand-staged promo's art can be a
    # data: URI or a repo-relative path (Logos/cards/...), and requests.get fails on
    # both, which silently left those cards out of the index.
    if url.startswith("data:"):
        head, _, body = url.partition(",")
        return base64.b64decode(body) if ";base64" in head else unquote_to_bytes(body)
    if not url.startswith(("http://", "https://")):
        return (REPO / url.lstrip("/")).read_bytes()
    r = requests.get(url, timeout=30, headers={"User-Agent": "packs.ink scanner index"})
    if r.status_code != 200:
        raise OSError(f"http {r.status_code}")
    return r.content


def download_one(card: dict) -> tuple[str, bool, str]:
    dest = IMGDIR / f"{card['id']}.avif"
    if dest.exists() and dest.stat().st_size > 500:
        return card["id"], True, "cached"
    try:
        data = fetch_bytes(card["url"])
        if len(data) < 500:
            return card["id"], False, f"len {len(data)}"
        dest.write_bytes(data)
        return card["id"], True, "downloaded"
    except Exception as e:  # noqa: BLE001
        return card["id"], False, f"{type(e).__name__}: {e}"


def main() -> None:
    load_dotenv(HERE.parent / ".env")
    DATA.mkdir(parents=True, exist_ok=True)
    IMGDIR.mkdir(parents=True, exist_ok=True)

    print("pulling catalog from Supabase ...")
    cards = pull_catalog()
    (DATA / "cards.json").write_text(json.dumps(cards, indent=0), encoding="utf-8")
    print(f"catalog: {len(cards)} cards, {len({c['art_key'] for c in cards})} distinct arts")

    ok = fail = 0
    fails: list[str] = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        futs = [ex.submit(download_one, c) for c in cards]
        for i, f in enumerate(as_completed(futs), 1):
            cid, success, msg = f.result()
            if success:
                ok += 1
            else:
                fail += 1
                fails.append(f"{cid}: {msg}")
            if i % 200 == 0:
                print(f"  {i}/{len(cards)}  ok={ok} fail={fail}")
    print(f"done: ok={ok} fail={fail}")
    if fails:
        print("failures (first 20):")
        for line in fails[:20]:
            print("  ", line)


if __name__ == "__main__":
    main()
