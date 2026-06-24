"""
ocr_slab_audit.py — "Option C": the slab-OCR backstop for graded_sales attribution.

Option B (scripts/fix_chase_by_price.sql) auto-corrects the EXPENSIVE mislabels
(a base-rarity sale priced >= $800 that has a chase twin → move to the chase).
C catches the rest: the cheap ones B's price floor can't see, plus cn-conflicts
and low-confidence matches. PSA / CGC / BGS print the rarity + collector# right
on the slab label, so reading the label resolves the card unambiguously.

Pipeline per UNCERTAIN sale:
  1. download the eBay image (i.ebayimg.com s-l1200 — public CDN),
  2. crop the top label strip,
  3. OCR it (pluggable engine — Tesseract or Anthropic vision),
  4. parse rarity + collector# + grade from the label text,
  5. reconcile to the correct card_id in the `cards` catalog,
  6. report (dry-run) or re-attribute (--commit).

eBay safety: these are anonymous GETs of PUBLIC CDN images (already URL'd in our
DB from the Terapeak scrape) from a server IP — NOT tied to the eBay account, and
much lower risk than the logged-in scrape itself. Rate-limited (DELAY) + a normal
User-Agent. Do NOT run from the account-holder's home IP while logged into eBay.

OCR engines (install ONE):
  • Tesseract (free, local):  pip install pytesseract  +  the tesseract binary
      (Windows: github.com/UB-Mannheim/tesseract/wiki). Run: --engine tesseract
  • Anthropic vision (best):  pip install anthropic  +  ANTHROPIC_API_KEY in env
      or scripts/.env. Run: --engine anthropic

    python scripts/ocr_slab_audit.py --selftest                 # parser + reconcile self-test (no OCR)
    python scripts/ocr_slab_audit.py --mode all --limit 20      # dry-run on the 20 priciest sales
    python scripts/ocr_slab_audit.py --mode uncertain --commit  # just the uncertain set
    python scripts/ocr_slab_audit.py --mode all --commit        # FULL one-time audit (resumable)

Modes:
  uncertain  cn-conflict / low-confidence / base-with-twin under $800 (Option B's blind spot)
  siblings   every sale on a card that has same-(name,version,set) printing siblings — the
             complete set reconcile() can act on; no-sibling sales are skipped (always no-ops)
  all        every auditable sale; sibling cards get re-attributed. FLAGGED to
             scripts/_ocr_mismatches.csv for manual review (never auto-changed):
               • rarity    — no-sibling card whose slab shows a chase rarity it isn't filed as
               • grade     — slab grader/grade disagrees with the filed sale (titled PSA 10
                             but the slab reads PSA 9 / raw) → rollup pollution
               • downgrade — an expensive sale OCR wants to move from chase DOWN to base
                             (likely an OCR misread; base cards don't sell at chase prices)

A --commit run writes scripts/_ocr_done.txt so a restart resumes where it left off.
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import io
import os
import re
import shutil
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; PacksInkSlabAudit/1.0)"}
DELAY = 0.2  # per-fetch politeness sleep (anonymous public-CDN GETs)
WORKERS = 8  # parallel download+OCR threads. Each pytesseract call spawns its own
             # tesseract.exe, so N workers ≈ N cores busy. Only the read-only compute
             # is parallel; ALL writes happen on the main thread (no data races).
CHUNK = 400  # sales per executor batch — bounds in-flight futures + lets the rollup
             # refresh between batches.
# An expensive sale that OCR wants to move from a CHASE rarity DOWN to base is almost
# always an OCR misread (base cards don't sell at chase prices) — flag it, don't apply.
DOWNGRADE_REVIEW_FLOOR = 150.0

CHASE = {"Enchanted", "Iconic", "Epic"}
RARITY_WORDS = [
    ("ENCHANTED", "Enchanted"), ("ICONIC", "Iconic"), ("EPIC", "Epic"),
    ("SUPER RARE", "Super Rare"), ("LEGENDARY", "Legendary"),
    ("UNCOMMON", "Uncommon"), ("COMMON", "Common"), ("PROMO", "Promo"),
    ("RARE", "Rare"),  # after SUPER RARE so "super rare" wins
]


# ── label parsing ───────────────────────────────────────────────────────────
def parse_label(text: str) -> dict:
    """Extract {rarity, collector_number, grader, grade} from OCR'd slab-label text."""
    t = " ".join((text or "").split())
    up = t.upper()
    out = {"rarity": None, "cn": None, "grader": None, "grade": None}

    for needle, canon in RARITY_WORDS:
        if re.search(r"\b" + needle.replace(" ", r"\s+") + r"\b", up):
            out["rarity"] = canon
            break

    # collector#: "#208", "208/204", "104/204", "2/C1"
    m = re.search(r"#\s*(\d{1,3})\b", up) or re.search(r"\b(\d{1,3})\s*/\s*(?:\d{2,3}|[A-Z]\d)\b", up)
    if m:
        out["cn"] = str(int(m.group(1)))

    mg = re.search(r"\b(PSA|CGC|BGS|SGC|TAG|BECKETT)\b", up)
    if mg:
        out["grader"] = "BGS" if mg.group(1) == "BECKETT" else mg.group(1)

    # grade: explicit "<grader> 10", "GEM MT 10", "MINT 9", "PRISTINE 10", or a bare 8-10(.5)
    mgr = (re.search(r"\b(?:PSA|CGC|BGS|SGC|TAG|BECKETT)\s*(10|\d(?:\.5)?)\b", up)
           or re.search(r"\b(?:GEM\s*MT|GEM\s*MINT|PRISTINE|MINT\+?|MINT)\s*(10|\d(?:\.5)?)\b", up))
    if mgr:
        out["grade"] = mgr.group(1)
    return out


