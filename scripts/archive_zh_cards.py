"""
archive_zh_cards.py - keep a LOCAL copy of every Simplified Chinese card print
we can reach. Archive only: nothing here touches the database or the bucket.

    python scripts/archive_zh_cards.py --archive "C:/Users/zaven/PacksInkBackup/card_art_intl"

Why archive-only. There is no official Chinese card list reachable from
outside mainland China (checked 2026-10-03, see docs/i18n.md): the official
WeChat mini-program's backend refuses every connection from here, and
disneylorcana.com/zh-CN carries no card data. The one working source is
Dreamborn's own per-language cache (dreamborn.ink/cache/zh/cards.db + its
image CDN) - real Chinese prints (the card footer reads `10/204 · ZH · 5`),
but an UNOFFICIAL, undocumented cache with no terms covering reuse, and its
text is half English. Publishing it on packs.ink is a decision for Zaven, not
a script; this keeps the pictures so that decision does not cost a re-scrape.

Writes <archive>/zh/<setId>-<number>.webp plus zh/manifest.json mapping each
file to our card_id (set + collector number, the numbering the Chinese
edition shares with English). Skips files already present.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

DB_URL = "https://dreamborn.ink/cache/zh/cards.db"
IMG_URL = "https://cdn.dreamborn.ink/images/zh/cards/{id}"
UA = "Mozilla/5.0 (packs.ink archive)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True)
    ap.add_argument("--no-match", action="store_true", help="skip the card_id match (no Supabase needed)")
    args = ap.parse_args()
    out_dir = os.path.join(args.archive, "zh")
    os.makedirs(out_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        dbp = os.path.join(tmp, "zh.db")
        r = requests.get(DB_URL, headers={"User-Agent": UA}, timeout=60)
        r.raise_for_status()
        open(dbp, "wb").write(r.content)
        con = sqlite3.connect(dbp)
        con.row_factory = sqlite3.Row
        rows = [dict(x) for x in con.execute(
            "select id, name, title, setId, number, rarity, type from cards where language = 'zh' order by id")]
        con.close()
    print(f"{len(rows)} Chinese prints listed")

    by_set_cn = {}
    if not args.no_match:
        from supabase_client import Supabase
        sb = Supabase()
        sets = {s["id"]: (s.get("code") or "") for s in sb.select("sets", columns="id,code")}
        for c in sb.select("cards", columns="id,set_id,collector_number,name,version"):
            by_set_cn.setdefault((sets.get(c["set_id"], ""), str(c.get("collector_number") or "")), []).append(c)

    manifest, got, skipped, failed = [], 0, 0, 0
    for row in rows:
        set_code = str(int(row["setId"])) if (row["setId"] or "").isdigit() else row["setId"]
        safe = "".join(ch if ch.isalnum() else "_" for ch in str(row["number"]))  # promo numbers carry "/P1"
        fn = f"{row['setId']}-{safe}.webp"
        path = os.path.join(out_dir, fn)
        cands = by_set_cn.get((set_code, str(row["number"])), [])
        manifest.append({"file": fn, "dreamborn_id": row["id"], "set": set_code, "number": row["number"],
                         "zh_name": row["name"], "zh_title": row["title"], "rarity": row["rarity"],
                         "card_id": cands[0]["id"] if len(cands) == 1 else None,
                         "en_name": (cands[0]["name"] + (" - " + cands[0]["version"] if cands[0].get("version") else "")) if len(cands) == 1 else None})
        if os.path.exists(path):
            skipped += 1
            continue
        try:
            ir = requests.get(IMG_URL.format(id=row["id"]), headers={"User-Agent": UA}, timeout=60)
            if ir.ok and ir.headers.get("Content-Type", "").startswith("image/"):
                open(path + ".part", "wb").write(ir.content)
                os.replace(path + ".part", path)
                got += 1
            else:
                failed += 1
        except requests.RequestException:
            failed += 1
        time.sleep(0.25)  # polite: one at a time
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    matched = sum(1 for m in manifest if m["card_id"])
    print(f"downloaded {got}, already had {skipped}, failed {failed}; matched {matched} of {len(manifest)} to our cards")
    return 0


if __name__ == "__main__":
    sys.exit(main())
