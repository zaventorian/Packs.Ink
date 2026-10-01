"""raw_watchlist.py — the cards whose RAW (ungraded) eBay sales are worth scraping.

We already track graded sales (terapeak_scrape -> graded_sales). This is the list
for the other half: high-end promos that TCGplayer either has NEVER recorded a
sale for, or froze on months ago, so the price the site shows is an asking price
or a fossil.

Why these and not "expensive cards" generally: a promo is a fixed, event-
distributed population, so its market is structurally elsewhere. Measured on the
live catalog 2026-09-15, promos freeze for 50-181 days while Enchanted/Iconic
chase cards freeze for 10-18 — they come out of packs continuously, so TCGplayer
supply is real and a flat reading there is a lull, not an absent market. Every
Enchanted and Iconic is deliberately out of scope.

The worst cases on this list, from card_prices_latest:

    C1 #5  Mickey Mouse - Brave Little Tailor   market_price NEVER populated,
                                                last row of ANY kind 2025-03-03
    C1 #7  Elsa's Ice Palace                    never; last row 2025-11-17
    C1 #9  Baymax - Armored Companion           never; site shows the $63 NON-foil
    P1 #3  Elsa - Snow Queen                    never; ask was $5,999.99

⚠ A C1 card's Top Prize foil and Prize Wall non-foil share ONE card_id, so a row
here carries the printing it means. Baymax's foil slabs reach $33,494 while the
site shows $63 — anything built on this list must keep the two apart.

⚠ Every entry's name collides with at least one other catalog card, because a
promo reprints a base card. "Mickey Mouse - Brave Little Tailor" is FIVE cards
(D23 Collection #1, Promo Set 1 #1, Format Coconut #13, Challenge Promo #5, The
First Chapter #115) spanning a bulk common to a $14,807 foil. So a search here is
a NET, not an identity — attribution still has to do the work, and requiring a
collector number does NOT rescue it (measured: that drops 30.6% of the graded
record, $1.97M of sale value, because most correct titles carry no number).

`verify()` checks every entry against the live catalog. Run it after editing:

    python scripts/raw_watchlist.py
"""
from __future__ import annotations

# (set, collector_number, name, version, searches, printing_tracked)
#
# `searches` are the eBay/Terapeak keyword searches that find THIS card. Each
# pairs the character (or the version subtitle) with a token only the promo
# printing carries -- "C1", "Challenge", "D23", "2022", "P3" -- because a bare
# subtitle drowns the promo in its own base card: '"Lorcana" "Brave Little
# Tailor"' hit the 60-page cap (3,000 rows) on its first deep run, nearly all of
# them the $1 First Chapter #115, and never reached the 2022 sales it existed for.
#
# ⚠ NARROW MUST NOT MEAN LOSSY, so this list was MEASURED, not written from
# memory (2026-09-27): every graded + raw title we hold for these 24 cards that
# carries identity evidence (3,225) was replayed against the 45 searches, and
# 3,201 are caught. The 24 that are not are rows already sitting on the wrong
# card in graded_sales (a D23 Collection Cinderella on C1 #42, base Ursula's
# Return Minnie on P3 #17) or seller typos ("Cindarella", "Michey"). The OLD
# subtitle-only list missed far more: of 184 Captain Hook P1 #7 sales, only 41
# say "Forceful Duelist" -- sellers write "2022 Captain Hook #7 D23 Expo".
#
# ⚠ Terapeak matches ITEM SPECIFICS as well as the title: a "Lorcana" search
# returns PSA auto-titles like "2024 PRIZE WALL EXCLUSIVE #4 RAPUNZEL - GIFTED
# WITH HEALING PSA 9", which never say Lorcana. So that title-only measurement is
# a FLOOR on what these searches catch, not a ceiling.
#
# `printing_tracked` is the printing whose raw price we are after -- "Foil" where
# the card_id is shared with a cheaper non-foil, None where the card has only one
# printing.
def _q(*words):
    return " ".join(f'"{w}"' for w in ("Lorcana",) + words)


