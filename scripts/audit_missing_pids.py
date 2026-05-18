"""
audit_missing_pids.py — find cards in the DB with no tcgplayer_product_id and
match them against TCGCSV's product catalogs (Disney Lorcana Promo Cards,
D23 Promos, Disney100 Promos) by collector number + name.

Output: JS object literal you can paste into Index.html's TCG_PID_OVERRIDES.
Re-run any time Lorcast lags behind TCGPlayer on new promo SKUs.
"""
import os
import sys

import requests
from dotenv import load_dotenv

PROMO_GROUP_IDS = [23234, 17690, 23305]  # Lorcana Promo Cards, D23 Promos, Disney100 Promos
TCGCSV = "https://tcgcsv.com/tcgplayer"


def fetch_tcgcsv_products(group_id: int) -> list[dict]:
    r = requests.get(
        f"{TCGCSV}/71/{group_id}/products",
        headers={"User-Agent": "packs.ink-audit/1.0"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json().get("results", [])


def extended(p: dict, key: str) -> str | None:
    for e in p.get("extendedData") or []:
        if e.get("name") == key:
            return e.get("value")
    return None


def main() -> None:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    h = {"apikey": key, "Authorization": f"Bearer {key}"}

    print("Fetching DB cards with null tcgplayer_product_id...", file=sys.stderr)
    r = requests.get(
        f"{url}/rest/v1/cards?select=name,version,collector_number,set_id,tcgplayer_product_id"
        f"&tcgplayer_product_id=is.null",
        headers=h, timeout=30,
    )
    r.raise_for_status()
    missing = r.json()
    print(f"  {len(missing)} missing", file=sys.stderr)

    # Index missing cards by (name+version, collector_number).
    by_key: dict[tuple[str, str], dict] = {}
    for c in missing:
        full = (c["name"] + " - " + c["version"]) if c.get("version") else c["name"]
        by_key[(full.lower(), str(c.get("collector_number") or ""))] = c

    # Fetch promo products from TCGCSV; match by lower(name) + Number.
    matches: list[tuple[str, str, int, str]] = []  # (full_name, cn, pid, source_group)
    for gid in PROMO_GROUP_IDS:
        products = fetch_tcgcsv_products(gid)
        print(f"  group {gid}: {len(products)} products", file=sys.stderr)
        for p in products:
            cn = extended(p, "Number") or ""
            name = (p.get("name") or "").strip()
            key = (name.lower(), str(cn))
            if key in by_key:
                matches.append((name, cn, int(p["productId"]), str(gid)))

    # Print as JS object literal lines, sorted by collector_number then name.
    matches.sort(key=lambda m: (m[1], m[0]))
    print(f"\n// {len(matches)} matches — paste into TCG_PID_OVERRIDES:")
    for name, cn, pid, gid in matches:
        print(f'  "{name}|{cn}": {pid}, // group {gid}')

    # Cards still unmatched — surface so the user knows what's left to handcraft.
    matched_keys = {(m[0].lower(), m[1]) for m in matches}
    unmatched = [c for k, c in by_key.items() if k not in matched_keys]
    if unmatched:
        print(f"\n// {len(unmatched)} cards still without a TCGCSV match:", file=sys.stderr)
        for c in unmatched[:50]:
            full = (c["name"] + " - " + c["version"]) if c.get("version") else c["name"]
            print(f"//   {full}  cn {c.get('collector_number')}", file=sys.stderr)


if __name__ == "__main__":
    main()
