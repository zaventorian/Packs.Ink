"""
reconcile_catalog.py — daily watchdog that flags TCGPlayer products which are
priced but missing from our catalog, so new singles Lorcast hasn't indexed
(promos, Store-Championship cards, regional drops) don't sit invisible the way
Dash Parr - Lava Runner (52/P3) did for a month.

The structural gap
------------------
  prices_daily      = the SUPERSET of everything TCGPlayer sells (keyed by
                      tcgplayer_product_id). Populated daily by etl_tcgcsv_daily.
  cards             = only the SUBSET Lorcast indexes. Populated weekly by
                      load_lorcast. Lorcast lags/skips promos + SC cards.
  sealed_products   = absorbs known sealed + promo-single SKUs (load_sealed_products).

card_prices_latest is `cards INNER JOIN prices_daily`, so a pid that's priced
but in NEITHER cards NOR sealed_products is an *orphan* — and if it's a genuine
single, it's an invisible card. Nothing watched that gap before this script.

What it does
------------
  1. orphans = recently-priced pids − cards.pid − sealed_products.pid
  2. Looks each orphan up in the TCGCSV product catalog (full JSON, no
     truncation): name, group, collector Number, Rarity, image, url.
  3. Classifies each:
       CARD    — carries a collector Number (TCGCSV extendedData "Number") and
                 isn't a sealed-named SKU  → should become a real `cards` row.
       SEALED  — booster / box / case / trove / set / bundle / starter / etc.
                 → belongs in sealed_products (run load_sealed_products.py).
  4. Reports both buckets to stdout, the GitHub Step Summary, and an optional
     Discord-style webhook (env RECONCILE_ALERT_WEBHOOK). The CARD bucket is the
     actionable one — those are the invisible cards.

Why alert-only
--------------
It never writes to `cards`. Clearing the first backlog by hand showed every
case needs judgment that a blind insert would get wrong:
  - promo set-assignment is ambiguous (TCGCSV lumps Promo Set 1/2/3 in one
    group; we split them by collector-number range),
  - some "new" pids are the FOIL-companion SKU of a card that already exists and
    just needs a pid override, not a new row (e.g. Simba - Pride Protector #4),
  - if we stub a pid and Lorcast later indexes the card, load_lorcast would
    create a second row with the same pid → duplicate tiles.
Once a confident auto-insert path exists it can graduate to a --apply mode.

Exit code is 0 by default so a standing backlog doesn't spam the ETL with red
runs. Pass --fail-on-card-orphans to make CI go red (and email) while any
genuine missing single exists.

Usage
-----
    python scripts/reconcile_catalog.py                  # daily watchdog, exit 0
    python scripts/reconcile_catalog.py --days 30        # widen priced window
    python scripts/reconcile_catalog.py --audit-promo-singles   # deep periodic audit
    python scripts/reconcile_catalog.py --fail-on-card-orphans
    python scripts/reconcile_catalog.py --json out.json  # machine-readable dump
    python scripts/reconcile_catalog.py --pid 711071     # "do we have THIS product?"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase
from tcgcsv_common import LORCANA_CATEGORY_ID, TCGCSV_BASE

USER_AGENT = "PacksInk/1.0 (+https://packs.ink) reconcile-catalog"

# Windows consoles default to cp1252 and choke on the report's glyphs; GitHub
# Actions is already UTF-8. Force UTF-8 so a local run never crashes on output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    pass

# Name substrings that mark a TCGPlayer product as sealed/non-single even if it
# somehow carries a Number. Mirrors load_sealed_products.classify intent.
SEALED_NAME_HINTS = (
    "booster box", "booster pack", "booster display", "display box",
    "starter deck", "starter set", "starter blister", "gift set", "gift box",
    "prerelease pack", "trove", "quest", "deep trouble", "collector's edition",
    "collectors edition", "curator's collection", "curators collection",
    "bundle", "gateway", "case", "set of", "(set of",
    "d23 expo promo set", "d23 collection", "illumineer's trove",
)


def get_json(url: str) -> Any:
    last: Exception | None = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = e
            if attempt < 2:
                time.sleep(2 ** attempt)
    raise last  # type: ignore[misc]


def fetch_results(url: str) -> list[dict]:
    data = get_json(url)
    return data.get("results") if isinstance(data, dict) else data


def ext(product: dict, name: str) -> str | None:
    """Pull a value out of TCGCSV's extendedData list by its `name`."""
    for e in product.get("extendedData") or []:
        if (e.get("name") or "").lower() == name.lower():
            v = (e.get("value") or "").strip()
            return v or None
    return None


