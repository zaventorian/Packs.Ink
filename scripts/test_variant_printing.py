"""
test_variant_printing.py - guard the NAMED-VARIANT printing axis.

A few cards' graded sales split on a variant rather than a finish: the error
print shares one card_id with the base, and graded_sales_rollup keeps the two
apart because cards.split_printing is true. The ::variant:: catalog tile is
raw-only and deliberately has NO graded market of its own.

That means the SAME two card ids have to be listed in three places, in two
languages, and nothing errors when they drift -- the sales just quietly pile up
in the wrong bucket, which is how Peter Pan #215 ended up with 19 rows filed
Normal and 21 with no printing at all against a real ~49% premium.

No network.

    python scripts/test_variant_printing.py
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("SUPABASE_URL", "https://example.invalid")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

import terapeak_load as L  # noqa: E402

PP = "crd_b5e74b533270492982dff9472aee8664"   # Peter Pan - Pirate's Bane  Ench #215
GE = "crd_ae7e91462bfc4861bbf97e99ed53a1c1"   # Genie - On the Job         Ench #209

FAILS, N = [], [0]


def check(cond, label):
    N[0] += 1
    print(("  ok    " if cond else "  FAIL  ") + label)
    if not cond:
        FAILS.append(label)


def main():
    print("\n1. the variant name is read off the title")
    for t in ("Peter Pan Pirate's Bane Enchanted - Text Error PSA 10",
              "2024 Disney Lorcana En 3 Peter Pan Enchanted-Text Error PSA Gem Mint 10",
              "LORCANA INTO THE INKLANDS #215 ENCHANTED TEXT ERR PETER PAN",
              "Peter Pan Enchanted Errata Error Card"):
        got = L.variant_printing_for(PP, t)
        check(got == "Text Error", "'Text Error' from: %s" % t[:52])
    check(L.variant_printing_for(GE, "Genie On the Job Enchanted Two Swords PSA 10") == "Two Swords",
          "'Two Swords' from the Genie variant title")

    print("\n2. silence means the BASE print, not an empty printing")
    # NULL would park the row in an "Unknown" rollup tier belonging to neither
    # market -- which is exactly the state this replaced.
    for t in ("PSA 10 Peter Pan 215/204 Enchanted Into the Inklands",
              "Disney Lorcana Peter Pan Pirate's Bane Enchanted PSA 9"):
        check(L.variant_printing_for(PP, t) == "Normal", "'Normal' from: %s" % t[:52])

    print("\n3. the vocabulary CANNOT leak onto another card")
    # "text error" in some other card's title must not mint a Text Error
    # printing there -- it is meaningful only for the card that has the error.
    check(L.variant_printing_for("crd_some_other_card", "Elsa Snow Queen text error PSA 10") is None,
          "a non-variant card falls through to the finish reader")
    check(L.printing_of("Elsa Snow Queen text error PSA 10") is None,
          "and the finish reader does not invent one either")

    print("\n4. the loader actually consults it")
    src = (HERE / "terapeak_load.py").read_text(encoding="utf-8")
    check("variant_printing_for(card[\"id\"], title)" in src,
          "terapeak_load's row builder calls variant_printing_for")
    check(re.search(r"variant_printing_for\(.*?\)\s*\n?\s*.*?\)\s*or printing_of\(title\)", src, re.S)
          or "or printing_of(title)" in src,
          "and falls back to printing_of for everything else")

    print("\n5. the python map and the client agree on WHICH cards these are")
    idx = (HERE.parent / "Index.html").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"const SPLIT_PRINTING_CARD_IDS = new Set\(\[(.*?)\]\)", idx, re.S)
    check(m is not None, "found SPLIT_PRINTING_CARD_IDS in Index.html")
    client_ids = set(re.findall(r'"(crd_[0-9a-f]+)"', m.group(1))) if m else set()
    py_ids = set(L.VARIANT_PRINTING_BY_CARD)
    check(client_ids == py_ids,
          "same card ids both sides (client=%d python=%d)" % (len(client_ids), len(py_ids)))

    # The client also names the printing VALUES; they must be the same strings,
    # or the rollup bucket and the UI toggle describe different things.
    opts = dict(re.findall(r'"(crd_[0-9a-f]+)":\s*\[([^\]]*)\]', idx))
    for cid, (name, _rx) in L.VARIANT_PRINTING_BY_CARD.items():
        vals = re.findall(r'"([^"]+)"', opts.get(cid, ""))
        check(name in vals,
              "client offers %r for %s (client=%s)" % (name, cid[:18] + "...", vals or "MISSING"))

    print("\n" + "=" * 62)
    if FAILS:
        print("FAILED %d of %d:" % (len(FAILS), N[0]))
        for f in FAILS:
            print("  - " + f)
        sys.exit(1)
    print("all %d checks passed" % N[0])


if __name__ == "__main__":
    main()