# ── catalog + reconciliation ────────────────────────────────────────────────
def fetch_cards():
    cards = []
    for off in range(0, 9000, 1000):
        r = requests.get(f"{SB_URL}/rest/v1/cards", headers=HEAD, timeout=30, params={
            "select": "id,set_id,name,version,collector_number,rarity", "offset": off, "limit": 1000, "order": "id"})
        r.raise_for_status()
        b = r.json()
        cards.extend(b)
        if len(b) < 1000:
            break
    return cards


def norm_cn(cn):
    m = re.match(r"^0*(\d+)$", str(cn or "").strip())
    return m.group(1) if m else str(cn or "").strip().upper()


def norm_grade(g):
    s = str(g or "").strip()
    return s[:-2] if s.endswith(".0") else s


def reconcile(cur_card, label, by_id, by_name):
    """Given the sale's current card row + parsed label, return the correct card_id
    (or None if no confident change). Strategy: stay on the same character
    (name+version); the label's rarity/cn picks WHICH printing of that character."""
    name, version = cur_card["name"], cur_card.get("version") or ""
    # SAME SET ONLY. A character can exist across promo sets with different
    # numbers (e.g. Cinderella - Stouthearted: Challenge #42 vs D23 #2), and an
    # OCR'd community-# can collide across sets. The matcher already got the SET
    # right via set hints — only the rarity/printing within that set is in doubt.
    sibs = [c for c in by_name.get((name, version), []) if c.get("set_id") == cur_card.get("set_id")]
    if len(sibs) < 2:  # nothing to disambiguate within the set
        return None
    lr, lcn = label.get("rarity"), label.get("cn")
    # 1) rarity + cn both present → the sibling matching both wins (most certain).
    if lr and lcn:
        for c in sibs:
            if c["rarity"] == lr and norm_cn(c["collector_number"]) == lcn:
                return c["id"]
    # 2) collector# alone (Enchanted/Iconic carry their own #) → unique sibling by cn.
    if lcn:
        hits = [c for c in sibs if norm_cn(c["collector_number"]) == lcn]
        if len(hits) == 1:
            return hits[0]["id"]
    # 3) rarity alone → unique sibling of that rarity.
    if lr:
        hits = [c for c in sibs if c["rarity"] == lr]
        if len(hits) == 1:
            return hits[0]["id"]
    return None


