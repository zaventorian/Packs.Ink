r"""probe_pop_report.py - READ-ONLY reconnaissance on a grader's population report.

    powershell -File scripts\graded_run.ps1 -DryRun      # get Chrome up + logged in
    python scripts\probe_pop_report.py --url "<a PSA or CGC pop page>"

WHY THIS EXISTS, AND WHY IT IS NOT A SCRAPER
--------------------------------------------
A population report answers the one question `graded_sales` cannot: how many of
this card exist at this grade. Sales tell you what people paid; pop tells you
what the supply is, and a PSA 10 that is 1-of-3 is a different asset from one
that is 1-of-900 at the same price.

But nothing about the page shape can be learned from an agent sandbox. PSA
(collectors.com) answers a Cloudflare interstitial and CGC 500s, both from a
datacenter IP - confirmed 2026-09-21. So a parser written from here would be
invented, and an invented parser fails the way every bad-data path in this repo
fails: silently, with confident numbers attached to the wrong card.

This script therefore PARSES NOTHING and STORES NOTHING. It opens a page in the
browser you are already logged into, reports what is actually on it, and exits.
Its output is the input to writing the real loader.

RULES IT INHERITS FROM THE GRADED SCRAPER
-----------------------------------------
  * Attach over CDP to a real, user-launched Chrome. A Playwright-launched
    browser sets navigator.webdriver and is refused; yours is not.
  * A challenge page is a FULL STOP, never a retry. Hammering a soft check is
    exactly what escalates it into an account-level flag.
  * One page at a time, with a pause between. There is no rush - this runs once.
  * Output goes to scripts/pop_output/, NEVER scripts/terapeak_output/, whose
    glob would happily swallow a foreign file and load it as graded sales.

Exit codes: 0 ok | 2 Chrome not reachable | 3 challenge/blocked | 1 anything else.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "pop_output"

# Same three-way detection as terapeak_scrape.detect_challenge: a wall can show
# up in the URL, as an element, or as nothing but body text on the same URL.
_BLOCK_URL_BITS = ("captcha", "challenge", "verify", "blocked", "attention-required")
_BLOCK_TEXT_BITS = (
    "verify you are a human", "are you a human", "unusual activity", "unusual traffic",
    "checking your browser", "attention required", "you have been blocked",
    "access denied", "enable javascript and cookies", "security challenge",
    "confirm you're not a robot", "press and hold", "cloudflare ray id",
)

# What the page looks like, reported rather than assumed. PSA's report has been
# a server-rendered <table>; CGC's is React and may be a div grid with ARIA
# roles, so both shapes are walked and whichever is present gets described.
_DESCRIBE_JS = r"""
() => {
  const txt = (el) => (el ? (el.innerText || "").trim().replace(/\s+/g, " ") : "");
  const cells = (row) =>
    Array.from(row.querySelectorAll("th,td,[role=columnheader],[role=cell],[role=gridcell]"))
      .map((c) => txt(c).slice(0, 60));

  const describe = (t, kind) => {
    const rows = Array.from(
      t.querySelectorAll("tr,[role=row]")
    ).filter((r) => r.closest("table,[role=table],[role=grid]") === t);
    const head = rows.length ? cells(rows[0]) : [];
    return {
      kind,
      classes: (t.className || "").toString().slice(0, 120),
      id: t.id || null,
      rowCount: rows.length,
      headers: head,
      sampleRows: rows.slice(1, 4).map(cells),
    };
  };

  const tables = [
    ...Array.from(document.querySelectorAll("table")).map((t) => describe(t, "table")),
    ...Array.from(document.querySelectorAll("[role=table],[role=grid]")).map((t) =>
      describe(t, "aria")
    ),
  ].filter((t) => t.rowCount > 1);

  // Grade columns are the tell that a table is the pop report rather than a
  // nav or a footer: PSA runs 1..10 plus halves and qualifiers, CGC similar.
  const gradeish = (h) => /^(psa|cgc|bgs|sgc)?\s*\d{1,2}(\.5)?$/i.test(h.trim());

  return {
    url: location.href,
    title: document.title,
    bodyChars: (document.body ? document.body.innerText : "").length,
    headingSample: Array.from(document.querySelectorAll("h1,h2,h3"))
      .slice(0, 8)
      .map((h) => txt(h).slice(0, 90)),
    tables: tables.map((t) => ({
      ...t,
      gradeHeaderCount: t.headers.filter(gradeish).length,
    })),
    // A React app that has not finished hydrating looks exactly like a page with
    // no table on it, so say which so the reader can wait longer instead of
    // concluding the report moved.
    looksReact: !!(document.querySelector("#__next,#root,[data-reactroot]")),
    links: Array.from(document.querySelectorAll("a[href]"))
      .map((a) => a.getAttribute("href"))
      .filter((h) => /pop|population|set|cert/i.test(h || ""))
      .slice(0, 25),
  };
}
"""


def looks_blocked(page) -> tuple[bool, str]:
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""
    for bit in _BLOCK_URL_BITS:
        if bit in url:
            return True, f"url contains {bit!r}"
    try:
        body = (page.inner_text("body") or "").lower()[:4000]
    except Exception:
        body = ""
    for bit in _BLOCK_TEXT_BITS:
        if bit in body:
            return True, f"page text says {bit!r}"
    try:
        if page.query_selector("iframe[src*='captcha'], iframe[src*='challenge'], #challenge-form"):
            return True, "a captcha/challenge frame is present"
    except Exception:
        pass
    return False, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", required=True,
                    help="A population-report URL. Repeat for several; they are "
                         "visited one at a time with --wait between.")
    ap.add_argument("--cdp", default="http://localhost:9222",
                    help="CDP endpoint of a Chrome YOU launched (default %(default)s).")
    ap.add_argument("--wait", type=float, default=6.0,
                    help="Seconds to settle after load, and between URLs (default %(default)s).")
    ap.add_argument("--save-html", action="store_true",
                    help="Also save the raw HTML, for writing selectors against.")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed in this interpreter.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {"probed_at": stamp, "pages": []}

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp(args.cdp)
        except Exception as e:
            print(f"Could not attach to Chrome at {args.cdp}: {e}", file=sys.stderr)
            print("Launch it first:  scripts\\graded_run.ps1 -DryRun", file=sys.stderr)
            return 2

        ctx = browser.contexts[0] if browser.contexts else browser.new_context()
        # ⚠ A NEW tab, never ctx.pages[0]. The graded scraper reuses the front
        # tab because that IS its tab; this browser also carries a live Terapeak
        # research session, and navigating it away to read a pop report would
        # throw away a login that is expensive to get back. The probe cleans up
        # its own tab and leaves every other one exactly as it found it.
        page = ctx.new_page()
        opened_page = True

        for i, url in enumerate(args.url):
            if i:
                time.sleep(args.wait)
            print(f"\n=== {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print(f"  navigation failed: {e}")
                report["pages"].append({"requested": url, "error": str(e)})
                continue
            time.sleep(args.wait)

            blocked, why = looks_blocked(page)
            if blocked:
                # STOP. Do not try the next URL, do not reload. A soft check that
                # is hammered becomes a hard one, and this browser carries a real
                # login worth more than this probe.
                print(f"  BLOCKED: {why}")
                print("  Stopping. Clear it by hand in that Chrome window, then re-run.")
                report["pages"].append({"requested": url, "final": page.url,
                                        "blocked": True, "why": why})
                (OUT_DIR / f"pop_probe_{stamp}.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8")
                return 3

            try:
                info = page.evaluate(_DESCRIBE_JS)
            except Exception as e:
                print(f"  could not describe the page: {e}")
                report["pages"].append({"requested": url, "final": page.url, "error": str(e)})
                continue

            info["requested"] = url
            report["pages"].append(info)

            print(f"  title    : {info['title'][:90]}")
            print(f"  final url: {info['url']}")
            print(f"  body     : {info['bodyChars']} chars"
                  + ("  [React app]" if info["looksReact"] else ""))
            if info["headingSample"]:
                print(f"  headings : {' | '.join(info['headingSample'][:4])}")
            if not info["tables"]:
                print("  NO TABLE FOUND. If this is a React app it may still have been")
                print("  hydrating -- re-run with a larger --wait before concluding.")
            for t in info["tables"]:
                print(f"  - {t['kind']} rows={t['rowCount']} "
                      f"gradeCols={t['gradeHeaderCount']} class={t['classes'][:50]!r}")
                print(f"      headers: {t['headers'][:14]}")
                for r in t["sampleRows"][:2]:
                    print(f"      row    : {r[:14]}")

            if args.save_html:
                f = OUT_DIR / f"pop_{stamp}_{i}.html"
                f.write_text(page.content(), encoding="utf-8")
                print(f"  html saved: {f}")

        if opened_page:
            try:
                page.close()
            except Exception:
                pass

    out = OUT_DIR / f"pop_probe_{stamp}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    print("Paste the section above (or attach that JSON) and the loader can be written "
          "against what is really there.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