def looks_sealed(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in SEALED_NAME_HINTS)


def recent_priced_pids(sb: Supabase, days: int) -> set[int]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id",
        filters={"source": "eq.tcgcsv", "date": f"gte.{cutoff}"},
        order="tcgplayer_product_id.asc,date.asc",
    )
    return {r["tcgplayer_product_id"] for r in rows if r.get("tcgplayer_product_id") is not None}


def column_pids(sb: Supabase, table: str) -> set[int]:
    rows = sb.select(table, columns="tcgplayer_product_id", order="tcgplayer_product_id.asc")
    return {r["tcgplayer_product_id"] for r in rows if r.get("tcgplayer_product_id") is not None}


def resolved_sealed_pids(sb: Supabase, audit_promo_singles: bool = False) -> set[int]:
    """Sealed pids we treat as already handled (so they're not orphans).

    Default (daily watchdog): every sealed_products row counts as resolved, so
    the orphan set is the tight "priced but in NO catalog table" signal — that's
    what would have caught Dash Parr 52/P3 the day it appeared.

    With audit_promo_singles=True: EXCLUDE the 'Promo Single' bucket. That's
    load_sealed_products' catch-all for products Lorcast didn't index — a
    standing pile of ~150 that mixes genuinely-missing singles (new-set cards,
    Epic/promo chases, Cold-Foil companions) with deliberate exclusions
    (Illumineer's Quest cards, oversized jumbos, errata reprints). Re-surfacing
    them is a periodic cleanup, not a daily alert."""
    rows = sb.select("sealed_products", columns="tcgplayer_product_id,product_type",
                     order="tcgplayer_product_id.asc")
    out: set[int] = set()
    for r in rows:
        pid = r.get("tcgplayer_product_id")
        if pid is None:
            continue
        if audit_promo_singles and (r.get("product_type") or "") == "Promo Single":
            continue  # re-surface for review
        out.add(pid)
    return out


def latest_prices(sb: Supabase, pids: set[int], days: int) -> dict[int, dict]:
    """For the orphan pids, collect printings + the most recent market/low so
    the report can sort by value and show what each is worth."""
    if not pids:
        return {}
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out: dict[int, dict] = {}
    pid_list = sorted(pids)
    for i in range(0, len(pid_list), 200):  # keep the in.() URL bounded
        chunk = pid_list[i : i + 200]
        rows = sb.select(
            "prices_daily",
            columns="tcgplayer_product_id,printing,market_price,low_price,date",
            filters={
                "tcgplayer_product_id": f"in.({','.join(str(p) for p in chunk)})",
                "date": f"gte.{cutoff}",
            },
            order="tcgplayer_product_id.asc,date.asc",
        )
        for r in rows:
            pid = r["tcgplayer_product_id"]
            slot = out.setdefault(pid, {"printings": set(), "market": None, "low": None, "date": None})
            if r.get("printing"):
                slot["printings"].add(r["printing"])
            if r.get("date") and (slot["date"] is None or r["date"] >= slot["date"]):
                slot["date"] = r["date"]
                slot["market"] = r.get("market_price")
                slot["low"] = r.get("low_price")
    return out


