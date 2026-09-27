"""
load_playmats.py - TCGplayer's Lorcana playmats -> public.playmats (migration 170).

TCGplayer does not file playmats under Lorcana (category 71). Every official mat -
retail, Set Championship, Disney Lorcana Challenge, convention - sits in its
separate Playmats category (35), group "Ravensburger Playmats" (23280). This pulls
that group from TCGCSV, sorts each mat into a SECTION, and upserts the catalog.
Prices are not this script's job: the daily ETL writes them to prices_daily
(tcgcsv_common.EXTRA_PRICE_GROUPS) and the playmat_prices_latest view joins them.

Sections (Zaven, 2026-09-27: "retail, set champ, dlc, event, etc"):
    retail     sold in stores, one or two per set - including the Ravensburger
               online-store and Disney-location exclusives, which are still bought
    set_champ  Set Championship prizes, Champion / Participant
    dlc        Disney Lorcana Challenge prizes
    event      conventions and one-off event exclusives
    other      nothing matched - reported by the catalog watch, never guessed

Almost everything is decided by what TCGplayer itself wrote: the "(Champion)" /
"(Disney Lorcana Challenge)" suffixes, the Set Championship description that
names its set, the release date a retail mat shipped on. What it cannot say
lives in scripts/playmat_overrides.json, one entry per mat, each with a reason.

Idempotent upsert, never deletes: an owned playmat is a sealed_collection_items
row (see PLAYMAT_PID_BASE in Index.html) and must not lose its catalog row
because TCGplayer delisted it.

Usage:
    python scripts/load_playmats.py              # write
    python scripts/load_playmats.py --dry-run    # print the plan, write nothing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from supabase_client import Supabase
from tcgcsv_common import PLAYMATS_CATEGORY_ID, PLAYMATS_GROUP_ID, TCGCSV_BASE


USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests playmat-loader"
OVERRIDES_PATH = Path(__file__).parent / "playmat_overrides.json"
SECTIONS = ("retail", "set_champ", "dlc", "event", "other")

# A retail mat ships a week or two after its set's LGS date (every release since
# Archazia's Island has run +7 days; Ursula's Return ran +14). 45 days is room
# for a late wave without letting a mat attach to the set BEFORE the right one.
RETAIL_RELEASE_WINDOW_DAYS = 45

_PREFIX_RE = re.compile(r"^\s*disney\s+lorcana\s*:\s*", re.I)
_TRAILING_BRACKET_RE = re.compile(r"\s*\(([^()]*)\)\s*$")
_FINISH_RE = re.compile(r"\s+(premium\s+foil|foil)\s+playmat\s*$", re.I)
_PLAYMAT_RE = re.compile(r"\s+playmat\s*$", re.I)
_TIER_RE = re.compile(r"\((champion|participant)\)\s*$", re.I)
_DLC_RE = re.compile(r"\(disney lorcana challenge\)\s*$", re.I)
_CONVENTION_RE = re.compile(r"\b(20\d\d)\s+convention\s+playmat\b", re.I)
_SC_DESC_RE = re.compile(
    r"prize for the (\d{4}) disney lorcana:\s*(.+?)\s+set championship", re.I)
_DLC_YEAR_RE = re.compile(r"\b(20\d\d)\s+disney lorcana challenge\b", re.I)
_EXCL_ONLINE_RE = re.compile(r"exclusively available on the ravensburger online store", re.I)
_EXCL_DISNEY_RE = re.compile(r"exclusively available at disney locations", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def clean_description(text: str | None) -> str:
    """TCGplayer's description as plain text: tags out, whitespace collapsed.
    The U+FFFD it carries where an apostrophe should be ("Archazia�s") is
    left alone - it is their data - and set matching ignores punctuation."""
    t = _TAG_RE.sub(" ", text or "")
    return " ".join(t.split())


def display_name(tcg_name: str) -> tuple[str, str | None]:
    """TCGplayer's name -> (title, finish).

    'Disney Lorcana: Rapunzel - Gifted with Healing Foil Playmat (Disney Lorcana
    Challenge)' -> ('Rapunzel - Gifted with Healing', 'Foil'). The prefix, the
    trailing bracket and the word Playmat all say something the tab already
    says; the FINISH is a fact about the mat and is kept, separately.
    """
    n = _PREFIX_RE.sub("", (tcg_name or "").strip())
    n = _TRAILING_BRACKET_RE.sub("", n).strip()
    finish = None
    m = _FINISH_RE.search(n)
    if m:
        finish = "Premium Foil" if "premium" in m.group(1).lower() else "Foil"
        n = n[: m.start()]
    else:
        n = _PLAYMAT_RE.sub("", n)
    return n.strip(), finish


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def numbered_sets(sets: list[dict]) -> list[dict]:
    """Booster sets only (code is a number). A playmat belongs to a set's
    release or a set's championship, never to a promo set."""
    out = [s for s in sets if str(s.get("code") or "").strip().isdigit()]
    return sorted(out, key=lambda s: int(str(s["code"]).strip()))


