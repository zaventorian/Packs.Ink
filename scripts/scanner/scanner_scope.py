"""
What the scanner is allowed to answer: every card the site itself renders.

The index is built from the `cards` table, but the client drops some of those
rows in transformSupabaseData, and a scan that answers one of them proposes a
card the catalog does not have. The review row resolves ids through the
scanner's own index, not the catalog, so nothing downstream catches it.

- The Format Coconut set. The client drops every raw Coconut row and puts its
  own synthetic `coconut::<slug>` rows in their place, which are unownable by
  design. Their names and versions also match the real cards they are drawn
  from, so the first index that carried them lost 20 clean reads of real
  released cards to them.
- SUPPRESSED_CARD_IDS. Lorcast rows the site refuses to carry. Read out of
  Index.html rather than copied, so the two lists cannot drift apart.

- A card with no image at all. The colour index needs art to descriptor, and
  the text index must never hold an id the colour index lacks: the review row
  resolves through the colour index's list, so an id only text.json knows is
  named by the matcher and then silently dropped.

fetch_cards.py (index.json / color.bin / dhash.bin) and build_text_index.py
(text.json) both filter through here, so the two halves of the index agree.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

EXCLUDED_SET_CODES = {"COCONUT"}

_SUPPRESSED_RE = re.compile(r"const SUPPRESSED_CARD_IDS\s*=\s*new Set\(\[(.*?)\]\);", re.S)


def suppressed_card_ids(index_html: Path | None = None) -> set[str]:
    src = (index_html or REPO / "Index.html").read_text(encoding="utf-8")
    m = _SUPPRESSED_RE.search(src)
    if not m:
        # Fail loudly: a renamed const would otherwise let every suppressed row
        # back into the index with nothing to say so.
        raise SystemExit("scanner_scope: SUPPRESSED_CARD_IDS not found in Index.html")
    return set(re.findall(r'"(crd_[0-9A-Za-z_]+)"', m.group(1)))


def excluded_set_ids(sets: list[dict]) -> set[str]:
    return {s["id"] for s in sets if (s.get("code") or "").strip().upper() in EXCLUDED_SET_CODES}


def in_scope(card_id: str, set_id: str | None, bad_sets: set[str], bad_ids: set[str]) -> bool:
    return card_id not in bad_ids and set_id not in bad_sets


IMAGE_COLUMNS = ("image_normal", "image_large", "image_small")


def card_image(row: dict) -> str | None:
    """The card's art: the first non-empty image column. Lorcast fills only
    `image_large` on a few Challenge Promo cards and leaves `image_normal` an
    EMPTY STRING, which passes a `not.is.null` filter and then fails `if not url`,
    so those cards reached text.json and never reached the colour index — the
    matcher could name them and the review row could not resolve them. The
    catalog's own buildRow falls back the same way (normal -> large -> small)."""
    for k in IMAGE_COLUMNS:
        v = (row.get(k) or "").strip()
        if v:
            return v
    return None
