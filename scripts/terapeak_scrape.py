"""
terapeak_scrape.py — Playwright-driven scraper for eBay Product Research
(Terapeak) Sold listings. Loads a saved session from terapeak_login.py,
runs one or more keyword searches, paginates through results, and writes
JSONL output per query (one file per query per run).

Why scrape Terapeak instead of public sold search:
    1. Real sold price for Best-Offer-Accepted listings (public sold pages
       show only the strikethrough ask).
    2. Three years of history (public sold pages cap at 90 days).
    3. Includes "All sites" (international marketplaces), not just .com.

Why Playwright instead of httpx:
    Terapeak requires an authenticated eBay seller session. Replaying the
    underlying API would require capturing live cookies + CSRF tokens on
    every request. Driving a real Chrome with a persistent session is more
    reliable and identical to a human seller using the tool.

Usage:
    pip install -r scripts/requirements.txt
    playwright install chromium
    python scripts/terapeak_login.py             # one-time, save session
    python scripts/terapeak_scrape.py            # default: 6 graded queries, 3y
    python scripts/terapeak_scrape.py --days 7   # incremental: last week
    python scripts/terapeak_scrape.py --headless # for cron/VPS

Output:
    scripts/terapeak_output/<keyword>_<timestamp>.jsonl   one row per line
    scripts/terapeak_snapshots/<keyword>_<offset>.html    raw HTML per page

Account-safety notes:
    - Uses the dedicated research account session, NEVER the main account.
    - All delays randomized to look like a human pacing through pages.
    - Mouse jitter between actions.
    - Long pause between different keyword queries.
    - Designed to run in a single window per session; no parallelism.
    - Run window: aim for normal business hours (cron schedule it that way).

TODO (revisit after first real run):
    - Verify selectors in parse_rows() match the actual Terapeak DOM
    - Verify "All sites" dropdown handler ensure_all_sites()
    - Add Supabase upsert (currently just writes JSONL)
    - Add resumable state (so we can continue a crashed multi-day backfill)
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import Page, sync_playwright


# --------------------------------------------------------------------------
# Paths and config
# --------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
SESSION_STATE = HERE / ".terapeak_state.json"
OUTPUT_DIR = HERE / "terapeak_output"
SNAPSHOTS_DIR = HERE / "terapeak_snapshots"

TERAPEAK_BASE = "https://www.ebay.com/sh/research"

# Default graded-card queries. Cover the major grading companies.
# "Beckett" overlaps heavily with BGS but catches listings that title
# the company name in full.
DEFAULT_KEYWORDS = [
    '"Lorcana" "PSA"',
    '"Lorcana" "CGC"',
    '"Lorcana" "BGS"',
    '"Lorcana" "Beckett"',
    '"Lorcana" "TAG"',
    '"Lorcana" "SGC"',
]

RESULTS_PER_PAGE = 50  # Terapeak's max

# Human-like timing ranges (seconds). All sleeps pick a random value in range.
# Tuned to look like a seller reading and clicking through results.
DELAY_BETWEEN_PAGES = (8.0, 14.0)
DELAY_BETWEEN_QUERIES = (45.0, 120.0)
DELAY_AFTER_NAV = (2.0, 4.5)
DELAY_AFTER_CLICK = (0.4, 1.2)


# --------------------------------------------------------------------------
# Human-like behaviors
# --------------------------------------------------------------------------

def human_sleep(rng: tuple[float, float]) -> None:
    """Sleep a random duration within rng=(min, max) seconds."""
    lo, hi = rng
    time.sleep(random.uniform(lo, hi))


def human_mouse_jitter(page: Page) -> None:
    """Move the mouse to a random position with a curved-ish path. Cheap
    anti-bot mitigation — real users move their mouse, bots usually don't."""
    try:
        # Pick a random target within the viewport
        x = random.randint(150, 1250)
        y = random.randint(150, 750)
        # steps>1 makes Playwright interpolate the path, which looks more natural
        page.mouse.move(x, y, steps=random.randint(8, 20))
    except Exception:
        # Mouse moves can fail silently in some contexts; not worth crashing
        pass


def human_scroll(page: Page) -> None:
    """Scroll down a random small amount, then back up sometimes. Mimics a
    user skimming the results table."""
    try:
        page.mouse.wheel(0, random.randint(150, 600))
        time.sleep(random.uniform(0.3, 1.0))
        if random.random() < 0.4:
            page.mouse.wheel(0, -random.randint(50, 200))
    except Exception:
        pass


