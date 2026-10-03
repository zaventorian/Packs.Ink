"""Tell us when one of the sites we RESEARCH from has something we don't have.

    python scripts/watch_sources.py              # report (exit 1 if new)
    python scripts/watch_sources.py --baseline   # accept today's reality as "known"
    python scripts/watch_sources.py --ack-all --why "..."

WHY THIS EXISTS
===============
Three things already answer "is there new stuff":

  * the ETL + `reconcile_catalog.py --watch` cover anything TCGplayer sells or
    Lorcast indexes — cards, sealed, sets;
  * `discover_events.py` + `watch_calendar_sources.py` cover events;
  * and everything else was a DATE IN A FILE. Pins, lore counters, spoiled
    cards, Japan Core waves, the brand bundle: `catalog_watch.json`'s `reviews`
    put them on a 90-day timer that fires a reminder saying "go look at this
    site". A reminder is not a watch. It cannot tell you whether anything
    actually changed, so the 90 days pass, someone re-reads the same page, and
    the usual answer is "nothing new" — which is the work a script should have
    done.

This is that script. It reads the sites we already go to by hand, extracts the
list each one publishes, and diffs it against a committed baseline. Red means
one of them grew something.

⚠ IT NEVER WRITES TO THE SITE'S DATA. Adding a pin means uploading a photo and
minting a permanent `n`; adding a set means a release date nobody has published.
Those are decisions. This only tells you to look — the same rule as `confirmed`
in the calendar and `--ack` in the catalog watch.

⚠ A SOURCE THAT READS ZERO ITEMS IS AN ERROR, NOT "NOTHING NEW". This is the
one invariant the whole thing rests on. Every failure here is silent by nature:
a redesign, a moved URL, a bot wall, a tightened regex all produce an empty list,
and an empty list diffs clean against any baseline. That is how the Elo board
froze at a set rotation on green runs, and how 212 events sat with no roster for
three weeks. So `source_empty` and `shrank` are findings in their own right, and
the committed baseline is what makes them detectable at all.

WHAT IT WATCHES, and why each one is here rather than in another watcher
----------------------------------------------------------------------
  lp-pins / lp-counters   lorcanaplayer.com's product sitemaps. Nobody sells a
      pin, so TCGCSV never sees one and `reconcile_catalog` structurally cannot
      answer this. These two are the only sources that also compare against OUR
      OWN list, so they say "you don't have this" rather than merely "this is
      new" — which is exactly the `pins-lore-counters` review, done by machine.
  lp-products             every other product slug on that site: playmats,
      sleeves, deck boxes, books, puzzles, the Illumineer's Lorebook. Sealed
      product reaches us through TCGCSV, but accessories and books never do.
  lp-sets                 that site's set pages. It lists sets ahead of release
      (`hyperia-city`, `cosmic-quest`, `into-the-inkdark` were all there before
      Lorcast had them), so it announces a set earlier than the `missing_set`
      check can, which needs a Lorcast id to exist first.
  ja-products             Takara Tomy's own card-search API. Japan SKIPS sets:
      Fabled, Whispers and Winterspell never got a standalone Japanese release
      and arrive through the Curator's Library slot and promo packs, so
      `isJapanCoreLegal` needs a per-number list that nothing else publishes.
      One request per product reads the count; ja_core_numbers.py does the rest.
  official-gallery        cards.disneylorcana.com embeds the ENTIRE card catalog
      inline — 2,986 `card_identifier` strings across `EN 1`..`EN 13` the day
      this was written. So a new `EN 14` bucket IS spoiler season starting, and
      a released set's count growing is a promo wave being added. That is the
      `set-spoilers` review reduced to a number, and `import_official_set.py`
      already knows how to turn it into prestaged rows.

DELIBERATELY NOT WATCHED
------------------------
  * Amazon. Their Conditions of Use prohibit automated data gathering outright,
    and the affiliate account is worth more than the check. `verify_amazon_asins.mjs`
    stays a thing you run by hand from an ordinary machine.
  * The Ravensburger brand bundle. No feed, no version, no notification — the
    `brand-assets` review is the only possible mechanism and it stays.
  * ravensburger.us. Measured: the search page answers 200 but publishes no
    product URLs (one category link), and `/discover/...` 403s. A source that
    reads one useless URL is worse than no source, because it looks covered.
  * lorhappy.com, the Japanese RETAILER that used to back Japan Core. Replaced,
    not automated: `ja-products` above reads the PUBLISHER instead. Its old
    `?mode=cate&cbid=...` URLs are dead anyway (404 as of 2026-09-14, and the
    host moved to www.), which is what sent us looking for a better source.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from datetime import date, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATE_PATH = os.path.join(HERE, "source_watch.json")
INDEX_HTML = os.path.join(ROOT, "Index.html")

# ⚠ lorcanaplayer.com is Cloudflare-fronted and RATE-SENSITIVE, not simply open
# or simply blocked. Measured 2026-09-14: a bare curl got 200 on every page and
# sitemap — and after perhaps thirty requests across an afternoon the same bare
# curl got a 403 challenge page, for hours. CLAUDE.md's older "it 403s curl and a
# headless browser" was written from the far side of that line.
#   Two consequences, and they are why _lp_product_slugs is memoised: keep a run
# to three requests, and treat a 403 as a finding (`source_error`) rather than
# something to defeat. A blocked day costs one red run that says "couldn't read";
# it never costs a silent "nothing new", and the committed baseline is untouched
# so the next readable day still diffs against the last thing a person saw.
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 "
                    "packs.ink-source-watch",
      "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
      "Accept-Language": "en-US,en;q=0.9"}

LP_SITEMAPS = ("https://lorcanaplayer.com/product-sitemap1.xml",
               "https://lorcanaplayer.com/product-sitemap2.xml")
LP_SET_SITEMAP = "https://lorcanaplayer.com/set-sitemap.xml"
GALLERY = "https://cards.disneylorcana.com/en-US/?set=set1"

# A source may legitimately lose an item (a product page retired). It may not
# lose a QUARTER of them — that is a redesign or a partial response, and the
# point of noticing is that the next run's baseline would bake the loss in.
SHRINK_TOLERANCE = 0.75

# ⚠ MEASURED, not chosen. Over all 62 real pin/counter slugs the site publishes,
# the LOWEST true-match coverage was 0.75; over seven synthetic "new" slugs
# (elsa-snow-queen, hyperia-city, stitch-rock-star, cosmic-quest-ink-symbol,
# goofy-super-goof, bolt-lightning-dog, into-the-inkdark) the HIGHEST false match
# was 0.50. 0.6 sits in that empty band. Re-measure with --explain if either list
# changes shape; a threshold tuned by eye here produces confident wrong answers
# in both directions, and both are silent.
MATCH_MIN = 0.6

# Words that carry no identity in a collectible's name. "lorcana league pin" is
# on most of them; "logo"/"ink"/"symbol" appear on both sides in different word
# order ("Maleficent Logo (Purple)" vs purple-maleficent-logo-pin). Dropping them
# is what took pin matching from 34/41 to 41/41.
STOPWORDS = {"lorcana", "league", "pin", "lore", "counter", "disney", "the", "a",
             "of", "and", "weekly", "play", "logo", "ink", "symbol", "exclusive"}


# ---------------------------------------------------------------- fetch + parse

def fetch(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "ignore")


def sitemap_locs(body: str) -> list[str]:
    return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)


_lp_cache: dict[str, list[str]] = {}


def _lp_product_slugs() -> list[str]:
    """⚠ MEMOISED for the process, and that is not an optimisation.

    Three sources read these two sitemaps (pins, counters, everything else).
    Fetching per source made one run SEVEN requests to a Cloudflare-fronted site
    and reliably tripped its bot protection — after which every lorcanaplayer
    source reported `source_error` and the run said nothing useful. One run is
    three requests now: two product sitemaps and one set sitemap.
    """
    if "slugs" in _lp_cache:
        return _lp_cache["slugs"]
    out: list[str] = []
    for u in LP_SITEMAPS:
        for loc in sitemap_locs(fetch(u)):
            m = re.match(r"https?://(?:www\.)?lorcanaplayer\.com/product/([^/]+)/?$", loc)
            if m:
                out.append(m.group(1))
    if not out:
        raise ValueError("lorcanaplayer product sitemaps listed no /product/ URLs")
    _lp_cache["slugs"] = out
    return out


def extract_lp_pins() -> dict[str, str]:
    return {s: s for s in _lp_product_slugs() if s.endswith("-pin")}


def extract_lp_counters() -> dict[str, str]:
    return {s: s for s in _lp_product_slugs() if s.endswith("-lore-counter")}


def extract_lp_products() -> dict[str, str]:
    # Everything that is NOT a pin or a counter — those have their own sources
    # with their own comparison against our lists, and an item must belong to
    # exactly one source or a single new pin reports twice.
    return {s: s for s in _lp_product_slugs()
            if not s.endswith("-pin") and not s.endswith("-lore-counter")}


def extract_lp_sets() -> dict[str, str]:
    out = {}
    for loc in sitemap_locs(fetch(LP_SET_SITEMAP)):
        m = re.match(r"https?://(?:www\.)?lorcanaplayer\.com/set/([^/]+)/?$", loc)
        if m:
            out[m.group(1)] = m.group(1)
    return out


def extract_ja_products() -> dict[str, int]:
    """Card count per JAPANESE product, from Takara Tomy's own card-search API.

    ⚠ One page-1 request per product and NO pagination — the `count` field is
    the whole signal and it costs ~17 requests instead of ~150. A Curator's
    Library wave adding cards moves that product's count; a new set or starter
    deck arrives as a new bucket. Turning either into `JAPAN_CORE_PARTIAL_NUMBERS`
    is `ja_core_numbers.py`'s job, which is where the pagination lives.

    Imported lazily so a change to that script cannot stop the other four
    sources from being read.
    """
    import ja_core_numbers as ja

    out: dict[str, int] = {}
    for name in ja.japanese_products():
        total, _rows = ja.pull(name, paginate=False)
        out[name] = total
        time.sleep(0.25)
    return out


def extract_gallery() -> dict[str, int]:
    """Per-set card counts off the official gallery.

    ⚠ The `?set=` parameter is a CLIENT-side filter — every slug returns the same
    ~4.7MB payload carrying every set — so the URL is arbitrary and the buckets
    come from the `EN <n>` field inside `card_identifier`, not from the request.
    """
    body = fetch(GALLERY, timeout=180)
    ids = re.findall(r'card_identifier:.?"?(\d+)/(\d+) EN (\d+)', body)
    counts: dict[str, int] = {}
    for _cn, _total, setnum in ids:
        key = f"EN {int(setnum):02d}"
        counts[key] = counts.get(key, 0) + 1
    return counts


DUELS_API = "https://duels.ink/api/cards?limit=200&offset="


def extract_duels_renders() -> dict[str, int]:
    """How many cards duels.ink holds a clean REVEAL render for, and how many
    it lists with only a placeholder.

    duels.ink's card API marks each card's art: `reveal` is a flat, upright
    render of the real print (the best art a stand-in can have, and what
    import_duels_art.py uploads), `generated` is its own gold placeholder with
    no art, and null is the official gallery's image. So during spoiler season
    `reveal` going UP means a better picture exists for a card we probably hold
    as a phone crop, and `generated` going up means a card was revealed that
    nobody has art for yet.

    Both keys are always present, so a quiet month (no reveals, no placeholders)
    reads as two zeros and not as an empty source; a response carrying no cards
    at all is raised as an error instead.
    """
    counts = {"reveal renders": 0, "placeholders": 0}
    off, seen = 0, 0
    while True:
        j = json.loads(fetch(DUELS_API + str(off), timeout=60))
        cards = j.get("cards") or []
        seen += len(cards)
        for c in cards:
            src = c.get("imageSource")
            if src == "reveal":
                counts["reveal renders"] += 1
            elif src == "generated":
                counts["placeholders"] += 1
        if not (j.get("meta") or {}).get("hasMore") or not cards:
            break
        off += 200
    if not seen:
        raise ValueError("duels.ink card API listed no cards")
    return counts


# ------------------------------------------------- our own lists, for comparing

def _const_block(html: str, name: str) -> str:
    i = html.index(f"const {name} = [")
    j = html.index("[", i)
    depth = 0
    for k in range(j, len(html)):
        if html[k] == "[":
            depth += 1
        elif html[k] == "]":
            depth -= 1
            if depth == 0:
                return html[j:k + 1]
    raise ValueError(f"unbalanced brackets in {name}")


def held_collectibles(const: str) -> list[tuple[int, str, str]]:
    """(n, name, source) for every entry in LORCANA_PINS / LORCANA_LORE_COUNTERS."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    block = _const_block(html, const)
    out = []
    for m in re.finditer(r"\{\s*n:\s*(\d+)\s*,(.*?)\}", block, re.S):
        body = m.group(2)
        nm = re.search(r'name:\s*"([^"]*)"', body)
        src = re.search(r'source:\s*"([^"]*)"', body)
        out.append((int(m.group(1)), nm.group(1) if nm else "", src.group(1) if src else ""))
    return out


