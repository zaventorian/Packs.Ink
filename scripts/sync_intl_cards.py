"""
sync_intl_cards.py - pull every Lorcana card printed in another language from
the publishers' own card lists, and keep `card_localizations` current.

    python scripts/sync_intl_cards.py                      # dry run: fetch + match, report
    python scripts/sync_intl_cards.py --commit             # + upload art, upsert rows
    python scripts/sync_intl_cards.py --langs ja --commit
    python scripts/sync_intl_cards.py --archive "C:/Users/zaven/PacksInkBackup/card_art_intl"

Sources and the matching rules live in intl_cards.py (pure, offline-tested by
scripts/test_intl_cards.py). This file is only the network half:

  * Fetch  - the English + de/fr/it Ravensburger gallery (scripts/
             intl_gallery_data.mjs, run with an EMPTY environment because it
             evaluates the page's own data script) and Takara Tomy's API (ja).
  * Art    - each foreign printing becomes ONE 600px WebP in the public
             card-art bucket at intl/<lang>/<source key>.webp. Keyed on the
             SOURCE's id (Ravensburger culture_invariant_id / Takara file name),
             never our card_id, so a stand-in being retired onto Lorcast's id
             does not orphan its art. The URL carries ?v=<hash of the source
             version> because packsink-img-v1 survives deploys and keys on URL.
             A row whose stored ?v= already matches is not re-downloaded.
  * Archive - --archive DIR also keeps the full-size ORIGINAL (760px PNG /
             800px AVIF) on disk. Skips files already there.
  * Rows   - upserted per (card_id, lang). Rows for cards the source no longer
             lists are deleted ONLY when that source's pull came back at least
             MIN_RATIO of the size already on file - a partial pull from a
             network flake must never wipe a language.

Dry run by default. Needs SUPABASE_URL + SUPABASE_SERVICE_KEY (scripts/.env).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
import intl_cards as ic  # noqa: E402
from supabase_client import Supabase  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except ImportError:
    pass

BUCKET = "card-art"
PREFIX = "intl"
WIDTH = 600
QUALITY = 80
MIN_RATIO = 0.9
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
HERE = os.path.dirname(os.path.abspath(__file__))


# ------------------------------------------------------------------ fetching

def fetch_gallery(locale: str, tmpdir: str) -> dict:
    """{cards, setNames, locale} for one gallery locale."""
    out = os.path.join(tmpdir, f"gallery_{locale}.json")
    node = shutil.which("node")
    if not node:
        sys.exit("node is required (scripts/intl_gallery_data.mjs)")
    # Empty environment: the evaluated page script must find no secrets even
    # if it ever escaped the vm context. Windows needs SYSTEMROOT for sockets.
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "TEMP", "TMP") if k in os.environ}
    for attempt in range(3):
        r = subprocess.run([node, os.path.join(HERE, "intl_gallery_data.mjs"), locale, out],
                           env=env, capture_output=True, text=True, timeout=180)
        if r.returncode == 0:
            break
        print(f"  gallery {locale} attempt {attempt + 1} failed: {r.stderr.strip()[-300:]}")
        time.sleep(5)
    else:
        raise RuntimeError(f"gallery {locale} unavailable")
    print("  " + r.stderr.strip())
    with open(out, encoding="utf8") as f:
        return json.load(f)


TT_FIELDS = [("freeword", "")] + [("freeword_field[]", f) for f in
            ["カード名", "バージョン名", "読み", "クラス", "テキスト", "フレーバー", "イラストレーター"]] + [
    ("ink_type", "すべて"), ("ink_color[]", "すべて"), ("card_type[]", "すべて"),
    ("classification[]", "すべて"), ("rarity[]", "すべて"), ("ability[]", "すべて"),
    ("sets[]", "すべて"), ("inkwell[]", "すべて"), ("search_sort", "リリース順"),
    ("posts_per_page", "100"),
]


def fetch_takaratomy() -> list[dict]:
    """Every card on Takara Tomy's Japanese card list. The site's own JS does
    exactly this: POST token.json for a CSRF token, then page through
    card-search/result. Polite: one request at a time, half a second apart."""
    base = ic.TT_BASE + "/api1.0/card-search"
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": ic.TT_BASE + "/cardlist/"})

    def token():
        for _ in range(5):
            r = s.post(base + "/token.json", timeout=30)
            if r.ok and r.json().get("csrf"):
                return r.json()["csrf"]
            time.sleep(2)
        raise RuntimeError("takaratomy: no CSRF token")

    tok, out, page, total = token(), [], 1, None
    while True:
        for attempt in range(4):
            r = s.post(base + "/result", data=TT_FIELDS + [("page", str(page))],
                       headers={"X-CSRF-Token": tok}, timeout=60)
            if r.ok:
                break
            time.sleep(2 + attempt * 2)
            tok = token()
        else:
            raise RuntimeError(f"takaratomy: page {page} failed ({r.status_code})")
        d = r.json()
        total = d.get("count", total)
        out += d.get("cards") or []
        if not d.get("cards") or len(out) >= (total or 0):
            break
        page += 1
        time.sleep(0.5)
    print(f"  takaratomy: {len(out)} of {total} cards")
    if total and len(out) < total:
        raise RuntimeError(f"takaratomy: partial pull {len(out)}/{total}")
    return out


# --------------------------------------------------------------------- art

def ver_token(v: str | None) -> str:
    return hashlib.sha1((v or "").encode("utf8")).hexdigest()[:10]


def public_url(sb: Supabase, key: str, v: str) -> str:
    return f"{sb.url}/storage/v1/object/public/{BUCKET}/{PREFIX}/{key}.webp?v={v}"


def to_webp(data: bytes) -> bytes:
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    im = im.convert("RGBA")  # rounded corners stay transparent, like Lorcast's art
    if im.width > WIDTH:
        im = im.resize((WIDTH, round(im.height * WIDTH / im.width)), Image.LANCZOS)
    b = io.BytesIO()
    im.save(b, "WEBP", quality=QUALITY, method=4)
    return b.getvalue()


class ArtMissing(Exception):
    """The source lists art that its own CDN does not have (HTTP 404). Seen on
    a handful of Ravensburger's German cards. Not a failure of ours: the row
    is written without localized art and the card keeps its English picture."""


def get_bytes(url: str) -> bytes:
    last = None
    for attempt in range(4):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/png,image/*,*/*"},
                             timeout=60)
            if r.ok and r.headers.get("Content-Type", "").startswith("image/"):
                return r.content
            if r.status_code == 404:
                raise ArtMissing(f"{url}: 404")
            last = f"HTTP {r.status_code} {r.headers.get('Content-Type')}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def archive_path(archive: str, row: dict) -> str:
    ext = ".png" if row["source"] == "takaratomy" else ".avif"
    return os.path.join(archive, row["_store_key"].replace("/", os.sep) + ext)


def process_art(sb: Supabase, row: dict, archive: str | None, commit: bool) -> str:
    """Download (or reuse the archived) original, archive it, convert, upload.
    Returns 'uploaded' / 'archived' / 'kept'."""
    data = None
    ap = archive_path(archive, row) if archive else None
    if ap and os.path.exists(ap):
        with open(ap, "rb") as f:
            data = f.read()
        try:  # a run killed mid-write leaves a truncated file; fetch it again
            from PIL import Image
            Image.open(io.BytesIO(data)).load()
        except Exception:
            data = None
    if data is None:
        try:
            data = get_bytes(row["_src_image"])
        except ArtMissing:
            if not row.get("_alt_image"):
                raise
            data = get_bytes(row["_alt_image"])
        if ap:
            os.makedirs(os.path.dirname(ap), exist_ok=True)
            with open(ap + ".part", "wb") as f:
                f.write(data)
            os.replace(ap + ".part", ap)
    if not commit:
        return "archived"
    webp = to_webp(data)
    path = f"{PREFIX}/{row['_store_key']}.webp"
    for attempt in range(4):
        up = requests.post(f"{sb.url}/storage/v1/object/{BUCKET}/{path}",
                           headers={**sb.auth_headers(), "Content-Type": "image/webp", "x-upsert": "true",
                                    "Cache-Control": "max-age=31536000"},
                           data=webp, timeout=90)
        if up.ok:
            return "uploaded"
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"upload {path}: HTTP {up.status_code} {up.text[:200]}")


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--langs", default=",".join(ic.LANGS))
    ap.add_argument("--commit", action="store_true", help="upload art and write rows (default: dry run)")
    ap.add_argument("--archive", default=os.environ.get("INTL_ART_ARCHIVE"),
                    help="keep full-size originals here (skips files already present)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-art", action="store_true", help="rows only; leave stored art as it is")
    ap.add_argument("--report", help="write the match report JSON here")
    ap.add_argument("--terms-out", help="write each language's glossary (ink/rarity/type/class/set) to this JSON; "
                                        "scripts/build_i18n.py bakes it into i18n/<lang>.js")
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    bad = [l for l in langs if l not in ic.LANGS]
    if bad:
        sys.exit(f"unknown language(s): {bad}; known: {ic.LANGS}")

    sb = Supabase()
    print("Loading our catalog ...")
    cards = sb.select("cards", columns="id,set_id,name,version,collector_number,rarity,classifications")
    sets = sb.select("sets", columns="id,code,name")
    cat = ic.Catalog(cards, sets)
    print(f"  {len(cards)} cards, {len(sets)} sets")

    existing: dict[tuple[str, str], dict] = {}
    try:
        for r in sb.select("card_localizations", columns="card_id,lang,image_url,match_how"):
            existing[(r["card_id"], r["lang"])] = r
    except Exception as e:  # pre-179 database
        print(f"  card_localizations unreadable ({e}); treating as empty")

    report: dict = {}
    terms: dict = {}
    all_rows: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        en_map = None
        for lang in langs:
            print(f"\n== {lang} ==")
            try:
                if lang == "ja":
                    tt = fetch_takaratomy()
                    rows, st = ic.match_tt(tt, cat)
                    terms[lang] = ic.derive_terms(lang, rows, cat, sets, tt_cards=tt)
                else:
                    if en_map is None:
                        en_cards = fetch_gallery("en-US", tmp)["cards"]
                        en_map = ic.match_gallery_en(en_cards, cat)
                        print(f"  english twins: {len(en_map)} of {len(en_cards)} gallery cards tied to our rows")
                    gal = fetch_gallery(ic.GALLERY_LOCALES[lang], tmp)
                    rows, st = ic.gallery_rows(lang, gal["cards"], en_map)
                    terms[lang] = ic.derive_terms(lang, rows, cat, sets, gallery_set_names=gal.get("setNames"))
            except Exception as e:
                print(f"  !! {lang} skipped: {e}")
                report[lang] = {"error": str(e)}
                continue
            extra = ic.text_only_rows(lang, rows, cat)
            st["text_only"] = len(extra)
            report[lang] = st
            print("  " + ", ".join(f"{k} {v}" for k, v in st.items() if k != "unmatched_files"))
            for f in (st.get("unmatched_files") or [])[:20]:
                print(f"    unmatched: {f}")
            all_rows += rows + extra

    # ---- art
    todo = []
    for r in all_rows:
        if not r.get("_src_image"):
            continue
        v = ver_token(r["_ver"])
        r["image_url"] = public_url(sb, r["_store_key"], v)
        old = existing.get((r["card_id"], r["lang"]))
        same = old and old.get("image_url") == r["image_url"]
        need_archive = args.archive and not os.path.exists(archive_path(args.archive, r))
        if not args.no_art and (not same or need_archive):
            todo.append((r, not same))
    print(f"\nArt: {len(todo)} to process "
          f"({sum(1 for _, u in todo if u)} new/changed uploads) with {args.workers} workers")
    failed: set[tuple[str, str]] = set()
    missing: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    def job(item):
        r, upload = item
        return process_art(sb, r, args.archive, args.commit and upload)

    if todo and not args.commit and not args.archive:
        print("  (dry run without --archive: nothing to download)")
        todo = []
    if todo:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(job, it): it[0] for it in todo}
            for i, fut in enumerate(cf.as_completed(futs), 1):
                r = futs[fut]
                try:
                    k = fut.result()
                    counts[k] = counts.get(k, 0) + 1
                except ArtMissing as e:
                    missing.add((r["card_id"], r["lang"]))
                    print(f"  art missing at source {r['lang']} {r['source_ref']}: {e}")
                except Exception as e:
                    failed.add((r["card_id"], r["lang"]))
                    print(f"  art FAIL {r['lang']} {r['source_ref']}: {e}")
                if i % 250 == 0:
                    print(f"  ... {i}/{len(todo)} {counts}")
    print(f"  art done: {counts}, missing at source {len(missing)}, failed {len(failed)}")

    # A row whose art failed keeps its previous image (or none) rather than
    # pointing at an object that was never written.
    for r in all_rows:
        key = (r["card_id"], r["lang"])
        if key in missing:
            r["image_url"] = None
        elif key in failed:
            old = existing.get(key)
            r["image_url"] = old.get("image_url") if old else None

    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in all_rows]
    if args.report:
        with open(args.report, "w", encoding="utf8") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
    if args.terms_out and terms:
        merged = {}
        if os.path.exists(args.terms_out):  # keep languages this run did not pull
            with open(args.terms_out, encoding="utf8") as f:
                merged = json.load(f)
        merged.update(terms)
        with open(args.terms_out, "w", encoding="utf8", newline="\n") as f:
            json.dump(merged, f, ensure_ascii=False, indent=1, sort_keys=True)
            f.write("\n")
        print(f"Glossary written: {args.terms_out}")

    if not args.commit:
        print(f"\nDRY RUN: {len(clean)} rows would be written. Re-run with --commit.")
        return 0

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    for r in clean:
        r["updated_at"] = now
    sb.upsert("card_localizations", clean, on_conflict="card_id,lang", batch=500)
    print(f"\nUpserted {len(clean)} rows.")

    # Stale rows: only for a language whose pull is plainly complete.
    for lang in langs:
        if "error" in report.get(lang, {}):
            continue
        fresh = {r["card_id"] for r in clean if r["lang"] == lang}
        on_file = {cid for (cid, l) in existing if l == lang}
        stale = on_file - fresh
        if not stale:
            continue
        if len(fresh) < MIN_RATIO * len(on_file):
            print(f"  {lang}: {len(stale)} stale rows KEPT - pull ({len(fresh)}) is under "
                  f"{MIN_RATIO:.0%} of what is on file ({len(on_file)})")
            continue
        for cid in stale:
            sb.delete("card_localizations", {"card_id": f"eq.{cid}", "lang": f"eq.{lang}"})
        print(f"  {lang}: deleted {len(stale)} stale rows")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