WATCHLIST = [
    # --- Challenge Promo (C1) Top Prize foils ------------------------------
    ("Challenge Promo", "5",  "Mickey Mouse", "Brave Little Tailor",
        (_q("Mickey", "Challenge"),), "Foil"),
    ("Challenge Promo", "43", "Rapunzel",     "Gifted with Healing",
        (_q("Rapunzel", "Challenge"),), "Foil"),
    ("Challenge Promo", "8",  "Kuzco",        "Temperamental Emperor",
        (_q("Kuzco", "Challenge"),), "Foil"),
    # "Ice Palace", not "Elsa's Ice Palace": sellers use both apostrophes.
    ("Challenge Promo", "7",  "Elsa's Ice Palace", "Place of Solitude",
        (_q("Ice Palace"),), "Foil"),
    ("Challenge Promo", "9",  "Baymax",       "Armored Companion",
        (_q("Baymax", "Challenge"), _q("Armored Companion", "Promo")), "Foil"),
    ("Challenge Promo", "10", "A Whole New World", None,
        (_q("A Whole New World", "Promo"),), "Foil"),
    ("Challenge Promo", "6",  "Invited to the Ball", None,
        (_q("Invited to the Ball"),), "Foil"),
    ("Challenge Promo", "42", "Cinderella",   "Stouthearted",
        (_q("Cinderella", "Challenge"),), "Foil"),
    ("Challenge Promo", "41", "Let It Go",    None,
        (_q("Let It Go", "Promo"), _q("Let It Go", "Challenge")), "Foil"),

    # --- Challenge Year 3 (C2) foils ---------------------------------------
    # #1-4 are the foils (Top 64 / Top 32 / Participation), #5-8 the Prize Wall
    # non-foils — confirmed from sale titles, not assumed. Only #2 and #4 clear
    # the $1,000 bar; #1 Pegasus ($150) and #3 Mulan ($385) are out.
    ("Lorcana Challenge Year 3", "2", "Elsa",  "Ice Maker",
        (_q("Elsa", "Challenge"),), "Foil"),
    ("Lorcana Challenge Year 3", "4", "Simba", "Pride Protector",
        (_q("Simba", "Challenge"), _q("Simba", "Tournament")), "Foil"),
    # #11 / #12 / #14 are the foil printings of #15 / #16 / #18 (added
    # 2026-09-30). TCGplayer lists them at $2,500-$6,500 asks with almost no
    # sales, so eBay is the price. Each has a non-foil twin of the same name in
    # the same set at ~$70, which TWIN_REQUIRE keeps out.
    ("Lorcana Challenge Year 3", "11", "Stand Out", None,
        (_q("Stand Out", "Challenge"), _q("Stand Out", "Promo")), None),
    ("Lorcana Challenge Year 3", "12", "Down in New Orleans", None,
        (_q("Down in New Orleans", "Challenge"), _q("Down in New Orleans", "Promo")), None),
    ("Lorcana Challenge Year 3", "14", "Tinker Bell", "Insistent Fairy",
        (_q("Tinker Bell", "Challenge"), _q("Insistent Fairy", "Promo")), None),

    # --- Challenge 2026-27 season (C3) --------------------------------------
    # 13/C3 is the foil of 1/C3 (the Qualifier prize). The non-foil has a live
    # TCGplayer price (~$117) and is not ours to price; the foil asks $775.
    ("Lorcana Challenge Promo (C3)", "13", "Mother Knows Best", None,
        (_q("Mother Knows Best", "Challenge"), _q("Mother Knows Best", "Promo"),
         _q("Mother Knows Best", "CCQ")), None),

    # --- Promo Set 1 #1-7 (the 2022 D23 Expo set; first Lorcana promos) -----
    # Both "D23" and "2022": TCGplayer-style titles say "4 D23 Promos Holo" with
    # no year, and PSA auto-titles say "2022 DISNEY LORCANA PROMO #4" with no D23.
    ("Promo Set 1", "3", "Elsa",           "Snow Queen",
        (_q("Elsa", "D23"), _q("Elsa", "2022")), None),
    ("Promo Set 1", "2", "Stitch",         "Rock Star",
        (_q("Stitch", "D23"), _q("Stitch", "2022")), None),
    ("Promo Set 1", "5", "Maleficent",     "Monstrous Dragon",
        (_q("Maleficent", "D23"), _q("Maleficent", "2022")), None),
    # Mickey + "D23" alone is the 2024 D23 Collection's market as well, and gate 4
    # drops any #1 sale without "2022" (TWIN_REQUIRE) -- so the year IS the search.
    ("Promo Set 1", "1", "Mickey Mouse",   "Brave Little Tailor",
        (_q("Brave Little Tailor", "2022"),), None),
    ("Promo Set 1", "7", "Captain Hook",   "Forceful Duelist",
        (_q("Captain Hook", "D23"), _q("Captain Hook", "2022")), None),
    ("Promo Set 1", "6", "Robin Hood",     "Unrivaled Archer",
        (_q("Robin Hood", "D23"), _q("Robin Hood", "2022"), _q("Robinhood", "D23")), None),
    ("Promo Set 1", "4", "Cruella De Vil", "Miserable As Usual",
        (_q("Cruella", "D23"), _q("Cruella", "2022"), _q("Cruella", "P1")), None),

    # --- Disney Cruise Line promos (Promo Set 3) ---------------------------
    # ⚠ Weakest group on the list, kept at Zaven's call. Unlike the Challenge
    # foils, TCGplayer has a LIVE moving price for these ($141-$232) and the five
    # raw sales we already caught by accident land at $175-$250 — so TCGplayer is
    # already right and the 5-7x graded gap is a real grading premium. Expect
    # this group to confirm the number we show rather than change it.
    ("Promo Set 3", "10", "Mickey Mouse",  "True Friend",
        (_q("Mickey", "P3"),), None),
    ("Promo Set 3", "13", "Mickey Mouse",  "Pirate Captain",
        (_q("Mickey", "P3"), _q("Pirate Captain", "P3")), None),
    ("Promo Set 3", "14", "Goofy",         "Expert Shipwright",
        (_q("Goofy", "P3"), _q("Expert Shipwright")), None),
    ("Promo Set 3", "15", "Donald Duck",   "Buccaneer",
        (_q("Donald", "P3"),), None),
    ("Promo Set 3", "17", "Minnie Mouse",  "Pirate Lookout",
        (_q("Minnie", "P3"), _q("Pirate Lookout")), None),
    ("Promo Set 3", "16", "Daisy Duck",    "Pirate Captain",
        (_q("Daisy", "P3"), _q("Pirate Captain", "P3")), None),
]