# --------------------------------------------------------------------------
# URL building
# --------------------------------------------------------------------------

def build_search_url(
    keywords: str,
    *,
    days_back: int = 1095,
    offset: int = 0,
    limit: int = RESULTS_PER_PAGE,
    marketplace: str = "ALL",
    category_id: str = "0",
    tz: str = "America/Chicago",
) -> str:
    """Construct a Terapeak Product Research URL.

    keywords: the search string (URL-encoded automatically). For exact-match
              segments, include the literal quotes, e.g. '"Lorcana" "PSA"'.
    days_back: 1095 = 3 years (max). Use small values for daily incremental.
    offset, limit: pagination. offset is 0-indexed.
    marketplace: "ALL" for all eBay sites combined, or "EBAY-US" for US only.
    category_id: 0 = All Categories.
    tz: timezone string; doesn't affect data but eBay puts it in the URL.
    """
    now_ms = int(time.time() * 1000)
    start_ms = int((time.time() - days_back * 86400) * 1000)
    params = {
        "marketplace": marketplace,
        "keywords": keywords,
        "dayRange": str(days_back),
        "endDate": str(now_ms),
        "startDate": str(start_ms),
        "categoryId": category_id,
        "offset": str(offset),
        "limit": str(limit),
        "tabName": "SOLD",
        "tz": tz,
    }
    qs = "&".join(f"{k}={quote_plus(v)}" for k, v in params.items())
    return f"{TERAPEAK_BASE}?{qs}"


# --------------------------------------------------------------------------
# Page-level helpers
# --------------------------------------------------------------------------

def assert_authenticated(page: Page) -> None:
    """Raise if the page looks like a sign-in redirect, meaning our saved
    session expired."""
    url = page.url.lower()
    if "signin" in url or "login" in url or "captcha" in url:
        sys.exit(
            f"Session looks expired or challenged (current URL: {page.url}). "
            "Re-run scripts/terapeak_login.py to refresh."
        )


def ensure_all_sites(page: Page) -> None:
    """Make sure the 'Listing Site' dropdown is set to 'All sites'.

    The URL has marketplace=ALL but the UI sometimes loads as 'ebay.com'
    on first navigation and only takes the URL param after explicit
    selection. Once set, subsequent pagination respects it.

    TODO: verify the exact selector after first headful run. Several
    candidate patterns tried in order.
    """
    candidates = [
        # By visible label text
        'button:has-text("Listing Site")',
        'div:has-text("Listing Site:") + div button',
        # By aria attributes
        '[aria-label*="Listing Site" i]',
        # Generic dropdowns near top of page
        'select[name*="site" i]',
    ]
    dropdown = None
    for sel in candidates:
        try:
            el = page.locator(sel).first
            if el.count() > 0 and el.is_visible():
                dropdown = el
                break
        except Exception:
            continue

    if not dropdown:
        print("    [warn] Couldn't find 'Listing Site' dropdown; relying on URL param")
        return

    try:
        dropdown.click()
        human_sleep(DELAY_AFTER_CLICK)
        # Look for the "All sites" option in the opened menu
        option = page.locator('text="All sites"').first
        if option.count() > 0:
            option.click()
            human_sleep(DELAY_AFTER_CLICK)
            print("    [ok] Set Listing Site to All sites")
        else:
            print("    [warn] Couldn't find 'All sites' option in dropdown")
    except Exception as e:
        print(f"    [warn] ensure_all_sites failed: {e}")


