"""Tell us when a Lorcana event is announced that the calendar doesn't have.

    python scripts/watch_calendar_sources.py            # report (exit 1 if new)
    python scripts/watch_calendar_sources.py --ack-all  # accept today's findings

WHY THIS EXISTS
===============
The curated calendar is the one part of the site nothing refreshes on its own.
Prices have an ETL, events have a daily discovery job, the catalog has
catalog-watch — but a Challenge announced next Tuesday reaches the calendar only
if a person happens to notice. That is exactly the failure catalog-watch was
built to stop, so this is the same shape: a daily sweep that goes red ONLY when
something is new, with every ruling recorded in a committed file.

THREE SOURCES, because none sees the whole picture:

  * Ravensburger's own Challenge page, which is the AUTHORITY on which events
    are sanctioned qualifiers. Added 2026-09-14 after the calendar was found
    three qualifiers short of it with two more misnamed and unlinked — it had
    never been read, so nothing could notice.
    ⚠ ITS QUALIFIER LIST IS SPLIT ACROSS LOCALES AND EACH CARRIES HALF. en-US
    heads its list "North America Challenge Championship Qualifiers"; en-GB
    carries a second, "EU & UK ...", that appears on no US page. Reading one
    locale silently loses half the season — that is exactly how CCQ Sevilla was
    missing. Both are fetched and merged. (it-IT is stale, still listing June
    2026, so it is not a third locale to add — it is a trap.)
    It lists only the qualifiers and the season's Challenges; a store-run event
    reaches us through the other two.

  * The community competitive-season page. It is the only place a whole season
    is listed at once — Ravensburger announces Challenges piecemeal — and it is
    usually updated within a day of an announcement. Fan-maintained, so it
    proposes and a person decides.
    ⚠ The site 403s a plain page fetch; its MediaWiki api.php answers 200.

  * Ravensburger Play itself, via `lorcana_events`, for qualifier-shaped titles
    at stores. Most big qualifiers are store-created and never appear on any
    official list, so the feed catches what the page misses. This overlaps
    scan_ccq_candidates.py deliberately: that one PROPOSES rows into the review
    queue, this one only reports, so a queue nobody has drained still shows up
    here as unfinished business.

⚠ IT NEVER WRITES TO THE CALENDAR. Publishing an event is a person's decision —
the same rule as `confirmed` in migration 139. This only tells you to look.

The state file is scripts/calendar_watch.json: one `acks` entry per ruling, with
a reason. `--ack-all` takes today's findings; an entry can carry `until` to make
the ack expire and re-alert, for "revisit when the venue is announced".
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
STATE = Path(__file__).resolve().parent / "calendar_watch.json"

WIKI_API = "https://lorcana.fandom.com/api.php"
SEASON_PAGES = ["Disney_Lorcana_2026-2027_Competitive_Season"]
# ⚠ The wiki needs a browser-ish User-Agent; SUPABASE MUST NOT GET ONE. Sending
# "Mozilla/5.0 (packs.ink calendar watch)" to PostgREST returns 401 Unauthorized
# with a perfectly valid service key — the edge in front of it rejects the agent
# string before the key is ever checked. Isolated by sending the same request
# four ways: bare 200, +Accept 200, +that UA 401. So the two callers below carry
# their own headers and there is no shared default.
WIKI_HEADERS = {"User-Agent": "Mozilla/5.0 (packs.ink calendar watch)", "Accept": "application/json"}

# ⚠ BOTH locales, always — each carries a qualifier list the other does not.
OFFICIAL_PAGES = (
    "https://www.disneylorcana.com/en-US/play/lorcana-challenge",
    "https://www.disneylorcana.com/en-GB/play/lorcana-challenge",
)
OFFICIAL_HEADERS = {"User-Agent": "Mozilla/5.0 (packs.ink calendar watch)",
                    "Accept": "text/html"}

# Qualifier-shaped titles at stores, the same net scan_ccq_candidates.py casts.
RPH_NET = ("ccq", "championship qualifier", "challenge qualifier")


def http_json(url, method="GET", headers=None, body=None):
    h = {"Accept": "application/json"}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw.strip() else []


def sb(path):
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    return http_json(f"{SUPABASE_URL}/rest/v1/{path}",
                     headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"})


def norm(s: str) -> str:
    """Fold accents and punctuation so 'Malmö Game Week Open #3' and
    'Malmo Game Week Open 3' are one event rather than two findings."""
    n = unicodedata.normalize("NFKD", s or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", n).strip()


def _stem(s: str) -> str:
    """norm() minus the noise words every source spells differently — the page
    calls it 'Utopica Fantasy Festival', we title it '... CCQ'."""
    drop = {"ccq", "the", "disney", "lorcana", "tcg", "official", "qualifier",
            "championship", "challenge"}
    return " ".join(w for w in norm(s).split() if w not in drop)


def already_have(name, start, url, have):
    """Is this announcement already on the calendar?

    ⚠ The registration URL is the only key that survives translation: the same
    qualifier is named differently on each locale and differently again in our
    own title. Name matching is the fallback, and it is DATE-GUARDED — a loose
    name test alone would suppress next season's 'CCQ Sevilla' because this
    season's is still in the table."""
    if url and url.rstrip("/") in {(r.get("url") or "").rstrip("/") for r in have if r.get("url")}:
        return True
    n, stem = norm(name), _stem(name)
    for r in have:
        if norm(r["title"]) == n:
            return True
        if start is None or r.get("starts_on") != start.isoformat():
            continue
        other = _stem(r["title"])
        if stem and other and (stem == other
                               or (len(stem) >= 8 and stem in other)
                               or (len(other) >= 8 and other in stem)):
            return True
    return False


