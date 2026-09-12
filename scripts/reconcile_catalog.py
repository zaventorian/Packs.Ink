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

The --watch mode (what CI runs)
-------------------------------
The sweep above only sees pids that have a PRICE, which structurally misses the
things that hurt most: a product listed weeks before release (a new Quest set,
next set's boxes), a whole new TCGCSV group nobody bound to a set, a card row
with no pid that therefore can never price. --watch adds those checks and, more
importantly, gives the result somewhere to go.

Before --watch existed this script ran green every day with 18 genuinely missing
singles in its output, because it exited 0 and wrote to a Step Summary nobody
opens. An alert with no delivery is not an alert.

    findings = everything wrong  −  everything acknowledged
    exit 1 if any remain  →  red run  →  GitHub failure email

Acknowledgements live in scripts/catalog_watch.json, each with a reason and
an optional `until` date that makes it expire and re-alert. That is what keeps
the noise floor at zero: a standing backlog is acknowledged once, with a stated
decision, instead of being re-reported forever until everyone stops looking.

Scheduled reviews
-----------------
The checks above all read a machine-readable feed. Some of the catalog does not
have one — Japan Core legality comes from a Japanese retailer's HTML, the pin
and lore-counter lists come from a fan site, next set's spoilers come from press
releases. Nothing can watch those, so the same file carries a `reviews` list:
each one becomes a finding on its due date and rides the same red run and the
same email. `--done <id>` rolls it forward.

That is the difference between a reminder and a note somebody wrote down once.

Usage
-----
    python scripts/reconcile_catalog.py --watch            # CI: red on anything new
    python scripts/reconcile_catalog.py --watch --no-fail  # same report, always exit 0
    python scripts/reconcile_catalog.py --ack missing_single:711520 --why "..."
    python scripts/reconcile_catalog.py --ack unbound_group:24740 --why "..." --until 2026-10-17
    python scripts/reconcile_catalog.py                  # legacy priced-orphan sweep, exit 0
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
import re
import sys
import time
from datetime import date, timedelta
from typing import Any

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase
from tcgcsv_common import LORCANA_CATEGORY_ID, TCGCSV_BASE
# The loader's own "not a real product" list, imported rather than restated so
# a deliberate exclusion can't come back as a watch finding. Adding a pattern
# there silences it here in the same commit.
from load_sealed_products import SKIP_NAME_PATTERNS as LOADER_SKIP_PATTERNS
# Same name-matching rules link_preorder_pids uses to bind a SKU to a card.
# Imported, never re-implemented: two normalizers that drift produce a
# classifier that disagrees with the linker about what matches what.
from link_preorder_pids import _norm_name as norm_name

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


ACK_PATH = os.path.join(os.path.dirname(__file__), "catalog_watch.json")

# `sealed_no_set` deliberately skips this bucket. 'Promo Single' is
# load_sealed_products' catch-all for products that map to no set by
# construction — the rows are hidden in the UI and a null set_id on them is the
# expected state, not a defect. 113 of the 121 null-set rows are these.
SEALED_NO_SET_SKIP_TYPES = {"Promo Single"}
# `card_no_pid` skips Format Coconut for the same reason: its leaders are static
# synthetic rows, not TCGplayer products, so they can never carry a pid.
CARD_NO_PID_SKIP_SETS = {"Format Coconut"}


def load_ack(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"acks": {}, "rules": [], "reviews": []}
    except json.JSONDecodeError as e:
        # A broken ack file must not silently un-acknowledge everything and
        # bury a real finding under a hundred old ones.
        raise SystemExit(f"catalog_watch.json is not valid JSON: {e}")
    data.setdefault("acks", {})
    data.setdefault("rules", [])
    data.setdefault("reviews", [])
    return data


def ack_reason(ack: dict, kind: str, key: str, name: str, today: str) -> str | None:
    """Why this finding is covered, or None if it is not.

    An `until` date expires the acknowledgement, so "revisit when Q3 actually
    releases" is a thing the file can express instead of a promise someone has
    to remember.
    """
    entry = ack["acks"].get(f"{kind}:{key}")
    if entry is not None:
        until = entry.get("until")
        if until and until < today:
            return None  # lapsed — re-alert
        return entry.get("why") or "(no reason recorded)"
    for rule in ack["rules"]:
        if rule.get("kind") and rule["kind"] != kind:
            continue
        pat = rule.get("name_matches")
        if pat and re.search(pat, name or ""):
            until = rule.get("until")
            if until and until < today:
                return None
            return rule.get("why") or "(no reason recorded)"
    return None


def save_ack(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def due_reviews(ack: dict, today: str) -> list[dict]:
    """Scheduled reviews whose due date has arrived.

    Not gated by `acks` at all — a review is "acknowledged" exactly when its
    `due` is still in the future, so the only way to silence one is to do it
    (--done) or to deliberately push its date out.
    """
    out = []
    for rv in ack.get("reviews", []):
        due = rv.get("due")
        if not due or due > today:
            continue
        out.append({
            "kind": "review_due",
            "key": rv.get("id") or "?",
            "name": rv.get("what") or rv.get("id") or "?",
            "detail": f"due {due}" + (f" · last done {rv['last_done']}" if rv.get("last_done") else " · never done"),
            "hint": rv.get("how") or "no steps recorded",
            "why": rv.get("why") or "",
        })
    return out


def fetch_all_products() -> tuple[list[dict], dict[int, dict]]:
    """Every TCGCSV group and every product in it, keyed by pid.

    build_tcgcsv_index already downloaded all of this and threw away everything
    that wasn't a priced orphan, so widening the sweep to unpriced products
    costs no extra requests — just the ones we were already discarding.
    """
    groups = fetch_results(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/groups")
    index: dict[int, dict] = {}
    for g in groups:
        gid = g.get("groupId")
        if gid is None:
            continue
        for prod in fetch_results(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/{gid}/products"):
            pid = prod.get("productId")
            if pid is None:
                continue
            index[pid] = {
                "name": (prod.get("name") or "").strip(),
                "group": g.get("name", str(gid)),
                "group_id": gid,
                "number": ext(prod, "Number"),
                "rarity": ext(prod, "Rarity"),
                "url": prod.get("url"),
            }
    return groups, index


# ── Promo printings ──────────────────────────────────────────────────────────
# Most of what the promo groups ever produce is a second printing of a card we
# already hold, and recognising that is nearly all of the work of filing one.
# TCGplayer names such a product after the card and puts the promo's identity in
# a trailing bracket: "Rapunzel - Escaping the Tower (Store Championship)".
_TRAILING_PAREN_RE = re.compile(r"\s*\([^()]*\)\s*$")


def promo_base_candidates(name: str) -> list[str]:
    """Names to try when asking "is this a promo printing of a card we hold?".

    The full name first — plenty of promo SKUs carry no bracket at all (Morph -
    Little Imitator) — then the name with ONE trailing bracket removed. Only
    one: stripping repeatedly would eat a genuinely parenthesised version.
    """
    name = (name or "").strip()
    if not name:
        return []
    out = [name]
    stripped = _TRAILING_PAREN_RE.sub("", name).strip()
    if stripped and stripped != name:
        out.append(stripped)
    return out


def promo_suffix_of(name: str) -> str | None:
    """The bracketed text — what says WHICH promo this is (Store Championship,
    Store Championship Participant, Magical Places Promo, Foil, …)."""
    m = re.search(r"\(([^()]*)\)\s*$", name or "")
    return (m.group(1).strip() or None) if m else None


def classify_promo_printing(name: str, cards_by_name: dict) -> dict | None:
    """Resolve a missing single to the card it is a promo printing OF.

    Returns {matched, suffix, base:[rows]} or None when we have no opinion.
    Deliberately makes no guess when the name matches several cards (a card
    printed in two sets has no single base row to clone) — it still reports
    them, because "which of these two" is a far cheaper question than "what
    even is this".
    """
    for cand in promo_base_candidates(name):
        rows = cards_by_name.get(norm_name(cand))
        if rows:
            return {"matched": cand, "suffix": promo_suffix_of(name), "base": rows}
    return None


def promo_printing_hint(pid, info: dict, set_name: dict) -> str:
    """The finding's hint, as a line you can nearly paste.

    Everything in a REPRINT_PROMOS entry is derivable except the PRINTED
    collector number, and that one is a trap worth spelling out every time:
    TCGplayer's promo groups hold several unrelated numbering series at once,
    so the group's own number is routinely not the number on the card.
    """
    rows = info["base"]
    suffix = info["suffix"]
    what = f'promo printing of "{info["matched"]}"'
    if suffix:
        what += f' — {suffix}'
    if len(rows) > 1:
        where = "; ".join(
            f'{set_name.get(r.get("set_id"), r.get("set_id"))} #{r.get("collector_number")}'
            f' (pid {r.get("tcgplayer_product_id")})' for r in rows[:4])
        return (f'{what}. Matches {len(rows)} cards we hold — pick the base: {where}. '
                f'Then add a REPRINT_PROMOS entry in scripts/patch_pid_overrides.py.')
    r = rows[0]
    base_pid = r.get("tcgplayer_product_id")
    sname = set_name.get(r.get("set_id"), r.get("set_id"))
    return (
        f'{what}, i.e. {sname} #{r.get("collector_number")} (base pid {base_pid}). '
        f'Add to REPRINT_PROMOS in scripts/patch_pid_overrides.py:  '
        f'({base_pid}, <PROMO_SET>, "<printed cn>", "crd_<slug>_{pid}", {pid})  '
        f'— read the printed collector number AND ITS SERIES off the card art at '
        f'https://tcgplayer-cdn.tcgplayer.com/product/{pid}_400w.jpg . One TCGplayer '
        f'promo group holds several series at once (P4 league/buy-a-box, PD1 '
        f'prerelease, DIS Disney Parks, C2 Challenge), so a bare number never '
        f'identifies a card: 4/PD1 and 4/DIS are different cards, and this group\'s '
        f'#15/#16 are BOTH the C2 Challenge cards and the P4 Rapunzel pair.'
    )


def collect_findings(sb: Supabase, ack: dict | None = None, today: str | None = None) -> list[dict]:
    """Everything the catalog is missing or hasn't wired up, as flat findings."""
    groups, products = fetch_all_products()
    card_pids = column_pids(sb, "cards")
    sealed_rows = sb.select("sealed_products",
                            columns="tcgplayer_product_id,name,product_type,set_id",
                            order="tcgplayer_product_id.asc")
    sealed_pids = {r["tcgplayer_product_id"] for r in sealed_rows
                   if r.get("tcgplayer_product_id") is not None}
    sets_rows = sb.select("sets", columns="id,name,tcgplayer_group_id", order="id.asc")
    set_name = {r["id"]: r.get("name") or r["id"] for r in sets_rows}
    # Name -> the cards we already hold under it, so a missing single can be
    # recognised as a promo PRINTING of one rather than reported as an unknown.
    cards_by_name: dict[str, list[dict]] = {}
    for r in sb.select("cards",
                       columns="name,version,collector_number,set_id,tcgplayer_product_id",
                       order="set_id.asc"):
        disp = (r.get("name") or "") + (f" - {r['version']}" if r.get("version") else "")
        cards_by_name.setdefault(norm_name(disp), []).append(r)
    bound_groups = {r["tcgplayer_group_id"] for r in sets_rows
                    if r.get("tcgplayer_group_id") is not None}

    out: list[dict] = []

    # 1/2. TCGplayer sells it; we have it in neither table. Unlike the legacy
    #      sweep this includes products with no price row yet, which is exactly
    #      how a set announces itself weeks before release.
    for pid, m in products.items():
        if pid in card_pids or pid in sealed_pids:
            continue
        low = m["name"].lower()
        if any(pat in low for pat in LOADER_SKIP_PATTERNS):
            continue  # load_sealed_products drops it on purpose
        is_card = bool(m["number"]) and not looks_sealed(m["name"])
        promo = classify_promo_printing(m["name"], cards_by_name) if is_card else None
        if promo:
            hint = promo_printing_hint(pid, promo, set_name)
        elif is_card:
            hint = "add a `cards` row (see MISSING SINGLES flow)"
        else:
            hint = "run `python scripts/load_sealed_products.py --skip-promo-singles`"
        out.append({
            "kind": "missing_single" if is_card else "missing_sealed",
            "key": str(pid),
            "name": m["name"],
            "detail": f"{m['group']} #{m['number'] or '?'} · {m['rarity'] or '—'}",
            "hint": hint,
        })

    # 3. A TCGCSV group nothing points at. A brand-new set or Quest shows up
    #    here first — before a single card of it is listed or priced.
    for g in groups:
        gid = g.get("groupId")
        if gid is None or gid in bound_groups:
            continue
        out.append({
            "kind": "unbound_group", "key": str(gid), "name": g.get("name") or str(gid),
            "detail": f"published {(g.get('publishedOn') or '?')[:10]}",
            "hint": "create the `sets` row and set tcgplayer_group_id, or add a "
                    "TCGCSV_GROUP_SET_ALIASES entry in scripts/tcgcsv_common.py",
        })

    # 4. Sealed product loaded but unbound, so it renders under "Other / Promo"
    #    instead of its own set section.
    for r in sealed_rows:
        if r.get("set_id") or (r.get("product_type") or "") in SEALED_NO_SET_SKIP_TYPES:
            continue
        out.append({
            "kind": "sealed_no_set", "key": str(r.get("tcgplayer_product_id")),
            "name": r.get("name") or "", "detail": r.get("product_type") or "—",
            "hint": "bind its TCGCSV group to a set, then re-run load_sealed_products.py",
        })

    # 5. card_prices_latest is an INNER JOIN on the pid, so a null one means the
    #    card can never show a price no matter how well TCGplayer lists it.
    for r in sb.select("cards", columns="name,version,collector_number,set_id,tcgplayer_product_id",
                       filters={"tcgplayer_product_id": "is.null"}, order="set_id.asc"):
        sname = set_name.get(r.get("set_id"), r.get("set_id") or "?")
        if sname in CARD_NO_PID_SKIP_SETS:
            continue
        disp = r["name"] + (f" - {r['version']}" if r.get("version") else "")
        out.append({
            "kind": "card_no_pid", "key": f"{sname}|{r.get('collector_number')}",
            "name": disp, "detail": f"{sname} #{r.get('collector_number')}",
            "hint": "find its pid on TCGplayer and add it to TCG_PID_OVERRIDES, "
                    "then run scripts/patch_pid_overrides.py",
        })

    # 6. Lorcast published a set we never created.
    try:
        for st in fetch_results("https://api.lorcast.com/v0/sets"):
            if st.get("id") and st["id"] not in set_name:
                out.append({
                    "kind": "missing_set", "key": st["id"],
                    "name": st.get("name") or st["id"],
                    "detail": f"code {st.get('code')} · released {st.get('released_at')}",
                    "hint": "run scripts/load_lorcast.py to create the set + its cards",
                })
    except Exception as e:  # Lorcast down must not fail the whole watch
        print(f"  (Lorcast set check skipped, non-fatal: {e})")

    if ack is not None:
        out.extend(due_reviews(ack, today or date.today().isoformat()))

    out.sort(key=lambda f: (f["kind"], f["name"]))
    return out


KIND_LABEL = {
    "missing_single": "Missing single (TCGplayer sells it, we don't list it)",
    "missing_sealed": "Missing sealed product",
    "unbound_group":  "TCGplayer group bound to no set",
    "sealed_no_set":  "Sealed product with no set",
    "card_no_pid":    "Card with no TCGplayer id (can never price)",
    "missing_set":    "Lorcast set we don't have",
    "review_due":     "Scheduled review (no feed watches this — a person has to look)",
}


def run_watch(sb: Supabase, fail: bool, json_path: str | None) -> int:
    today = date.today().isoformat()
    ack = load_ack(ACK_PATH)
    findings = collect_findings(sb, ack, today)
    fresh = [f for f in findings
             if f["kind"] == "review_due"
             or ack_reason(ack, f["kind"], f["key"], f["name"], today) is None]
    known = len(findings) - len(fresh)

    print(f"\n{'='*72}")
    print(f"CATALOG WATCH — {len(fresh)} new, {known} acknowledged")
    print("=" * 72)

    if not fresh:
        print("\n✅ Nothing new. Every gap in the catalog is one we've already ruled on.")
    else:
        by_kind: dict[str, list[dict]] = {}
        for f in fresh:
            by_kind.setdefault(f["kind"], []).append(f)
        for kind, items in by_kind.items():
            print(f"\n▶ {KIND_LABEL.get(kind, kind)}  ({len(items)})")
            if kind == "review_due":
                # A review's whole value is that the steps travel with the
                # alert — nobody is going to go dig up how to do it.
                for f in items:
                    print(f"\n    {f['key']}   [{f['detail']}]")
                    print(f"      {f['name']}")
                    if f.get("why"):
                        print(f"      why:  {f['why']}")
                    for i, line in enumerate(str(f["hint"]).split("\n")):
                        print(("      how:  " if i == 0 else "            ") + line)
                    print(f"      done: python scripts/reconcile_catalog.py --done {f['key']} "
                          f"--next YYYY-MM-DD")
                continue
            for f in items:
                print(f"    {f['kind']}:{f['key']}")
                print(f"      {f['name']}   [{f['detail']}]")
            print(f"    → {items[0]['hint']}")
        gap = next((f for f in fresh if f["kind"] != "review_due"), None)
        if gap:
            print("\nEither fix it, or record the decision so it stops asking:")
            print(f"    python scripts/reconcile_catalog.py --ack {gap['kind']}:{gap['key']} "
                  f'--why "why this is fine" [--until YYYY-MM-DD]')

    _write_watch_summary(fresh, known)
    _send_watch_webhook(fresh)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"new": fresh, "acknowledged": known}, f, indent=2)
        print(f"\nWrote structured report → {json_path}")

    if fresh and fail:
        print(f"\n{len(fresh)} unacknowledged finding(s) → exiting 1 so the run goes red.")
        return 1
    return 0


def _write_watch_summary(fresh: list[dict], known: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Catalog watch\n\n"]
    if not fresh:
        lines.append(f"✅ Nothing new. {known} known gap(s) already acknowledged.\n")
    else:
        lines.append(f"**{len(fresh)} new finding(s)**, {known} acknowledged.\n\n")
        lines.append("| key | what | where |\n|--|--|--|\n")
        for f in fresh:
            lines.append(f"| `{f['kind']}:{f['key']}` | {f['name']} | {f['detail']} |\n")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        pass


def _send_watch_webhook(fresh: list[dict]) -> None:
    url = os.environ.get("RECONCILE_ALERT_WEBHOOK")
    if not url or not fresh:
        return
    top = "\n".join(f"• [{f['kind']}] {f['name']} — {f['detail']}" for f in fresh[:15])
    extra = f"\n…and {len(fresh) - 15} more" if len(fresh) > 15 else ""
    try:
        requests.post(url, json={"content":
            f"**Packs.Ink catalog watch** — {len(fresh)} new gap(s):\n{top}{extra}"[:1900]}, timeout=30)
    except requests.RequestException as e:
        print(f"  (webhook post failed, non-fatal: {e})")


# An acknowledgement is one of exactly two things, and the file has to say
# which: a PERMANENT one ("this null is the correct steady state" — a JP
# exclusive with no SKU, a promo group no single set can own), or a DEFERRAL
# ("not now"). A deferral with no expiry is how a found problem goes quiet:
# the Rapunzel Store Championship pair was acked on 2026-09-05 with no `until`
# and would have stayed silent indefinitely, having been found the day it was
# listed. So a deferral always gets one, and this is the default.
DEFAULT_ACK_DAYS = 30


def run_ack(key: str, why: str | None, until: str | None, permanent: bool = False) -> int:
    if ":" not in key:
        print(f"Key must look like kind:id, e.g. missing_single:711520 (got {key!r})")
        return 2
    kind = key.split(":", 1)[0]
    if kind not in KIND_LABEL:
        print(f"Unknown kind {kind!r}. One of: {', '.join(sorted(KIND_LABEL))}")
        return 2
    if not why or not why.strip():
        print("--why is required. This file is a decision record; an entry with no "
              "reason is indistinguishable from hiding the problem.")
        return 2
    if until:
        try:
            date.fromisoformat(until)
        except ValueError:
            print(f"--until must be YYYY-MM-DD (got {until!r})")
            return 2
    if permanent and until:
        print("--permanent and --until contradict each other. --permanent means this "
              "finding's current state is CORRECT and should never re-alert; --until "
              "means come back to it. Pick one.")
        return 2
    if not permanent and not until:
        until = (date.today() + timedelta(days=DEFAULT_ACK_DAYS)).isoformat()
        defaulted = True
    else:
        defaulted = False
    ack = load_ack(ACK_PATH)
    entry = {"why": why.strip(), "added": date.today().isoformat()}
    if until:
        entry["until"] = until
    ack["acks"][key] = entry
    save_ack(ACK_PATH, ack)
    if permanent:
        print(f"Acknowledged {key} PERMANENTLY (never re-alerts)")
    else:
        print(f"Acknowledged {key} until {until}"
              + (f" (defaulted to {DEFAULT_ACK_DAYS} days — pass --until to choose, "
                 "or --permanent if this state is correct forever)" if defaulted else ""))
    print(f"  {why.strip()}")
    print("Commit scripts/catalog_watch.json so CI picks it up.")
    return 0


def run_done(review_id: str, next_due: str | None) -> int:
    ack = load_ack(ACK_PATH)
    reviews = ack.get("reviews", [])
    rv = next((r for r in reviews if r.get("id") == review_id), None)
    if rv is None:
        print(f"No review with id {review_id!r}. Known: "
              f"{', '.join(r.get('id', '?') for r in reviews) or '(none)'}")
        return 2
    today = date.today()
    if next_due:
        try:
            date.fromisoformat(next_due)
        except ValueError:
            print(f"--next must be YYYY-MM-DD (got {next_due!r})")
            return 2
        nxt = next_due
    else:
        every = rv.get("every_days")
        if not every:
            print(f"{review_id} has no `every_days`, so --next is required "
                  "(these are keyed to set releases, not a fixed cadence).")
            return 2
        nxt = (today + timedelta(days=int(every))).isoformat()
    rv["last_done"] = today.isoformat()
    rv["due"] = nxt
    save_ack(ACK_PATH, ack)
    print(f"{review_id} marked done today; next due {nxt}.")
    print("Commit scripts/catalog_watch.json so CI picks it up.")
    return 0


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
    ap.add_argument("--watch", action="store_true",
                    help="Widened sweep (unpriced products, unbound groups, null pids, new "
                         "Lorcast sets) filtered through catalog_watch.json. Exits 1 on "
                         "anything unacknowledged — this is what CI runs.")
    ap.add_argument("--no-fail", action="store_true",
                    help="With --watch: print the report but always exit 0.")
    ap.add_argument("--ack", default=None, metavar="KIND:ID",
                    help="Record an acknowledgement for one finding and exit.")
    ap.add_argument("--done", default=None, metavar="REVIEW_ID",
                    help="Mark a scheduled review done and roll it forward.")
    ap.add_argument("--next", dest="next_due", default=None, metavar="YYYY-MM-DD",
                    help="With --done: when it is due again (defaults to every_days).")
    ap.add_argument("--why", default=None,
                    help="Required with --ack: why this finding is acceptable.")
    ap.add_argument("--permanent", action="store_true",
                    help="This finding's current state is CORRECT and must never re-alert "
                         "(a regional card with no SKU, a promo group no set can own). "
                         "Without it, and without --until, an ack expires in "
                         f"{DEFAULT_ACK_DAYS} days so a deferral cannot go silent.")
    ap.add_argument("--until", default=None, metavar="YYYY-MM-DD",
                    help="With --ack: expire the acknowledgement on this date so it re-alerts.")
    ap.add_argument("--pid", action="append", default=None, metavar="ID",
                    help="Probe specific TCGPlayer product id(s) instead of running the sweep. "
                         "Repeatable, and accepts a comma-separated list. Exits 1 if any probed "
                         "product is in neither cards nor sealed_products.")
    args = ap.parse_args()

    if args.ack:
        return run_ack(args.ack, args.why, args.until, args.permanent)

    if args.done:
        return run_done(args.done, args.next_due)

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    if args.watch:
        return run_watch(sb, fail=not args.no_fail, json_path=args.json_path)

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
