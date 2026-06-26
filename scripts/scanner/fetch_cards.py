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

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
IMGDIR = DATA / "img"

sys.path.insert(0, str(HERE.parent))
from supabase_client import Supabase  # noqa: E402


def pull_catalog() -> list[dict]:
    sb = Supabase()
    rows = sb.select(
        "cards",
        columns="id,name,version,set_id,rarity,image_normal",
        filters={"image_normal": "not.is.null"},
    )
    out = []
    for r in rows:
        url = r.get("image_normal")
        if not url:
            continue
        # art_key = filename without the ?ts cache-buster
        art_key = url.split("/")[-1].split("?")[0]
        out.append({
            "id": r["id"],
            "name": r.get("name"),
            "version": r.get("version"),
            "set_id": r.get("set_id"),
            "rarity": r.get("rarity"),
            "url": url,
            "art_key": art_key,
        })
    return out


def download_one(card: dict) -> tuple[str, bool, str]:
    dest = IMGDIR / f"{card['id']}.avif"
    if dest.exists() and dest.stat().st_size > 500:
        return card["id"], True, "cached"
    try:
        r = requests.get(card["url"], timeout=30)
        if r.status_code != 200 or len(r.content) < 500:
            return card["id"], False, f"http {r.status_code} len {len(r.content)}"
        dest.write_bytes(r.content)
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
