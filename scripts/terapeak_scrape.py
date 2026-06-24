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
from datetime import datetime, timezone
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
    sorting: str = "-datelastsold",
    tz: str = "America/Chicago",
    end_ms: int | None = None,
    start_ms: int | None = None,
) -> str:
    """Construct a Terapeak Product Research URL.

    keywords: the search string (URL-encoded automatically). For exact-match
              segments, include the literal quotes, e.g. '"Lorcana" "PSA"'.
    days_back: 1095 = 3 years (max). Use small values for daily incremental.
    offset, limit: pagination. offset is 0-indexed.
    marketplace: "ALL" = all eBay sites combined (default, matches the working
                 manual search), or "EBAY-US" for US only.
    category_id: 0 = All Categories.
    sorting: "-datelastsold" = newest sale first; "datelastsold" (no "-") =
             OLDEST first, used for the resumable backfill (new sales land at
             the newest/high-offset end, so already-covered low offsets stay
             stable). Without an explicit sort, eBay falls back to best-match
             and floats high-volume accessory listings (slab cases, stands) to
             the top — the pollution we saw on the first run.
    end_ms, start_ms: fix the date window explicitly (epoch ms). Pass these for
             a multi-day backfill so the window doesn't slide forward each call
             and shift offsets. Default: now and now - days_back.
    tz: timezone string; doesn't affect data but eBay puts it in the URL.
    """
    if end_ms is None:
        end_ms = int(time.time() * 1000)
    if start_ms is None:
        start_ms = int((time.time() - days_back * 86400) * 1000)
    params = {
        "marketplace": marketplace,
        "keywords": keywords,
        "dayRange": str(days_back),
        "endDate": str(end_ms),
        "startDate": str(start_ms),
        "categoryId": category_id,
        "offset": str(offset),
        "limit": str(limit),
        "sorting": sorting,
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

    # Title + eBay item id. The current Terapeak DOM carries both on the
    # product-name span:
    #   <div class="...__product-info-name"><span data-item-id="385...">Title</span></div>
    # There is NO <a href="/itm/..."> in this render — the old selector matched
    # 0 links and dropped every row. Fall back to an /itm/ anchor for older
    # renders, and synthesize the listing URL from the id when absent.
    title = (
        text('.research-table-row__product-info-name [data-item-id]')
        or text('.research-table-row__product-info-name')
        or text('[data-item-id]')
        or text('a[href*="/itm/"]')
        or text('h3')
    )
    item_id = attr('[data-item-id]', 'data-item-id')
    item_url = attr('a[href*="/itm/"]', "href")
    if not item_id and item_url:
        m = re.search(r'/itm/(?:[^/]+/)?(\d+)', item_url)
        item_id = m.group(1) if m else None
    if item_id and not item_url:
        item_url = f"https://www.ebay.com/itm/{item_id}"

    # Thumbnail image URL (protocol-relative // -> https)
    thumb = attr('img', 'src') or attr('img', 'data-src')
    if thumb and thumb.startswith("//"):
        thumb = "https:" + thumb

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

def _row_key(r: dict) -> str:
    """Dedup key. Prefer item_id; fall back to a title/price/date composite for
    the rare row that has no item id."""
    return r.get("item_id") or (
        f"{r.get('title')}|{r.get('avg_sold_price')}|{r.get('date_last_sold_text')}"
    )


def _load_progress(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_progress(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _load_seen(out_path: Path) -> set[str]:
    """Item keys already on disk, so a resumed run dedups against prior pages."""
    seen: set[str] = set()
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(_row_key(json.loads(line)))
            except Exception:
                pass
    return seen


def _load_page_rows(page: Page, url: str, save_snapshots: bool,
                    keywords: str, snap_tag: int) -> list[dict]:
    """Navigate to one results page and return parsed rows. Waits for the table
    to actually render (a real [data-item-id] row) to beat the skeleton-row
    render race. Raises SystemExit (via assert_authenticated) on a challenge."""
    # Retry the navigation on a transient timeout / nav error. A single
    # page.goto timeout used to be swallowed by main()'s per-query handler,
    # making the scraper exit 0 and the watchdog FALSELY declare the backfill
    # complete (it stopped at PSA window 7/19 overnight on one blip). Retry
    # here; if it still fails, raise SystemExit so the scraper exits NON-zero
    # and the watchdog resumes from progress instead of thinking it finished.
    last_err = None
    for attempt in range(4):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            break
        except Exception as e:
            last_err = e
            print(f"    [nav retry {attempt + 1}/4] {type(e).__name__}: {str(e)[:70]}")
            try:
                page.wait_for_timeout(5000)
            except Exception:
                pass
    else:
        sys.exit(f"navigation failed after 4 retries: {last_err}")
    assert_authenticated(page)
    try:
        page.wait_for_selector('.research-table-row [data-item-id]', timeout=20000)
    except Exception:
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
    human_sleep(DELAY_AFTER_NAV)
    human_mouse_jitter(page)
    human_scroll(page)
    if save_snapshots:
        snap_path = save_snapshot(page, keywords, snap_tag)
        print(f"    [snap] saved {snap_path.name}")
    return parse_rows(page)


def _iso_to_ms(s: str) -> int:
    dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_to_date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _build_windows(start_ms: int, end_ms: int, window_days: int) -> list[tuple[int, int]]:
    """Split [start_ms, end_ms] into consecutive window_days-sized windows."""
    step = window_days * 86400 * 1000
    wins: list[tuple[int, int]] = []
    s = start_ms
    while s < end_ms:
        e = min(s + step, end_ms)
        wins.append((s, e))
        s = e
    return wins


def scrape_query(
    page: Page,
    keywords: str,
    *,
    out_path: Path,
    progress_path: Path,
    sorting: str = "-datelastsold",
    end_ms: int | None = None,
    start_ms: int | None = None,
    days_back: int = 1095,
    max_pages: int | None = None,
    save_snapshots: bool = False,
) -> int:
    """Scrape one keyword search, appending rows INCREMENTALLY and resuming.

    Built for the multi-day 3-year backfill: every page is flushed to `out_path`
    (JSONL) immediately and `progress_path` records the next offset + the fixed
    date window, so a CAPTCHA/crash never loses collected rows and a re-run picks
    up where it left off. Use sorting="datelastsold" (oldest first) for the
    backfill — new sales land at the newest/high-offset end, so already-covered
    low offsets stay stable across days.

    End detection tolerates resume-overlap (a few already-seen pages right at the
    resume point) via a consecutive-all-duplicate counter rather than stopping on
    the first all-dup page. Returns the cumulative saved-row count.
    """
    seen = _load_seen(out_path)
    prog = _load_progress(progress_path)
    offset = int(prog.get("offset", 0))
    total = len(seen)
    # Reuse the fixed window from a prior run so offsets stay stable across days.
    end_ms = prog.get("end_ms") or end_ms
    start_ms = prog.get("start_ms") or start_ms
    if offset:
        print(f"  resuming at offset={offset} ({total} rows already on disk)")

    out_f = out_path.open("a", encoding="utf-8")
    page_num = 0
    consec_dup = 0
    try:
        while True:
            page_num += 1
            url = build_search_url(
                keywords, days_back=days_back, offset=offset,
                sorting=sorting, end_ms=end_ms, start_ms=start_ms,
            )
            print(f"  page {page_num} (offset={offset})")
            rows = _load_page_rows(page, url, save_snapshots, keywords, offset)
            n_new = 0
            for r in rows:
                k = _row_key(r)
                if k not in seen:
                    seen.add(k)
                    out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    n_new += 1
            out_f.flush()
            total += n_new
            last_date = rows[-1].get("date_last_sold_text") if rows else None
            print(f"    page {page_num}: +{n_new} new "
                  f"(saved total: {total}) last_sold={last_date}")

            if not rows:
                print("    [info] empty page; reached the end")
                break
            if n_new == 0:
                consec_dup += 1
                if consec_dup >= 3:
                    print("    [info] 3 consecutive all-duplicate pages; done")
                    break
            else:
                consec_dup = 0

            offset += RESULTS_PER_PAGE
            _save_progress(progress_path, {
                "offset": offset, "count": total, "last_date": last_date,
                "end_ms": end_ms, "start_ms": start_ms,
            })
            if max_pages and page_num >= max_pages:
                print(f"    [info] hit max_pages={max_pages}; stopping")
                break
            human_sleep(DELAY_BETWEEN_PAGES)
    finally:
        out_f.close()

    return total


def scrape_query_windowed(
    page: Page,
    keywords: str,
    *,
    out_path: Path,
    progress_path: Path,
    windows: list[tuple[int, int]],
    sorting: str = "datelastsold",
    save_snapshots: bool = False,
) -> int:
    """Scrape one query across a SEQUENCE of date windows to defeat Terapeak's
    hard 10,000-offset pagination cap (hit by high-volume graders like PSA).

    Each window is small enough that its own offset pagination finishes under the
    cap. Within a window we paginate to the GENUINE end (an empty page) — NOT the
    consec-duplicate heuristic — so the boundary window that overlaps
    already-scraped data still reaches its new rows instead of stopping on the
    leading dupes. Rows append + dedup to the shared per-query file. Resumable
    per window via progress_path: {done:[idx...], cur_idx, cur_offset}.
    """
    seen = _load_seen(out_path)
    prog = _load_progress(progress_path)
    done = set(prog.get("done", []))
    cur_idx = int(prog.get("cur_idx", 0))
    cur_offset = int(prog.get("cur_offset", 0))
    total = len(seen)

    out_f = out_path.open("a", encoding="utf-8")
    try:
        for idx, (s_ms, e_ms) in enumerate(windows):
            if idx in done:
                continue
            offset = cur_offset if idx == cur_idx else 0
            print(f"  window {idx + 1}/{len(windows)} "
                  f"[{_ms_to_date(s_ms)} .. {_ms_to_date(e_ms)}] from offset {offset}")
            while True:
                url = build_search_url(
                    keywords, offset=offset, sorting=sorting,
                    end_ms=e_ms, start_ms=s_ms,
                )
                rows = _load_page_rows(page, url, save_snapshots, keywords, offset)
                n_new = 0
                for r in rows:
                    k = _row_key(r)
                    if k not in seen:
                        seen.add(k)
                        out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        n_new += 1
                out_f.flush()
                total += n_new
                last_date = rows[-1].get("date_last_sold_text") if rows else None
                print(f"    win{idx + 1} off{offset}: +{n_new} new "
                      f"({len(rows)} parsed, total {total}) last_sold={last_date}")

                if not rows:
                    break  # genuine end of this window
                offset += RESULTS_PER_PAGE
                _save_progress(progress_path, {
                    "done": sorted(done), "cur_idx": idx, "cur_offset": offset,
                })
                if offset >= 10000:
                    print(f"    [warn] window {idx + 1} hit the 10000 offset cap — "
                          f"shrink --window-days; rows in this window are missing")
                    break
                human_sleep(DELAY_BETWEEN_PAGES)

            done.add(idx)
            _save_progress(progress_path, {
                "done": sorted(done), "cur_idx": idx + 1, "cur_offset": 0,
            })
            human_sleep(DELAY_AFTER_NAV)
    finally:
        out_f.close()

    return total


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def slugify(s: str) -> str:
    """Make a string safe to use as a filename."""
    s = re.sub(r'[^\w\s-]', '', s).strip()
    s = re.sub(r'[\s_-]+', '_', s)
    return s.lower() or "query"


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
        "--grader", metavar="NAME", action="append", default=None,
        help='Convenience: scrape a grader by name (repeatable). --grader PSA '
             'expands to \'"Lorcana" "PSA"\'; pass several (--grader CGC '
             '--grader BGS) to scrape multiple without shell-quoting the quotes.',
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
        "--oldest-first", action="store_true",
        help="Sort oldest sale first (sorting=datelastsold). Use for the "
             "resumable 3-year backfill so already-covered offsets stay stable "
             "as new sales land at the newest end. Default: newest first.",
    )
    p.add_argument(
        "--snapshots", action="store_true",
        help="Save raw HTML snapshots per page (debugging). Off by default — a "
             "full backfill would write thousands of ~1MB files.",
    )
    p.add_argument(
        "--window-days", type=int, default=None, metavar="N",
        help="Scrape each query in N-day date windows to beat Terapeak's hard "
             "10000-offset cap (needed for high-volume graders like PSA whose "
             "3-year total exceeds 10000). ~60 is a safe size. Default: off.",
    )
    p.add_argument(
        "--start", metavar="YYYY-MM-DD", default=None,
        help="Window range start (default: now - --days). Used with --window-days.",
    )
    p.add_argument(
        "--end", metavar="YYYY-MM-DD", default=None,
        help="Window range end (default: now). Used with --window-days.",
    )
    p.add_argument(
        "--cdp", nargs="?", const="http://localhost:9222", default=None,
        metavar="URL",
        help="Attach to an ALREADY-RUNNING Chrome via the DevTools Protocol "
             "instead of launching a fresh Playwright browser. Start Chrome "
             "yourself with --remote-debugging-port=9222, log the burner "
             "account in + clear any CAPTCHA by hand, then run with --cdp. A "
             "user-launched Chrome doesn't advertise automation, so hCaptcha "
             "renders normally. Bare --cdp uses http://localhost:9222.",
    )
    args = p.parse_args()

    if not args.cdp and not SESSION_STATE.exists():
        sys.exit(
            f"No session state at {SESSION_STATE}.\n"
            "Run: python scripts/terapeak_login.py first "
            "(or use --cdp to attach to a real Chrome you control)."
        )

    if args.grader:
        keywords = [f'"Lorcana" "{g}"' for g in args.grader]
    else:
        keywords = args.keyword or DEFAULT_KEYWORDS
    OUTPUT_DIR.mkdir(exist_ok=True)
    sorting = "datelastsold" if args.oldest_first else "-datelastsold"
    # Fix the date window once at run start so multi-day backfills don't drift
    # (each query also persists its own copy in its .progress.json on resume).
    end_ms = int(time.time() * 1000)
    start_ms = int((time.time() - args.days * 86400) * 1000)

    with sync_playwright() as p:
        if args.cdp:
            # Attach to a real, user-launched Chrome. Because that browser was
            # NOT started by Playwright, it doesn't set navigator.webdriver or
            # show the automation banner, so eBay/hCaptcha treat it like a
            # human's browser. We reuse its existing (default) context, which
            # carries the burner login + any CAPTCHA the user already cleared.
            print(f"Attaching to Chrome over CDP at {args.cdp} ...")
            browser = p.chromium.connect_over_cdp(args.cdp)
            context = (
                browser.contexts[0] if browser.contexts else browser.new_context()
            )
            page = context.pages[0] if context.pages else context.new_page()
            owns_browser = False
        else:
            # Same anti-detection flag as the login script: drop
            # navigator.webdriver so eBay is less likely to throw the splashui
            # CAPTCHA at us. Keep the user-agent identical to the one used at
            # login so the saved session's fingerprint stays consistent.
            browser = p.chromium.launch(
                headless=args.headless,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                storage_state=str(SESSION_STATE),
                viewport={"width": 1400, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()
            owns_browser = True

        total_rows = 0
        for kw in keywords:
            print(f"\n=== query: {kw} ===")
            slug = slugify(kw)
            out_path = OUTPUT_DIR / f"{slug}.jsonl"
            try:
                if args.window_days:
                    ws = _iso_to_ms(args.start) if args.start else start_ms
                    we = _iso_to_ms(args.end) if args.end else end_ms
                    windows = _build_windows(ws, we, args.window_days)
                    wprog = OUTPUT_DIR / f"{slug}.win.progress.json"
                    print(f"  windowed: {len(windows)} x {args.window_days}d "
                          f"[{_ms_to_date(ws)} .. {_ms_to_date(we)}]")
                    count = scrape_query_windowed(
                        page, kw,
                        out_path=out_path, progress_path=wprog,
                        windows=windows, sorting=sorting,
                        save_snapshots=args.snapshots,
                    )
                else:
                    progress_path = OUTPUT_DIR / f"{slug}.progress.json"
                    count = scrape_query(
                        page, kw,
                        out_path=out_path, progress_path=progress_path,
                        sorting=sorting, end_ms=end_ms, start_ms=start_ms,
                        days_back=args.days, max_pages=args.max_pages,
                        save_snapshots=args.snapshots,
                    )
                print(f"  {count} rows total on disk -> {out_path.name}")
                total_rows += count
            except SystemExit:
                raise  # auth/captcha failure - bail completely
            except Exception as e:
                print(f"  ERROR on '{kw}': {type(e).__name__}: {e}")

            # Long pause between different queries, looks more natural
            if kw != keywords[-1]:
                pause = random.uniform(*DELAY_BETWEEN_QUERIES)
                print(f"  pausing {pause:.0f}s before next query...")
                time.sleep(pause)

        print(f"\nDone. {total_rows} total rows across {len(keywords)} queries.")
        # In CDP mode the browser belongs to the user — leave it open.
        if owns_browser:
            browser.close()


if __name__ == "__main__":
    main()
