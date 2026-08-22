"""
seed_coconut_starter_decks.py — publish the house [Format Coconut] starter decks.

One deck per Coconut leader, written as a plain text file in
scripts/coconut_starter_decks/. They exist so the Decks tab's Coconut feed is
not empty at launch: someone who has never seen the format can open a leader,
see a real 60 built around it, and copy the list.

They are OWNERLESS (user_id = null), the same shape tournament decks use, so
they read as house decks, stay out of anyone's "Your Decks", and — like
tournament decks — are stored PLAINTEXT (the deck obfuscation codec only
covers user-authored decks; see the deck-obfuscation notes in Index.html).
`tags` carries the marker the client keys the "Packs.Ink" byline off:

    tags = ['packs-ink-starter', 'coconut:<leader-slug>']

Deck ids are a UUIDv5 of the leader slug, so re-running this REPLACES a deck
in place instead of publishing a second copy — edit a .txt file, re-run, done.
Existing deck_cards for that id are deleted first so a removed card actually
disappears.

Usage:
    python scripts/seed_coconut_starter_decks.py            # dry run + validate
    python scripts/seed_coconut_starter_decks.py --commit
    python scripts/seed_coconut_starter_decks.py --only ariel-spectacular-singer

File format (see any file in scripts/coconut_starter_decks/):
    LEADER: <coconut slug>          # must match COCONUT_CARDS in Index.html
    INKS:   <Ink, Ink, Ink>         # declared, cross-checked against the cards
    NAME:   <deck name>
    DESC:   <one-paragraph blurb shown on the deck>
    4 <Product Name>                # the leader's associated card
    1 <Product Name>                # ...58 more, singleton
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import uuid

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

DECK_DIR = os.path.join(os.path.dirname(__file__), "coconut_starter_decks")
STARTER_TAG = "packs-ink-starter"
# Stable namespace so the ids never move. Do not change it — that would orphan
# every published deck and republish the whole set as duplicates.
NS = uuid.uuid5(uuid.NAMESPACE_URL, "https://packs.ink/coconut-starter")

# Mirrors COCONUT_CARDS (Index.html): slug -> (ink, associated Product Name,
# extra per-name copy allowances granted by the leader's own text).
LEADERS = {
    "ariel-spectacular-singer":          ("Amber",    "Ariel - Spectacular Singer", {}),
    "pocahontas-peacekeeper":            ("Amber",    "Pocahontas - Peacekeeper", {}),
    "stitch-rock-star":                  ("Amber",    "Stitch - Rock Star", {}),
    "dumbo-ninth-wonder-of-the-universe":("Amethyst", "Dumbo - Ninth Wonder of the Universe", {}),
    "snow-white-merry-as-the-morning":   ("Amethyst", "Snow White - Merry as the Morning", {}),
    "winnie-the-pooh-hunny-wizard":      ("Amethyst", "Winnie the Pooh - Hunny Wizard", {}),
    "donald-duck-fred-honeywell":        ("Emerald",  "Donald Duck - Fred Honeywell", {}),
    "robin-hood-sneaky-sleuth":          ("Emerald",  "Robin Hood - Sneaky Sleuth", {}),
    "ursula-deceiver-of-all":            ("Emerald",  "Ursula - Deceiver of All", {}),
    "mickey-mouse-brave-little-tailor":  ("Ruby",     "Mickey Mouse - Brave Little Tailor", {}),
    "mr-incredible-super-strong":        ("Ruby",     "Mr. Incredible - Super Strong", {}),
    "sisu-emboldened-warrior":           ("Ruby",     "Sisu - Emboldened Warrior", {}),
    "moana-curious-explorer":            ("Sapphire", "Moana - Curious Explorer", {}),
    "mufasa-ruler-of-pride-rock":        ("Sapphire", "Mufasa - Ruler of Pride Rock", {}),
    "nick-wilde-wily-fox":               ("Sapphire", "Nick Wilde - Wily Fox", {"Pawpsicle": 4}),
    "john-silver-greedy-treasure-seeker":("Steel",    "John Silver - Greedy Treasure Seeker", {}),
    "scar-finally-king":                 ("Steel",    "Scar - Finally King", {}),
    "tinker-bell-giant-fairy":           ("Steel",    "Tinker Bell - Giant Fairy", {}),
}
INK_LIMIT = 3   # Coconut's one concession: a third ink, one of which is the leader's
MIN_CARDS = 60

# Cards that carry their own copy exception regardless of leader (card text
# beats the format's singleton rule). Mirrors SPECIAL_DECK_LIMITS in Index.html.
SPECIAL_LIMITS = {"Dalmatian Puppy - Tail Wagger": 99, "Microbots": 10 ** 9}


def product_name(row):
    return f"{row['name']} - {row['version']}" if row.get("version") else row["name"]


def load_catalog(sb):
    """Product Name -> best card row. Prefers the earliest mainline printing so
    the deck links to the ordinary version of a card rather than a promo."""
    mainline = ["The First Chapter", "Rise of the Floodborn", "Into the Inklands",
                "Ursula's Return", "Shimmering Skies", "Azurite Sea", "Archazia's Island",
                "Reign of Jafar", "Fabled", "Whispers in the Well", "Winterspell",
                "Wilds Unknown", "Attack of the Vine!"]
    rank = {s: i for i, s in enumerate(mainline)}
    sets = {s["id"]: s["name"] for s in sb.select("sets", "id,name", limit=500)}
    rows = sb.select("cards", "id,name,version,set_id,rarity,ink,inks,cost,card_type", order="id.asc")
    best = {}
    for r in rows:
        set_name = sets.get(r["set_id"])
        if set_name == "Format Coconut":
            # The leaders themselves have catalog rows the client suppresses.
            # A deck_cards row pointing at one would render as nothing.
            continue
        key = (rank.get(set_name, 90), r.get("rarity") in ("Enchanted", "Iconic", "Epic"), r["id"])
        n = product_name(r)
        if n not in best or key < best[n][0]:
            r["set"] = set_name
            best[n] = (key, r)
    return {n: v[1] for n, v in best.items()}


def parse_deck(path):
    meta, cards = {}, []
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(LEADER|INKS|NAME|DESC):\s*(.*)$", line)
        if m:
            meta[m.group(1)] = m.group(2).strip()
            continue
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if not m:
            raise ValueError(f"{os.path.basename(path)}: unparsed line: {line}")
        cards.append((int(m.group(1)), m.group(2).strip()))
    for k in ("LEADER", "INKS", "NAME", "DESC"):
        if k not in meta:
            raise ValueError(f"{os.path.basename(path)}: missing {k}:")
    return meta, cards


def validate(path, meta, cards, catalog):
    """Every rule checkDeckLegality() enforces client-side, checked before we
    publish — a starter deck that renders with a warning badge is worse than no
    starter deck."""
    slug = meta["LEADER"]
    if slug not in LEADERS:
        return [f"unknown leader slug {slug!r}"]
    leader_ink, assoc, extra = LEADERS[slug]
    errs, inks, counts = [], set(), {}
    for qty, name in cards:
        counts[name] = counts.get(name, 0) + qty
        row = catalog.get(name)
        if row is None:
            errs.append(f"no such card: {name!r}")
            continue
        for ink in (row.get("inks") or ([row["ink"]] if row.get("ink") else [])):
            inks.add(ink)
    total = sum(q for q, _ in cards)
    if total < MIN_CARDS:
        errs.append(f"{total} cards (need {MIN_CARDS})")
    if len(inks) > INK_LIMIT:
        errs.append(f"{len(inks)} inks: {sorted(inks)}")
    if leader_ink not in inks:
        errs.append(f"no {leader_ink} cards — one ink must match the leader")
    declared = {i.strip() for i in meta["INKS"].split(",") if i.strip()}
    if declared != inks:
        errs.append(f"INKS: says {sorted(declared)}, cards say {sorted(inks)}")
    for name, qty in counts.items():
        limit = 4 if name == assoc else extra.get(name, SPECIAL_LIMITS.get(name, 1))
        if qty > limit:
            errs.append(f"{qty}x {name} (limit {limit})")
    if counts.get(assoc, 0) != 4:
        errs.append(f"{counts.get(assoc, 0)}x {assoc} — the associated card should be a full playset")
    return errs


def deck_id(slug):
    return str(uuid.uuid5(NS, slug))


def publish(sb, slug, meta, cards, catalog):
    did = deck_id(slug)
    ink_list = [i.strip() for i in meta["INKS"].split(",") if i.strip()]
    headers = {"apikey": sb.key, "Authorization": f"Bearer {sb.key}",
               "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"}
    body = {
        "id": did, "user_id": None, "name": meta["NAME"], "description": meta["DESC"],
        "inks": ink_list, "tags": [STARTER_TAG, f"coconut:{slug}"],
        "visibility": "public", "coconut_card": slug,
    }
    r = requests.post(f"{sb.url}/rest/v1/decks", headers=headers, json=body, timeout=60)
    if not r.ok:
        raise RuntimeError(f"deck upsert failed ({r.status_code}): {r.text[:300]}")
    # Delete-then-insert: an upsert alone would leave cards that were cut from
    # the list still sitting in the deck.
    d = requests.delete(f"{sb.url}/rest/v1/deck_cards?deck_id=eq.{did}",
                        headers=headers, timeout=60)
    if not d.ok:
        raise RuntimeError(f"deck_cards clear failed ({d.status_code}): {d.text[:300]}")
    rows = [{"deck_id": did, "card_id": catalog[name]["id"], "printing": "Normal", "quantity": qty}
            for qty, name in cards]
    c = requests.post(f"{sb.url}/rest/v1/deck_cards", headers=headers, json=rows, timeout=60)
    if not c.ok:
        raise RuntimeError(f"deck_cards insert failed ({c.status_code}): {c.text[:300]}")
    return did, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--only", help="publish just this leader slug")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()
    catalog = load_catalog(sb)
    print(f"catalog: {len(catalog)} product names\n")

    files = sorted(f for f in os.listdir(DECK_DIR) if f.endswith(".txt"))
    seen, failed = set(), 0
    for fn in files:
        path = os.path.join(DECK_DIR, fn)
        meta, cards = parse_deck(path)
        slug = meta["LEADER"]
        if args.only and slug != args.only:
            continue
        if slug in seen:
            print(f"  {fn:24s} DUPLICATE leader {slug}")
            failed += 1
            continue
        seen.add(slug)
        errs = validate(path, meta, cards, catalog)
        total = sum(q for q, _ in cards)
        if errs:
            failed += 1
            print(f"  {fn:24s} {total:3d} cards  FAILED")
            for e in errs:
                print(f"      - {e}")
            continue
        if args.commit:
            did, n = publish(sb, slug, meta, cards, catalog)
            print(f"  {fn:24s} {total:3d} cards  -> {did} ({n} rows)")
        else:
            print(f"  {fn:24s} {total:3d} cards  ok (dry run) -> {deck_id(slug)}")

    missing = sorted(set(LEADERS) - seen) if not args.only else []
    if missing:
        print(f"\nNo deck file for: {', '.join(missing)}")
    print(f"\n{len(seen) - failed}/{len(seen)} decks valid"
          f"{'' if args.commit else ' — dry run, pass --commit to publish'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