def build_tcgcsv_index(orphans: set[int]) -> dict[int, dict]:
    """Map each orphan pid → {name, group, number, rarity, image, url}."""
    groups = fetch_results(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/groups")
    index: dict[int, dict] = {}
    for g in groups:
        gid = g.get("groupId")
        if gid is None:
            continue
        products = fetch_results(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/{gid}/products")
        for p in products:
            pid = p.get("productId")
            if pid in orphans:
                index[pid] = {
                    "name": (p.get("name") or "").strip(),
                    "group": g.get("name", str(gid)),
                    "number": ext(p, "Number"),
                    "rarity": ext(p, "Rarity"),
                    "image": p.get("imageUrl"),
                    "url": p.get("url"),
                }
    return index


def fmt_money(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14,
                    help="How many days back to consider a product 'actively priced' (default 14).")
    ap.add_argument("--fail-on-card-orphans", action="store_true",
                    help="Exit 1 (red CI / failure email) if any genuine missing single exists.")
    ap.add_argument("--audit-promo-singles", action="store_true",
                    help="Also re-surface the 'Promo Single' pile already in sealed_products "
                         "(periodic deep audit; off for the daily watchdog).")
    ap.add_argument("--json", dest="json_path", default=None,
                    help="Write the full structured report to this path.")
    ap.add_argument("--pid", action="append", default=None, metavar="ID",
                    help="Probe specific TCGPlayer product id(s) instead of running the sweep. "
                         "Repeatable, and accepts a comma-separated list. Exits 1 if any probed "
                         "product is in neither cards nor sealed_products.")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    if args.pid:
        pids = []
        for chunk in args.pid:
            for tok in str(chunk).replace(",", " ").split():
                pids.append(int(tok))
        return _probe_pids(sb, pids, args.days)

    print(f"Computing orphans (priced in last {args.days}d, not in cards or sealed_products)…")
    priced = recent_priced_pids(sb, args.days)
    card_pids = column_pids(sb, "cards")
    sealed_pids = resolved_sealed_pids(sb, audit_promo_singles=args.audit_promo_singles)
    orphans = priced - card_pids - sealed_pids
    print(f"  priced={len(priced)}  cards={len(card_pids)}  sealed={len(sealed_pids)}  orphans={len(orphans)}")

    if not orphans:
        print("\n✅ Catalog reconciled — every actively-priced product maps to a card or sealed row.")
        _write_summary([], [], args.days)
        return 0

    meta = build_tcgcsv_index(orphans)
    prices = latest_prices(sb, orphans, args.days)

    cards_bucket: list[dict] = []
    sealed_bucket: list[dict] = []
    for pid in orphans:
        m = meta.get(pid, {"name": f"(pid {pid} — not in TCGCSV catalog / delisted)",
                           "group": "?", "number": None, "rarity": None, "image": None, "url": None})
        pr = prices.get(pid, {})
        row = {
            "pid": pid,
            "name": m["name"],
            "group": m["group"],
            "number": m["number"],
            "rarity": m["rarity"],
            "printings": sorted(pr.get("printings", set())) if pr else [],
            "market": pr.get("market"),
            "low": pr.get("low"),
            "url": m["url"],
        }
        # A genuine single carries a collector Number and isn't a sealed-named SKU.
        is_card = bool(m["number"]) and not looks_sealed(m["name"])
        (cards_bucket if is_card else sealed_bucket).append(row)

    cards_bucket.sort(key=lambda r: (r["market"] is None, -(float(r["market"]) if r["market"] else 0)))
    sealed_bucket.sort(key=lambda r: r["name"])

    _print_report(cards_bucket, sealed_bucket, args.days)
    _write_summary(cards_bucket, sealed_bucket, args.days)
    _send_webhook(cards_bucket)

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"cards": cards_bucket, "sealed": sealed_bucket}, f, indent=2)
        print(f"\nWrote structured report → {args.json_path}")

    if args.fail_on_card_orphans and cards_bucket:
        print(f"\n--fail-on-card-orphans: {len(cards_bucket)} missing single(s) → exiting 1")
        return 1
    return 0


def _probe_pids(sb: Supabase, pids: list[int], days: int) -> int:
    """Answer "do we have this TCGPlayer product?" for specific pids.

    The sweep only sees pids priced in the last `days` and only reports the
    ones missing everywhere. This reports every probed pid either way, so a
    TCGPlayer link someone pastes can be checked in one command — including a
    brand-new SKU that has no price row yet, which the sweep can't see at all.
    """
    in_list = "in.(" + ",".join(str(p) for p in pids) + ")"
    by_card = {
        r["tcgplayer_product_id"]: r
        for r in sb.select("cards",
                           columns="id,name,version,collector_number,set_id,tcgplayer_product_id",
                           filters={"tcgplayer_product_id": in_list},
                           order="tcgplayer_product_id.asc")
    }
    by_sealed = {
        r["tcgplayer_product_id"]: r
        for r in sb.select("sealed_products",
                           columns="tcgplayer_product_id,name,product_type,set_id",
                           filters={"tcgplayer_product_id": in_list},
                           order="tcgplayer_product_id.asc")
    }
    meta = build_tcgcsv_index(set(pids))
    prices = latest_prices(sb, set(pids), days)

    missing = 0
    for pid in pids:
        m = meta.get(pid)
        pr = prices.get(pid) or {}
        card = by_card.get(pid)
        sealed = by_sealed.get(pid)
        print(f"\n{'='*70}\npid {pid}\n{'='*70}")
        if m:
            num = f"  #{m['number']}" if m.get("number") else ""
            print(f"  TCGCSV    {m['name']}{num}   [group: {m['group']}]")
            if m.get("url"):
                print(f"            {m['url']}")
        else:
            print("  TCGCSV    NOT in the Lorcana catalog (delisted, or a different category)")

        if card:
            disp = card["name"] + (f" - {card['version']}" if card.get("version") else "")
            print(f"  cards     ✅ {disp}  #{card.get('collector_number')}  set={card.get('set_id')}")
        else:
            print("  cards     —")

        if sealed:
            print(f"  sealed    ✅ [{sealed.get('product_type')}] {sealed.get('name')}  "
                  f"set={sealed.get('set_id') or 'NULL'}")
            if not sealed.get("set_id"):
                print("            ⚠ set_id NULL — the TCGCSV group didn't match a sets.name. "
                      "Add it to TCGCSV_GROUP_SET_ALIASES in scripts/tcgcsv_common.py.")
        else:
            print("  sealed    —")

        if pr:
            print(f"  prices    ✅ {pr.get('date')}  low={fmt_money(pr.get('low'))}  "
                  f"market={fmt_money(pr.get('market'))}  printings={sorted(pr.get('printings', set()))}")
        else:
            print(f"  prices    — nothing in prices_daily in the last {days}d")

        if card or sealed:
            print("  VERDICT   we have it.")
        else:
            missing += 1
            if not m:
                hint = "TCGCSV doesn't list it either — nothing to import"
            elif looks_sealed(m["name"]):
                hint = "run `python scripts/load_sealed_products.py --skip-promo-singles`"
            else:
                hint = ("it's a single — see reconcile's MISSING SINGLES flow "
                        "(load_lorcast / link_preorder_pids / patch_pid_overrides)")
            print(f"  VERDICT   ❌ MISSING from both cards and sealed_products → {hint}")

    print(f"\nProbed {len(pids)} product(s); {missing} missing.")
    return 1 if missing else 0


