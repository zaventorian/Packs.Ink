"""Which Lorcana cards are actually released in JAPAN, from the publisher.

    python scripts/ja_core_numbers.py --check    # diff against Index.html, exit 1 on drift
    python scripts/ja_core_numbers.py --print    # emit the JS consts to paste
    python scripts/ja_core_numbers.py --names    # audit JAPAN_CORE_PARTIAL_NAMES

WHY THIS EXISTS
===============
`isJapanCoreLegal` answers "can you buy this card in Japan at all", and it backs
the `legality: japan` search filter. Until 2026-09-14 its data came from **a
Japanese singles retailer's product titles**, regexed for `N/204 JA-1x` strings,
because — as the comment in Index.html put it — "Ravensburger publishes no
Japan-legal card list".

They don't. **Takara Tomy does**, and they are the Japanese publisher:

    https://www.takaratomy.co.jp/products/disneylorcana/cardlist/

That page is a Vue app over a real JSON API, and the API returns the publisher's
own card database — `collector_number`, rarity, stats, and a `card_file` whose
middle token is the SET CODE (`005_DLCS10_Higgins_UndercoverOfficer_JA`). So the
question stops being "what is this retailer holding in stock" and becomes "what
has the publisher printed", which is the question that was being asked.

Two calls, no key:
  POST /products/disneylorcana/api1.0/card-search/token.json  -> {"csrf": "..."}
  POST /products/disneylorcana/api1.0/card-search/result      -> {"cards": [...], "count": N}
      form-urlencoded `sets[]=<japanese product name>&page=N`, X-CSRF-Token header,
      20 rows a page. The product names come from the site's own env.js, parsed
      rather than retyped — they are full-width Japanese and one wrong character
      returns an empty list, which would read as "nothing released".

WHAT IT FOUND ON THE FIRST RUN (2026-09-14)
-------------------------------------------
  * **Fabled was marked fully released in Japan and is not.** Japan never gave it
    a standalone release; it arrives through two "特別プロモーションパック"
    (special promotion pack) vol.1 + vol.2 carrying **71 of its 243 cards**. So
    172 Fabled cards were Japan-Core-legal and should not have been.
  * **Whispers in the Well matched exactly, 59/59.** The old retailer scrape was
    right, which is worth knowing: this replaces it for authority, not because it
    was sloppy.
  * **Winterspell had two transposed numbers** — 12 for 21, 141 for 143. Both
    rescued by the `JAPAN_CORE_PARTIAL_NAMES` union, so only #12 and #141 were
    wrongly legal. That union existing is why a digit slip cost two cards instead
    of four.

⚠ FULL vs PARTIAL IS DERIVED, NOT LISTED. A set is FULL when ONE product accounts
for at least `JA_FULL_SET_MIN` of its cards — i.e. that product IS the set's
standalone Japanese release. Measured: standalone releases return **216..245**
cards and every partial vehicle returns **≤ 87** (Curator's Library 50 and 87,
the two starter decks 24 each, the Fabled packs 36 and 35), so 150 sits in a very
wide empty band. Deriving it is what caught Fabled: env.js lists that product in
the same array as the real set releases, so membership proves nothing and only
the card count separates them.

⚠ A FULL set is still missing its last 1-3 numbers. Japan prints 222 cards a set
where English adds up to 3 more at the very end (Ursula's Return 223-225,
Archazia's Island 223-224, Reign of Jafar 223-224, Shimmering Skies 223). Those
are the English-only tail slots. They are NOT modelled: `JAPAN_CORE_FULL_SETS` is
a whole-set flag, so treating those sets as full over-includes at most 8 cards
site-wide. Narrowing it means giving every set a number list, which is a bigger
change than the error justifies — but the `--check` output prints them so the
decision stays visible instead of being forgotten.
"""
from __future__ import annotations

import argparse
import http.cookiejar as cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_HTML = os.path.join(os.path.dirname(HERE), "Index.html")

