"""Terapeak top-up over the CDP Chrome (All-sites SPA, no goto).

For each grader: switches the search box, AUTO-SETS 'All sites', forces the
newest-first sort, resets to page 1, and scrapes bounded to (file max date - 2d).

Usage:
  python terapeak_topup.py            # ALL six graders (default), challenge-guarded
  python terapeak_topup.py ALL        # same as above
  python terapeak_topup.py BGS        # a single grader
  GRADER can be: PSA CGC BGS BECKETT TAG SGC   (case-insensitive)

Requires: Chrome launched with remote debugging on port 9222 with the burner
Terapeak profile signed in and the research tool open (a cold launch loading
https://www.ebay.com/sh/research is enough — this script sets All sites itself):
  chrome.exe --remote-debugging-port=9222
             --user-data-dir=C:\\Users\\zaven\\terapeak-chrome
             --disable-blink-features=AutomationControlled
             https://www.ebay.com/sh/research

CRITICAL: Do NOT do a full page.goto mid-scrape — eBay resets marketplace=ALL
to EBAY-US on every cold load. Only SPA pagination (clicking Next / native
<select> change) holds All-sites.
"""
import sys, time, re, json, random
from datetime import datetime, date, timedelta
sys.path.insert(0, r"C:\Users\zaven\OneDrive\Desktop\Packs.Ink\scripts")
from playwright.sync_api import sync_playwright
import terapeak_scrape as ts

GRADERS_ALL = ["PSA", "CGC", "BGS", "BECKETT", "TAG", "SGC"]
_arg = (sys.argv[1] if len(sys.argv) > 1 else "").upper()
GRADERS = GRADERS_ALL if _arg in ("", "ALL") else [_arg]
TODAY = date.today()
MAX_PAGES = 60  # safety cap (~1500 rows max, well above any weekly delta)


def pdate(s):
    try:
        return datetime.strptime((s or "").strip(), "%b %d, %Y").date()
    except Exception:
        return None


def first_id(page):
    loc = page.locator('.research-table-row [data-item-id]').first
    try:
        return loc.get_attribute("data-item-id") if loc.count() else None
    except Exception:
        return None


def rows_now(page):
    return ts.parse_rows(page)


def file_max_date(slug):
    f = ts.OUTPUT_DIR / f"{slug}.jsonl"
    mx = None
    if f.exists():
        for l in f.open(encoding="utf-8"):
            if not l.strip():
                continue
            try:
                d = pdate(json.loads(l).get("date_last_sold_text"))
                if d and (mx is None or d > mx):
                    mx = d
            except Exception:
                pass
    return mx


def click_by(page, selectors, label):
    for sel in selectors:
        loc = page.locator(sel)
        for i in range(loc.count()):
            el = loc.nth(i)
            try:
                if not el.is_visible() or el.get_attribute("disabled") is not None:
                    continue
                if (el.get_attribute("aria-disabled") or "").lower() == "true":
                    continue
                el.scroll_into_view_if_needed(timeout=3000)
                el.click(timeout=5000)
                return True
            except Exception:
                continue
    return False


def wait_swap(page, prev_id, secs=18):
    for _ in range(int(secs * 2)):
        time.sleep(0.5)
        if first_id(page) not in (None, prev_id):
            return True
    try:
        page.wait_for_load_state("networkidle", timeout=5000)
    except Exception:
        pass
    return False


def market(page):
    m = re.search(r'marketplace=([^&]+)', page.url)
    return m.group(1) if m else None


def ensure_all_sites(page):
    """Flip the Listing-Site control to 'All sites' via its NATIVE <select>.

    A cold Chrome launch loads the research tool as EBAY-US; the Listing-Site
    control is a plain native <select> (.select-filter__side-label select) whose
    'All sites' option value is 'ALL'. select_option fires the SPA change → the
    URL becomes marketplace=ALL WITHOUT a page.goto (so All-sites persists across
    later pagination). This removes the old by-hand step. Idempotent.
    """
    if market(page) == "ALL":
        print("marketplace already ALL")
        return
    sel = page.locator('.select-filter__side-label select').first
    if not sel.count():
        sys.exit("SAFETY STOP: Listing-Site <select> not found — is the Terapeak "
                 "research tool open in the CDP Chrome? Select 'All sites' by hand, then re-run.")
    try:
        sel.select_option("ALL")
    except Exception as e:
        sys.exit(f"SAFETY STOP: could not select All sites ({e}). Set it by hand, then re-run.")
    for _ in range(20):
        time.sleep(1)
        if market(page) == "ALL":
            print("set marketplace=ALL")
            time.sleep(1.5)
            return
    sys.exit(f"SAFETY STOP: marketplace stayed {market(page)}, not ALL after selecting All sites.")


def is_newest_first(rows):
    """Strict newest-first check: the visible page must be genuinely date-desc.

    The first several dates must be non-increasing AND the top row must be
    recent (within ~150 days across all sites). The old check only compared
    row[0] vs row[-1], which gave a FALSE POSITIVE on best-match ordering when
    row[0] happened to be a recent sale — so the sort was never applied and the
    run silently missed the newest days. (Empirically the keyword-Enter search
    resets the table to best-match, so this must catch that.)"""
    ds = [pdate(r.get("date_last_sold_text")) for r in (rows or [])]
    ds = [d for d in ds if d]
    if len(ds) < 3:
        return False
    seq = ds[:12]
    monotonic_desc = all(seq[i] >= seq[i + 1] for i in range(len(seq) - 1))
    return monotonic_desc and ds[0] >= (TODAY - timedelta(days=150))


