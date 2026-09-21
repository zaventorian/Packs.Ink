"""
terapeak_load.py — load cleaned + matched Terapeak graded sales into Supabase
`graded_sales` (migration 71). This is now the ONLY graded price source; the old
TCGPriceLookup feed (graded_prices_daily/_latest) was retired 2026-06-30 and its
tables are being dropped (migration 112).

Loads the single-graded-card buckets (GRADED + NEEDS_GRADE); the EXCLUDE_*
buckets (lots/sealed/accessory/raw/other-TCG) are skipped — they aren't
single-card sales. Each row carries the matcher's card_id + grader + grade plus
two quality columns (match_confidence, cn_conflict) so nothing is blindly
trusted and the slab-OCR pass can target the uncertain rows. Re-runnable
(upsert on item_id) — re-matching never requires re-scraping.

    python scripts/terapeak_load.py --limit 200   # test
    python scripts/terapeak_load.py               # full load
"""
from __future__ import annotations

import argparse
import datetime
import os
import re
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

from terapeak_clean import load_all_dedup, classify
from terapeak_match import build_index, match_one, is_nonsingle

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEAD = {
    "apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}


def parse_date(s):
    try:
        return datetime.datetime.strptime(s, "%b %d, %Y").date().isoformat()
    except Exception:
        return None


# Lorcana Challenge (C1/C2) prize tiers imply the finish even when the title never
# says "foil": the Top Prize / Top N / Continentals cards ARE the foil printing and
# the Prize Wall handouts are non-foil. Both share ONE card_id, and their markets
# are far apart (Cinderella - Stouthearted PSA 10 medians $1,707 foil vs $280
# non-foil), so an unlabelled row is indistinguishable downstream and gets dropped
# rather than guessed.
#
# "Prize Wall" is Challenge-exclusive terminology, so it stands alone. "Top Prize"
# is NOT — Set Championship promos in Promo Set 1/2 use it too ("Ursula Set
# Championship Top Prize Promo 38/P1", $66), and those aren't C1 foils. So the
# foil side additionally requires Challenge context.
# "DLC" is Disney Lorcana Challenge, and terapeak_match's SET_ALIASES already
# reads it as one (it is what makes set_hint return "Challenge Promo") -- this
# regex was the one place that did not, so a "DLC Top Prize" title scored a set
# hint and NO printing, landing the row in a different pkey bucket from the same
# card's other sales. Measured over all 88,912 stored titles: 225 say DLC, 180
# already carry another Challenge token, and adding it flips exactly 4 rows
# None -> Foil -- three of which someone had ALREADY corrected to Foil by hand,
# which is the argument for the token. The 34 DLC titles with no Top-Prize
# wording are untouched, and none of the 225 is a "downloadable content" false
# positive.
CHALLENGE_CTX_RE = re.compile(r"\bc[12]\b|/\s*c[12]\b|challenge|continentals|\bdlc\b", re.I)
TOP_PRIZE_RE = re.compile(r"\btop\s*(?:prize|4|8|16|32|64)\b|\bcontinentals\b", re.I)
PRIZE_WALL_RE = re.compile(r"\bprize\s*wall\b|\bside\s*event\b", re.I)

# ⚠ C1 has a SECOND prize vocabulary that the Top Prize / Prize Wall pair above
# cannot read, and A Whole New World (#10) is the only card that uses it. PSA
# prints "INFINITY WEEKEND" as the sub-designation on its non-foil slabs (label
# photographed 2026-09-21), and sellers copy the line into their titles — so the
# distribution name is the finish, the same way "Prize Wall" is.
#
# Measured over all 88,912 stored titles: 41 say "Infinity Weekend", ALL 41 are
# this one card, and NONE already carries a printing — so this can only fill
# NULLs and can never overwrite a hand correction. At PSA 10 the token separates
# the markets it should: tagged sales average $213 against $396 untagged.
#
# ⚠ The foil counterpart is deliberately NOT here. CGC labels the foil "World
# Championship - Rainbow Foil", but "Rainbow Foil" already contains "foil" and is
# caught above, while "World Championship" ALONE is not evidence: all 9 such
# titles are CGC 10s at $145-$200 (the cheap side, i.e. probably non-foil) and one
# of them is already tagged Non-Foil. Adding it would guess, and on a split card
# a wrong finish files the sale in the wrong market.
INFINITY_WEEKEND_RE = re.compile(r"\binfinity\s*weekend\b", re.I)

# ⚠ A missed "non-foil" does not produce a NULL — it falls through to the bare
# `"foil" in t` test below and is stored as FOIL, i.e. the exact opposite. On a
# Challenge card that is not cosmetic: the Top Prize foil and the Prize Wall
# non-foil share ONE card_id and their markets are ~50x apart. A Whole New World
# (C1 #10) is the case that exposed it — two real foil sales at $17,500/$14,100
# against non-foils at $175-$400, three of which were stored as "Foil" purely
# because the old `non[\s-]?foil` could not read their titles.
#
# Two gaps, both found in live data: the separator must allow MORE THAN ONE
# character ("NON - Foil", "NON- Foil") and the negator must cover what sellers
# actually type ("No Foil", "No. Foil", "Not Foil", "N/Foil").
#
# ⚠ Digits are deliberately NOT in the separator class. "No. 42 Foil" is a card
# NUMBER followed by a genuine foil and must stay Foil — that is the one false
# positive this pattern has to avoid, and it is why the class is [\s\-./] and not
# a bare \W*.
NON_FOIL_RE = re.compile(r"\b(?:non?|not|n/)[\s\-./]*foil")


# A few cards' graded sales split on a NAMED VARIANT rather than a finish: the
# error/variant print shares one card_id with the base, and graded_sales_rollup
# keeps the two apart because cards.split_printing is true. The client mirrors
# this exactly in SPLIT_PRINTING_CARD_IDS / SPLIT_CARD_PRINTING_OPTIONS -- the
# ::variant:: catalog tile is raw-only and has no graded market of its own.
#
# Nothing here used to set these, so EVERY such sale landed as Normal or NULL and
# the two markets blurred: measured on Peter Pan #215, 19 rows were filed Normal
# and 21 carried no printing at all, against a real ~49% premium for the error
# print (PSA 10 avg-of-5 $400 vs $269).
#
# WARNING: the title is only ~93% reliable here. Measured by OCR-ing 280 slab
# labels: 14 rows whose seller never wrote "text error" carry PSA's own
# ENCHANTED-TEXT ERROR designation, and 6 that claim it are labelled plain.
# The SLAB LABEL is the authoritative signal -- for a graded card it IS the
# product identity -- and terapeak_ocr_reconcile.py is where that correction
# belongs. This is a floor, not the last word.
VARIANT_PRINTING_BY_CARD = {
    # Peter Pan - Pirate's Bane (Enchanted #215): a stray "}" after "Peter Pan"
    # in the Shift reminder text, corrected on a later print run.
    "crd_b5e74b533270492982dff9472aee8664": (
        "Text Error", re.compile(r"text\s*[-_. ]?\s*err(?:or)?\b|errata", re.I)),
    # Genie - On the Job (Enchanted #209): the "double sword error" -- the first
    # print shows TWO swords in the background detail, corrected to one later.
    #
    # WARNING: unlike Peter Pan, NOTHING detects this. PSA does not designate it
    # (12 slabs we already call Two Swords all read a plain "GENIE ENCHANTED"
    # label), no title in the table has ever contained the words, and the
    # difference is a background detail too small to read in a listing photo. So
    # this entry only stops the finish-reader filing Genie sales as Foil/NULL;
    # the 28 rows currently marked Two Swords were curated by hand and a new one
    # will land as Normal until somebody says otherwise. Do not mistake the
    # presence of this key for working detection.
    "crd_ae7e91462bfc4861bbf97e99ed53a1c1": (
        "Two Swords", re.compile(r"two\s*swords", re.I)),
}


def variant_printing_for(card_id, title):
    """For a named-variant card, the variant name or "Normal"; None otherwise.

    Returning "Normal" rather than None is deliberate: on these cards the base
    print IS the default, and leaving it NULL parks the row in an "Unknown"
    rollup tier that belongs to neither market."""
    ent = VARIANT_PRINTING_BY_CARD.get(card_id)
    if not ent:
        return None
    name, rx = ent
    return name if rx.search(title or "") else "Normal"


def printing_for(card_id, title):
    """THE printing a graded sale should carry: a named variant when the card has
    one, otherwise the finish read off the title.

    Every writer must go through this -- the loader, rematch_graded_unmatched and
    backfill_graded_printing. Calling printing_of() directly on a named-variant
    card files the sale under a finish (or NULL) instead of its variant, which
    blurs two markets that are ~49% apart. scripts/test_variant_printing.py pins
    that all three callers use this and not printing_of."""
    return variant_printing_for(card_id, title) or printing_of(title)


def printing_of(title: str):
    t = (title or "").lower()
    if NON_FOIL_RE.search(t):
        return "Non-Foil"
    if "cold foil" in t:
        return "Cold Foil"
    if "foil" in t or "holo" in t:
        return "Foil"
    if PRIZE_WALL_RE.search(t):
        return "Non-Foil"
    # Sits with PRIZE_WALL rather than above the finish words, deliberately: an
    # explicit "foil" in the title still wins, so this only decides a title that
    # names no finish at all — which is every one of the 41.
    if INFINITY_WEEKEND_RE.search(t):
        return "Non-Foil"
    if TOP_PRIZE_RE.search(t) and CHALLENGE_CTX_RE.search(t):
        return "Foil"
    return None


# Foreign-language listings (Chinese / Japanese / Korean printings) are a
# separate market — keep the rows but flag `excluded` so they don't blend into a
# card's graded price history (migration 76). Full words any-case OR standalone
# UPPERCASE language codes (verified no English false positives).
FOREIGN_WORD_RE = re.compile(
    r"\b(chinese|japanese|korean|china|japan|korea|"
    r"german|germany|deutsch|deutsche|"
    r"french|francais|française|francaise|"
    r"italian|italiano|italien|italienne)\b", re.I)
# Uppercase language codes (case-sensitive so we don't catch English words like
# "it"/"de"). JPN/JAP/KOR/CHN are the 3-letter Asian forms; GER/DEU/FR/FRA are the
# European edition tags eBay sellers append (e.g. "GERMAN DE 1", "Lorcana FR 2").
# Note: "IT"/"ITA" are intentionally excluded — uppercase "IT" is almost always an
# English card name ("It Means No Worries", "Wreck-It Ralph", "Let It Go"), not Italy.
FOREIGN_CODE_RE = re.compile(r"\b(ZH|JA|JP|JPN|JAP|KR|KOR|CN|CHN|GER|DEU|FR|FRA)\b")
# Bare uppercase "DE" is the German-edition tag, but it collides with the character
# name "Cruella de Vil" — only treat a standalone uppercase DE as German when the
# title isn't "...de vil..." (genuinely-German Cruella sales are still caught by the
# "german"/"deutsch" word above).
DE_TAG_RE = re.compile(r"\bDE\b")
DE_VIL_RE = re.compile(r"de\s+vil", re.I)
# German umlaut/eszett — English Lorcana titles never have these, so they're a clean
# German marker (catches "Rückkehr", "Hüter", "Mäuse", "Domäne", "Legendär", etc.).
GERMAN_CHAR_RE = re.compile(r"[äöüÄÖÜß]")


def is_foreign_lang(title: str) -> bool:
    t = title or ""
    if GERMAN_CHAR_RE.search(t):
        return True
    if FOREIGN_WORD_RE.search(t) or FOREIGN_CODE_RE.search(t):
        return True
    return bool(DE_TAG_RE.search(t) and not DE_VIL_RE.search(t))


# Troll / not-actually-graded listings: a RAW card the seller claims *would*
# grade (e.g. "PSA 10 CONTENDER", "would grade 10"). Parsed as graded (it says
# "PSA 10") but it's not a real graded sale — flag excluded.
TROLL_RE = re.compile(
    r"contender|\b(would|will|could|should)\s+grade|"
    r"gem\s*mint\s*(candidate|contender|worthy)|"
    r"\b(psa|cgc|bgs)\s*10\s*(candidate|worthy|quality)\b", re.I)


def is_troll_listing(title: str) -> bool:
    return bool(TROLL_RE.search(title or ""))


# Autographed / artist-signed / sketch cards are a separate (much pricier) market —
# an artist signature or 1/1 sketch isn't comparable to a plain graded copy, so they
# blow out the price history. Flag excluded. NOTE: do NOT match bare "1/1" — it
# collides with "Pop 1/1" (a normal card that's simply the only one PSA-graded).
# `\bautograph` has NO trailing boundary so it also catches autographed/autographs
# (the `\bautograph\b` form missed "Autographed", which slipped a $1k sale through).
AUTOGRAPH_RE = re.compile(
    r"\b(auto|signed|signature|jsa|sketch|witnessed|inscribed)\b"
    r"|\bautograph|psa/?dna|hand.?drawn", re.I)


def is_autograph(title: str) -> bool:
    return bool(AUTOGRAPH_RE.search(title or ""))


def exclude_reason_for(title: str):
    """Why this listing shouldn't count as a graded sale, or None if it should.
    Recorded in graded_sales.exclude_reason (migration 111) so exclusions stay
    auditable and one class can be reversed without disturbing the others."""
    if is_foreign_lang(title):
        return "foreign"
    if is_troll_listing(title):
        return "troll"
    if is_autograph(title):
        return "auto"
    return None


def upsert(batch):
    last = None
    for attempt in range(4):
        try:
            r = requests.post(f"{SB_URL}/rest/v1/graded_sales", headers=HEAD,
                              json=batch, timeout=60)
            if r.status_code < 300:
                return
            if r.status_code >= 500 or r.status_code == 429:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                time.sleep(3 * (attempt + 1))
                continue
            raise SystemExit(f"upsert HTTP {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise SystemExit(f"upsert failed after retries: {last}")


def refresh_rollup():
    """Rebuild graded_sales_rollup (Last Sold / Avg-of-5 per card+grader+grade)
    so the site reflects the rows we just loaded. Migration 73."""
    try:
        r = requests.post(f"{SB_URL}/rest/v1/rpc/refresh_graded_sales_rollup",
                          headers=HEAD, json={}, timeout=300)
        if r.status_code < 300:
            print("refreshed graded_sales_rollup")
        else:
            print(f"WARN: rollup refresh HTTP {r.status_code}: {r.text[:200]}")
    except requests.RequestException as e:
        print(f"WARN: rollup refresh failed: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap rows (testing)")
    ap.add_argument("--batch", type=int, default=500)
    ap.add_argument("--new-only", action="store_true",
                    help="INSERT only new item_ids (ON CONFLICT DO NOTHING); never "
                         "UPDATE existing rows, so manual excluded/card_id edits and "
                         "slab-OCR grade fills are preserved. Use for incremental "
                         "top-up loads after a re-scrape.")
    args = ap.parse_args()

    if args.new_only:
        HEAD["Prefer"] = "resolution=ignore-duplicates,return=minimal"
        print("--new-only: existing rows will NOT be updated (ON CONFLICT DO NOTHING)")

    print("Loading + classifying sales ...")
    rows, _, _ = load_all_dedup()
    print("Building catalog index ...")
    by_cn, inv, ncards, nsets = build_index()
    print(f"catalog: {ncards} cards / {nsets} sets")

    out = []
    stats = {"matched": 0, "unmatched": 0, "no_grade": 0, "conflict": 0, "skip_no_id": 0}
    for r in rows:
        cat, grader, grade = classify(r.get("title", ""), r["_file_grader"])
        if cat not in ("GRADED", "NEEDS_GRADE"):
            continue
        item_id = r.get("item_id")
        if not item_id:
            stats["skip_no_id"] += 1
            continue
        title = r.get("title", "")
        card, conf, cn_conflict = match_one(title, by_cn, inv)
        if card:
            stats["matched"] += 1
        else:
            stats["unmatched"] += 1
        if cat == "NEEDS_GRADE":
            stats["no_grade"] += 1
            grade = None
        if cn_conflict:
            stats["conflict"] += 1
        # Lots/sets/packs and collector#-conflicts are the matcher's verdict; the
        # title-based reasons are the loader's. Attribution failure loses to a
        # concrete title reason only when there isn't one.
        reason = exclude_reason_for(title)
        if reason is None:
            if is_nonsingle(title):
                reason = "lot"
            elif cn_conflict:
                reason = "cn-conflict"
        out.append({
            "item_id": item_id,
            "title": title,
            "listing_url": r.get("listing_url"),
            "image_url": r.get("thumbnail_url"),
            "sale_price": r.get("avg_sold_price"),
            "shipping": r.get("avg_shipping"),
            "quantity_sold": r.get("total_sold"),
            "bids": r.get("bids"),
            "sold_date": parse_date(r.get("date_last_sold_text")),
            "listing_type": r.get("listing_type"),
            "source_query": r.get("_file_grader"),
            "scraped_at": r.get("scraped_at"),
            "card_id": card["id"] if card else None,
            "grader": grader,
            "grade": grade,
            # A named-variant card decides its own printing (see
            # VARIANT_PRINTING_BY_CARD); everything else reads the finish.
            "printing": printing_for(card["id"], title) if card else printing_of(title),
            "match_confidence": conf,
            "cn_conflict": cn_conflict,
            "excluded": reason is not None,
            "exclude_reason": reason,
        })
        if args.limit and len(out) >= args.limit:
            break

    print(f"\nprepared {len(out)} rows  "
          f"(matched {stats['matched']}, unmatched {stats['unmatched']}, "
          f"no-grade {stats['no_grade']}, cn-conflict {stats['conflict']}, "
          f"skipped-no-id {stats['skip_no_id']})")

    print("Upserting ...")
    for i in range(0, len(out), args.batch):
        upsert(out[i:i + args.batch])
        print(f"  {min(i + args.batch, len(out))}/{len(out)}", flush=True)
    print("Refreshing rollup ...")
    refresh_rollup()
    print("DONE.")


if __name__ == "__main__":
    main()