def tokens(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ").replace("'", "")
    return {t for t in re.split(r"[^a-z0-9]+", s) if t and t not in STOPWORDS}


def best_match(slug: str, held: list[tuple[int, str, str]]) -> tuple[float, tuple[int, str] | None]:
    """How much of THEIR slug do we account for, and with which of our entries.

    Coverage is one-directional on purpose: our `name` plus `source` is usually
    wordier than their slug ("Ariel - Whoseit Collector" + "Lorcana League -
    Ursula's Return"), so scoring by intersection-over-union would punish the
    entries we describe best.
    """
    want = tokens(slug)
    if not want:
        return 0.0, None
    best, score = None, 0.0
    for n, name, source in held:
        mine = tokens(name) | tokens(source)
        if not mine:
            continue
        cov = len(want & mine) / len(want)
        if cov > score:
            best, score = (n, name), cov
    return score, best


def compare_pins(found: dict, _state) -> list[tuple[str, str]]:
    return _compare_collectibles(found, "LORCANA_PINS", "pin")


def compare_counters(found: dict, _state) -> list[tuple[str, str]]:
    return _compare_collectibles(found, "LORCANA_LORE_COUNTERS", "lore counter")


def _compare_collectibles(found: dict, const: str, label: str) -> list[tuple[str, str]]:
    held = held_collectibles(const)
    out = []
    for slug in sorted(found):
        score, _best = best_match(slug, held)
        if score < MATCH_MIN:
            out.append((slug, f"no {label} in {const} matches it (best token coverage "
                              f"{score:.0%}, need {MATCH_MIN:.0%})"))
    return out


# ------------------------------------------------------------- the declarations

SOURCES = [
    {
        "id": "lp-pins",
        "what": "Pins on lorcanaplayer.com",
        "site": "lorcanaplayer.com/product-sitemap{1,2}.xml",
        "mode": "items",
        "extract": extract_lp_pins,
        "compare": compare_pins,
        "how": ("Read the /product/<slug>/ page for its photo (the GALLERY, not just the\n"
                "main image — two of our pins were only ever gallery shots on another\n"
                "pin's page). Pull bytes from the i0.wp.com Jetpack mirror. Then add an\n"
                "entry to LORCANA_PINS taking the next free `n` — NEVER renumber, `n`\n"
                "keys both the owned mark and the photo path — at its CHRONOLOGICAL\n"
                "position in the array, since collectible_seq is release order.\n"
                "Cut the background with scripts/cut_collectible_bg.py, then --contact\n"
                "and LOOK at the sheet."),
    },
    {
        "id": "lp-counters",
        "what": "Lore counters on lorcanaplayer.com",
        "site": "lorcanaplayer.com/product-sitemap{1,2}.xml",
        "mode": "items",
        "extract": extract_lp_counters,
        "compare": compare_counters,
        "how": ("Same as lp-pins but into LORCANA_LORE_COUNTERS. ⚠ Name it for its ART,\n"
                "not its set — the Trove dials already carry set names, so a set name\n"
                "here gives one season two identically-named counters. A dial shot on\n"
                "set art or a mat needs cut_hex_collectible.py, not cut_collectible_bg.py."),
    },
    {
        "id": "lp-sets",
        "what": "Set pages on lorcanaplayer.com (it lists sets before release)",
        "site": "lorcanaplayer.com/set-sitemap.xml",
        "mode": "items",
        "extract": extract_lp_sets,
        "compare": None,
        "how": ("A slug we have never seen is either a new set or a promo set. Decide\n"
                "which, then: a booster set eventually needs MAINLINE_SETS + published\n"
                "SET_RELEASE_DATES (never inferred — UPCOMING_SET_NAMES is where an\n"
                "announced-but-undated set goes, and the calendar estimates from it).\n"
                "A promo set is a promo-printing-policy question, not a MAINLINE_SETS one."),
    },
    {
        "id": "lp-products",
        "what": "Other Lorcana products on lorcanaplayer.com (playmats, sleeves, books, puzzles)",
        "site": "lorcanaplayer.com/product-sitemap{1,2}.xml",
        "mode": "items",
        "extract": extract_lp_products,
        "compare": None,
        "how": ("Sealed product reaches us through TCGCSV, so check reconcile_catalog\n"
                "first — if it is a box or a trove this is a duplicate signal and an ack\n"
                "is the right answer. Accessories and books never reach TCGCSV: a puzzle\n"
                "belongs in SEALED_PUZZLES, an accessory in LORCANA_GEAR (an Amazon\n"
                "SEARCH, not an ASIN — see the state-the-spec-never-rank rule)."),
    },
    {
        "id": "ja-products",
        "what": "Cards released in JAPAN, per product (Japan skips and part-releases sets)",
        "site": "takaratomy.co.jp/products/disneylorcana (card-search API)",
        "mode": "counts",
        "extract": extract_ja_products,
        "compare": None,
        "how": ("Japan's release schedule is its own thing — it skipped standalone\n"
                "releases of Fabled, Whispers and Winterspell, whose cards trickle out\n"
                "through the Curator's Library slot and promo packs. A count that MOVED\n"
                "is a new wave; a NEW bucket is a new product. Either way:\n"
                "  python scripts/ja_core_numbers.py --check    # what changed\n"
                "  python scripts/ja_core_numbers.py --print    # regenerate the consts\n"
                "then paste the JAPAN_CORE_* consts into Index.html and run\n"
                "node scripts/test_japan_core.mjs. Never hand-type the numbers — the\n"
                "source this replaced had two transposed and nothing noticed."),
    },
    {
        "id": "official-gallery",
        "what": "Cards in the official gallery, per set (spoiler season announces itself here)",
        "site": "cards.disneylorcana.com",
        "mode": "counts",
        "extract": extract_gallery,
        "compare": None,
        "how": ("A NEW `EN n` bucket means that set's cards are being revealed: run\n"
                "scripts/import_official_set.py --set-id <lorcast set> --slug set<n>\n"
                "--setnum <n> to prestage them with official art (add --commit), and\n"
                "clear the set-spoilers review. A GROWN bucket on a released set is\n"
                "usually a promo wave — reconcile_catalog will see it once TCGplayer\n"
                "lists it, so the question here is only whether it needs prestaging."),
    },
    {
        "id": "duels-renders",
        "what": "Clean reveal renders on duels.ink (better art for our stand-ins)",
        "site": "duels.ink/api/cards",
        "mode": "counts",
        "extract": extract_duels_renders,
        "compare": None,
        "how": ("`reveal renders` went UP: duels.ink has a flat render for a card we\n"
                "probably hold as a pasted crop. Dry run first, then commit:\n"
                "  python scripts/import_duels_art.py --setnum <n> --tag set<n>\n"
                "  python scripts/import_duels_art.py --setnum <n> --tag set<n> --commit\n"
                "It only upgrades rows that are already stand-ins, writes image columns\n"
                "only, and an art change wants a scanner index rebuild afterwards.\n"
                "`placeholders` went UP: a card was revealed that nobody has art for\n"
                "yet - if we do not hold it, add it from the reveal photo (the add-cards\n"
                "skill). Either number going DOWN is the official gallery taking over:\n"
                "run scripts/import_official_set.py for that set."),
    },
]

KIND_LABEL = {
    "unheld":       "On the site, not in our list (the research finding)",
    "new_item":     "New since the baseline",
    "count_moved":  "Card count moved",
    "source_empty": "SOURCE READ ZERO ITEMS — a dead URL or a redesign, not 'nothing new'",
    "shrank":       "Source lost a big share of its items — partial read or redesign",
    "source_error": "Source could not be read",
}
# Order matters: a broken source is reported above anything it might be hiding.
KIND_ORDER = ["source_error", "source_empty", "shrank", "unheld", "new_item", "count_moved"]


# --------------------------------------------------------------- state and acks

def load_state(path: str = STATE_PATH) -> dict:
    if not os.path.exists(path):
        return {"baselines": {}, "acks": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("baselines", {})
    data.setdefault("acks", {})
    return data


def save_state(data: dict, path: str = STATE_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=False)
        f.write("\n")


def ack_reason(state: dict, key: str, today: str) -> str | None:
    """The recorded reason this finding is fine, or None if it should alert.

    An `until` in the past EXPIRES the ack — that is how "revisit when the photo
    exists" becomes a mechanism instead of a promise someone has to remember.
    """
    entry = (state.get("acks") or {}).get(key)
    if not entry:
        return None
    until = entry.get("until")
    if until and until <= today:
        return None
    return entry.get("why") or "(no reason recorded)"


# ------------------------------------------------------------------- the sweep

def collect(state: dict, only: set[str] | None = None) -> list[dict]:
    findings: list[dict] = []
    for src in SOURCES:
        sid = src["id"]
        if only and sid not in only:
            continue
        base = (state.get("baselines") or {}).get(sid) or {}
        try:
            found = src["extract"]()
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
            findings.append({
                "kind": "source_error", "source": sid, "key": f"{sid}:fetch",
                "name": f"{src['what']} — {type(e).__name__}: {e}",
                "detail": src["site"],
                "hint": "Fix the URL or the extraction in scripts/watch_sources.py. Until it "
                        "reads, this source is telling you nothing — which is the failure "
                        "mode the whole file is written against.",
            })
            continue

        if not found:
            findings.append({
                "kind": "source_empty", "source": sid, "key": f"{sid}:empty",
                "name": f"{src['what']} returned no items",
                "detail": src["site"],
                "hint": "The URL moved, the page was redesigned, or the regex no longer "
                        "matches. An empty read diffs clean against any baseline, so this "
                        "is reported rather than passed.",
            })
            continue

        known = base.get("items") if src["mode"] == "items" else base.get("counts")
        if known is None:
            findings.append({
                "kind": "new_item", "source": sid, "key": f"{sid}:unbaselined",
                "name": f"{src['what']} has no baseline yet ({len(found)} items read)",
                "detail": src["site"],
                "hint": "Run: python scripts/watch_sources.py --baseline   then commit "
                        "scripts/source_watch.json.",
            })
            continue

        if src["mode"] == "items":
            _diff_items(findings, src, found, known)
        else:
            _diff_counts(findings, src, found, known)

        if src.get("compare"):
            for slug, why in src["compare"](found, state):
                findings.append({
                    "kind": "unheld", "source": sid, "key": f"{sid}:{slug}",
                    "name": slug, "detail": why, "hint": src["how"],
                })
    return findings


def _diff_items(findings: list[dict], src: dict, found: dict, known) -> None:
    known_set = set(known if isinstance(known, list) else known.keys())
    for slug in sorted(set(found) - known_set):
        findings.append({
            "kind": "new_item", "source": src["id"], "key": f"{src['id']}:{slug}",
            "name": slug, "detail": src["site"], "hint": src["how"],
        })
    if known_set and len(found) < len(known_set) * SHRINK_TOLERANCE:
        findings.append({
            "kind": "shrank", "source": src["id"], "key": f"{src['id']}:shrank",
            "name": f"{len(known_set)} items at baseline, {len(found)} now",
            "detail": src["site"],
            "hint": "Check the source by hand before re-baselining — --baseline would bake "
                    "the loss in and the items would never be mentioned again.",
        })


def _diff_counts(findings: list[dict], src: dict, found: dict, known) -> None:
    for bucket in sorted(found):
        was = (known or {}).get(bucket)
        now = found[bucket]
        if was is None:
            findings.append({
                "kind": "count_moved", "source": src["id"], "key": f"{src['id']}:{bucket}",
                "name": f"{bucket} is new — {now} cards",
                "detail": src["site"], "hint": src["how"],
            })
        elif now != was:
            findings.append({
                "kind": "count_moved", "source": src["id"],
                "key": f"{src['id']}:{bucket}:{now}",
                "name": f"{bucket}: {was} → {now} cards",
                "detail": src["site"], "hint": src["how"],
            })


def current_baselines(only: set[str] | None = None) -> tuple[dict, list[str]]:
    out, errors = {}, []
    for src in SOURCES:
        if only and src["id"] not in only:
            continue
        try:
            found = src["extract"]()
        except Exception as e:  # noqa: BLE001 - a baseline run reports and moves on
            errors.append(f"{src['id']}: {type(e).__name__}: {e}")
            continue
        if not found:
            errors.append(f"{src['id']}: read zero items — NOT baselined (that would "
                          f"make a dead source look healthy forever)")
            continue
        entry = {"site": src["site"], "checked": date.today().isoformat()}
        if src["mode"] == "items":
            entry["count"] = len(found)
            entry["items"] = sorted(found)
        else:
            entry["counts"] = dict(sorted(found.items()))
        out[src["id"]] = entry
    return out, errors


# ------------------------------------------------------------------------- CLI

def run_report(fail: bool, only: set[str] | None, json_path: str | None) -> int:
    today = date.today().isoformat()
    state = load_state()
    findings = collect(state, only)
    fresh = [f for f in findings if ack_reason(state, f["key"], today) is None]
    known = len(findings) - len(fresh)

    print("\n" + "=" * 72)
    print(f"SOURCE WATCH — {len(fresh)} new, {known} acknowledged")
    print("=" * 72)

    if not fresh:
        print("\nNothing new. Every site we research from lists what it listed last time.")
    else:
        by_kind: dict[str, list[dict]] = {}
        for f in fresh:
            by_kind.setdefault(f["kind"], []).append(f)
        for kind in KIND_ORDER:
            items = by_kind.get(kind)
            if not items:
                continue
            print(f"\n>> {KIND_LABEL.get(kind, kind)}  ({len(items)})")
            for f in items:
                print(f"\n    {f['key']}")
                print(f"      {f['name']}")
                print(f"      where: {f['detail']}")
            for i, line in enumerate(str(items[0]["hint"]).split("\n")):
                print(("      how:   " if i == 0 else "             ") + line)
        print("\nEither act on it, or record the decision so it stops asking:")
        print(f'    python scripts/watch_sources.py --ack {fresh[0]["key"]} '
              f'--why "why this is fine" [--until YYYY-MM-DD]')
        print("  ...or accept every finding at once:")
        print('    python scripts/watch_sources.py --ack-all --why "..."')

    _write_summary(fresh, known)
    if json_path:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump({"new": fresh, "acknowledged": known}, f, indent=2, ensure_ascii=False)
        print(f"\nWrote structured report -> {json_path}")

    if fresh and fail:
        print(f"\n{len(fresh)} unacknowledged finding(s) -> exiting 1 so the run goes red.")
        return 1
    return 0


def _write_summary(fresh: list[dict], known: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    lines = ["## Source watch\n\n"]
    if not fresh:
        lines.append(f"Nothing new. {known} finding(s) already acknowledged.\n")
    else:
        lines.append(f"**{len(fresh)} new finding(s)**, {known} acknowledged.\n\n")
        lines.append("| key | what | where |\n|--|--|--|\n")
        for f in fresh:
            lines.append(f"| `{f['key']}` | {f['name']} | {f['detail']} |\n")
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError:
        pass


def run_baseline(only: set[str] | None) -> int:
    state = load_state()
    fresh, errors = current_baselines(only)
    if not fresh:
        print("Nothing baselined." + (" Errors:" if errors else ""))
        for e in errors:
            print("  " + e)
        return 1
    for sid, entry in fresh.items():
        was = (state["baselines"].get(sid) or {})
        old = was.get("count") if "count" in was else sum((was.get("counts") or {}).values())
        new = entry.get("count") if "count" in entry else sum(entry["counts"].values())
        print(f"  {sid}: {old if old is not None else '-'} -> {new}")
        state["baselines"][sid] = entry
    save_state(state)
    print(f"\nWrote {STATE_PATH}. Commit it so CI compares against what you just saw.")
    for e in errors:
        print("  ! " + e)
    return 1 if errors else 0


DEFAULT_ACK_DAYS = 0  # permanent unless --until says otherwise


def run_ack(keys: list[str], why: str | None, until: str | None, ack_all: bool,
            only: set[str] | None) -> int:
    if not why:
        print("--why is required. This file is a decision record: an entry with no reason "
              "cannot be told apart from sweeping something under the rug.")
        return 2
    state = load_state()
    if ack_all:
        findings = collect(state, only)
        today = date.today().isoformat()
        keys = [f["key"] for f in findings if ack_reason(state, f["key"], today) is None]
        if not keys:
            print("Nothing to acknowledge.")
            return 0
    if until:
        try:
            date.fromisoformat(until)
        except ValueError:
            print(f"--until must be YYYY-MM-DD (got {until!r})")
            return 2
    for key in keys:
        entry = {"acked": date.today().isoformat(), "why": why}
        if until:
            entry["until"] = until
        state["acks"][key] = entry
        print(f"  acked {key}")
    save_state(state)
    print(f"\nWrote {STATE_PATH}. Commit it so CI stops asking.")
    return 0


def run_explain() -> int:
    """Re-measure the pin/counter match threshold against today's real data.

    The 0.6 in MATCH_MIN is only defensible as long as the two clouds stay apart,
    and both lists grow. This prints the margin so the claim can be re-checked
    rather than believed.
    """
    for sid, const, extract in (("lp-pins", "LORCANA_PINS", extract_lp_pins),
                                ("lp-counters", "LORCANA_LORE_COUNTERS", extract_lp_counters)):
        held = held_collectibles(const)
        found = extract()
        scored = sorted((best_match(s, held)[0], s) for s in found)
        print(f"\n{sid}: {len(found)} on the site, {len(held)} in {const}")
        if not scored:
            continue
        print(f"  lowest true-match coverage: {scored[0][0]:.0%}  ({scored[0][1]})")
        below = [(sc, s) for sc, s in scored if sc < MATCH_MIN]
        print(f"  would report as unheld at MATCH_MIN={MATCH_MIN:.0%}: {len(below)}")
        for sc, s in below:
            print(f"     {sc:.0%}  {s}")
    print("\nA healthy margin is: every real item well above MATCH_MIN, and nothing "
          "sitting just under it.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--baseline", action="store_true",
                    help="Accept what the sources read right now as the known state.")
    ap.add_argument("--ack", action="append", default=[], metavar="KEY",
                    help="Record a decision about one finding key.")
    ap.add_argument("--ack-all", action="store_true",
                    help="Record the same decision about every current finding.")
    ap.add_argument("--why", help="Why the finding is fine (required with --ack/--ack-all).")
    ap.add_argument("--until", help="Expire the ack on this date and re-alert (YYYY-MM-DD).")
    ap.add_argument("--only", action="append", default=[], metavar="SOURCE_ID",
                    help="Limit to one source id (repeatable).")
    ap.add_argument("--json", dest="json_path", help="Also write the report as JSON.")
    ap.add_argument("--no-fail", action="store_true",
                    help="Report but always exit 0.")
    ap.add_argument("--explain", action="store_true",
                    help="Re-measure the pin/counter match threshold against live data.")
    ap.add_argument("--list", action="store_true", help="List the declared sources and exit.")
    args = ap.parse_args()

    only = set(args.only) or None
    if only:
        bad = only - {s["id"] for s in SOURCES}
        if bad:
            print(f"Unknown source id(s): {', '.join(sorted(bad))}")
            print("Known: " + ", ".join(s["id"] for s in SOURCES))
            return 2

    if args.list:
        for s in SOURCES:
            print(f"{s['id']:18s} {s['mode']:7s} {s['site']}")
            print(f"{'':18s}         {s['what']}")
        return 0
    if args.explain:
        return run_explain()
    if args.baseline:
        return run_baseline(only)
    if args.ack or args.ack_all:
        return run_ack(args.ack, args.why, args.until, args.ack_all, only)
    return run_report(not args.no_fail, only, args.json_path)


if __name__ == "__main__":
    raise SystemExit(main())
