#!/usr/bin/env python3
"""
Load Near Mint weekly sales rows from the bulk capture into
public.tcgplayer_sales_weekly (created by migration 70).

Maps tcgplayer_product_id -> cards.id (prefers non-custom id on the few
pids that map to multiple card rows). Sale-price fields are nulled on
zero-sale weeks (TCGplayer reports "0" as a no-data sentinel); market_price
is kept (it's carried forward).

Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from scripts/.env.

Usage:
  python scripts/tcg_sales/load_to_supabase.py
  python scripts/tcg_sales/load_to_supabase.py --condition "Near Mint" --batch 2000
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
# .env lives at scripts/.env (parent of this dir); fall back to local dir.
ENV_CANDIDATES = [
    os.path.join(os.path.dirname(HERE), ".env"),
    os.path.join(HERE, ".env"),
]
TABLE = "tcgplayer_sales_weekly"


def load_env():
    env = {}
    for path in ENV_CANDIDATES:
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            if k.startswith("export "):
                k = k[len("export "):].strip()
            env[k] = v.strip().strip('"').strip("'")
        break
    env.setdefault("SUPABASE_URL", os.environ.get("SUPABASE_URL", ""))
    env.setdefault("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_KEY", ""))
    return env


def num(x):
    if x is None:
        return None
    s = str(x).strip()
    if s == "" :
        return None
    try:
        f = float(s)
    except ValueError:
        return None
    return f


def fetch_pid_to_cardid(url, key):
    """Paginate cards; prefer non-custom card id when a pid maps to several."""
    out = {}
    page, offset = 1000, 0
    base = f"{url}/rest/v1/cards?" + urllib.parse.urlencode({
        "select": "id,tcgplayer_product_id",
        "tcgplayer_product_id": "not.is.null",
        "order": "tcgplayer_product_id.asc",
    })
    while True:
        req = urllib.request.Request(base, headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Range-Unit": "items", "Range": f"{offset}-{offset+page-1}",
        })
        with urllib.request.urlopen(req, timeout=60) as r:
            rows = json.loads(r.read().decode())
        if not rows:
            break
        for row in rows:
            pid = row["tcgplayer_product_id"]
            cid = row["id"]
            cur = out.get(pid)
            if cur is None:
                out[pid] = cid
            else:
                # prefer the non-custom id
                if cur.startswith("crd_custom") and not cid.startswith("crd_custom"):
                    out[pid] = cid
        if len(rows) < page:
            break
        offset += page
    return out


def upsert(url, key, rows, retries=4):
    body = json.dumps(rows).encode()
    endpoint = f"{url}/rest/v1/{TABLE}"
    last = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(endpoint, data=body, method="POST", headers={
                "apikey": key, "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,return=minimal",
            })
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.status
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:300]
            except Exception:
                pass
            last = f"HTTP {e.code} {detail}"
            if e.code < 500 and e.code != 429:
                raise RuntimeError(last)  # non-retryable (e.g. 400 bad row)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            import time
            time.sleep(min(2 ** attempt, 15))
    raise RuntimeError(f"upsert failed after {retries} tries: {last}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--infile", default=os.path.join(HERE, "out", "tcgplayer_sales.jsonl"))
    ap.add_argument("--condition", default="Near Mint")
    ap.add_argument("--batch", type=int, default=2000)
    args = ap.parse_args()

    env = load_env()
    url, key = env["SUPABASE_URL"], env["SUPABASE_SERVICE_KEY"]
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY missing"); sys.exit(1)

    print("Building pid -> card_id map from cards ...", flush=True)
    pid2cid = fetch_pid_to_cardid(url, key)
    print(f"  {len(pid2cid)} pids mapped.", flush=True)

    print(f"Reading {args.infile} (condition={args.condition!r}) ...", flush=True)
    # Dedupe by PK (pid, printing, condition, week_start) since `language` is NOT
    # in the PK -> an English + Japanese SKU of the same printing would collide and
    # break the ON CONFLICT upsert. On collision, prefer English then higher sales.
    by_pk = {}
    unmapped_pids = set()
    collisions = 0

    def better(new, old):
        ne, oe = new["language"] == "English", old["language"] == "English"
        if ne != oe:
            return ne
        return (new["transaction_count"] or 0) > (old["transaction_count"] or 0)

    for line in open(args.infile, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        if not rec.get("ok"):
            continue
        pid = rec["pid"]
        cid = pid2cid.get(pid)
        if cid is None:
            unmapped_pids.add(pid)
        for sku in rec.get("skus", []):
            if sku.get("condition") != args.condition:
                continue
            printing = sku.get("variant") or "Normal"
            lang = sku.get("language")
            for b in sku.get("buckets", []):
                tc = int(num(b.get("transactionCount")) or 0)
                no_sales = tc == 0
                wk = b.get("bucketStartDate")
                pk = (pid, printing, args.condition, wk)
                row = {
                    "tcgplayer_product_id": pid,
                    "printing": printing,
                    "condition": args.condition,
                    "week_start": wk,
                    "card_id": cid,
                    "market_price": num(b.get("marketPrice")),
                    "low_sale_price": None if no_sales else num(b.get("lowSalePrice")),
                    "high_sale_price": None if no_sales else num(b.get("highSalePrice")),
                    "low_sale_price_ship": None if no_sales else num(b.get("lowSalePriceWithShipping")),
                    "high_sale_price_ship": None if no_sales else num(b.get("highSalePriceWithShipping")),
                    "quantity_sold": int(num(b.get("quantitySold")) or 0),
                    "transaction_count": tc,
                    "sku_id": int(num(sku.get("skuId"))) if num(sku.get("skuId")) else None,
                    "language": lang,
                }
                if pk in by_pk:
                    collisions += 1
                    if better(row, by_pk[pk]):
                        by_pk[pk] = row
                else:
                    by_pk[pk] = row

    rows = list(by_pk.values())
    print(f"  {len(rows)} unique rows ({collisions} PK collisions deduped).", flush=True)

    sent = 0
    for i in range(0, len(rows), args.batch):
        chunk = rows[i:i + args.batch]
        upsert(url, key, chunk)
        sent += len(chunk)
        print(f"  upserted {sent}/{len(rows)} rows", flush=True)

    print("=" * 60)
    print(f"DONE. rows upserted: {sent}")
    if unmapped_pids:
        print(f"WARNING: {len(unmapped_pids)} pids had no card_id (loaded with card_id=null): "
              f"{sorted(unmapped_pids)[:10]}{' ...' if len(unmapped_pids) > 10 else ''}")


if __name__ == "__main__":
    main()