# Set-wide nets, searched FIRST. They name no card, so they catch what a
# per-card search cannot: a title that misspells the character ("Maymax",
# "Kuzo"), or a "Top 8 Prize Card 5/C1" that never says Challenge. Each is
# bounded by a token only promos carry, and raw_match throws away anything they
# drag in that is not a watchlist card.
SET_NETS = [
    _q("C1"), _q("Top Prize"), _q("Prize Wall"), _q("Side Event"),
    _q("C2"), _q("C3"),
    _q("D23", "2022"), _q("Expo", "2022"),
    _q("Cruise"),
]


# ⚠ TWO of these cards share a (name, collector number) with ANOTHER catalog
# card, and a title cannot always tell them apart. Found 2026-09-20 in the loaded
# data, not in theory: Promo Set 1 #1's sales came back bimodal -- $855-$1,900
# against $166-$295 -- with the two clusters carrying LITERALLY indistinguishable
# titles ("...Brave Little Tailor D23 Expo Promo Foil 01/D23 EN" at $202.95 and
# "...Brave Little Tailor D23 Expo Pro..." at $1,900). The cheap cluster is the
# 2024 D23 COLLECTION #1, whose TCGplayer market is $209.05 -- a dead match.
#
# The matcher cannot fix this: `set_hint` maps the token "D23" to Promo Set 1
# unconditionally, so every D23 Collection card is hinted onto the 2022 set. That
# bias is invisible in the graded pipeline (a slab's title carries a year and a
# grade) and fatal here, because last-sold is the headline number -- the card
# would have published $202.95 against a real market near $1,142.
#
# So a twinned card must PROVE its era. This is gate 2's rule (undecidable means
# dropped) applied where the ambiguity is between two real cards rather than
# between a promo and a bulk rare. It fails closed: sales that cannot prove it
# are excluded, including genuine ones, which is the cheap side of the trade.
#
# ⚠ Both twins have a live TCGplayer price, so by gate 3 they are not ours to
# price anyway -- we simply cannot tell which rows are theirs.
#   #1 -> D23 Collection #1 ($209.05) : "D23" is shared, so only a YEAR separates
#         them. 2022 is the Expo set; the Collection is 2024.
#   #5 -> Promo Set 3 #5 ($49.40)     : Promo Set 3 is Disney Cruise Line, so the
#         token "D23" IS decisive here, as is the year.
def _foil_or(number_re):
    return number_re + r"|(?<!non-)(?<!non )(?<!non)\bfoil\b"


