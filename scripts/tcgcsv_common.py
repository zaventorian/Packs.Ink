"""
Shared TCGCSV helpers — used by both the daily ETL and the historical backfill.
TCGCSV is a free mirror of TCGPlayer's catalog + price data. No auth, no key.
"""
from __future__ import annotations

from datetime import date
from typing import Iterable

TCGCSV_BASE = "https://tcgcsv.com/tcgplayer"
LORCANA_CATEGORY_ID = 71


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
