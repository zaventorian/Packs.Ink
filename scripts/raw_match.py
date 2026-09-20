"""raw_match.py — decide what a RAW (ungraded) eBay sale is, and which card.

The graded pipeline sweeps by GRADER ("Lorcana" "PSA") and matches the whole
catalog. The raw pipeline sweeps by CARD NAME (scripts/raw_watchlist.py), and
that one difference is the source of every rule in this file: a name search is a
NET, not an identity. Measured on the 88,912 stored graded titles, every single
watchlist token nets 2-5 different catalog cards — "Brave Little Tailor" alone
returns The First Chapter #115 (a bulk rare), D23 Collection #1, and Promo Set 1
#1, whose graded copies run past $14,000.

So this module is not a matcher. `terapeak_match.match_one` is the matcher and
stays the only one — measured 2026-09-20 over the 8,253 corpus titles containing
a watchlist token, stripping every grading token out of the title (which is what
a raw title looks like) changed the attributed card in 0 of 8,182 cases. What
this module adds is the three gates a raw sweep needs and a grader sweep does
not.

THE ASYMMETRY THAT DRIVES ALL OF IT. Wrongly publishing a number here is far
worse than publishing nothing. These cards are on the watchlist precisely
BECAUSE the site currently shows a fossil or a dash, so a reader who sees a
price will believe it; and every mis-attribution available is an order of
magnitude off, in both directions (a $1.75 base-card sale onto a $1,350 promo,
or a $16,406 PSA 10 onto a raw card). A dropped sale costs one row of a dataset
that is deliberately sparse. So every gate below fails CLOSED, and the residual
is reported rather than guessed at.

  1. GRADED LISTINGS ARE NOT RAW SALES. A keyword sweep for a card name returns
     that card's slabs too, and they are already in graded_sales. Any title
     carrying a grader+grade token is dropped. This deliberately also drops the
     "PSA 10 CONTENDER" hype listings, which genuinely ARE raw cards: including
     them would mean trusting a regex to tell "PSA 10" from "PSA 10 contender"
     on the one axis where being wrong publishes a 10x price.

  2. NO EVIDENCE MEANS NO ATTRIBUTION. `match_one` will match on name tokens
     alone (its `ov >= 0.85` branch). For a grader sweep that is fine. Here it is
     the whole hazard: the five cards named "Mickey Mouse - Brave Little Tailor"
     have IDENTICAL name-token sets, so `ov` ties for all of them and the winner
     is whichever the scorer happens to order first. Measured over the corpus,
     700 titles carry neither a collector number nor a set hint, and the cards
     they land on include Let It Go (C1 #41, a $1,350 promo) at $1.75 and
     Stouthearted (C1 #42) at $13.50 — the cheap First Chapter base cards,
     conflated by that tiebreak. A title with no collector number and no set hint
     is therefore UNDECIDABLE and is recorded as such.

     ⚠ Price is NOT admissible as evidence of identity, and this is the rule most
     likely to look like an easy win later. Using "$1.75 is too cheap to be the
     promo" to reject a row, or "$16,000 must be the promo" to accept one, makes
     the output a function of the assumption — we would be deciding which sales
     count by whether they already agree with the price we expect, and then
     publishing that price as evidence. Price may flag a row for a human. It may
     never attribute one.

  3. OFF-WATCHLIST SALES ARE DROPPED, NOT KEPT. A sale that attributes to The
     First Chapter #115 is a real sale of a real card — and that card has a live,
     moving TCGplayer price, which is the authority for it. The watchlist is the
     set of cards where TCGplayer has nothing or has frozen; everything else
     belongs to the existing pipeline.

⚠ The EXCLUDE_RAW bucket of `terapeak_clean.classify` is inverted here. A title
saying "ungraded" / "raw card" is noise to the grader sweep and is exactly what
this pipeline is looking for, so `classify` is NOT reused wholesale — its
structural regexes are, one at a time, and its raw bucket is skipped.

Guarded by `python scripts/test_raw_match.py` (no network, no .env).
"""
from __future__ import annotations

import re

import terapeak_clean as tc
import terapeak_match as tm
from raw_watchlist import WATCHLIST