TWIN_REQUIRE = {
    ("Promo Set 1", "1"): r"\b2022\b",
    ("Promo Set 1", "5"): r"\bd23\b|\b2022\b",
    # The Challenge foils whose NON-FOIL twin shares the name and the set, at a
    # thirtieth of the price. A sale counts only when its title carries the
    # foil's own printed number or says foil without "non" in front of it.
    ("Lorcana Challenge Year 3", "11"): _foil_or(r"\b0?11\s*/\s*c2\b"),
    ("Lorcana Challenge Year 3", "12"): _foil_or(r"\b0?12\s*/\s*c2\b"),
    ("Lorcana Challenge Year 3", "14"): _foil_or(r"\b0?14\s*/\s*c2\b"),
    ("Lorcana Challenge Promo (C3)", "13"): _foil_or(r"\b0?13\s*/\s*c3\b"),
}


def queries():
    """The DISTINCT keyword searches covering the whole list: the set-wide nets
    first, then each card's own searches in list order (highest-value cards
    first, so a captcha mid-run keeps what it got). Cards share searches --
    '"Lorcana" "Mickey" "P3"' covers P3 #10 and #13 -- hence the dedupe."""
    seen, out = set(), []
    for q in SET_NETS + [q for row in WATCHLIST for q in row[4]]:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


# The short forms a per-card search may use for a character name.
_NAME_FORMS = {"Elsa's Ice Palace": ("ice palace",), "Robin Hood": ("robin hood", "robinhood")}


def names_card(search, name, ver):
    """True when a per-card search names its card -- by version subtitle, full
    name, or the first word of the character name ("Mickey", "Cruella"). A
    search that names nobody belongs in SET_NETS, not on a card's row."""
    s = search.lower()
    forms = _NAME_FORMS.get(name, (name.lower(), name.lower().split()[0]))
    return bool(ver and ver.lower() in s) or any(f'"{f}"' in s for f in forms)


def verify():
    """Check every entry resolves to exactly one catalog card. Needs .env."""
    import collections
    import os
    import sys
    from pathlib import Path

    import requests
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
    sb = os.environ["SUPABASE_URL"].rstrip("/")
    head = {"apikey": os.environ["SUPABASE_SERVICE_KEY"],
            "Authorization": f"Bearer {os.environ['SUPABASE_SERVICE_KEY']}"}
    sets = {s["id"]: s["name"] for s in
            requests.get(f"{sb}/rest/v1/sets?select=id,name", headers=head, timeout=60).json()}
    cards, off = [], 0
    while True:
        b = requests.get(f"{sb}/rest/v1/cards?select=id,name,version,collector_number,set_id"
                         f"&order=id&offset={off}&limit=1000", headers=head, timeout=120).json()
        cards += b
        if len(b) < 1000:
            break
        off += 1000

    fam = collections.defaultdict(list)
    for c in cards:
        fam[(c["name"] + "|" + (c.get("version") or "")).lower()].append(c)

    fails = []
    for st, cn, name, ver, q, pr in WATCHLIST:
        hit = [c for c in cards
               if sets.get(c["set_id"]) == st and c["collector_number"] == cn]
        if len(hit) != 1:
            fails.append(f"  {st} #{cn}: matched {len(hit)} catalog cards")
            continue
        c = hit[0]
        if c["name"] != name or (c.get("version") or None) != ver:
            fails.append(f"  {st} #{cn}: catalog says {c['name']!r}/{c.get('version')!r}, "
                         f"list says {name!r}/{ver!r}")
        if not q:
            fails.append(f"  {st} #{cn}: no searches — nothing would ever look for this card")
        for one in q:
            if not names_card(one, name, ver):
                fails.append(f"  {st} #{cn}: search {one!r} does not name this card")
        sib = fam[(c["name"] + "|" + (c.get("version") or "")).lower()]
        if len(sib) < 2:
            fails.append(f"  {st} #{cn}: expected a name collision (every promo reprints a "
                         f"base card); found only {len(sib)} — check the list is still right")

    print(f"{len(WATCHLIST)} cards, {len(queries())} distinct queries")
    if fails:
        print(f"FAIL ({len(fails)})")
        print("\n".join(fails))
        return 1
    print("ok - every entry resolves to exactly one catalog card")
    return 0


if __name__ == "__main__":
    raise SystemExit(verify())
