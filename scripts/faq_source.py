"""
faq_source.py - the How-it-works (FAQ) page body as plain HTML, for translation.

    python scripts/faq_source.py            # print the English body
    python scripts/faq_source.py --hash     # print its hash

FAQView in Index.html writes the page as an htm template. Everything from the
first <h2> to the close of the English branch of its I18N.faqHtml ternary is
static prose; its only interpolations are literal strings (${"cost<=2"}) and the accent-link style.
This turns that into HTML so a translator (i18n/src/faq/<lang>.html) works on
the real page, and build_i18n.py bakes each translation into the dictionary
as I18N.faqHtml along with the hash of the English it was translated from.
A changed English FAQ makes build_i18n.py warn that the translations are
behind; the translated page keeps rendering until they are redone.
"""
from __future__ import annotations

import hashlib
import html as _html
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def faq_body() -> str:
    with open(os.path.join(ROOT, "Index.html"), encoding="utf-8-sig") as f:
        s = f.read()
    i = s.index("function FAQView(")
    a = s.index("<h2>What is Packs.Ink?</h2>", i)
    b = s.index("\n    `}\n  </div>`;\n}", a)   # the English branch of FAQView's faqHtml ternary
    body = s[a:b].rstrip()
    body = body.replace('style=${{color:"var(--accent)"}}', 'class="faq-link"')
    body = re.sub(r'\$\{"((?:[^"\\]|\\.)*)"\}', lambda m: _html.escape(m.group(1)), body)
    if "${" in body:
        raise SystemExit("faq_source: an unexpected ${...} in the FAQ body - teach faq_source.py about it")
    return re.sub(r"\n[ \t]+", "\n", body).strip() + "\n"


def faq_hash(body: str | None = None) -> str:
    return hashlib.sha1((body or faq_body()).encode("utf8")).hexdigest()[:12]


if __name__ == "__main__":
    b = faq_body()
    sys.stdout.reconfigure(encoding="utf-8")
    print(faq_hash(b) if "--hash" in sys.argv else b)