# Every reason a scraped row is kept but not counted. Stored in
# raw_sales.exclude_reason so a class can be re-evaluated on its own later --
# the lesson of migration 111, applied from the start this time rather than
# after 8.3k rows had been excluded for reasons nobody recorded.
EXCLUDE_REASONS = (
    "graded",        # a slab; already in graded_sales (gate 1)
    "ambiguous",     # no collector# and no set hint; identity undecidable (gate 2)
    "off-watchlist", # attributed to a card TCGplayer already prices (gate 3)
    "nomatch",       # the matcher declined
    "cn-conflict",   # title's explicit collector# disagrees with the matched card
    "lot",           # multi-card listing
    "sealed",        # sealed product
    "accessory",     # not a card -- toploader, sleeve, and above all a PIN
    "merch",         # a poster / proxy / puzzle wearing the card's name
    "variant",       # a printing qualifier the catalog cannot place (Extended Art)
    "other-tcg",     # not Lorcana
    "foreign",       # a regional printing; a separate market
    "auto",          # autographed / sketch / 1-of-1
)

# Grading vocabulary that carries NO grader name. Measured against the corpus:
# `tc.parse_grade` needs a grader AND a number, so it read all of these as raw --
# "A Whole New World Foil Gem Mint 10 - 10/C1 World Champ Promo" ($17,500),
# "Let It Go - Foil Prize Card 2/C1 Gem Mint 9.5 Graded English" ($1,400),
# "... BRAVE LITTLE TAILOR GRADED MINT 9" ($1,400). 23 slabs in all, the dearest
# of them a five-figure sale that would have published as this card's RAW price.
#
# ⚠ Every word here was checked against the live catalog for a card-name
# collision, and three candidates were dropped for one: bare `badge` hits
# "Detective's Badge", bare `pop` hits "Gazelle - Pop Star" and "Jumbo Pop" (so
# the population report is matched only WITH its number, which it always has --
# "Pop 90", "Pop8"), and bare `slab` hits "Vision Slab". `authentic` is
# deliberately absent: every "PSA Authentic" / "CGC Authentic" / "SGC Authentic"
# title in the corpus carries its grader's name, so `grader_present` already has
# them, and a rule for it would only add the risk of eating a raw seller's
# "100% authentic".
#
# NOT matched, on purpose: a bare "mint" / "near mint" / "NM". That is ordinary
# raw condition language and is most of what a raw listing says about itself.
# `\bgraded?\s*\d` is the bare "Grade 9" / "Graded 10" form, which carries no
# grader name at all and so passes both tests above. It reached the review report
# on "Lorcana D23 Expo | Mickey Mouse - Brave Little Tailor EXT ART P - Grade 9".
# 0 card-name collisions in the catalog.
GRADE_LANGUAGE_RE = re.compile(
    r"gem\s*-?\s*(?:mint|mt)\b|\bgraded\b|\bgraded?\s*\d|\bpristine\b|\bpop\s*\d", re.I)


# ⚠ "EXTENDED ART" IS A DIFFERENT CARD, and the prices make the stakes plain.
# The 2024 D23 Collection printings are the Rainbow Foil / Extended Art ones and
# sell for $16-$316; the 2022 Promo Set 1 cards this watchlist tracks sell for
# $700-$1,900. They share a character, a collector number (#01) and the token
# "D23", so a title saying "Extended Art" with no year attributes straight onto
# the 2022 card and drags its published price down by an order of magnitude --
# five such rows reached the first review report.
#
# The catalog does not model an extended-art printing for any watchlist card, so
# this is gate 2's rule in another costume: a qualifier we cannot place makes the
# identity undecidable, and undecidable means dropped, not guessed. It resolves
# to D23 Collection in practice, which is not on the watchlist and would be
# dropped anyway -- so nothing is lost either way.
VARIANT_UNPLACEABLE_RE = re.compile(r"\bext(?:ended)?\.?\s*art\b", re.I)


def is_graded_listing(title: str) -> bool:
    """Gate 1. True if the listing is a slab rather than a raw card.

    Three tests, because a slab announces itself in three ways and the corpus
    contains all of them:
      * a full grader+grade parse    ("PSA 10", "CGC 9.5")
      * a grader NAME with no number ("PSA Authentic", "TAG Score 942", "1st Ed
        PSA") -- `tc.classify` calls this its NEEDS_GRADE bucket and still
        treats it as graded, which is exactly right here
      * grading language with no grader at all (see GRADE_LANGUAGE_RE)
    """
    t = title or ""
    grader, grade = tc.parse_grade(t)
    if grade:
        return True
    if tc.grader_present(t):
        return True
    return bool(GRADE_LANGUAGE_RE.search(t))


