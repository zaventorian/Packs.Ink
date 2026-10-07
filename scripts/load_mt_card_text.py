"""
load_mt_card_text.py - rules text for cards that were NEVER printed in a language.

    python scripts/load_mt_card_text.py            # dry run: what would be written / is missing
    python scripts/load_mt_card_text.py --commit
    python scripts/load_mt_card_text.py --todo DIR # write the cards still needing a translation

A card Japan never printed (Hyperia City, the Winterspell cards outside the
Curator's Library, newer promos) has no official Japanese text anywhere, so a
Japanese reader would see English rules. `i18n/cards_mt/<lang>.json` holds an
UNOFFICIAL translation for each such card, written against Takara Tomy's /
Ravensburger's own wording of the same keywords, and keyed on the English text
it translates (`en_hash`). This script writes them as card_localizations rows
with match_how='machine' and source='packs-ink-mt'. The site labels them
"unofficial translation".

Rules (the official text always wins):
  * a card with ANY other row in that language (an official printing, or a
    'name' row borrowing an official translation) is skipped;
  * a translation whose en_hash no longer matches the card's English text is
    stale - its row is deleted and the card is listed as needing a new one;
  * name / version stay NULL: inventing an official-looking Japanese name
    would collide with the real one the day Takara prints the card.

Runs after sync_intl_cards.py in .github/workflows/intl-cards.yml.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MT_DIR = os.path.join(ROOT, "i18n", "cards_mt")
SOURCE = "packs-ink-mt"
LANGS = ("ja", "de", "fr", "it")


def en_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf8")).hexdigest()[:12]


def plan(lang: str, cards: list[dict], rows: list[dict], mt: dict) -> dict:
    """Pure: which MT rows to write, which to delete, which cards still need one."""
    by_card = {r["card_id"]: r for r in rows if r["lang"] == lang}
    write, delete, todo = [], [], []
    for c in cards:
        text = (c.get("text") or "").strip()
        cur = by_card.get(c["id"])
        if cur and cur.get("source") != SOURCE:
            continue                      # official (or borrowed official) text exists
        if not text:
            continue
        t = mt.get(c["id"])
        if t and t.get("en_hash") == en_hash(text) and (t.get("text") or "").strip():
            if not cur or cur.get("text") != t["text"]:
                write.append({"card_id": c["id"], "lang": lang, "name": None, "version": None,
                              "text": t["text"].strip(), "flavor_text": None, "classifications": None,
                              "image_url": None, "image_thumb_url": None, "source": SOURCE,
                              "source_id": t["en_hash"], "source_ref": None, "match_how": "machine"})
        else:
            if cur:
                delete.append(c["id"])    # stale against a changed English text
            todo.append({"card_id": c["id"], "name": c["name"] + (" - " + c["version"] if c.get("version") else ""),
                         "en": text, "en_hash": en_hash(text)})
    return {"write": write, "delete": delete, "todo": todo}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--todo", help="write todo_<lang>.json files here for cards needing a translation")
    args = ap.parse_args()
    sb = Supabase()
    cards = sb.select("cards", columns="id,name,version,text")
    rows = sb.select("card_localizations", columns="card_id,lang,source,text",
                     order="card_id.asc,lang.asc")
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for lang in LANGS:
        p = os.path.join(MT_DIR, f"{lang}.json")
        mt = json.load(open(p, encoding="utf8")) if os.path.exists(p) else {}
        pl = plan(lang, cards, rows, mt)
        print(f"{lang}: {len(pl['write'])} to write, {len(pl['delete'])} stale, {len(pl['todo'])} still untranslated")
        if args.todo and pl["todo"]:
            os.makedirs(args.todo, exist_ok=True)
            with open(os.path.join(args.todo, f"todo_{lang}.json"), "w", encoding="utf8") as f:
                json.dump(pl["todo"], f, ensure_ascii=False, indent=1)
        if not args.commit:
            continue
        for r in pl["write"]:
            r["updated_at"] = now
        if pl["write"]:
            sb.upsert("card_localizations", pl["write"], on_conflict="card_id,lang", batch=500)
        for cid in pl["delete"]:
            sb.delete("card_localizations", {"card_id": f"eq.{cid}", "lang": f"eq.{lang}", "source": f"eq.{SOURCE}"})
    if not args.commit:
        print("DRY RUN - re-run with --commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
