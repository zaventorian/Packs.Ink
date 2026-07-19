"""
load_sealed_products.py — pull TCGPlayer's product catalog for Lorcana from
TCGCSV and upsert anything that's NOT in our `cards` table into
`public.sealed_products`.

The catch: TCGPlayer's category 71 (Lorcana) contains booster boxes,
booster packs, starter decks, gift sets, Illumineer's Troves, Quest
products, plus a long tail of promos / oversized / errata singles that
Lorcast doesn't index. The daily ETL already pulls prices for all of
them — they just had nowhere to land. This loader populates the catalog
side so those orphan prices can finally surface in the UI.

Idempotent. Safe to re-run any time TCGPlayer adds a new product.

Usage:
    python load_sealed_products.py            # write to Supabase
    python load_sealed_products.py --dry-run  # print summary, no writes

What it does:
    1. Fetch all groups (sets) for category 71 → map name → set_id.
    2. Fetch existing cards.tcgplayer_product_id values from Supabase →
       set of "already a single, don't import as sealed".
    3. For each group, fetch /products. Skip anything in (2). Classify the
       rest by name heuristic. Upsert into sealed_products.

What it does NOT do:
    - Touch the `cards` table.
    - Pull prices (that's etl_tcgcsv_daily.py's job — already running).
    - Filter out genuine singles classified as 'Promo Single' / 'Other'.
      Those are still orphan products and worth tracking; the
      product_type column flags them so the UI can split sealed vs
      promo-single later.
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import Counter
from typing import Any

import requests
from dotenv import load_dotenv

from supabase_client import Supabase
from tcgcsv_common import LORCANA_CATEGORY_ID, TCGCSV_BASE


USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests sealed-loader"


def get_json(url: str) -> Any:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last_err = e
            if attempt == 2:
                break
            wait = 2 ** attempt
            print(f"  retry in {wait}s ({e})")
            time.sleep(wait)
    raise last_err  # type: ignore[misc]


def fetch_groups(category_id: int) -> list[dict]:
    data = get_json(f"{TCGCSV_BASE}/{category_id}/groups")
    # Explicit key-presence check: a valid empty response is {"results": []},
    # and `... or data` would wrongly fall through to the raw dict for that.
    return data.get("results") if isinstance(data, dict) and "results" in data else data


def fetch_group_products(category_id: int, group_id: int) -> list[dict]:
    data = get_json(f"{TCGCSV_BASE}/{category_id}/{group_id}/products")
    return data.get("results") if isinstance(data, dict) and "results" in data else data


# SKUs we don't want surfaced even though TCGCSV lists them. Substring match,
# case-insensitive. Add here when you spot a "not a real product" entry.
SKIP_NAME_PATTERNS = (
    "disney cruise promos",   # single SKU for a 5-card cruise giveaway; not a real shoppable product
    "gateway case",           # case-of-Gateways; we surface Gateway itself, ignore the case SKU
)


def classify(name: str) -> str:
    """Bucket a TCGPlayer product by name. Order matters — more specific
    matches first. 'Promo Single' is the catch-all for products that don't
    match any sealed-product naming pattern (usually genuine promo singles,
    oversized cards, errata reprints, or puzzle inserts)."""
    n = (name or "").lower()
    if "booster box" in n or "booster display" in n or "display box" in n:
        return "Booster Box"
    if "booster pack" in n:
        return "Booster Pack"
    if "starter deck" in n or "starter set" in n or "starter blister" in n:
        return "Starter Deck"
    if "gift set" in n or "gift box" in n:
        return "Gift Set"
    # Prerelease Packs are a recurring per-set SKU distinct from Troves —
    # bucket them on their own so the UI can surface "latest prerelease" as
    # a separate thing from "set's Illumineer's Trove".
    if "prerelease pack" in n:
        return "Prerelease Pack"
    if "trove" in n:
        return "Trove"
    # Illumineer's Quest products (Deep Trouble, etc.) come through as their
    # own SKUs with names containing "Quest" or specific Quest titles.
    if "quest" in n or "deep trouble" in n:
        return "Quest"
    if "collector's edition" in n or "collectors edition" in n:
        return "Collector's Edition"
    # Misc sealed bundle SKUs that don't fit a cleaner bucket — portfolio
    # bundles, collector set bundles, starter blister bundles, etc. Catches
    # things AFTER the specific buckets above so "Booster Pack Art Bundle"
    # still gets booked as a Booster Pack.
    if "bundle" in n:
        return "Bundle"
    # General "Sealed" catch-all for sealed product that doesn't fit any of
    # the canonical buckets above — Gateway (learn-to-play box), D23 Expo /
    # Collection sets (sealed multi-card promo sets), etc.
    if "gateway" in n or "d23 expo promo set" in n or "d23 collection" in n:
        return "Sealed"
    # Likely a single card we don't index — promo, oversized, errata, etc.
    return "Promo Single"


def build_group_to_setid(sb: Supabase, groups: list[dict]) -> dict[int, str]:
    """Match TCGCSV group names to sets.name and return groupId -> set_id."""
    sets_rows = sb.select("sets", columns="id,name,tcgplayer_group_id")
    by_name = {(s["name"] or "").lower(): s for s in sets_rows}
    out: dict[int, str] = {}
    for g in groups:
        gid = g.get("groupId")
        gname = (g.get("name") or "").strip()
        if not gid or not gname:
            continue
        candidates = {gname.lower()}
        if ":" in gname:
            candidates.add(gname.split(":", 1)[1].strip().lower())
        for c in candidates:
            row = by_name.get(c)
            if row:
                out[gid] = row["id"]
                break
    return out


def existing_card_pids(sb: Supabase) -> set[int]:
    """All tcgplayer_product_id values currently in `cards`. Anything in
    this set is a single we already track via Lorcast — skip it."""
    rows = sb.select("cards", columns="tcgplayer_product_id", order="tcgplayer_product_id.asc")
    return {r["tcgplayer_product_id"] for r in rows if r.get("tcgplayer_product_id") is not None}


def transform_product(p: dict, group_id: int, set_id: str | None) -> dict | None:
    pid = p.get("productId")
    if pid is None:
        return None
    name = (p.get("name") or "").strip()
    if not name:
        return None
    n = name.lower()
    if any(pat in n for pat in SKIP_NAME_PATTERNS):
        return None
    return {
        "tcgplayer_product_id": int(pid),
        "tcgplayer_group_id":   group_id,
        "set_id":               set_id,
        "name":                 name,
        "clean_name":           (p.get("cleanName") or "").strip() or None,
        "product_type":         classify(name),
        "image_url":            p.get("imageUrl") or None,
        "tcgplayer_url":        p.get("url") or None,
        "modified_on":          p.get("modifiedOn") or None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print summary and a sample. Do not write to Supabase.")
    ap.add_argument("--sample", type=int, default=20,
                    help="How many rows to show in the dry-run sample (default 20).")
    ap.add_argument("--skip-promo-singles", action="store_true",
                    help="Drop rows classified as 'Promo Single' before writing — genuine "
                         "sealed products only. This is the mode the daily ETL runs. Two "
                         "reasons it's the right default for an automated run: (1) the sealed "
                         "UI filters out product_type=='Promo Single' everywhere, so those "
                         "rows never surface in the tab anyway; (2) keeping those pids OUT of "
                         "sealed_products is exactly what lets reconcile_catalog.py still flag "
                         "them as missing singles — writing them here would blind that watchdog.")
    args = ap.parse_args()

    load_dotenv()
    sb = Supabase()

    print(f"Fetching TCGPlayer groups for categoryId {LORCANA_CATEGORY_ID}...")
    groups = fetch_groups(LORCANA_CATEGORY_ID)
    print(f"  {len(groups)} groups")

    print("Building groupId -> set_id map from public.sets...")
    group_to_setid = build_group_to_setid(sb, groups)
    print(f"  matched {len(group_to_setid)}/{len(groups)} groups")

    print("Loading existing card product IDs from public.cards...")
    known_card_pids = existing_card_pids(sb)
    print(f"  {len(known_card_pids)} cards have a tcgplayer_product_id")

    print("\nFetching products per group...")
    all_rows: list[dict] = []
    type_counts: Counter[str] = Counter()
    skipped_in_cards = 0

    for g in groups:
        gid = g.get("groupId")
        gname = g.get("name", str(gid))
        if gid is None:
            continue
        products = fetch_group_products(LORCANA_CATEGORY_ID, gid)
        kept = 0
        for p in products:
            pid = p.get("productId")
            if pid is None:
                continue
            if int(pid) in known_card_pids:
                skipped_in_cards += 1
                continue
            row = transform_product(p, gid, group_to_setid.get(gid))
            if row is None:
                continue
            all_rows.append(row)
            type_counts[row["product_type"]] += 1
            kept += 1
        print(f"  {gname:<48s}  {len(products):4d} products -> {kept:4d} sealed/orphan")

    print(f"\nTotal products skipped (already in cards): {skipped_in_cards}")
    print(f"Total products to upsert into sealed_products: {len(all_rows)}")
    print("\nBy classified type:")
    for t, n in type_counts.most_common():
        print(f"  {t:<22s}  {n}")

    if args.skip_promo_singles:
        before = len(all_rows)
        all_rows = [r for r in all_rows if r["product_type"] != "Promo Single"]
        dropped = before - len(all_rows)
        print(f"\n--skip-promo-singles: dropped {dropped} 'Promo Single' row(s) — hidden in "
              f"the UI and owned by the reconcile watchdog. {len(all_rows)} genuine sealed "
              f"product(s) to write.")

    if args.dry_run:
        print(f"\n--- DRY RUN — first {args.sample} rows ---")
        for row in all_rows[:args.sample]:
            print(f"  [{row['product_type']:<18s}] {row['tcgplayer_product_id']:>8d}  {row['name']}")
        print("\nDry run complete — no writes.")
        return

    if not all_rows:
        print("Nothing to upsert. Done.")
        return

    print(f"\nUpserting {len(all_rows)} rows...")
    sb.upsert("sealed_products", all_rows, on_conflict="tcgplayer_product_id")

    # Refresh the matview the sealed UI reads (sealed_products JOIN prices_daily)
    # so a newly-added product surfaces in the tab immediately instead of waiting
    # for the next prices ETL. Best-effort: if it transient-fails, the daily
    # prices refresh + the selfheal job will pick it up.
    try:
        print("Refreshing sealed_prices_latest matview...")
        sb.rpc("refresh_sealed_prices_latest")
    except Exception as e:  # noqa: BLE001 — non-fatal, next ETL heals it
        print(f"  (matview refresh failed, non-fatal: {e})")
    print("Done.")


if __name__ == "__main__":
    main()
