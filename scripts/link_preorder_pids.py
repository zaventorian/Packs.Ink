"""
link_preorder_pids.py — fill in tcgplayer_product_id on cards that Lorcast has
indexed but NOT yet linked to a TCGPlayer SKU.

Why this exists
---------------
When a new set hits Lorcast (e.g. Set 13 "Attack of the Vine!"), the weekly
load_lorcast refresh pulls every card's metadata — name, version, rarity, art —
but Lorcast leaves `tcgplayer_id` NULL until much closer to release. TCGPlayer,
meanwhile, has had pre-order product pages (and prices) live for weeks, and our
daily TCGCSV ETL is already writing those pre-order prices into prices_daily.

The catalog never shows them because card_prices_latest is
`cards INNER JOIN prices_daily ON tcgplayer_product_id` — a NULL pid means no
join, no price, invisible card. This script bridges that gap by matching each
unlinked card to its TCGCSV product by collector number (validated by name) and
writing the pid into `cards`, so the matview JOIN fires and pre-order prices
flow through.

Safety invariants
-----------------
  * ONLY fills NULL pids — never overwrites an existing link (that's
    TCG_PID_OVERRIDES / patch_pid_overrides.py's job).
  * Requires the TCGCSV product name to match the card's "Name - Version"
    (normalized) before linking — guards against a mis-numbered SKU getting
    stapled to the wrong card.
  * Idempotent: re-running re-links nothing once pids are set. Safe to run on
    every weekly metadata refresh.

This is the generic, self-healing answer to "new set cards have no prices yet" —
it covers every current and future set automatically via sets.tcgplayer_group_id
(maintained by the daily TCGCSV ETL's update_set_group_mapping).

Usage:
    python scripts/link_preorder_pids.py            # dry run — prints proposed links
    python scripts/link_preorder_pids.py --commit   # apply + refresh matview
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
LORCANA_CATEGORY_ID = 71
USER_AGENT = "PacksInk/1.0 (+https://packs.ink) python-requests"


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


def _results(data: Any) -> list[dict]:
    return data.get("results") if isinstance(data, dict) and "results" in data else data


def _norm_name(s: str | None) -> str:
    """Lowercase, drop apostrophes, collapse whitespace. TCGCSV and Lorcast
    agree on the "Name - Version" shape but differ on stray punctuation/casing.
    TCGCSV also suffixes chase printings with " (Epic)"/"(Iconic)"/"(Enchanted)"
    which Lorcast never carries — strip it or no chase card ever passes the
    name check."""
    s = re.sub(r"\s*\((?:Iconic|Enchanted|Epic)\)\s*$", "", s or "", flags=re.I)
    s = s.lower().replace("’", "'").replace("'", "")
    return re.sub(r"\s+", " ", s).strip()


def _norm_cn(cn: str | None) -> str | None:
    """TCGCSV numbers come as "21/207"; Lorcast stores "21". Strip the set total
    and normalize numeric forms ("021" -> "21") while leaving non-numeric promo
    numbers (e.g. "P1-1") untouched."""
    if cn is None:
        return None
    cn = str(cn).split("/", 1)[0].strip()
    if not cn:
        return None
    return str(int(cn)) if cn.isdigit() else cn


def card_display_name(c: dict) -> str:
    name = c.get("name") or ""
    version = c.get("version")
    return f"{name} - {version}" if version else name


def build_tcgcsv_singles(group_id: int) -> dict[str, dict]:
    """collector_number -> {pid, name} for the SINGLES in a TCGCSV group.
    Sealed products (booster boxes/packs) carry no "Number" extendedData and
    are skipped."""
    prods = _results(get_json(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/{group_id}/products"))
    out: dict[str, dict] = {}
    for p in prods or []:
        num = None
        for ext in p.get("extendedData") or []:
            if ext.get("name") == "Number":
                num = ext.get("value")
                break
        cn = _norm_cn(num)
        if cn is None:
            continue  # sealed / numberless
        out[cn] = {"pid": p.get("productId"), "name": p.get("name") or ""}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="apply links (default is dry run)")
    ap.add_argument("--set", dest="set_id", default=None,
                    help="limit to one Lorcast set_id (default: every set with unlinked cards)")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    set_filters = {"tcgplayer_group_id": "not.is.null"}
    if args.set_id:
        set_filters["id"] = f"eq.{args.set_id}"
    sets = sb.select("sets", columns="id,code,name,tcgplayer_group_id", filters=set_filters)

    total_linked = 0
    total_unmatched = 0
    total_namemiss = 0

    for s in sorted(sets, key=lambda x: str(x.get("code") or "")):
        sid = s["id"]
        gid = s["tcgplayer_group_id"]
        unlinked = sb.select(
            "cards",
            columns="id,name,version,collector_number,tcgplayer_product_id",
            filters={"set_id": f"eq.{sid}", "tcgplayer_product_id": "is.null"},
        )
        if not unlinked:
            continue

        singles = build_tcgcsv_singles(gid)
        print(f"\n[{s.get('code')}] {s.get('name')}  (group {gid}) — "
              f"{len(unlinked)} unlinked card(s), {len(singles)} TCGCSV single(s)")

        for c in unlinked:
            cn = _norm_cn(c.get("collector_number"))
            disp = card_display_name(c)
            tp = singles.get(cn) if cn is not None else None
            if not tp:
                print(f"  .   no TCGCSV single for #{cn}: {disp}")
                total_unmatched += 1
                continue
            if _norm_name(tp["name"]) != _norm_name(disp):
                print(f"  !   name mismatch #{cn}: card='{disp}' vs tcg='{tp['name']}' -- skip")
                total_namemiss += 1
                continue
            pid = tp["pid"]
            print(f"  OK  #{cn:>4}  {disp}  ->  {pid}")
            total_linked += 1
            if args.commit:
                sb.update("cards", match={"id": c["id"]}, patch={"tcgplayer_product_id": pid})

    print(f"\n{'APPLIED' if args.commit else 'DRY RUN'} — "
          f"{total_linked} linkable, {total_unmatched} no-TCGCSV-product, "
          f"{total_namemiss} name-mismatch (skipped).")

    if args.commit and total_linked:
        print("\nRefreshing card_prices_latest matview...")
        try:
            sb.rpc("refresh_card_prices_latest")
            print("  matview refreshed.")
        except Exception as e:
            print(f"  refresh failed: {e}\n  → run `select public.refresh_card_prices_latest();` in the SQL editor.")

    print("\nDone.")


if __name__ == "__main__":
    main()