def match_set_name(text: str, sets: list[dict]) -> str | None:
    """A set named in free text -> its id. Punctuation is ignored (TCGplayer
    writes "Archazia�s Island"), and a typo of one or two trailing letters
    is tolerated ("Reign of Jafarl") by accepting the LONGEST set name the text
    starts with - never a shorter one that merely prefixes a different set."""
    want = _norm(text)
    if not want:
        return None
    best = None
    for s in numbered_sets(sets):
        have = _norm(s.get("name") or "")
        if not have:
            continue
        if want == have:
            return s["id"]
        if want.startswith(have) and len(want) - len(have) <= 2:
            if best is None or len(have) > len(_norm(best.get("name") or "")):
                best = s
    return best["id"] if best else None


def set_by_release(released_on: str | None, sets: list[dict]) -> str | None:
    """The booster set a retail mat shipped with: the latest set released on or
    before the mat's street date, within RETAIL_RELEASE_WINDOW_DAYS."""
    if not released_on:
        return None
    try:
        d = date.fromisoformat(released_on[:10])
    except ValueError:
        return None
    best = None
    for s in numbered_sets(sets):
        ra = s.get("released_at")
        if not ra:
            continue
        try:
            sd = date.fromisoformat(str(ra)[:10])
        except ValueError:
            continue
        gap = (d - sd).days
        if 0 <= gap <= RETAIL_RELEASE_WINDOW_DAYS and (best is None or sd > best[0]):
            best = (sd, s["id"])
    return best[1] if best else None