# ── the season page ─────────────────────────────────────────────────────────
MONTHS = {m.lower(): i for i, m in enumerate(
    ["January","February","March","April","May","June","July","August",
     "September","October","November","December"], 1)}
# "August 22-23, 2026" / "October 31-November 1, 2026" / "March 27, 2027"
DATE_RE = re.compile(r"([A-Z][a-z]+)\s+(\d{1,2})(?:\s*[-–]\s*(?:([A-Z][a-z]+)\s+)?(\d{1,2}))?,\s*(\d{4})")


def parse_date(text):
    m = DATE_RE.search(text or "")
    if not m:
        return None, None
    mon1, d1, mon2, d2, year = m.groups()
    i1 = MONTHS.get(mon1.lower())
    if not i1:
        return None, None
    try:
        start = dt.date(int(year), i1, int(d1))
    except ValueError:
        return None, None
    end = None
    if d2:
        i2 = MONTHS.get((mon2 or mon1).lower(), i1)
        try:
            end = dt.date(int(year), i2, int(d2))
            # "December 31-January 2, 2027" rolls the year on the far end.
            if end < start:
                end = dt.date(int(year) + 1, i2, int(d2))
        except ValueError:
            end = None
    return start, end


SECTION_KIND = {
    "challenge championship qualifiers": "ccq",
    "disney lorcana challenges": "dlc",
    "grand prix": "dlc",
    "national & continental championships": "dlc",
    "world championship": "dlc",
}


def fetch_season_events():
    """(kind, name, start, end) for every dated row in the season tables."""
    out = []
    for page in SEASON_PAGES:
        q = urllib.parse.urlencode({"action": "parse", "page": page,
                                    "prop": "wikitext", "format": "json"})
        try:
            d = http_json(f"{WIKI_API}?{q}", headers=WIKI_HEADERS)
        except Exception as e:
            print(f"  ::warning:: could not read the season page ({e})")
            continue
        text = (d.get("parse") or {}).get("wikitext", {}).get("*", "")
        kind = None
        for block in re.split(r"===\s*", text):
            head = block.split("===")[0].strip().lower()
            if head in SECTION_KIND:
                kind = SECTION_KIND[head]
            if not kind:
                continue
            # Table rows are "|cell" lines separated by "|-".
            for row in block.split("|-"):
                cells = [c.strip() for c in row.split("\n") if c.startswith("|")]
                cells = [re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", c[1:]).strip() for c in cells]
                cells = [c for c in cells if c]
                if len(cells) < 2:
                    continue
                name, start, end = cells[0], None, None
                for c in cells[1:3]:
                    start, end = parse_date(c)
                    if start:
                        break
                if start and name and not name.startswith("!"):
                    out.append((kind, name, start, end))
    return out


# ── Ravensburger's own Challenge page ───────────────────────────────────────
# Each qualifier is one <p>: "<strong>DATE:</strong>" then "City, Country –
# Event Name – Venue", usually wrapped in the registration <a href>. The name is
# the MIDDLE dash-segment; with only two, the venue is absent and it is the last.
_P_RE = re.compile(r"(?is)<p[^>]*>(.*?)</p>")
_STRONG_RE = re.compile(r"(?is)<strong[^>]*>(.*?)</strong>")
_HREF_RE = re.compile(r"""(?is)<a[^>]+href=["']([^"']+)["']""")


def _detag(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"(?s)<[^>]+>", " ", s or ""))).strip()


