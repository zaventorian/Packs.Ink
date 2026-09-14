#!/usr/bin/env python3
"""
promo_capture.py — re-shoot the promo screenshots against the live site.

The August 2026 capture scripts lived in a session scratchpad and were lost, so
the kit could be re-assembled but not re-shot. This lives in scripts/ for that
reason: it is the only half of the regeneration path that was ever missing.

    python scripts/promo_capture.py --list
    python scripts/promo_capture.py                 # every shot, against prod
    python scripts/promo_capture.py --only d_home d_calendar
    python scripts/promo_capture.py --target http://localhost:8766

NO SECRET LIVES IN THIS FILE. The demo account's password is read from
`promo/build/demo_account.txt`, which is untracked and must stay that way — the
repo is public. Without that file the signed-out shots still run and the
signed-in ones are skipped with a note.

Onboarding overlays are suppressed in an init script rather than clicked away:
the welcome modal, the section coachmarks and the install nudge all mount over
the page and eat the clicks a shot's own steps need.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "promo", "shots")
CREDS = os.path.join(REPO, "promo", "build", "demo_account.txt")

SUPABASE_URL = "https://umwqowkiatjjltologrd.supabase.co"
SUPABASE_KEY = "sb_publishable_B2qq0Dsfij-7X2CZSxl2uQ_7PWc6Ob0"
AUTH_STORAGE_KEY = "sb-umwqowkiatjjltologrd-auth-token"

# 1600x900 at 1.2x lands on the 1920x1080 the graphics templates expect, with
# crisper text than shooting 1920 flat. Mobile matches an iPhone 12-17 Pro.
DESKTOP = dict(viewport={"width": 1600, "height": 900}, device_scale_factor=1.2)
MOBILE = dict(viewport={"width": 390, "height": 844}, device_scale_factor=3,
              is_mobile=True, has_touch=True)
TICKER = dict(viewport={"width": 1600, "height": 180}, device_scale_factor=1.2)

VIEWS = ["home", "screener", "history", "market", "cards", "collection",
         "decks", "faq", "gear", "calendar", "elo"]


def boot_script(session: dict | None, theme: str) -> str:
    """Runs before any page script, on every navigation."""
    seen = {f"packsink:sectionTourSeen:{v}": "1" for v in VIEWS}
    keys = {
        "packsink:tourSeen": "1",
        "packsink:installDismissed": "1",
        "packsink:installVisits": "99",
        "packsink:avatarPromptShown": "1",
        "packsink:gradedTos": "2026-06-23",
        "packsink:feedback:noticeDismissed": "2099-01-01T00:00:00.000Z",
        "packsink:themeMode": "dark" if theme == "dark" else "light",
        **seen,
    }
    if session:
        keys[AUTH_STORAGE_KEY] = json.dumps(session)
    return (
        "try{const k=" + json.dumps(keys) + ";"
        "for(const [a,b] of Object.entries(k)) localStorage.setItem(a,b);"
        "sessionStorage.setItem('packsink:autoTourFired','1');}catch(e){}"
    )


def sign_in() -> dict | None:
    if not os.path.exists(CREDS):
        return None
    kv = {}
    for line in open(CREDS, encoding="utf8"):
        if "=" in line:
            a, b = line.strip().split("=", 1)
            kv[a] = b
    req = urllib.request.Request(
        f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": kv["email"], "password": kv["password"]}).encode(),
        headers={"apikey": SUPABASE_KEY, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        s = json.load(r)
    s["expires_at"] = int(time.time()) + int(s.get("expires_in", 3600))
    return s


# ---------------------------------------------------------------- step helpers

def settle(page, ms=1200):
    page.wait_for_timeout(ms)


def click_if(page, sel, timeout=4000, ms=900):
    try:
        page.locator(sel).first.click(timeout=timeout)
        page.wait_for_timeout(ms)
        return True
    except Exception:
        return False


def wait_any(page, sels, timeout=20000):
    """First selector to appear wins; returns its index or -1."""
    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        for i, s in enumerate(sels):
            try:
                if page.locator(s).first.is_visible(timeout=250):
                    return i
            except Exception:
                pass
        page.wait_for_timeout(250)
    return -1


def type_search(page, sel, text, per=55):
    box = page.locator(sel).first
    box.click()
    box.type(text, delay=per)
    page.wait_for_timeout(1400)


def scroll_to(page, y):
    page.evaluate(f"window.scrollTo(0,{y})")
    page.wait_for_timeout(700)


# ---------------------------------------------------------------------- shots
# Each entry: name, path, device, auth, theme, and an optional steps callable.
# Paths lean on the site's own deep links (?c= ?m= ?a= ?cv= ?sczip=) rather than
# clicking through the nav — a URL is the one selector that cannot rot.

def s_search_cards(page):
    type_search(page, "input[placeholder^='Smart search']", "amber legendary under $20")
    page.keyboard.press("Enter")
    settle(page, 1800)


def s_open_card(page, query="enchanted elsa"):
    # A card from the newest set has blank 3M/6M/1Y columns and a 22-cent price:
    # true, and the worst possible advert for a price tracker. Shoot a chase card
    # with a real history instead.
    if query:
        type_search(page, "input[placeholder^='Smart search']", query)
        page.keyboard.press("Enter")
        settle(page, 2200)
    page.locator(".card-tile").first.click()
    wait_any(page, [".card-detail"], 15000)
    settle(page, 3000)


def s_open_card_graded(page):
    s_open_card(page)
    click_if(page, ".card-detail button:has-text('Graded')", 6000, 3200)
    # The per-sale scatter is the point of this shot — the table above it is the
    # summary, and the summary is what every other site already has.
    try:
        page.locator(".card-detail").first.evaluate(
            "el => {const s = el.closest('.card-detail-overlay') || el;"
            " (s.scrollTop !== undefined ? s : el).scrollTop += 760;}")
    except Exception:
        pass
    page.mouse.wheel(0, 700)
    settle(page, 2400)


def s_compare(page):
    box = page.locator("input[placeholder*='Search' i]").first
    for term in ["elsa spirit of winter", "mickey brave little", "stitch carefree"]:
        try:
            box.click()
            box.fill("")
            box.type(term, delay=40)
            page.wait_for_timeout(1500)
            page.locator("button.history-picker-item").first.click(timeout=5000)
            page.wait_for_timeout(1200)
        except Exception:
            pass
    settle(page, 2500)


def s_scan(page):
    click_if(page, "button:has-text('Scan')", 8000, 3000)


def s_deck_open(page):
    page.locator(".deck-card").first.click()
    settle(page, 3500)


def s_deck_poster(page):
    s_deck_open(page)
    click_if(page, ".deck-card-preview", 6000, 4500)


def s_pins_tidy(page):
    click_if(page, "button:has-text('Tidy up')", 6000, 2500)


def s_counters(page):
    click_if(page, "button:has-text('Counter board')", 8000, 2000)
    click_if(page, "button:has-text('Tidy up')", 5000, 2500)


def s_checklist(page):
    click_if(page, "button:has-text('Checklist')", 8000, 2500)


def s_graded_chart(page):
    """The per-sale scatter on its own — what card_graded.html is built from."""
    s_open_card(page)
    click_if(page, ".card-detail button:has-text('Graded')", 6000, 3200)
    page.mouse.wheel(0, 1100)
    settle(page, 2600)


def s_proxies(page):
    page.locator(".deck-card").first.click()
    settle(page, 3800)
    click_if(page, "button:has-text('Proxies')", 6000, 4200)


def s_dice_rolled(page):
    click_if(page, ".dice-roll-btn, button:has-text('Roll')", 6000, 3200)
    settle(page, 1800)


def s_scroll(y):
    return lambda page: scroll_to(page, y)


SHOTS = [
    # ---- home / signed out -------------------------------------------------
    ("d_home",               "/",                         "d", False, "dark",  None),
    ("d_home_scrolled",      "/",                         "d", False, "dark",  s_scroll(1150)),
    ("d_home_light",         "/",                         "d", False, "light", None),
    ("d_home_amazon",        "/",                         "d", False, "dark",  s_scroll(2300)),
    ("d_events_finder",      "/?sczip=60614&scdist=50",   "d", False, "dark",  None),
    # ---- calendar (new since the August kit) -------------------------------
    ("d_calendar",           "/calendar",                 "d", False, "dark",  None),
    ("d_calendar_month",     "/calendar?cv=month",        "d", False, "dark",  None),
    # ---- cards -------------------------------------------------------------
    ("d_cards",              "/cards",                    "d", False, "dark",  None),
    ("d_cards_search",       "/cards",                    "d", False, "dark",  s_search_cards),
    ("d_card_detail",        "/cards",                    "d", False, "dark",  s_open_card),
    ("d_card_detail_graded", "/cards",                    "d", False, "dark",  s_open_card_graded),
    # ---- screener ----------------------------------------------------------
    ("d_screener",           "/screener",                 "d", False, "dark",  None),
    ("d_screener_graded",    "/screener?m=graded",        "d", False, "dark",  None),
    ("d_screener_sealed",    "/screener?m=sealed",        "d", False, "dark",  None),
    # ---- price graphing ----------------------------------------------------
    ("d_graphing_start",     "/price-graphing",           "d", False, "dark",  None),
    ("d_graphing_compare",   "/price-graphing",           "d", False, "dark",  s_compare),
    ("d_graphing_graded",    "/price-graphing?hm=graded", "d", False, "dark",  None),
    ("d_graphing_index",     "/price-graphing?hm=index",  "d", False, "dark",  None),
    # ---- decks -------------------------------------------------------------
    ("d_decks",              "/decks",                    "d", False, "dark",  None),
    ("d_decks_coconut",      "/decks?f=coconut",          "d", False, "dark",  None),
    ("d_deck_view",          "/decks",                    "d", False, "dark",  s_deck_open),
    ("d_deck_poster",        "/decks",                    "d", False, "dark",  s_deck_poster),
    # ---- analytics ---------------------------------------------------------
    ("d_analytics_ev",       "/analytics?a=ev",           "d", False, "dark",  None),
    ("d_analytics_avg",      "/analytics?a=avg",          "d", False, "dark",  None),
    ("d_sim",                "/analytics?a=sim",          "d", False, "dark",  None),
    ("d_swiss",              "/analytics?a=swiss",        "d", False, "dark",  None),
    ("d_lore",               "/analytics?a=lore",         "d", False, "dark",  None),
    ("d_trade",              "/analytics?a=trade",        "d", False, "dark",  None),
    # ---- other surfaces ----------------------------------------------------
    ("d_gear",               "/gear",                     "d", False, "dark",  None),
    ("d_faq",                "/how-it-works",             "d", False, "dark",  None),
    ("d_ticker_config",      "/ticker",                   "d", False, "dark",  None),
    ("d_scan_consent",       "/cards",                    "d", False, "dark",  s_scan),
    # ---- signed in (demo account) ------------------------------------------
    ("d_home_signedin",      "/",                         "d", True,  "dark",  None),
    ("d_collection",         "/collection?c=cards",       "d", True,  "dark",  None),
    ("d_collection_sealed",  "/collection?c=sealed",      "d", True,  "dark",  None),
    ("d_collection_graded",  "/collection?c=graded",      "d", True,  "dark",  None),
    ("d_collection_pins",    "/collection?c=pins",        "d", True,  "dark",  s_pins_tidy),
    ("d_collection_counters", "/collection?c=pins",       "d", True,  "dark",  s_counters),
    ("d_collection_checklist", "/collection?c=pins",      "d", True,  "dark",  s_checklist),
    # ---- mobile ------------------------------------------------------------
    ("m_home",               "/",                         "m", False, "dark",  None),
    ("m_home_signedin",      "/",                         "m", True,  "dark",  None),
    ("m_cards",              "/cards",                    "m", False, "dark",  None),
    ("m_card_detail",        "/cards",                    "m", False, "dark",  s_open_card),
    ("m_screener",           "/screener",                 "m", False, "dark",  None),
    ("m_calendar",           "/calendar",                 "m", False, "dark",  None),
    ("m_collection",         "/collection?c=cards",       "m", True,  "dark",  None),
    ("m_collection_pins",    "/collection?c=pins",        "m", True,  "dark",  s_pins_tidy),
    ("m_lore",               "/analytics?a=lore",         "m", False, "dark",  None),
    ("m_decks",              "/decks",                    "m", False, "dark",  None),
    # ---- re-shoots of assets the kit/graphics still reference ---------------
    ("d_graded_scatter",       "/cards",                    "d", False, "dark",  s_graded_chart),
    ("d_graded_scatter_chart", "/cards",                    "d", False, "dark",  s_graded_chart),
    ("d_deck_proxies",         "/decks?f=coconut",          "d", False, "dark",  s_proxies),
    ("d_dice_rolled",          "/analytics?a=dice",         "d", False, "dark",  s_dice_rolled),
    ("d_swiss_embed",          "/analytics?a=swiss",        "d", False, "dark",  None),
    ("d_ticker_bar",           "/ticker?bar=1",             "t", False, "dark",  None),
    ("m_collection_graded",    "/collection?c=graded",      "m", True,  "dark",  None),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", default="https://packs.ink")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--settle", type=int, default=7000,
                    help="ms to wait after load before steps run (data has to land)")
    a = ap.parse_args()

    if a.list:
        for s in SHOTS:
            print(f"{s[0]:26s} {s[2]}  {'auth' if s[3] else '    '}  {s[1]}")
        return 0

    shots = [s for s in SHOTS if not a.only or s[0] in a.only]
    if not shots:
        print("no shots matched")
        return 1

    session = sign_in()
    if not session:
        print(f"! no {CREDS} — signed-in shots will be skipped")
    os.makedirs(OUT, exist_ok=True)

    from playwright.sync_api import sync_playwright
    ok = fail = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, path, dev, auth, theme, steps in shots:
            if auth and not session:
                print(f"  skip {name} (needs sign-in)")
                continue
            ctx = None
            try:
                ctx = browser.new_context(**{"d": DESKTOP, "m": MOBILE, "t": TICKER}[dev])
                ctx.add_init_script(boot_script(session if auth else None, theme))
                page = ctx.new_page()
                page.goto(a.target + path, wait_until="domcontentloaded", timeout=90000)
                page.wait_for_timeout(a.settle)
                if steps:
                    steps(page)
                page.screenshot(path=os.path.join(OUT, name + ".png"))
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
    print(f"\n{ok} captured, {fail} failed -> {OUT}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