def classify(product: dict, sets: list[dict]) -> dict:
    """One TCGCSV product -> the catalog fields this script decides.

    Returns {name, finish, section, tier, set_id, source, year, released_on,
    presale}. Pure: the test runs it over a frozen copy of the group.
    """
    tcg_name = (product.get("name") or "").strip()
    desc = clean_description(_ext(product, "Description"))
    presale = (product.get("presaleInfo") or {})
    released_on = (presale.get("releasedOn") or "")[:10] or None
    name, finish = display_name(tcg_name)
    out: dict[str, Any] = {
        "name": name, "finish": finish, "section": "other", "tier": None,
        "set_id": None, "source": None, "year": None,
        "released_on": released_on, "presale": bool(presale.get("isPresale")),
    }
    tier = _TIER_RE.search(tcg_name)
    conv = _CONVENTION_RE.search(tcg_name)
    if tier:
        out["section"] = "set_champ"
        out["tier"] = tier.group(1).title()
        m = _SC_DESC_RE.search(desc)
        if m:
            out["year"] = int(m.group(1))
            out["set_id"] = match_set_name(m.group(2), sets)
    elif _DLC_RE.search(tcg_name):
        out["section"] = "dlc"
        m = _DLC_YEAR_RE.search(desc)
        if m:
            out["year"] = int(m.group(1))
    elif conv:
        out["section"] = "event"
        out["year"] = int(conv.group(1))
        out["source"] = f"{conv.group(1)} conventions"
    else:
        # Everything else TCGplayer lists here has been a mat you could BUY. An
        # online-store or Disney-location exclusive is still a purchase, so it
        # files under retail with its shop named, beside its set's other mats.
        out["section"] = "retail"
        if _EXCL_ONLINE_RE.search(desc):
            out["source"] = "Ravensburger online store"
        elif _EXCL_DISNEY_RE.search(desc):
            out["source"] = "Disney locations"
        out["set_id"] = set_by_release(released_on, sets)
    return out


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[int, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[int, dict] = {}
    for key, entry in (raw.get("overrides") or {}).items():
        out[int(key)] = entry
    return out


def apply_override(row: dict, entry: dict | None, sets: list[dict]) -> dict:
    """An override wins field by field. `set` is a set NAME (readable in the
    file), resolved to its id here; an unknown name is an error rather than a
    silent null, because a typo there would quietly move a mat out of its set."""
    if not entry:
        return row
    row = dict(row)
    for k in ("section", "tier", "finish", "source", "year", "name"):
        if k in entry:
            row[k] = entry[k]
    if "set" in entry:
        if entry["set"] is None:
            row["set_id"] = None
        else:
            by_name = {(s.get("name") or "").strip().lower(): s["id"] for s in sets}
            sid = by_name.get(str(entry["set"]).strip().lower())
            if not sid:
                raise ValueError(f"playmat override names unknown set {entry['set']!r}")
            row["set_id"] = sid
    if row["section"] not in SECTIONS:
        raise ValueError(f"playmat override has unknown section {row['section']!r}")
    return row


def is_lorcana(product: dict) -> bool:
    return bool(_PREFIX_RE.match(product.get("name") or ""))


def build_rows(products: list[dict], sets: list[dict], overrides: dict[int, dict]) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for p in products:
        pid = p.get("productId")
        if pid is None or not is_lorcana(p):
            continue
        c = apply_override(classify(p, sets), overrides.get(int(pid)), sets)
        rows.append({
            "tcgplayer_product_id": int(pid),
            "tcg_name": (p.get("name") or "").strip(),
            "name": c["name"],
            "section": c["section"],
            "set_id": c["set_id"],
            "tier": c["tier"],
            "finish": c["finish"],
            "source": c["source"],
            "year": c["year"],
            "released_on": c["released_on"],
            "description": clean_description(_ext(p, "Description")) or None,
            "image_url": p.get("imageUrl") or None,
            "tcgplayer_url": p.get("url") or None,
            "presale": c["presale"],
            "modified_on": p.get("modifiedOn") or None,
            "updated_at": now,
        })
    return rows


def _ext(product: dict, name: str) -> str | None:
    for e in product.get("extendedData") or []:
        if (e.get("name") or "").lower() == name.lower():
            v = (e.get("value") or "").strip()
            return v or None
    return None


def fetch_products() -> list[dict]:
    url = f"{TCGCSV_BASE}/{PLAYMATS_CATEGORY_ID}/{PLAYMATS_GROUP_ID}/products"
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            data = r.json()
            return data.get("results") if isinstance(data, dict) else data
        except requests.RequestException as e:
            last = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"TCGCSV playmats fetch failed: {last}")


def _table_missing(err: Exception) -> bool:
    s = str(err)
    return "42P01" in s or "PGRST205" in s or ("(404)" in s and "playmats" in s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()
    sets = sb.select("sets", columns="id,code,name,released_at", order="id.asc")
    overrides = load_overrides()
    products = fetch_products()
    rows = build_rows(products, sets, overrides)
    set_name = {s["id"]: s.get("name") for s in sets}

    print(f"{len(products)} TCGCSV products in the playmat group -> {len(rows)} Lorcana playmats")
    by_section: dict[str, int] = {}
    for r in sorted(rows, key=lambda r: (SECTIONS.index(r["section"]), r["tcgplayer_product_id"])):
        by_section[r["section"]] = by_section.get(r["section"], 0) + 1
        bits = [x for x in (set_name.get(r["set_id"]), r["tier"], r["finish"], r["source"],
                            str(r["year"]) if r["year"] else None) if x]
        print(f"  [{r['section']:<9}] {r['tcgplayer_product_id']:>7}  {r['name']}"
              + (f"  ({' / '.join(bits)})" if bits else ""))
    print("  " + ", ".join(f"{k}: {v}" for k, v in by_section.items()))
    unplaced = [r for r in rows if r["section"] == "other"
                or (r["section"] in ("retail", "set_champ") and not r["set_id"])]
    if unplaced:
        print(f"\n{len(unplaced)} not placed in a set - add a playmat_overrides.json entry:")
        for r in unplaced:
            print(f"  {r['tcgplayer_product_id']}  {r['tcg_name']}")

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0
    try:
        sb.upsert("playmats", rows, on_conflict="tcgplayer_product_id")
    except Exception as e:
        if _table_missing(e):
            print("\nplaymats table missing - apply supabase/170_playmats.sql first. Nothing written.")
            return 0
        raise
    print(f"\nUpserted {len(rows)} playmats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
