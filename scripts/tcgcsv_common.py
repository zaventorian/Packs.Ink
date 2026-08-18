"""
Shared TCGCSV helpers — used by both the daily ETL and the historical backfill.
TCGCSV is a free mirror of TCGPlayer's catalog + price data. No auth, no key.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
LORCANA_CATEGORY_ID = 71

# TCGCSV group names usually differ from Lorcast set names only by the
# "Disney Lorcana: " prefix, so the post-colon form is enough to match them.
# A handful of promo groups are named nothing like the set they hold, and the
# consequences of an unmatched group are quiet but real:
#   * sets.tcgplayer_group_id stays NULL, and link_preorder_pids.py only walks
#     sets that HAVE one — so that set's new cards never get their pid linked
#     and sit priceless/invisible until Lorcast fills tcgplayer_id itself.
#   * every sealed product in the group lands with set_id NULL (no set pill,
#     sorts last in the Sealed tab).
# Key = normalized group name (lowercased, "Disney Lorcana:" prefix stripped),
# value = the exact sets.name it belongs to.
TCGCSV_GROUP_SET_ALIASES = {
    # TCGplayer files every D23 drop under one "D23 Promos" group — the 2024
    # singles (#1-9), the 2026 ones (#10-15), and the sealed D23 Collection
    # SKUs for both years. Lorcast calls the set "D23 Collection".
    "d23 promos": "D23 Collection",
}


def group_name_candidates(group_name: str) -> list[str]:
    """Lowercased sets.name candidates for a TCGCSV group name, best first.

    Order matters and is deliberate: an alias wins over the literal name,
    which wins over the post-colon form. (Both call sites used to build an
    unordered set here, so which candidate matched was arbitrary.)
    """
    raw = (group_name or "").strip()
    out: list[str] = []

    def add(v: str) -> None:
        v = " ".join(v.split()).lower()
        if v and v not in out:
            out.append(v)

    add(raw)
    if ":" in raw:
        add(raw.split(":", 1)[1])
    for c in list(out):
        alias = TCGCSV_GROUP_SET_ALIASES.get(c)
        if alias:
            out.insert(0, alias.strip().lower())
            break
    return out



def parse_price(v) -> float | None:
    """TCGCSV returns 0 / null for missing prices. Normalize both to None so
    the DB stores NULL rather than a misleading $0.00."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= 0:
        return None
    return f


def transform_price_row(p: dict, snapshot_date: date) -> dict | None:
    """Convert a raw TCGCSV price entry into a prices_daily row.

    A single TCGCSV product can have multiple price entries — one per
    subTypeName ('Normal', 'Foil', 'Cold Foil'). We emit one row per entry.
    """
    pid = p.get("productId")
    if pid is None:
        return None
    printing = p.get("subTypeName") or "Normal"
    low = parse_price(p.get("lowPrice"))
    mid = parse_price(p.get("midPrice"))
    market = parse_price(p.get("marketPrice"))
    high = parse_price(p.get("highPrice"))
    direct_low = parse_price(p.get("directLowPrice"))

    # Skip rows with no actual price signal at all.
    if all(x is None for x in (low, mid, market, high, direct_low)):
        return None

    return {
        "tcgplayer_product_id": int(pid),
        "date": snapshot_date.isoformat(),
        "printing": printing,
        "source": "tcgcsv",
        "grade": "raw",
        "low_price": low,
        "mid_price": mid,
        "market_price": market,
        "high_price": high,
        "direct_low_price": direct_low,
    }


def transform_price_rows(
    raw_prices: Iterable[dict], snapshot_date: date
) -> list[dict]:
    out: list[dict] = []
    for p in raw_prices:
        row = transform_price_row(p, snapshot_date)
        if row is not None:
            out.append(row)
    return out