def scrape_grader(page, grader):
    """Scrape one grader's newest-first delta. Returns the new-row count, or the
    string "CHALLENGE" if a captcha/bot-block appeared (caller stops the run)."""
    # --- 1. Switch the search box to this grader ---
    inp = page.locator('input[placeholder*="keyword" i]').first
    if not inp.count():
        sys.exit("SAFETY STOP: keyword input not found — is Terapeak open in Chrome?")
    prev = first_id(page)
    inp.click()
    inp.fill(f'"Lorcana" "{grader}"')
    inp.press("Enter")
    wait_swap(page, prev)
    time.sleep(2.0)

    kw = re.search(r'keywords=([^&]+)', page.url)
    print(f"after switch: keywords={kw.group(1) if kw else '?'} marketplace={market(page)}")
    if not kw or grader not in kw.group(1).upper():
        sys.exit(f"SAFETY STOP: search did not switch to {grader} (keywords={kw.group(1) if kw else '?'})")
    if market(page) != "ALL":
        # keyword search shouldn't drop All-sites, but re-assert if it did
        ensure_all_sites(page)

    # --- 2. Ensure newest-first sort ---
    rows = rows_now(page)
    if not is_newest_first(rows):
        print("  not newest-first; clicking 'Date last sold' header...")
        date_header_sels = [
            '[role="columnheader"]:has-text("Date last sold")',
            'th:has-text("Date last sold")',
            'button:has-text("Date last sold")',
            'text="Date last sold"',
        ]
        prev = first_id(page)
        click_by(page, date_header_sels, "date header")
        wait_swap(page, prev)
        time.sleep(1.5)
        rows = rows_now(page)
        if not is_newest_first(rows):  # sorted ascending; toggle again to desc
            prev = first_id(page)
            click_by(page, date_header_sels, "date header")
            wait_swap(page, prev)
            time.sleep(1.5)
            rows = rows_now(page)
        if not is_newest_first(rows):
            sys.exit(
                f"SAFETY STOP: could not get newest-first sort for {grader} "
                f"(top date={rows[0].get('date_last_sold_text') if rows else None}). "
                f"Sort by 'Date last sold' (desc) in Chrome, then re-run."
            )
    print(f"  sorted OK; newest={rows[0].get('date_last_sold_text')}")

    # --- 3. Reset to first page ---
    prev = first_id(page)
    if click_by(page, ['button[aria-label="Go to first page"]'], "first page"):
        wait_swap(page, prev)
        time.sleep(1.0)

    slug = f"lorcana_{grader.lower()}"
    mx = file_max_date(slug)
    cutoff = (mx - timedelta(days=2)) if mx else (TODAY - timedelta(days=14))
    out_path = ts.OUTPUT_DIR / f"{slug}.jsonl"
    seen = ts._load_seen(out_path)
    print(f"slug={slug}  file_max={mx}  cutoff={cutoff}  existing_rows={len(seen)}")

    # --- 4. Bounded paginate (newest → cutoff) ---
    out_f = out_path.open("a", encoding="utf-8")
    total_new, page_num = 0, 0
    try:
        while page_num < MAX_PAGES:
            page_num += 1
            if ts.detect_challenge(page):
                print(f"\n>>> CAPTCHA/CHALLENGE on {grader} page {page_num}. STOPPING (saved {total_new}).")
                return "CHALLENGE"
            rows = rows_now(page)
            if not rows:
                print(f"  page {page_num}: 0 rows -> done")
                break
            newest = pdate(rows[0].get("date_last_sold_text"))
            if newest and newest < cutoff:
                print(f"  page {page_num}: newest {newest} < cutoff {cutoff} -> caught up, done")
                break
            cur_first = first_id(page)
            n_new = 0
            for r in rows:
                k = ts._row_key(r)
                if k not in seen:
                    seen.add(k)
                    out_f.write(json.dumps(r, ensure_ascii=False) + "\n")
                    n_new += 1
            out_f.flush()
            total_new += n_new
            print(
                f"  page {page_num}: {len(rows)} rows "
                f"[{rows[0].get('date_last_sold_text')} .. {rows[-1].get('date_last_sold_text')}] "
                f"+{n_new} new (total {total_new}) mk={market(page)}"
            )
            if not click_by(page, ['button[aria-label="Go to next page"]'], "next"):
                print("  no Next button -> last page, done")
                break
            wait_swap(page, cur_first)
            time.sleep(random.uniform(6.0, 10.0))
    finally:
        out_f.close()
    print(f"DONE {slug}: +{total_new} new rows across {page_num} pages. JSONL now {len(seen)} rows.")
    return total_new


def main():
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        ensure_all_sites(page)  # once — persists across the per-grader SPA searches

        grand_total = 0
        for i, grader in enumerate(GRADERS):
            print(f"\n==================== {grader} ====================")
            res = scrape_grader(page, grader)
            if res == "CHALLENGE":
                print(f"\n>>> Solve the challenge in the Chrome window, then re-run "
                      f"(`python scripts/terapeak_topup.py {grader}` to resume this grader, "
                      f"or ALL). Grand total so far: +{grand_total} new rows.")
                sys.exit(3)
            grand_total += res
            if i < len(GRADERS) - 1:
                time.sleep(random.uniform(6.0, 10.0))

        print(f"\nALL DONE: +{grand_total} new rows across {len(GRADERS)} grader(s).")
        print("Next: run  python scripts/terapeak_load.py --new-only  to push to Supabase.")


if __name__ == "__main__":
    main()
