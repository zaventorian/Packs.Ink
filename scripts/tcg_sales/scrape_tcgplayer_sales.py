#!/usr/bin/env python3
"""
One-off bulk scraper for TCGplayer weekly sales-history via the Apify actor
scraped/tcgplayer-sales-history (run-sync REST endpoint).

Pulls the Lorcana product list straight from Supabase (cards table), then
scrapes each product's 52-week sales buckets (per condition x printing SKU)
and appends one JSON record per product to a JSONL file.

Resumable: re-running skips any product already present with ok:true.
Pure stdlib (urllib + concurrent.futures); no pip installs needed.

Usage:
  APIFY_TOKEN=apify_api_xxx python scrape_tcgplayer_sales.py \
      --rarities Enchanted,Iconic,Epic --workers 5

  # everything (all Lorcana products with a tcgplayer id):
  APIFY_TOKEN=... python scrape_tcgplayer_sales.py --all
"""
import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://umwqowkiatjjltologrd.supabase.co")
SUPABASE_ANON = os.environ.get(
    "SUPABASE_ANON",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVtd3Fvd2tpYXRqamx0b2xvZ3JkIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg1NDUwMDMsImV4cCI6MjA5NDEyMTAwM30.b2DFdZm69Mj-1uzSTEu8ltYDjbao9ZX1Fpev6kA4LKk",
)
APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
ACTOR = "scraped~tcgplayer-sales-history"
RUN_SYNC = f"https://api.apify.com/v2/acts/{ACTOR}/run-sync-get-dataset-items?token={{tok}}"

HERE = os.path.dirname(os.path.abspath(__file__))

# Windows consoles default to cp1252 and choke on card names like "Te Ka".
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def fetch_products(rarities, all_products=False, source="cards"):
    """Pull distinct products from Supabase cards or sealed_products."""
    if source == "sealed":
        table = "sealed_products"
        params = {
            "select": "tcgplayer_product_id,name,product_type,set_id",
            "tcgplayer_product_id": "not.is.null",
            "order": "tcgplayer_product_id.asc",
        }
    else:
        table = "cards"
        params = {
            "select": "tcgplayer_product_id,name,rarity,set_id",
            "tcgplayer_product_id": "not.is.null",
            "order": "tcgplayer_product_id.asc",
        }
        if not all_products:
            quoted = ",".join(f'"{r}"' for r in rarities)
            params["rarity"] = f"in.({quoted})"
    url = f"{SUPABASE_URL}/rest/v1/{table}?" + urllib.parse.urlencode(params)
    # PostgREST caps pages at 1000 rows -> paginate via Range header.
    seen, out = set(), []
    page = 1000
    offset = 0
    while True:
        req = urllib.request.Request(
            url,
            headers={
                "apikey": SUPABASE_ANON,
                "Authorization": f"Bearer {SUPABASE_ANON}",
                "Accept": "application/json",
                "Range-Unit": "items",
                "Range": f"{offset}-{offset + page - 1}",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            rows = json.loads(resp.read().decode())
        if not rows:
            break
        for r in rows:
            pid = r.get("tcgplayer_product_id")
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            out.append(r)
        if len(rows) < page:
            break
        offset += page
    return out


def scrape_one(pid, retries=4, timeout=120):
    """Run the actor synchronously and return the list of SKU dicts."""
    url = (
        f"https://www.tcgplayer.com/product/{pid}?page=1&Language=English"
    )
    body = json.dumps({"url": url}).encode()
    endpoint = RUN_SYNC.format(tok=APIFY_TOKEN)
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                endpoint, data=body,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode())
            if isinstance(data, list):
                return data, None
            # actor returned an error object
            last_err = f"non-list response: {str(data)[:200]}"
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode()[:200]
            except Exception:
                pass
            last_err = f"HTTP {e.code} {detail}"
            # 400 "Actor run did not succeed" is a transient run failure -> retry.
            transient_400 = e.code == 400 and "did not succeed" in detail
            if e.code in (401, 403, 404) or (e.code == 400 and not transient_400):
                break  # non-retryable
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(min(2 ** attempt, 20))
    return None, last_err


def load_done(out_path):
    done = set()
    if not os.path.exists(out_path):
        return done
    with open(out_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("ok"):
                    done.add(rec["pid"])
            except Exception:
                continue
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rarities", default="Enchanted,Iconic,Epic")
    ap.add_argument("--all", action="store_true", help="scrape every product, ignore --rarities")
    ap.add_argument("--source", choices=["cards", "sealed"], default="cards")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="cap products (testing)")
    ap.add_argument("--out", default="")
    args = ap.parse_args()
    if not args.out:
        fname = "tcgplayer_sales_sealed.jsonl" if args.source == "sealed" else "tcgplayer_sales.jsonl"
        args.out = os.path.join(HERE, "out", fname)

    if not APIFY_TOKEN:
        log("ERROR: set APIFY_TOKEN env var")
        sys.exit(1)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    rarities = [r.strip() for r in args.rarities.split(",") if r.strip()]

    scope = "sealed" if args.source == "sealed" else ("ALL cards" if args.all else ",".join(rarities))
    log(f"Fetching product list from Supabase ({scope})...")
    products = fetch_products(rarities, all_products=args.all, source=args.source)
    log(f"{len(products)} distinct products.")

    done = load_done(args.out)
    if done:
        log(f"Resuming: {len(done)} already scraped, skipping those.")
    todo = [p for p in products if p["tcgplayer_product_id"] not in done]
    if args.limit:
        todo = todo[: args.limit]
    log(f"{len(todo)} products to scrape with {args.workers} workers.")

    out_f = open(args.out, "a", encoding="utf-8")
    counts = {"ok": 0, "fail": 0, "skus": 0, "buckets": 0}
    n = len(todo)

    def work(p):
        pid = p["tcgplayer_product_id"]
        skus, err = scrape_one(pid)
        return p, skus, err

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, p): p for p in todo}
        i = 0
        for fut in as_completed(futs):
            i += 1
            p, skus, err = fut.result()
            pid = p["tcgplayer_product_id"]
            rec = {
                "pid": pid,
                "name": p.get("name"),
                "rarity": p.get("rarity"),
                "product_type": p.get("product_type"),
                "set_id": p.get("set_id"),
                "scraped_at": datetime.now(timezone.utc).isoformat(),
                "ok": skus is not None,
            }
            if skus is not None:
                rec["skus"] = skus
                counts["ok"] += 1
                counts["skus"] += len(skus)
                counts["buckets"] += sum(len(s.get("buckets", [])) for s in skus)
                tag = f"{len(skus)} SKUs"
            else:
                rec["error"] = err
                counts["fail"] += 1
                tag = f"FAIL: {err}"
            out_f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            out_f.flush()
            kind = p.get("rarity") or p.get("product_type") or "?"
            log(f"[{i}/{n}] {pid} {(p.get('name') or '')[:32]:32} ({kind}) -> {tag}")

    out_f.close()
    log("=" * 60)
    log(f"DONE. ok={counts['ok']} fail={counts['fail']} "
        f"skus={counts['skus']} buckets={counts['buckets']}")
    log(f"Output: {args.out}")


if __name__ == "__main__":
    main()
