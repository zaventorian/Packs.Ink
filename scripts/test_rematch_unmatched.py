"""
test_rematch_unmatched.py - guard the SAFETY SCOPING of rematch_graded_unmatched.

No network, no DB: it builds a tiny in-memory catalog index in the exact shape
build_index() returns and drives the real decide() over it.

Every failure mode this guards is silent. Loosening the scoping does not throw -
it quietly starts overwriting hand-made attributions and un-excluding rows
somebody deliberately excluded, which is precisely what got
reattribute_graded_sales.py banned. Tightening it too far does not throw either -
it just goes back to losing five-figure sales for ever, which is the bug the
script was written for. Both directions are pinned here.

    python scripts/test_rematch_unmatched.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# decide() imports terapeak_load, which needs these at import time. The test
# never opens a socket; these are only here so the module can be imported.
os.environ.setdefault("SUPABASE_URL", "https://example.invalid")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test-key")

from terapeak_match import toks, norm_cn          # noqa: E402
from rematch_graded_unmatched import decide       # noqa: E402

FAILS = []
CHECKS = [0]


def check(cond, label):
    CHECKS[0] += 1
    if not cond:
        FAILS.append(label)
        print("  FAIL  " + label)
    else:
        print("  ok    " + label)


def mini_index(cards):
    """Reproduce build_index()'s output shape for a handful of cards."""
    import collections
    by_cn, inv = collections.defaultdict(list), collections.defaultdict(list)
    for c in cards:
        c["_tok"] = toks(c.get("name")) | toks(c.get("version"))
        c["_set"] = c.pop("set_name", "")
        c["_cn"] = norm_cn(c.get("collector_number"))
        c["_rarity"] = c.get("rarity") or ""
        by_cn[c["_cn"]].append(c)
        for tk in c["_tok"]:
            inv[tk].append(c)
    return by_cn, inv


CARDS = [
    # The real golden Mickey: the $39,100 sale's card.
    dict(id="crd_custom_554628_golden_mickey", name="Mickey Mouse",
         version="Brave Little Tailor", set_name="Challenge Promo",
         collector_number="5", rarity="Promo"),
    # Its mainline namesake, so the "which Mickey" question is a real one here.
    dict(id="crd_tfc_blt", name="Mickey Mouse", version="Brave Little Tailor",
         set_name="The First Chapter", collector_number="115", rarity="Legendary"),
    dict(id="crd_elsa_sq", name="Elsa", version="Snow Queen",
         set_name="The First Chapter", collector_number="42", rarity="Legendary"),
]

GOLD_MICKEY = ("Disney Lorcana - Gold Mickey - Brave Little Tailor PSA 10 "
               "DLC Top Prize Promo")


def row(**kw):
    base = dict(item_id="1", title="", card_id=None, grader="PSA", grade="10",
                sale_price=100.0, sold_date="2026-05-31", printing=None,
                excluded=True, exclude_reason=None, match_confidence=0.8)
    base.update(kw)
    return base


def main():
    by_cn, inv = mini_index([dict(c) for c in CARDS])

    print("\n1. the $39,100 sale this script exists for")
    body, kind = decide(row(title=GOLD_MICKEY, sale_price=39100.0), by_cn, inv)
    check(kind == "attributed:now-visible", "gold Mickey is attributed and un-excluded")
    check(body and body.get("card_id") == "crd_custom_554628_golden_mickey",
          "it lands on the Challenge Promo golden Mickey, not the mainline #115")
    check(body and body.get("excluded") is False, "excluded is lifted")
    # Its sibling sales are stored as Foil; a None here would file this $39k in a
    # different rollup pkey bucket from the same card's other sales.
    check(body and body.get("printing") == "Foil",
          "printing resolves to Foil via the DLC challenge context")

    print("\n2. NEVER touch a row that already has an attribution")
    body, kind = decide(row(title=GOLD_MICKEY, card_id="crd_someone_fixed_this"),
                        by_cn, inv)
    check(body is None and kind == "skip:already-attributed",
          "an attributed row is refused outright")

    print("\n3. NEVER overrule a concrete exclude_reason")
    for reason in ("foreign", "troll", "auto", "lot", "cn-conflict", "outlier", "manual"):
        body, kind = decide(row(title=GOLD_MICKEY, exclude_reason=reason), by_cn, inv)
        check(body is None and kind == "skip:has-reason",
              "exclude_reason=%s is left alone" % reason)

    print("\n4. do not claim to fix a row that still cannot reach the rollup")
    body, kind = decide(row(title=GOLD_MICKEY, grade=None), by_cn, inv)
    check(kind == "attributed:needs-grade", "a gradeless row is reported, not 'fixed'")
    check(body and "excluded" not in body,
          "and its excluded flag is NOT lifted (the rollup needs a grade)")
    body, kind = decide(row(title=GOLD_MICKEY, sale_price=None), by_cn, inv)
    check(kind == "attributed:no-price" and body and "excluded" not in body,
          "a priceless row is attributed but stays excluded")

    print("\n5. tighten: an anonymous exclusion gains its real reason")
    body, kind = decide(row(title="Lot of 5 Disney Lorcana PSA 10 Elsa Snow Queen"),
                        by_cn, inv)
    check(body and body.get("exclude_reason") == "lot" and body.get("excluded") is True,
          "a multi-card lot is recorded as exclude_reason=lot")
    body, kind = decide(row(title="Elsa Snow Queen PSA 10 Japanese Japan JP"), by_cn, inv)
    check(body and body.get("exclude_reason") == "foreign", "a foreign printing is 'foreign'")
    body, kind = decide(row(title="Elsa Snow Queen raw PSA 10 CONTENDER gem mint"),
                        by_cn, inv)
    check(body and body.get("exclude_reason") == "troll", "a 'PSA 10 CONTENDER' is 'troll'")
    body, kind = decide(row(title="Elsa Snow Queen PSA 10 signed autograph"), by_cn, inv)
    check(body and body.get("exclude_reason") == "auto", "an autographed card is 'auto'")

    print("\n6. a title the matcher still cannot place is left alone, not guessed")
    body, kind = decide(row(title="Disney Lorcana PSA 10 mystery slab"), by_cn, inv)
    check(body is None and kind == "skip:still-unmatched",
          "no card -> no write (it shows up in the straggler report instead)")

    print("\n7. the ordering itself: verdicts are checked BEFORE the matcher")
    # A row that would match happily AND carries a reason must still be skipped -
    # if the matcher ran first this would come back attributed.
    body, kind = decide(row(title=GOLD_MICKEY, exclude_reason="manual"), by_cn, inv)
    check(kind == "skip:has-reason",
          "a matchable row carrying a manual verdict is still skipped")

    print("\n" + "=" * 62)
    if FAILS:
        print("FAILED %d of %d checks:" % (len(FAILS), CHECKS[0]))
        for f in FAILS:
            print("  - " + f)
        sys.exit(1)
    print("all %d checks passed" % CHECKS[0])


if __name__ == "__main__":
    main()