# ⚠ PINS NEED A BROADER RULE HERE THAN THEY GET IN THE GRADED PIPELINE, and the
# two must not be merged. `tc.ACC_RE` is narrow on purpose -- a bare \bpins?\b
# matches 30 active graded rows and nearly all are real card sales that merely
# THREW IN a pin ("Brave Little Tailor D23 Expo Promo PSA 10 #1 w/ pin", $8,500),
# so breadth there loses real money.
#
# The raw sweep inverts that trade completely:
#   * those 30 listings all say PSA/CGC, so gate 1 already has them here;
#   * a Lorcana pin shares its card's name BY DESIGN and is sold under the same
#     D23 wording, so it satisfies every identity gate this module has -- "Disney
#     D23 Expo 2026 Lorcana Mickey Mouse Brave Little Tailor Promo Pin" carries a
#     real set hint and attributes cleanly to Promo Set 1 #1. Nothing but a
#     product-type rule can stop it;
#   * 17 such pins survived the first cut of this file, at $7.00-$14.99, against
#     a card whose graded copies pass $14,000. A pin published as that card's raw
#     price is the single most embarrassing failure this pipeline can produce.
# The cost is a genuine raw sale whose title happens to mention a bundled pin.
# That is one row, and one row is the cheap side of this trade.
RAW_PIN_RE = re.compile(r"\bpins?\b|\bpinback\b|\benamel\b|\blapel\b", re.I)

# MERCHANDISE AND FAKES that carry the card's name. The same blind spot as pins:
# a poster of Elsa - Snow Queen satisfies every identity gate here, because it
# genuinely IS "the 2023 D23 Lorcana Elsa Snow Queen". Three such posters
# ("2023 DISNEY D23 LORCANA CARD 13X19 POSTER ELSA SNOW QUEEN") survived the
# second cut of this file at $34-$100, against a card whose raw copies run past
# $3,750 -- so they do not merely add noise, they drag the published price down
# by an order of magnitude.
#
# `proxy` / `custom` / `replica` matter more here than anywhere else in the
# codebase: a counterfeit of a $1 common is not worth making, and every card on
# this watchlist is worth four figures.
#
# ⚠ Checked against every card name in the catalog. Two words that look obvious
# are deliberately absent:
#   * bare `print` -- 0 name collisions but 367 corpus hits, essentially all
#     "1st Print" / "First Print", which is a legitimate and desirable thing for
#     a seller to say about a real card. Only `art print` is matched.
#   * `jumbo` -- collides with the card "Jumbo Pop". `oversized` covers the same
#     listings ("OVERSIZED FOIL JUMBO") without the collision.
# `custom` is safe only because \bcustom\b cannot match "Customer" (Kuzco -
# Picky Customer, and two others); do not relax that boundary.
RAW_MERCH_RE = re.compile(
    r"\bposter|\blithograph|\blitho\b|\bart\s+print|\bproxy|\bcustom\b|\bsticker"
    r"|\bmagnet|\bdecal|\breplica|\boversized|\bstandee|\bpuzzle|\bbanner"
    r"|\bcanvas|\bplaque|\bframed\b", re.I)


# ⚠ A raw sale of a C1 card is undecidable between the Top Prize FOIL and the
# Prize Wall NON-FOIL unless the title says which: they share one card_id and
# their graded markets sit ~50x apart ($1,707 vs $280 on Cinderella -
# Stouthearted). The row is still stored -- `graded_sale_pkey` buckets a null
# printing as 'Unknown', which is its own key and can never be read as either
# real printing -- so nothing is lost and nothing is guessed. That is why this
# is not an exclusion.
printing_of = None  # bound below, from terapeak_load (see _printing_of)


def _printing_of(title: str):
    """The finish a title declares, or None. Imported lazily from terapeak_load
    so this module stays importable without Supabase credentials (the loader
    reads .env at import). One definition of 'what finish is this', shared with
    the graded loader, including the Challenge prize-tier wording."""
    global printing_of
    if printing_of is None:
        from terapeak_load import printing_of as _p
        printing_of = _p
    return printing_of(title)