def _print_report(cards: list[dict], sealed: list[dict], days: int) -> None:
    print(f"\n{'='*70}\nCATALOG RECONCILE — {len(cards)} missing CARD(s), {len(sealed)} unsorted SEALED\n{'='*70}")
    if cards:
        print("\n⚠ MISSING SINGLES (priced on TCGPlayer, invisible on site):")
        for r in cards:
            num = f"#{r['number']}" if r["number"] else "#?"
            pr = "/".join(r["printings"]) or "?"
            print(f"  {r['pid']:>7}  {r['name']}  [{r['group']} {num} · {r['rarity']} · {pr}]"
                  f"  mkt {fmt_money(r['market'])}")
        print("\n  → Add each as a real `cards` row (clone art/stats from a base printing if one")
        print("    exists), then refresh card_prices_latest. Record durable entries in")
        print("    patch_pid_overrides.py (OVERRIDES for missing-pid cards, synthetic_cards for")
        print("    Lorcast-unindexed ones).")
    if sealed:
        print(f"\nℹ {len(sealed)} sealed/non-single orphan(s) → run `python scripts/load_sealed_products.py`:")
        for r in sealed[:12]:
            print(f"    {r['pid']:>7}  {r['name']}")
        if len(sealed) > 12:
            print(f"    … and {len(sealed) - 12} more")


def _write_summary(cards: list[dict], sealed: list[dict], days: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = [f"## Catalog reconcile ({days}d window)\n"]
    if not cards and not sealed:
        lines.append("✅ Every actively-priced product maps to a card or sealed row.\n")
    else:
        lines.append(f"- **{len(cards)}** missing single(s) — invisible cards\n")
        lines.append(f"- **{len(sealed)}** unsorted sealed orphan(s) — run `load_sealed_products.py`\n")
        if cards:
            lines.append("\n### Missing singles\n")
            lines.append("| pid | name | set | # | rarity | printing | market |\n|--|--|--|--|--|--|--|\n")
            for r in cards:
                lines.append(
                    f"| {r['pid']} | {r['name']} | {r['group']} | {r['number'] or '?'} | "
                    f"{r['rarity'] or '?'} | {'/'.join(r['printings']) or '?'} | {fmt_money(r['market'])} |\n"
                )
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        pass


def _send_webhook(cards: list[dict]) -> None:
    url = os.environ.get("RECONCILE_ALERT_WEBHOOK")
    if not url or not cards:
        return
    top = "\n".join(
        f"• {r['name']} ({r['group']} #{r['number'] or '?'}) — {fmt_money(r['market'])}  pid {r['pid']}"
        for r in cards[:15]
    )
    extra = f"\n…and {len(cards) - 15} more" if len(cards) > 15 else ""
    content = f"**Packs.Ink catalog reconcile** — {len(cards)} missing single(s) priced but invisible:\n{top}{extra}"
    try:
        requests.post(url, json={"content": content[:1900]}, timeout=30)
    except requests.RequestException as e:
        print(f"  (webhook post failed, non-fatal: {e})")


if __name__ == "__main__":
    raise SystemExit(main())