# ── OCR engines ─────────────────────────────────────────────────────────────
def crop_label(img_bytes: bytes) -> bytes:
    """Crop the top ~24% of the slab (the printed grading label), grayscale +
    autocontrast + upscale for cleaner OCR. Returns PNG bytes."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    w, h = im.size
    strip = im.crop((0, 0, w, int(h * 0.24)))
    g = ImageOps.autocontrast(ImageOps.grayscale(strip), cutoff=2)
    if g.width < 1600:
        sc = 1600 / g.width
        g = g.resize((int(g.width * sc), int(g.height * sc)))
    buf = io.BytesIO()
    g.save(buf, format="PNG")
    return buf.getvalue()


# Tesseract binary (Windows installs to Program Files, often NOT on PATH).
_TESS = shutil.which("tesseract") or next((p for p in [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
] if os.path.exists(p)), None)


def ocr_tesseract(label_png: bytes) -> str:
    import pytesseract
    from PIL import Image
    if _TESS:
        pytesseract.pytesseract.tesseract_cmd = _TESS
    # PSM 6 = assume a single uniform block of text (the label strip).
    return pytesseract.image_to_string(Image.open(io.BytesIO(label_png)), config="--psm 6")


def ocr_anthropic(label_png: bytes) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    b64 = base64.standard_b64encode(label_png).decode()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001", max_tokens=120,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": "Transcribe the graded-slab label text verbatim (card name, set, collector number, rarity word, grader, grade). One line."},
        ]}])
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")


def pick_engine(name):
    if name == "tesseract" or (name == "auto" and _has("pytesseract")):
        return ocr_tesseract, "tesseract"
    if name == "anthropic" or (name == "auto" and os.environ.get("ANTHROPIC_API_KEY") and _has("anthropic")):
        return ocr_anthropic, "anthropic"
    return None, None


def _has(mod):
    try:
        __import__(mod)
        return True
    except Exception:
        return False


# ── uncertain-sale selection ────────────────────────────────────────────────
def base_twin_ids(cards):
    """card_ids of base-rarity cards that HAVE a chase twin (same name+version,
    Enchanted/Iconic/Epic) — the set Option B's $800 floor can't fully cover."""
    twins = set((c["name"], c.get("version") or "") for c in cards if c["rarity"] in CHASE)
    return [c["id"] for c in cards
            if c["rarity"] in ("Common", "Uncommon", "Rare", "Super Rare", "Legendary")
            and (c["name"], c.get("version") or "") in twins]


def sibling_card_ids(cards):
    """All card_ids that share (set_id, name, version) with >=1 other card — i.e.
    the only cards reconcile() can ever re-attribute among (base<->Enchanted/Iconic/
    Epic in one set, C1 foil/non-foil). Sales on any other card are guaranteed no-ops."""
    groups = {}
    for c in cards:
        groups.setdefault((c["set_id"], c["name"], c.get("version") or ""), []).append(c["id"])
    out = set()
    for ids in groups.values():
        if len(ids) >= 2:
            out.update(ids)
    return out


def _slice(rows, offset, limit):
    return rows[offset:(offset + limit) if limit else None]


SEL = "item_id,card_id,title,image_url,sale_price,grader,grade,cn_conflict,match_confidence"


def fetch_all_auditable(limit, offset, only_ids=None):
    """Every auditable sale (non-excluded, has card_id + image), priciest first.
    If only_ids is given, keep only sales on those cards (siblings mode)."""
    rows, off = [], 0
    while True:
        r = requests.get(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=120, params={
            "select": SEL, "excluded": "is.false", "card_id": "not.is.null", "image_url": "not.is.null",
            "order": "sale_price.desc.nullslast,item_id.asc", "offset": off, "limit": 1000})
        r.raise_for_status()
        page = r.json()
        rows.extend(page if only_ids is None else [x for x in page if x["card_id"] in only_ids])
        if len(page) < 1000:
            break
        off += 1000
    return _slice(rows, offset, limit)


def fetch_uncertain(limit, offset, twin_ids):
    """Union of (a) cn-conflict / low-confidence sales and (b) base-with-twin sales
    under $800 (Option B's blind spot), deduped by item_id, priciest first."""
    seen, rows = set(), []

    def take(params):
        r = requests.get(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD, timeout=60, params=params)
        r.raise_for_status()
        for x in r.json():
            if x["item_id"] not in seen:
                seen.add(x["item_id"])
                rows.append(x)

    take({"select": SEL, "excluded": "is.false", "card_id": "not.is.null", "image_url": "not.is.null",
          "or": "(cn_conflict.is.true,match_confidence.lt.0.5)",
          "order": "sale_price.desc.nullslast", "limit": "2000"})
    for i in range(0, len(twin_ids), 80):  # batch the IN(...) list to keep URLs sane
        take({"select": SEL, "excluded": "is.false", "image_url": "not.is.null",
              "card_id": "in.(" + ",".join(twin_ids[i:i + 80]) + ")",
              "sale_price": "lt.800", "order": "sale_price.desc.nullslast", "limit": "1000"})

    rows.sort(key=lambda x: (x.get("sale_price") or 0), reverse=True)
    return _slice(rows, offset, limit)


def patch_one(item_id, cid):
    """Re-attribute a single sale immediately (so a long run commits incrementally
    and a mid-run failure never loses progress)."""
    r = requests.patch(f"{SB_URL}/rest/v1/graded_sales",
                       headers={**HEAD, "Content-Type": "application/json", "Prefer": "return=minimal"},
                       params={"item_id": "eq." + item_id}, json={"card_id": cid}, timeout=30)
    if r.status_code < 300:
        return True
    print(f"  PATCH {item_id} -> {r.status_code}: {r.text[:120]}")
    return False


def refresh_rollup():
    requests.post(f"{SB_URL}/rest/v1/rpc/refresh_graded_sales_rollup", headers=HEAD, json={}, timeout=300)


# ── self-test (no OCR / no network) ─────────────────────────────────────────
def selftest():
    samples = [
        ("2023 DISNEY LORCANA EN 1 #208 MICKEY MOUSE ENCHANTED GEM MT 10",
         {"rarity": "Enchanted", "cn": "208", "grader": "PSA" if False else None, "grade": "10"}),
        ("Aladdin - Heroic Outlaw Disney Lorcana 2023 The First Chapter - 104/204 Demo CGC MINT 9",
         {"rarity": None, "cn": "104", "grader": "CGC", "grade": "9"}),
        ("2025 DISNEY LORCANA EN 9 #233 POWERLINE ENCHANTED GEM MT 10",
         {"rarity": "Enchanted", "cn": "233", "grade": "10"}),
        ("Simba Returned King 215/204 BGS 9.5",
         {"rarity": None, "cn": "215", "grader": "BGS", "grade": "9.5"}),
    ]
    ok = True
    for text, exp in samples:
        got = parse_label(text)
        for k, v in exp.items():
            if got.get(k) != v:
                ok = False
                print(f"  PARSE MISMATCH [{k}] for {text!r}\n    got {got.get(k)!r} expected {v!r}")
    print("parse self-test:", "PASS" if ok else "FAIL")

    # reconcile self-test against the live catalog
    cards = fetch_cards()
    by_id = {c["id"]: c for c in cards}
    by_name = {}
    for c in cards:
        by_name.setdefault((c["name"], c.get("version") or ""), []).append(c)
    # Mickey Wayward Sorcerer base (SR) + label says ENCHANTED #208 → Enchanted id
    base = next((c for c in cards if c["name"] == "Mickey Mouse" and (c.get("version") or "") == "Wayward Sorcerer"
                 and c["rarity"] != "Enchanted"), None)
    if base:
        newid = reconcile(base, {"rarity": "Enchanted", "cn": "208"}, by_id, by_name)
        tgt = by_id.get(newid)
        print("reconcile Mickey Wayward Sorcerer ENCHANTED #208 ->",
              (tgt["rarity"] + " #" + str(tgt["collector_number"])) if tgt else "None",
              "PASS" if (tgt and tgt["rarity"] == "Enchanted") else "FAIL")
    else:
        print("reconcile self-test: base card not found (catalog?)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="0 = no limit (all matching sales)")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--mode", choices=["uncertain", "siblings", "all"], default="uncertain",
                    help="uncertain=cn-conflict/low-conf/twin<$800 (default); "
                         "siblings=every sale on a card with same-set printing siblings; "
                         "all=every auditable sale (no-sibling cards get a mismatch FLAG, not a re-attr)")
    ap.add_argument("--no-resume", action="store_true",
                    help="ignore the _ocr_done.txt checkpoint and re-OCR from scratch")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"parallel download+OCR threads (default {WORKERS}; 1 = serial)")
    ap.add_argument("--engine", choices=["auto", "tesseract", "anthropic"], default="auto")
    ap.add_argument("--commit", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--verbose", action="store_true", help="print raw OCR + parsed label per sale")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    ocr, engine = pick_engine(args.engine)
    if not ocr:
        print("No OCR engine available. Install Tesseract (pip install pytesseract + the\n"
              "tesseract binary) OR set ANTHROPIC_API_KEY (pip install anthropic).")
        return
    print(f"OCR engine: {engine}")

    cards = fetch_cards()
    by_id = {c["id"]: c for c in cards}
    by_name = {}
    for c in cards:
        by_name.setdefault((c["name"], c.get("version") or ""), []).append(c)

    sib_set = sibling_card_ids(cards)
    if args.mode == "uncertain":
        sales = fetch_uncertain(args.limit, args.offset, base_twin_ids(cards))
    else:
        sales = fetch_all_auditable(args.limit, args.offset,
                                    sib_set if args.mode == "siblings" else None)
    print(f"[{args.mode}] sales to check: {len(sales)}", flush=True)

    # Resume checkpoint — skip sales already OCR'd in a prior COMMIT run (this is a
    # multi-hour pass; a restart should not re-fetch what's done). Only active under
    # --commit: a dry-run must never mark items done (the real run would then skip
    # them and never commit their re-attrs). Errors are NOT marked done, so transient
    # network failures retry next run.
    done_path = HERE / "_ocr_done.txt"
    done, done_fh = set(), None
    if args.commit:
        if done_path.exists() and not args.no_resume:
            done = set(done_path.read_text(encoding="utf-8").split())
            print(f"resume: {len(done)} sales already done (skipping)", flush=True)
        done_fh = open(done_path, "a", encoding="utf-8")

    # Mismatch review log — two issue types, both FLAGGED for MANUAL review (never
    # auto-changed): "rarity" = slab shows a chase rarity the filed card isn't, with
    # no same-set sibling to move to (likely a wrong-character/wrong-set title match);
    # "grade" = the slab's grader/grade disagrees with what the sale is filed as
    # (e.g. titled PSA 10 but the slab reads PSA 9, or raw) — pollutes the rollup.
    mm_path = HERE / "_ocr_mismatches.csv"
    mm_new = not mm_path.exists()
    mm_fh = open(mm_path, "a", encoding="utf-8")
    if mm_new:
        mm_fh.write("issue,item_id,sale_price,cur_card_id,cur_card,stored_grader,stored_grade,"
                    "slab_grader,slab_grade,slab_rarity,slab_cn,title,image_url\n")

    def write_flag(issue, s, cur, label):
        ttl = (s.get("title") or "").replace('"', "'")
        mm_fh.write(",".join([
            issue, s["item_id"], str(s.get("sale_price")), s["card_id"],
            f'"{cur["name"]} - {cur.get("version") or ""} {cur["rarity"]} #{cur["collector_number"]}"',
            str(s.get("grader") or ""), str(s.get("grade") or ""),
            str(label.get("grader") or ""), str(label.get("grade") or ""),
            str(label.get("rarity") or ""), str(label.get("cn") or ""),
            f'"{ttl}"', s["image_url"],
        ]) + "\n")
        mm_fh.flush()

    # Read-only per-sale compute (download + crop + OCR + reconcile). Runs in worker
    # threads and touches NO shared mutable state — every write (DB patch, checkpoint,
    # counters, mismatch log) happens back on the main thread, so there's nothing to
    # race on. Returns a tuple the main thread acts on.
    def work(s):
        cur = by_id.get(s["card_id"])
        if not cur:
            return (s, None, None, None, "nocard")
        try:
            img = requests.get(s["image_url"], headers=UA, timeout=30).content
            label = parse_label(ocr(crop_label(img)))
            newid = reconcile(cur, label, by_id, by_name)
        except Exception:
            return (s, cur, None, None, "error")  # transient — not marked done, retried next run
        finally:
            if DELAY:
                time.sleep(DELAY)
        return (s, cur, label, newid, "ok")

    todo = [s for s in sales if s["item_id"] not in done]
    resumed = len(sales) - len(todo)
    if resumed:
        print(f"resume: skipping {resumed} already-done sales", flush=True)
    print(f"to process: {len(todo)} with {max(1, args.workers)} workers", flush=True)

    proposed = committed = skipped = flag_rar = flag_grd = flag_dng = processed = last_refresh = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        for cstart in range(0, len(todo), CHUNK):
            for (s, cur, label, newid, status) in ex.map(work, todo[cstart:cstart + CHUNK]):
                processed += 1
                if processed % 100 == 0:
                    print(f"  ... {processed}/{len(todo)}  (re-attr {proposed}, committed {committed}, "
                          f"flag-rar {flag_rar}, flag-grd {flag_grd}, flag-dng {flag_dng}, "
                          f"skip {skipped})", flush=True)
                if status == "nocard":
                    continue
                if status == "error":
                    skipped += 1
                    continue
                if args.verbose:
                    print(f"  [{(s.get('title') or '')[:50]}] -> {label}", flush=True)

                lr = label.get("rarity")
                if newid and newid != s["card_id"]:
                    tgt = by_id[newid]
                    downgrade = cur["rarity"] in CHASE and tgt["rarity"] not in CHASE
                    if downgrade and (s.get("sale_price") or 0) >= DOWNGRADE_REVIEW_FLOOR:
                        flag_dng += 1
                        write_flag("downgrade", s, cur, label)
                        print(f"  ⚑ DOWNGRADE? ${s.get('sale_price')}  {cur['name']} {cur['rarity']} "
                              f"#{cur['collector_number']} -> {tgt['rarity']} #{tgt['collector_number']}  (review, not applied)", flush=True)
                    else:
                        proposed += 1
                        print(f"  RE-ATTR ${s['sale_price']}  {cur['name']} - {cur.get('version')}  "
                              f"{cur['rarity']} #{cur['collector_number']}  ->  {tgt['rarity']} #{tgt['collector_number']}", flush=True)
                        if args.commit and patch_one(s["item_id"], newid):
                            committed += 1
                elif s["card_id"] not in sib_set and lr in CHASE and cur["rarity"] != lr:
                    flag_rar += 1
                    write_flag("rarity", s, cur, label)
                    print(f"  ⚑ RARITY ${s.get('sale_price')}  {cur['name']} {cur['rarity']} "
                          f"#{cur['collector_number']}  — slab says {lr} {label.get('cn') or ''}", flush=True)

                # Grade mismatch — independent of card_id (check every sale). Gate on the
                # slab grader+grade both being read (confidence); flag if either disagrees
                # with the filed sale. Flag-only: OCR grade reads can be noisy.
                og, ogr = norm_grade(label.get("grade")), label.get("grader")
                sg = norm_grade(s.get("grade"))
                sgr = str(s.get("grader") or "").upper() or None
                if ogr and og and ((sg and og != sg) or (sgr and ogr != sgr)):
                    flag_grd += 1
                    write_flag("grade", s, cur, label)
                    print(f"  ⚑ GRADE  ${s.get('sale_price')}  {cur['name']} - {cur.get('version')}"
                          f"  — DB {sgr or '?'} {sg or '?'}  vs slab {ogr} {og}", flush=True)

                if done_fh:
                    done_fh.write(s["item_id"] + "\n")
                    done_fh.flush()

            # Between chunks: refresh the rollup if there are new commits to surface.
            if args.commit and committed > last_refresh:
                refresh_rollup()
                last_refresh = committed
                print(f"  (rollup refreshed @ {processed}, {committed} committed)", flush=True)

    if done_fh:
        done_fh.close()
    mm_fh.close()
    print(f"\ndone. re-attr {proposed}, committed {committed}, "
          f"flag-rarity {flag_rar}, flag-grade {flag_grd}, flag-downgrade {flag_dng}, "
          f"skipped {skipped}, resumed {resumed}")
    if flag_rar or flag_grd or flag_dng:
        print(f"mismatches logged to {mm_path}")
    if args.commit and committed > last_refresh:
        refresh_rollup()
        print("rollup refreshed.")
    elif not args.commit and proposed:
        print("dry-run — re-run with --commit to apply.")


if __name__ == "__main__":
    main()