BASE = "https://www.takaratomy.co.jp"
ENV_JS = BASE + "/products/disneylorcana/common/components/js/env.js"
TOKEN_URL = BASE + "/products/disneylorcana/api1.0/card-search/token.json"
RESULT_URL = BASE + "/products/disneylorcana/api1.0/card-search/result"
REFERER = BASE + "/products/disneylorcana/cardlist/"
PAGE_SIZE = 20

# See the docstring: standalone releases return 216..245, every partial vehicle
# returns <= 87. Anything in between has never existed.
JA_FULL_SET_MIN = 150

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ja,en;q=0.9",
    "Referer": REFERER,
    "Origin": BASE,
}
_jar = cookiejar.CookieJar()
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(_jar))


def _get(url: str) -> str:
    req = urllib.request.Request(url, headers={**HEADERS, "Accept": "*/*"})
    with _opener.open(req, timeout=60) as r:
        return r.read().decode("utf-8", "ignore")


def _post(url: str, body: str = "", token: str | None = None) -> dict:
    h = {**HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
    if token:
        h["X-CSRF-Token"] = token
    req = urllib.request.Request(url, data=body.encode(), headers=h, method="POST")
    with _opener.open(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "{}")


def japanese_products() -> list[str]:
    """The publisher's own product list, parsed out of the site's env.js.

    ⚠ Parsed, never retyped. The names are full-width Japanese ('ＷＩＬＤＳ
    ＵＮＫＮＯＷＮ　未知なる彼方へ！') and the API answers a wrong name with an
    empty list — which would read as "that set released nothing in Japan".
    Commented-out entries are skipped: env.js carries a disabled `special_sets`
    block holding 'ＧＡＴＥＷＡＹ', which really does return 0 cards.
    """
    env = _get(ENV_JS)
    block = env[env.index("sets: {"):env.index("ink_type:")]
    live = [ln for ln in block.split("\n")
            if not ln.strip().startswith(("//", "/*", "*"))]
    names = [n for n in re.findall(r"'([^']+)'", "\n".join(live)) if len(n) > 4]
    if not names:
        raise SystemExit("env.js published no product names — the page was redesigned.")
    return names


def get_token() -> str:
    """⚠ The token goes stale mid-run and the API then answers 403.

    The site's own useSearch.js loops `getToken` five times with a 1s sleep, so
    a failed token is the expected case rather than an outage — and a long walk
    of the catalog outlives one. Every request goes through `_search` below,
    which re-acquires on 403 instead of dying two thirds of the way through and
    reporting a partial Japanese catalog as the truth.
    """
    last = None
    for i in range(5):
        try:
            tok = _post(TOKEN_URL).get("csrf")
            if tok:
                return tok
        except Exception as e:  # noqa: BLE001
            last = e
        time.sleep(1 + i)
    raise SystemExit(f"could not get a CSRF token after 5 tries ({last})")


_token: list[str] = []


def _search(name: str, page: int) -> dict:
    """One page of results, re-acquiring the token and backing off on 403/5xx."""
    body = urllib.parse.urlencode([("sets[]", name), ("page", str(page))],
                                  encoding="utf-8")
    for attempt in range(4):
        if not _token:
            _token.append(get_token())
        try:
            return _post(RESULT_URL, body, _token[0])
        except urllib.error.HTTPError as e:
            if e.code not in (401, 403, 419, 429, 500, 502, 503):
                raise
            _token.clear()
            time.sleep(1.5 * (attempt + 1))
        except urllib.error.URLError:
            time.sleep(1.5 * (attempt + 1))
    raise SystemExit(f"the card-search API kept refusing page {page} of {name!r}. "
                     "Back off and re-run; do not treat a partial pull as the answer.")


def pull(name: str, paginate: bool) -> tuple[int, list[dict]]:
    """(total the API claims, rows actually fetched).

    `paginate=False` fetches only page 1, which is enough to learn a standalone
    set release's size — the expensive case, and one whose numbers we never need
    because the whole set is legal.

    ⚠ It raises rather than returning a short list. A truncated pull would look
    exactly like "Japan released fewer cards", which is the one wrong answer this
    whole script exists to prevent.
    """
    rows: list[dict] = []
    total = None
    page = 1
    while True:
        d = _search(name, page)
        got = d.get("cards") or []
        if total is None:
            total = int(d.get("count") or 0)
        rows += got
        if not paginate or not got or len(rows) >= total:
            if paginate and total and len(rows) < total:
                raise SystemExit(
                    f"{name!r}: API claims {total} cards, only {len(rows)} came back. "
                    "Refusing to report a partial pull as the Japanese catalog.")
            return total or 0, rows
        page += 1
        time.sleep(0.5)


_CARD_FILE = re.compile(r"^(\d+)[A-Za-z]?_(DLCS\d+)_(?:[A-Z]{2,5}_)?(.*?)_JA$")


def parse_card_file(cf: str) -> tuple[str, int, str] | None:
    """('DLCS10', 5, 'Higgins_UndercoverOfficer') out of
    '005_DLCS10_Higgins_UndercoverOfficer_JA'.

    The leading token is the collector number and the second is the set code,
    whose digits are the ENGLISH set index — DLCS9 is Fabled, the ninth entry of
    MAINLINE_SETS. That is the join that makes any of this usable.

    ⚠ Some files carry a rarity/ink block between the two (`001_DLCS9_RCAX_
    TheQueen_ConceitedRuler_JA`) and some do not. The optional 2-5 uppercase
    group absorbs it; without that, the English name comes back with `RCAX_`
    glued to the front and every name comparison misses.
    """
    m = _CARD_FILE.match(cf or "")
    return (m.group(2), int(m.group(1)), m.group(3)) if m else None


def mainline_sets() -> list[str]:
    """MAINLINE_SETS, read out of Index.html so the mapping cannot drift."""
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    i = html.index("const MAINLINE_SETS = [")
    block = html[i:html.index("];", i)]
    return re.findall(r'"([^"]+)"', block)


def fetch_japan_state(verbose: bool = True) -> dict:
    """{'full': {set names}, 'partial': {set name: {numbers}}, 'products': {...}}"""
    sets_in_order = mainline_sets()
    products = japanese_products()

    # Pass 1: one request each, to learn every product's size.
    sizes: dict[str, int] = {}
    first: dict[str, list[dict]] = {}
    for name in products:
        total, rows = pull(name, paginate=False)
        sizes[name], first[name] = total, rows
        if verbose:
            print(f"  {total:>4} cards  {name}")
        time.sleep(0.25)

    # Pass 2: paginate ONLY the small products. A standalone set release is
    # wholly legal, so its individual numbers are never needed — and skipping
    # them is the difference between ~28 requests and ~150.
    by_code: dict[str, dict[int, str]] = defaultdict(dict)
    full_codes: set[str] = set()
    for name, total in sizes.items():
        rows = first[name]
        if total >= JA_FULL_SET_MIN:
            codes = {p[0] for p in (parse_card_file(r.get("card_file")) for r in rows) if p}
            # A standalone release is one set's own product; if page 1 somehow
            # spans codes, fall through and count it properly rather than guess.
            if len(codes) == 1:
                full_codes |= codes
                continue
        if total and len(rows) < total:
            _t, rows = pull(name, paginate=True)
            time.sleep(0.25)
        for r in rows:
            p = parse_card_file(r.get("card_file"))
            if p:
                by_code[p[0]][p[1]] = p[2]

    def name_of(code: str) -> str | None:
        n = int(code.replace("DLCS", ""))
        return sets_in_order[n - 1] if 1 <= n <= len(sets_in_order) else None

    full = {name_of(c) for c in full_codes}
    full.discard(None)
    partial, partial_names = {}, {}
    for code, found in by_code.items():
        nm = name_of(code)
        if nm and nm not in full:
            partial[nm] = set(found)
            partial_names[nm] = dict(found)
    return {"full": full, "partial": partial, "partial_names": partial_names,
            "products": sizes, "full_codes": full_codes,
            "by_code": {k: dict(v) for k, v in by_code.items()}}


# ------------------------------------------------------- what Index.html says

def current_consts() -> dict:
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    i = html.index("const JAPAN_CORE_FULL_SETS = new Set([")
    full = set(re.findall(r'"([^"]+)"', html[i:html.index("]);", i)]))
    i = html.index("const JAPAN_CORE_PARTIAL_SETS = new Set([")
    partial_sets = set(re.findall(r'"([^"]+)"', html[i:html.index("]);", i)]))
    i = html.index("const JAPAN_CORE_PARTIAL_NUMBERS = {")
    block = html[i:html.index("\n};", i)]
    nums = {}
    for m in re.finditer(r'"([^"]+)":\s*new Set\(\[(.*?)\]\)', block, re.S):
        nums[m.group(1)] = {int(x) for x in re.findall(r"\d+", m.group(2))}
    return {"full": full, "partial_sets": partial_sets, "numbers": nums}


def render_consts(state: dict) -> str:
    order = mainline_sets()
    full = sorted(state["full"], key=lambda s: order.index(s) if s in order else 99)
    partial = sorted(state["partial"], key=lambda s: order.index(s) if s in order else 99)
    out = ["const JAPAN_CORE_FULL_SETS = new Set(["]
    line = "  "
    for s in full:
        piece = f'"{s}", '
        if len(line) + len(piece) > 96:
            out.append(line.rstrip())
            line = "  "
        line += piece
    out.append(line.rstrip().rstrip(","))
    out.append("]);")
    out.append("const JAPAN_CORE_PARTIAL_SETS = new Set([" +
               ", ".join(f'"{s}"' for s in partial) + "]);")
    out.append("const JAPAN_CORE_PARTIAL_NUMBERS = {")
    for s in partial:
        out.append(f'  "{s}": new Set([')
        nums = sorted(state["partial"][s])
        line = "    "
        for n in nums:
            piece = f"{n},"
            if len(line) + len(piece) > 92:
                out.append(line)
                line = "    "
            line += piece
        out.append(line)
        out.append("  ]),")
    out.append("};")
    return "\n".join(out)


def run_check(state: dict) -> int:
    cur = current_consts()
    bad = 0
    print("\n" + "=" * 74)
    print("JAPAN CORE — publisher vs Index.html")
    print("=" * 74)

    wrongly_full = sorted(cur["full"] & set(state["partial"]))
    for s in wrongly_full:
        have = len(state["partial"][s])
        print(f"\n  ! {s}: marked FULLY released, publisher has {have} cards.")
        print(f"    Japan gave it no standalone release. Move it to "
              f"JAPAN_CORE_PARTIAL_SETS with its {have} numbers.")
        bad += 1
    missing_full = sorted(state["full"] - cur["full"])
    for s in missing_full:
        print(f"\n  ! {s}: fully released in Japan but not in JAPAN_CORE_FULL_SETS.")
        bad += 1

    for s in sorted(state["partial"]):
        theirs = state["partial"][s]
        mine = cur["numbers"].get(s)
        if mine is None:
            if s not in wrongly_full:
                print(f"\n  ! {s}: partial in Japan ({len(theirs)} cards) with no "
                      f"JAPAN_CORE_PARTIAL_NUMBERS entry.")
                bad += 1
            continue
        extra, short = sorted(mine - theirs), sorted(theirs - mine)
        if not extra and not short:
            print(f"\n  ok {s}: {len(theirs)} numbers, exact match.")
            continue
        print(f"\n  ! {s}: publisher {len(theirs)}, we list {len(mine)}")
        if extra:
            print(f"      we allow, Japan has NOT released: {extra}")
        if short:
            print(f"      Japan released, we omit:          {short}")
        bad += 1

    print("\n  Note: a FULL set still lacks the last 1-3 numbers English adds"
          "\n  (Japan prints 222 a set). Not modelled — JAPAN_CORE_FULL_SETS is a"
          "\n  whole-set flag, so at most ~8 cards site-wide are over-included."
          "\n  Run with --print to regenerate the consts.")
    print("\n" + ("=" * 74))
    print(f"{bad} discrepanc{'y' if bad == 1 else 'ies'}.")
    return 1 if bad else 0


def run_names(state: dict) -> int:
    """Audit JAPAN_CORE_PARTIAL_NAMES, the union that rescues number misses.

    It exists because a retailer can be out of stock; a publisher cannot. So the
    question is now whether it LEGALISES anything the publisher does not list.
    """
    with open(INDEX_HTML, encoding="utf-8") as f:
        html = f.read()
    i = html.index("const JAPAN_CORE_PARTIAL_NAMES = new Set([")
    block = html[i:html.index("].map(_jpNorm));", i)]
    names = re.findall(r'"([^"]+)"', block)

    def norm(s):
        return re.sub(r"[^a-z0-9]+", "", (s or "").lower())

    # Publisher-side names come out of card_file: Higgins_UndercoverOfficer.
    published = {norm(eng) for byn in state["partial_names"].values()
                 for eng in byn.values()}
    # ...plus every card of a fully-released set, which the name list may also
    # mention. Those are legal via JAPAN_CORE_FULL_SETS regardless, so a name
    # matching one of them is harmless rather than wrong.
    print(f"\nJAPAN_CORE_PARTIAL_NAMES holds {len(names)} names; the publisher "
          f"lists {len(published)} cards across the partial sets.")
    unmatched = [n for n in names if norm(n) not in published]
    print(f"\n  names the publisher does NOT list in a partial set: {len(unmatched)}")
    for n in unmatched:
        print("     ", n)
    print("\n  Any name above is either (a) a card of a FULLY released set, where"
          "\n  the name entry is redundant, or (b) a card Japan has not released,"
          "\n  where the union is WRONGLY legalising it. The numbers are the"
          "\n  authority now — a publisher has no out-of-stock gaps to paper over,"
          "\n  which was this list's whole reason for existing.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="Diff the publisher against Index.html; exit 1 on drift.")
    ap.add_argument("--print", dest="do_print", action="store_true",
                    help="Emit the JS consts to paste into Index.html.")
    ap.add_argument("--names", action="store_true",
                    help="Audit JAPAN_CORE_PARTIAL_NAMES.")
    ap.add_argument("--json", dest="json_path", help="Dump the raw state as JSON.")
    ap.add_argument("--quiet", action="store_true", help="Don't list every product.")
    args = ap.parse_args()

    print("Reading the Japanese publisher's card database "
          "(takaratomy.co.jp/products/disneylorcana)...")
    state = fetch_japan_state(verbose=not args.quiet)
    order = mainline_sets()
    print(f"\nFully released in Japan ({len(state['full'])}): "
          + ", ".join(sorted(state["full"], key=lambda s: order.index(s))))
    print(f"Partially released ({len(state['partial'])}): "
          + ", ".join(f"{s} ({len(v)})" for s, v in
                      sorted(state["partial"].items(), key=lambda kv: order.index(kv[0]))))

    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump({"full": sorted(state["full"]),
                       "partial": {k: sorted(v) for k, v in state["partial"].items()},
                       "products": state["products"]}, f, ensure_ascii=False, indent=2)
        print(f"\nWrote {args.json_path}")
    if args.do_print:
        print("\n" + "-" * 74)
        print(render_consts(state))
        print("-" * 74)
    if args.names:
        return run_names(state)
    if args.check or not (args.do_print or args.json_path):
        return run_check(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