def build_watchlist_index(by_cn, inv):
    """(set_name, normalized collector#) -> the WATCHLIST row, for gate 3.

    Keyed on the pair rather than on a card id because the watchlist is written
    in the terms a human can check against a card face, and `raw_watchlist.
    verify()` already proves the pair resolves to exactly one catalog card."""
    idx = {}
    for st, cn, name, ver, query, printing_tracked in WATCHLIST:
        idx[(st, tm.norm_cn(cn))] = {
            "set": st, "cn": cn, "name": name, "version": ver,
            "query": query, "printing_tracked": printing_tracked,
        }
    return idx


def has_identity_evidence(title: str) -> bool:
    """Gate 2. True when the title carries something that can distinguish one
    same-named card from another: an explicit collector number, or a set hint
    (set name, 'EN n', a '/P1'-style promo suffix, 'D23', 'DLC', ...).

    Name tokens alone do NOT count -- that is the entire point. See the module
    docstring for the measured consequence of letting them."""
    t = title or ""
    return bool(tm.collectors(t)) or bool(tm.set_hint(t))


def structural_reason(title: str):
    """Why this listing is not a single raw Lorcana card, or None.

    Order matters: 'other-tcg' first so a Pokemon lot reports as the former (the
    more actionable fact about it), then lots, then sealed, then accessories.
    `tc.ACC_RE` is what keeps PINS out -- Lorcana pins share card names by
    design, and a raw name sweep walks straight into them where a grader sweep
    never did (of 39 rows one probe attributed to Promo Set 1 #1, a ~$1,500 card,
    25 were $7-$30 D23 Expo pins)."""
    t = title or ""
    if tc.OTHER_TCG_RE.search(t):
        return "other-tcg"
    if tc.LOT_RE.search(t) or tc.is_multi_card(t) or tm.is_nonsingle(t):
        return "lot"
    if tc.SEALED_RE.search(t):
        return "sealed"
    if tc.ACC_RE.search(t) or RAW_PIN_RE.search(t):
        return "accessory"
    if RAW_MERCH_RE.search(t):
        return "merch"
    if VARIANT_UNPLACEABLE_RE.search(t):
        return "variant"
    # NOTE: tc.RAW_RE ("ungraded", "raw card") is deliberately NOT consulted --
    # it is the grader sweep's exclusion and this pipeline's target.
    return None


def title_reason(title: str):
    """Foreign-language / autograph exclusions, reusing the graded loader's
    patterns. Imported lazily for the same credentials reason as _printing_of."""
    from terapeak_load import is_foreign_lang, is_autograph
    t = title or ""
    if is_foreign_lang(t):
        return "foreign"
    if is_autograph(t):
        return "auto"
    return None


def raw_verdict(title, by_cn, inv, wl_idx, *, skip_title_reasons=False):
    """Resolve one raw listing.

    Returns (card_or_None, confidence, cn_conflict, exclude_reason_or_None).
    `exclude_reason is None` is the ONLY including verdict, and it always comes
    with a card that is on the watchlist.

    `skip_title_reasons` exists for the guard test, which asserts the gates in
    isolation without needing the loader's credentials.
    """
    t = title or ""

    # Gate 1 -- a slab is not a raw sale. Checked before anything else: it is the
    # one misclassification that publishes a 10x-inflated price.
    if is_graded_listing(t):
        return None, 0.0, False, "graded"

    reason = structural_reason(t)
    if reason:
        return None, 0.0, False, reason

    if not skip_title_reasons:
        reason = title_reason(t)
        if reason:
            return None, 0.0, False, reason

    # Gate 2 -- no collector# and no set hint means the name tokens are the only
    # evidence, and same-named cards tie on those. Undecidable, not a guess.
    if not has_identity_evidence(t):
        return None, 0.0, False, "ambiguous"

    card, conf, cn_conflict = tm.match_one(t, by_cn, inv)
    if card is None:
        return None, conf, cn_conflict, ("cn-conflict" if cn_conflict else "nomatch")

    # Gate 3 -- TCGplayer is the authority for any card it actually prices.
    if (card["_set"], card["_cn"]) not in wl_idx:
        return card, conf, cn_conflict, "off-watchlist"

    return card, conf, cn_conflict, None