def save_snapshot(page: Page, keyword: str, offset: int) -> Path:
    """Save full page HTML for debugging/replay. Filenames are safe slugs."""
    SNAPSHOTS_DIR.mkdir(exist_ok=True)
    slug = slugify(keyword)
    path = SNAPSHOTS_DIR / f"{slug}_offset{offset:05d}.html"
    path.write_text(page.content(), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Row parser
# --------------------------------------------------------------------------

def parse_rows(page: Page) -> list[dict]:
    """Extract listing rows from the rendered Terapeak page.

    TODO: selectors are best-guess based on the screenshot you shared.
    Will need refinement after the first real run reveals the actual DOM
    structure (raw HTML is saved by save_snapshot for inspection).

    Returns a list of dicts with normalized field names.
    """
    rows: list[dict] = []

    # Try several patterns for the row container, in order of specificity.
    # The Product Research table appears to use either a real <table> or a
    # list of divs styled like one.
    row_locators = [
        'table tbody tr',
        '[role="row"]',
        '[data-test-id*="row" i]',
        '.research-table-row, .research__row',  # speculative
    ]
    found_rows = None
    for sel in row_locators:
        try:
            loc = page.locator(sel)
            cnt = loc.count()
            if cnt > 0:
                found_rows = loc
                print(f"    [parse] matched {cnt} rows with selector {sel!r}")
                break
        except Exception:
            continue

    if not found_rows:
        print("    [parse] no rows matched any candidate selector")
        return rows

    for i in range(found_rows.count()):
        row_el = found_rows.nth(i)
        try:
            data = _parse_one_row(row_el)
            if data and data.get("title"):
                rows.append(data)
        except Exception as e:
            print(f"    [parse] row {i}: {e}")

    return rows


def _parse_one_row(row_el) -> dict:
    """Pull fields out of a single row. Defensive: returns whatever it can
    find, missing fields default to None."""
    def text(sel: str) -> str | None:
        try:
            el = row_el.locator(sel).first
            if el.count() > 0:
                return el.inner_text().strip() or None
        except Exception:
            pass
        return None

    def attr(sel: str, name: str) -> str | None:
        try:
            el = row_el.locator(sel).first
            if el.count() > 0:
                v = el.get_attribute(name)
                return v.strip() if v else None
        except Exception:
            pass
        return None

    # Title — usually in a link element
    title = text('a[href*="/itm/"]') or text('h3') or text('[data-test*="title" i]')

    # eBay item URL → itemId
    item_url = attr('a[href*="/itm/"]', "href")
    item_id = None
    if item_url:
        m = re.search(r'/itm/(?:[^/]+/)?(\d+)', item_url)
        item_id = m.group(1) if m else None

    # Thumbnail image URL
    thumb = attr('img', 'src') or attr('img', 'data-src')

    # The Terapeak table columns from the screenshot:
    #   Listing | Actions | Avg sold price | Avg shipping | Total sold |
    #   Item sales | Bids | Date last sold
    # Many of these have associated "Fixed price"/"Auction" sublabels.

    avg_price_text = text('[data-test*="price" i], .price, td:nth-of-type(3)')
    avg_ship_text  = text('[data-test*="ship"  i], td:nth-of-type(4)')
    total_sold_text = text('[data-test*="sold" i], td:nth-of-type(5)')
    item_sales_text = text('[data-test*="sales" i], td:nth-of-type(6)')
    bids_text       = text('[data-test*="bid"   i], td:nth-of-type(7)')
    date_text       = text('[data-test*="date"  i], td:nth-of-type(8)')

    # Detect listing format from sublabel (Fixed price / Auction)
    full_row_text = ""
    try:
        full_row_text = row_el.inner_text()
    except Exception:
        pass
    listing_type = None
    if "Fixed price" in full_row_text:
        listing_type = "fixed_price"
    elif "Auction" in full_row_text:
        listing_type = "auction"

    return {
        "item_id": item_id,
        "listing_url": item_url,
        "title": title,
        "thumbnail_url": thumb,
        "avg_sold_price_text": avg_price_text,
        "avg_sold_price": _parse_money(avg_price_text),
        "avg_shipping_text": avg_ship_text,
        "avg_shipping": _parse_money(avg_ship_text),
        "total_sold": _parse_int(total_sold_text),
        "item_sales_text": item_sales_text,
        "item_sales": _parse_money(item_sales_text),
        "bids": _parse_int(bids_text),
        "date_last_sold_text": date_text,
        "listing_type": listing_type,
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }


def _parse_money(s: str | None) -> float | None:
    if not s:
        return None
    m = re.search(r'(\$|US\s*\$)?\s*([\d,]+\.?\d*)', s)
    if not m:
        return None
    try:
        return float(m.group(2).replace(",", ""))
    except ValueError:
        return None


def _parse_int(s: str | None) -> int | None:
    if not s:
        return None
    m = re.search(r'(\d[\d,]*)', s)
    if not m:
        return None
    try:
        return int(m.group(1).replace(",", ""))
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Search runner
# --------------------------------------------------------------------------

def scrape_query(
    page: Page,
    keywords: str,
    *,
    days_back: int = 1095,
    max_pages: int | None = None,
    save_snapshots: bool = True,
) -> list[dict]:
    """Run one keyword search. Paginates until empty page or max_pages."""
    all_rows: list[dict] = []
    offset = 0
    page_num = 0

    while True:
        page_num += 1
        url = build_search_url(keywords, days_back=days_back, offset=offset)
        print(f"  page {page_num} (offset={offset})")
        page.goto(url, wait_until="domcontentloaded")
        assert_authenticated(page)

        # Wait for the results area to render. We don't know the exact
        # selector yet, so wait for either a table or a "no results" marker
        # OR a brief networkidle.
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass

        human_sleep(DELAY_AFTER_NAV)
        human_mouse_jitter(page)
        human_scroll(page)

        if page_num == 1:
            ensure_all_sites(page)
            human_sleep(DELAY_AFTER_NAV)

        if save_snapshots:
            snap_path = save_snapshot(page, keywords, offset)
            print(f"    [snap] saved {snap_path.name}")

        rows = parse_rows(page)
        if not rows:
            print(f"    [info] no rows on this page; stopping")
            break

        all_rows.extend(rows)
        print(f"    [data] +{len(rows)} rows (running total: {len(all_rows)})")

        # If we got a partial page, we're at the end
        if len(rows) < RESULTS_PER_PAGE:
            print(f"    [info] partial page ({len(rows)} < {RESULTS_PER_PAGE}); done")
            break

        if max_pages and page_num >= max_pages:
            print(f"    [info] hit max_pages={max_pages}; stopping")
            break

        offset += RESULTS_PER_PAGE
        human_sleep(DELAY_BETWEEN_PAGES)

    return all_rows


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def slugify(s: str) -> str:
    """Make a string safe to use as a filename."""
    s = re.sub(r'[^\w\s-]', '', s).strip()
    s = re.sub(r'[\s_-]+', '_', s)
    return s.lower() or "query"


def write_jsonl(rows: list[dict], path: Path) -> None:
    """Write one dict per line to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--days", type=int, default=1095,
        help="Days of history to scrape per query (default 1095 = 3 years)",
    )
    p.add_argument(
        "--keyword", "-k", action="append", metavar="QUERY",
        help="Search keyword (can repeat). Default: 6 graded queries.",
    )
    p.add_argument(
        "--max-pages", type=int, default=None,
        help="Cap pages per query (useful for testing). Default: unlimited",
    )
    p.add_argument(
        "--headless", action="store_true",
        help="Run without UI window. Use for VPS/cron. Default: headful for dev.",
    )
    p.add_argument(
        "--no-snapshots", action="store_true",
        help="Don't save raw HTML snapshots (smaller disk footprint)",
    )
    args = p.parse_args()

    if not SESSION_STATE.exists():
        sys.exit(
            f"No session state at {SESSION_STATE}.\n"
            "Run: python scripts/terapeak_login.py first."
        )

    keywords = args.keyword or DEFAULT_KEYWORDS
    OUTPUT_DIR.mkdir(exist_ok=True)
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=args.headless)
        context = browser.new_context(
            storage_state=str(SESSION_STATE),
            viewport={"width": 1400, "height": 900},
            locale="en-US",
        )
        page = context.new_page()

        total_rows = 0
        for kw in keywords:
            print(f"\n=== query: {kw} ===")
            try:
                rows = scrape_query(
                    page, kw,
                    days_back=args.days,
                    max_pages=args.max_pages,
                    save_snapshots=not args.no_snapshots,
                )
                outfile = OUTPUT_DIR / f"{slugify(kw)}_{run_stamp}.jsonl"
                write_jsonl(rows, outfile)
                print(f"  wrote {len(rows)} rows -> {outfile.name}")
                total_rows += len(rows)
            except SystemExit:
                raise  # auth failure - bail completely
            except Exception as e:
                print(f"  ERROR on '{kw}': {type(e).__name__}: {e}")

            # Long pause between different queries, looks more natural
            if kw != keywords[-1]:
                pause = random.uniform(*DELAY_BETWEEN_QUERIES)
                print(f"  pausing {pause:.0f}s before next query...")
                time.sleep(pause)

        print(f"\nDone. {total_rows} total rows across {len(keywords)} queries.")
        browser.close()


if __name__ == "__main__":
    main()
