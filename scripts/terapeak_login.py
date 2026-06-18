"""
terapeak_login.py — one-time interactive login to eBay, saves the browser
session state to .terapeak_state.json so the scraper can reuse it without
prompting for credentials each run.

Run this manually whenever the saved session expires (typically every few
weeks). The scraper exits with a clear error when re-login is needed.

Usage:
    pip install -r scripts/requirements.txt
    playwright install chromium
    python scripts/terapeak_login.py

What happens:
    1. Opens a real Chrome window (headful — you can see it)
    2. Navigates to eBay sign-in
    3. Waits for you to log in manually (including 2FA, CAPTCHAs if any)
    4. After login, navigates to Terapeak to confirm access works
    5. You press Enter in this terminal to save the session
    6. Saves cookies + localStorage to scripts/.terapeak_state.json
    7. Closes the browser

Security notes:
    - .terapeak_state.json contains live session cookies and should be
      treated like a password. It's added to .gitignore by convention.
    - Use the DEDICATED research eBay account, not your personal account.
    - On the VPS, run via X-forwarding or set HEADFUL_LOGIN=0 to use a
      one-time pairing code flow (TBD).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
SESSION_STATE = HERE / ".terapeak_state.json"
LOGIN_URL = "https://www.ebay.com/signin"
TERAPEAK_URL = "https://www.ebay.com/sh/research"


def main() -> None:
    if SESSION_STATE.exists():
        ans = input(
            f"{SESSION_STATE.name} already exists. Overwrite? [y/N] "
        ).strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    with sync_playwright() as p:
        # --disable-blink-features=AutomationControlled drops the
        # navigator.webdriver flag, which is the main signal eBay/Google use to
        # decide a browser is "not secure" / automated. Doesn't defeat Google's
        # full bot check (use eBay's email-code login, NOT "Sign in with
        # Google"), but cuts down on eBay-side challenge redirects.
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1400, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        print()
        print("=" * 70)
        print("eBay login — manual step")
        print("=" * 70)
        print("A Chrome window just opened.")
        print()
        print("1. Sign in with the DEDICATED RESEARCH ACCOUNT (NOT your main).")
        print("2. Complete any 2FA / CAPTCHA challenges.")
        print(f"3. Navigate to {TERAPEAK_URL} and confirm you can see the")
        print("   Product Research page (table of sold listings).")
        print("4. Come back here and press Enter to save the session.")
        print()

        page.goto(LOGIN_URL)

        input("Press Enter once you're logged in and Terapeak loads... ")

        # Save the session FIRST so a flaky verification nav can never lose it.
        # (eBay redirects mid-navigation, which makes page.goto raise
        # "interrupted by another navigation" — that must NOT cost us the login.)
        context.storage_state(path=str(SESSION_STATE))
        print()
        print(f"Saved session state to {SESSION_STATE}")

        try:
            print(f"Current page when you pressed Enter: {page.url}")
        except Exception:
            pass

        # Best-effort verification: try to reach Terapeak and report the final
        # URL. wait_until='commit' + a manual settle tolerates eBay's redirect
        # chains instead of throwing on them.
        final_url, title = "", ""
        try:
            page.goto(TERAPEAK_URL, wait_until="commit", timeout=30000)
            page.wait_for_timeout(5000)  # let any redirect chain settle
        except Exception as e:
            print(f"[note] verification nav reported: {type(e).__name__}: {e}")
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            pass
        try:
            final_url = page.url
            title = page.title()
        except Exception:
            pass

        print(f"Final URL after Terapeak check: {final_url}")
        print(f"Final page title: {title!r}")

        low = final_url.lower()
        if "/sh/research" in low:
            print("[ok] Reached Terapeak Product Research. Re-saving session "
                  "with Seller Hub cookies.")
            try:
                context.storage_state(path=str(SESSION_STATE))
            except Exception:
                pass
        elif "signin" in low or "login" in low or "accounts.google" in low:
            print("[warn] Bounced to a sign-in page — the session isn't fully "
                  "authenticated. Log in with eBay's EMAIL/TEXT CODE (not the "
                  "Google button), then load /sh/research BY HAND in the window "
                  "and confirm the research table renders BEFORE pressing Enter.")
        else:
            print("[warn] Did NOT land on /sh/research. Most likely the burner "
                  "account doesn't have Seller Hub / Product Research access yet "
                  "(seller-registration / Store gate). Session is still saved; "
                  "tell me the Final URL above and we'll sort the access path.")
        print()
        print("You can now run: python scripts/terapeak_scrape.py")

        browser.close()


if __name__ == "__main__":
    main()
