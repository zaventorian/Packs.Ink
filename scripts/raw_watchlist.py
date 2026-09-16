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

# (set, collector_number, name, version, query, printing_tracked)
# `query` is the eBay/Terapeak keyword. The version subtitle is the most
# distinctive token a listing reliably carries; a card with no subtitle uses its
# name. `printing_tracked` is the printing whose raw price we are after — "Foil"
# where the card_id is shared with a cheaper non-foil, None where the card has
# only one printing.
WATCHLIST = [
    # --- Challenge Promo (C1) Top Prize foils ------------------------------
    ("Challenge Promo", "5",  "Mickey Mouse", "Brave Little Tailor",   '"Lorcana" "Brave Little Tailor"',  "Foil"),
    ("Challenge Promo", "43", "Rapunzel",     "Gifted with Healing",   '"Lorcana" "Gifted with Healing"',   "Foil"),
    ("Challenge Promo", "8",  "Kuzco",        "Temperamental Emperor", '"Lorcana" "Temperamental Emperor"', "Foil"),
    ("Challenge Promo", "7",  "Elsa's Ice Palace", "Place of Solitude",'"Lorcana" "Place of Solitude"',     "Foil"),
    ("Challenge Promo", "9",  "Baymax",       "Armored Companion",     '"Lorcana" "Armored Companion"',     "Foil"),
    ("Challenge Promo", "10", "A Whole New World", None,               '"Lorcana" "A Whole New World"',     "Foil"),
    ("Challenge Promo", "6",  "Invited to the Ball", None,             '"Lorcana" "Invited to the Ball"',   "Foil"),
    ("Challenge Promo", "42", "Cinderella",   "Stouthearted",          '"Lorcana" "Stouthearted"',          "Foil"),
    ("Challenge Promo", "41", "Let It Go",    None,                    '"Lorcana" "Let It Go"',             "Foil"),

    # --- Challenge Year 3 (C2) foils ---------------------------------------
    # #1-4 are the foils (Top 64 / Top 32 / Participation), #5-8 the Prize Wall
    # non-foils — confirmed from sale titles, not assumed. Only #2 and #4 clear
    # the $1,000 bar; #1 Pegasus ($150) and #3 Mulan ($385) are out.
    ("Lorcana Challenge Year 3", "2", "Elsa",  "Ice Maker",            '"Lorcana" "Ice Maker"',             "Foil"),
    ("Lorcana Challenge Year 3", "4", "Simba", "Pride Protector",      '"Lorcana" "Pride Protector"',       "Foil"),

    # --- Promo Set 1 #1-7 (the 2022 D23 Expo set; first Lorcana promos) -----
    ("Promo Set 1", "3", "Elsa",           "Snow Queen",               '"Lorcana" "Snow Queen"',            None),
    ("Promo Set 1", "2", "Stitch",         "Rock Star",                '"Lorcana" "Rock Star"',             None),
    ("Promo Set 1", "5", "Maleficent",     "Monstrous Dragon",         '"Lorcana" "Monstrous Dragon"',      None),
    ("Promo Set 1", "1", "Mickey Mouse",   "Brave Little Tailor",      '"Lorcana" "Brave Little Tailor"',   None),
    ("Promo Set 1", "7", "Captain Hook",   "Forceful Duelist",         '"Lorcana" "Forceful Duelist"',      None),
    ("Promo Set 1", "6", "Robin Hood",     "Unrivaled Archer",         '"Lorcana" "Unrivaled Archer"',      None),
    ("Promo Set 1", "4", "Cruella De Vil", "Miserable As Usual",       '"Lorcana" "Miserable As Usual"',    None),

    # --- Disney Cruise Line promos (Promo Set 3) ---------------------------
    # ⚠ Weakest group on the list, kept at Zaven's call. Unlike the Challenge
    # foils, TCGplayer has a LIVE moving price for these ($141-$232) and the five
    # raw sales we already caught by accident land at $175-$250 — so TCGplayer is
    # already right and the 5-7x graded gap is a real grading premium. Expect
    # this group to confirm the number we show rather than change it.
    ("Promo Set 3", "10", "Mickey Mouse",  "True Friend",              '"Lorcana" "True Friend"',           None),
    ("Promo Set 3", "13", "Mickey Mouse",  "Pirate Captain",           '"Lorcana" "Pirate Captain"',        None),
    ("Promo Set 3", "14", "Goofy",         "Expert Shipwright",        '"Lorcana" "Expert Shipwright"',     None),
    ("Promo Set 3", "15", "Donald Duck",   "Buccaneer",                '"Lorcana" "Buccaneer"',             None),
    ("Promo Set 3", "17", "Minnie Mouse",  "Pirate Lookout",           '"Lorcana" "Pirate Lookout"',        None),
    ("Promo Set 3", "16", "Daisy Duck",    "Pirate Captain",           '"Lorcana" "Pirate Captain"',        None),
]


def queries():
    """The DISTINCT keyword searches covering the whole list, ordered so the
    highest-value cards are scraped first (a captcha mid-run keeps what it got).

    Fewer queries than cards: a version subtitle is shared by every printing of
    that character, so '"Lorcana" "Brave Little Tailor"' nets C1 #5 and P1 #1 in
    one pass, and '"Lorcana" "Pirate Captain"' nets P3 #13 and #16."""
    seen, out = set(), []
    for _set, _cn, _n, _v, q, _p in WATCHLIST:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


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
        token = (ver or name).lower()
        if token not in q.lower():
            fails.append(f"  {st} #{cn}: query {q!r} does not contain {token!r}")
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
