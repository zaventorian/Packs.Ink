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
        browser = p.chromium.launch(headless=False)
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

        # Sanity check: confirm we can reach Terapeak after login
        page.goto(TERAPEAK_URL)
        page.wait_for_load_state("domcontentloaded")
        title = page.title()
        url = page.url
        if "signin" in url.lower() or "login" in url.lower():
            sys.exit(
                f"Still on a sign-in page (url={url}). Login didn't take. "
                "Try again."
            )

        context.storage_state(path=str(SESSION_STATE))
        print()
        print(f"Saved session state to {SESSION_STATE}")
        print(f"Final page title: {title!r}")
        print(f"Final URL: {url}")
        print()
        print("You can now run: python scripts/terapeak_scrape.py")

        browser.close()


if __name__ == "__main__":
    main()