def fetch_official_ccqs():
    """(kind, name, start, end, url) for every qualifier Ravensburger lists.

    Returns [] on any failure — this source going quiet must not take the whole
    sweep down, since the other two still answer."""
    out, seen = [], set()
    for page in OFFICIAL_PAGES:
        try:
            req = urllib.request.Request(page, headers=OFFICIAL_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                doc = r.read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  ::warning:: could not read {page} ({e})")
            continue
        for m in re.finditer(r"Challenge Championship Qualifiers", doc):
            for para in _P_RE.findall(doc[m.end():m.end() + 4000]):
                sm = _STRONG_RE.search(para)
                if not sm:
                    continue
                start, end = parse_date(_detag(sm.group(1)))
                if not start:
                    continue
                rest = _detag(_STRONG_RE.sub(" ", para)).lstrip(": ").strip()
                parts = [p.strip() for p in re.split(r"[–—-]", rest) if p.strip()]
                if not parts:
                    continue
                name = parts[1] if len(parts) >= 3 else parts[-1]
                hm = _HREF_RE.search(para)
                url = hm.group(1) if hm else None
                key = url or norm(name)
                if key in seen:
                    continue
                seen.add(key)
                out.append(("ccq", name, start, end, url))
    return out


def fetch_rph_qualifiers():
    ors = ",".join(f"name.ilike.*{urllib.parse.quote(t)}*" for t in RPH_NET)
    rows = sb("lorcana_events?select=event_id,name,start_datetime,store_name,country"
              f"&or=({ors})&start_datetime=gte.now()&order=start_datetime.asc&limit=300")
    out = []
    for r in rows:
        try:
            d = dt.date.fromisoformat((r.get("start_datetime") or "")[:10])
        except Exception:
            continue
        out.append(("ccq", (r.get("name") or "").strip(), d, None, r.get("event_id")))
    return out


def load_state():
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"acks": {}}


def ack_live(entry, today):
    """An ack with an `until` in the past has expired and re-alerts — that is how
    'revisit when the venue is announced' becomes a mechanism instead of a
    promise somebody has to remember."""
    if not isinstance(entry, dict):
        return True
    until = entry.get("until")
    if not until:
        return True
    try:
        return dt.date.fromisoformat(until) >= today
    except Exception:
        return True


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ack-all", action="store_true",
                    help="record every current finding as seen")
    ap.add_argument("--why", default="seen", help="reason stored with --ack-all")
    args = ap.parse_args()

    today = dt.date.today()
    state = load_state()
    acks = state.get("acks", {})

    have = sb("calendar_events?select=kind,title,starts_on,event_id,url&limit=2000")
    have_ids = {r.get("event_id") for r in have if r.get("event_id")}
    print(f"calendar holds {len(have)} curated events")

    findings = []
    for kind, name, start, end, url in fetch_official_ccqs():
        if start < today:
            continue
        if already_have(name, start, url, have):
            continue
        findings.append({"key": f"official:{(url or norm(name)).rstrip('/')}",
                         "kind": kind, "name": name,
                         "date": start.isoformat(), "where": "official page"})
    for kind, name, start, end in fetch_season_events():
        if start < today:
            continue
        if already_have(name, start, None, have):
            continue
        findings.append({"key": f"season:{norm(name)}", "kind": kind, "name": name,
                         "date": start.isoformat(), "where": "season page"})
    for kind, name, start, end, eid in fetch_rph_qualifiers():
        if eid in have_ids or already_have(name, start, None, have):
            continue
        findings.append({"key": f"rph:{eid}", "kind": kind, "name": name,
                         "date": start.isoformat(), "where": "Ravensburger Play"})

    fresh = [f for f in findings if not ack_live(acks.get(f["key"]), today)
             or f["key"] not in acks]
    seen = len(findings) - len(fresh)

    print(f"announced but not on the calendar: {len(findings)}  ({seen} already ruled on)")
    for f in sorted(fresh, key=lambda x: x["date"]):
        print(f"  NEW  {f['date']}  {f['kind'].upper():<4} {f['name'][:58]:<58} [{f['where']}]")

    if args.ack_all:
        for f in findings:
            acks[f["key"]] = {"why": args.why, "name": f["name"], "acked": today.isoformat()}
        state["acks"] = acks
        STATE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nrecorded {len(findings)} finding(s) as seen — commit scripts/calendar_watch.json")
        return 0

    if fresh:
        print("\nAdd them in the editor on /calendar, or record them as seen with --ack-all.")
        return 1
    print("nothing new")
    return 0


if __name__ == "__main__":
    sys.exit(main())
