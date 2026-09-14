#!/usr/bin/env python3
"""
promo_video.py — record the raw screen segments the promo videos are cut from.

Pipeline: this script writes `promo/video/segments/seg_<name>.webm`, then
`promo/build/assemble.mjs` cuts each segment, lays an overlay caption plate on
top, and concatenates the result into `tour_main.mp4` and the feature shorts.

    python scripts/promo_video.py --list
    python scripts/promo_video.py --only seg_calendar seg_pins
    python scripts/promo_video.py                 # every segment

⚠ assemble.mjs clips each segment from its END (`fromEnd`/`take`), so every
segment here must FINISH on the frame worth showing and hold there for a beat.
A segment that ends mid-scroll cuts to a blur, and the failure only shows up
after assembly, in the finished file.

Recording is 1920x1080 to match the plates in `promo/video/overlays/`; Playwright
writes 25fps VP8 and assemble.mjs resamples to 30. Sign-in and the onboarding
suppression are shared with promo_capture.py so the two can't drift.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from promo_capture import boot_script, sign_in, settle, click_if, type_search, scroll_to  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEGS = os.path.join(REPO, "promo", "video", "segments")
TMP = os.path.join(REPO, "promo", "video", "_raw")

SIZE = {"width": 1920, "height": 1080}
# assemble_mobile.mjs scales 780x1688 up to a padded 1080x1920, so the phone
# segments must record at exactly that — a different size letterboxes wrong.
MSIZE = {"width": 780, "height": 1688}
MVIEW = {"width": 390, "height": 844}


def is_mobile(name: str) -> bool:
    return name.startswith("seg_m_")


# ------------------------------------------------------------------ segments
# Each takes (page) and should end holding on the payoff for ~2s.

def seg_home(page):
    # Ends back at the top: the movers banners under the search box are the
    # frame worth holding, and the rails below them read as clutter at 1080p.
    settle(page, 3500)
    scroll_to(page, 520)
    settle(page, 2500)
    scroll_to(page, 1100)
    settle(page, 2600)
    scroll_to(page, 0)
    settle(page, 3400)


def seg_search(page):
    settle(page, 1500)
    type_search(page, "input[placeholder^='Smart search']",
                "amber legendary under $20", per=95)
    page.keyboard.press("Enter")
    settle(page, 4200)


def seg_detail(page):
    type_search(page, "input[placeholder^='Smart search']", "enchanted elsa", per=80)
    page.keyboard.press("Enter")
    settle(page, 2200)
    page.locator(".card-tile").first.click()
    settle(page, 3000)
    page.mouse.wheel(0, 620)
    settle(page, 2200)
    for label in ["6M", "1Y"]:
        click_if(page, f".card-detail button:has-text('{label}')", 3000, 1900)
    settle(page, 1800)


def seg_screener(page):
    settle(page, 2500)
    click_if(page, "button:has-text('Gainers')", 6000, 2200)
    click_if(page, ".price-db-winbtns button:has-text('1W'), button:has-text('1W')", 5000, 2200)
    page.mouse.wheel(0, 420)
    settle(page, 3200)


def seg_graded(page):
    type_search(page, "input[placeholder^='Smart search']", "enchanted elsa", per=80)
    page.keyboard.press("Enter")
    settle(page, 2200)
    page.locator(".card-tile").first.click()
    settle(page, 2600)
    click_if(page, ".card-detail button:has-text('Graded')", 6000, 2800)
    page.mouse.wheel(0, 700)
    settle(page, 3400)


def seg_graphing(page):
    settle(page, 2200)
    box = page.locator("input[placeholder*='Search' i]").first
    for term in ["elsa ice artisan", "mickey brave little tailor", "stitch rock star"]:
        try:
            box.click(); box.fill("")
            box.type(term, delay=55)
            page.wait_for_timeout(1400)
            page.locator("button.history-picker-item").first.click(timeout=5000)
            page.wait_for_timeout(1300)
        except Exception:
            pass
    for label in ["1Y", "Since Release"]:
        click_if(page, f"button:has-text('{label}')", 3500, 2100)
    settle(page, 2200)


def seg_collection(page):
    settle(page, 4000)
    page.mouse.wheel(0, 500)
    settle(page, 2600)
    for tab in ["Sealed", "Graded"]:
        click_if(page, f".collection-section-tab:has-text('{tab}')", 5000, 3200)
    settle(page, 2000)


def seg_pins(page):
    settle(page, 4500)
    click_if(page, "button:has-text('Tidy up')", 6000, 3000)
    click_if(page, "button:has-text('Counter board')", 5000, 3400)
    click_if(page, "button:has-text('Pin board')", 5000, 3200)
    settle(page, 2200)


def seg_calendar(page):
    settle(page, 3500)
    click_if(page, "button:has-text('Month')", 5000, 3200)
    click_if(page, "button:has-text('List')", 5000, 2600)
    click_if(page, ".cal-chip:has-text('CCQ'), button:has-text('CCQs')", 4000, 2800)
    settle(page, 2600)


def seg_decks(page):
    # ⚠ .deck-card-preview is the corner button on a deck TILE, not a control in
    # the editor — clicking the tile first navigates away from it, which is how
    # this segment previously ended on a half-scrolled editor instead of the
    # poster. Open the poster straight off the tile.
    #
    # ⚠ And it runs on the DEMO ACCOUNT'S OWN deck, never Discover's first tile:
    # that one is a tournament deck, and those are sourced from other sites, so
    # they must not be spotlighted in promo material.
    settle(page, 3500)
    page.locator(".deck-card-preview").first.click()
    # The poster lazily fetches ~20 card images; holding only ~5s left three
    # cells blank in the finished frame. Wait for the art, then hold.
    page.wait_for_timeout(4000)
    try:
        page.wait_for_function(
            "() => {const i=[...document.querySelectorAll('.poster-view-stage img,"
            " .deck-poster img')]; return i.length>0 && i.every(x => x.complete &&"
            " x.naturalWidth > 0);}", timeout=25000)
    except Exception:
        pass
    settle(page, 4000)


def seg_lore(page):
    # The score buttons are the big numbers themselves (.lore-tap); an empty
    # 0-0 board is a screenshot of nothing.
    settle(page, 3000)
    seats = page.locator(".lore-tap")
    for i, taps in enumerate((13, 8)):
        try:
            seat = seats.nth(i)
            for _ in range(taps):
                seat.click(timeout=2500)
                page.wait_for_timeout(190)
        except Exception:
            pass
    settle(page, 3200)


def seg_ev(page):
    settle(page, 3500)
    page.mouse.wheel(0, 300)
    settle(page, 2200)
    click_if(page, ".ev-row-simbtn", 6000, 3200)
    for _ in range(2):
        click_if(page, "button:has-text('Open')", 4000, 2600)
    settle(page, 2400)


def seg_swiss(page):
    settle(page, 4000)
    page.mouse.wheel(0, 260)
    settle(page, 2200)
    click_if(page, "button:has-text('Run')", 5000, 4200)
    settle(page, 3000)


def seg_m_home(page):
    settle(page, 3500)
    scroll_to(page, 380)
    settle(page, 2600)
    scroll_to(page, 900)
    settle(page, 2600)
    scroll_to(page, 200)
    settle(page, 2600)


def seg_m_cards(page):
    settle(page, 1500)
    type_search(page, "input[placeholder^='Smart search']", "ench elsa", per=110)
    page.keyboard.press("Enter")
    settle(page, 4200)


def seg_m_screener(page):
    settle(page, 2500)
    click_if(page, "button:has-text('Gainers')", 6000, 2400)
    page.mouse.wheel(0, 380)
    settle(page, 3400)


def seg_m_collection(page):
    settle(page, 4000)
    page.mouse.wheel(0, 380)
    settle(page, 2600)
    click_if(page, ".collection-section-tab:has-text('Graded')", 5000, 3400)
    settle(page, 2000)


SEGMENTS = [
    # name,            path,                        auth,  fn
    ("seg_home",       "/",                          False, seg_home),
    ("seg_search",     "/cards",                     False, seg_search),
    ("seg_detail",     "/cards",                     False, seg_detail),
    ("seg_screener",   "/screener",                  False, seg_screener),
    ("seg_graded",     "/cards",                     False, seg_graded),
    ("seg_graphing",   "/price-graphing",            False, seg_graphing),
    ("seg_calendar",   "/calendar",                  False, seg_calendar),
    ("seg_decks",      "/decks?s=yours",             True,  seg_decks),
    ("seg_ev",         "/analytics?a=ev",            False, seg_ev),
    ("seg_swiss",      "/analytics?a=swiss",         False, seg_swiss),
    ("seg_lore",       "/analytics?a=lore",          False, seg_lore),
    ("seg_collection", "/collection?c=cards",        True,  seg_collection),
    ("seg_pins",       "/collection?c=pins",         True,  seg_pins),
    # ---- vertical 9:16, for tour_mobile.mp4 --------------------------------
    ("seg_m_home",     "/",                          False, seg_m_home),
    ("seg_m_cards",    "/cards",                     False, seg_m_cards),
    ("seg_m_screener", "/screener",                  False, seg_m_screener),
    ("seg_m_collection", "/collection?c=cards",      True,  seg_m_collection),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="https://packs.ink")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for n, p, auth, _ in SEGMENTS:
            print(f"{n:16s} {'auth' if auth else '    '}  {p}")
        return 0

    segs = [s for s in SEGMENTS if not a.only or s[0] in a.only]
    if not segs:
        print("no segments matched")
        return 1

    session = sign_in()
    os.makedirs(SEGS, exist_ok=True)
    os.makedirs(TMP, exist_ok=True)

    from playwright.sync_api import sync_playwright
    ok = fail = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, path, auth, fn in segs:
            if auth and not session:
                print(f"  skip {name} (needs sign-in)")
                continue
            ctx = None
            try:
                mob = is_mobile(name)
                ctx = browser.new_context(
                    viewport=MVIEW if mob else SIZE,
                    device_scale_factor=2 if mob else 1,
                    is_mobile=mob, has_touch=mob,
                    record_video_dir=TMP,
                    record_video_size=MSIZE if mob else SIZE)
                ctx.add_init_script(boot_script(session if auth else None, "dark"))
                page = ctx.new_page()
                page.goto(a.target + path, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(7000)
                fn(page)
                video = page.video
                ctx.close()          # the webm is only flushed on close
                ctx = None
                dest = os.path.join(SEGS, name + ".webm")
                shutil.move(video.path(), dest)
                print(f"  ok   {name}")
                ok += 1
            except Exception as e:
                print(f"  FAIL {name}: {str(e)[:140]}")
                fail += 1
            finally:
                if ctx:
                    try:
                        ctx.close()
                    except Exception:
                        pass
        browser.close()
    print(f"\n{ok} recorded, {fail} failed -> {SEGS}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
