"""Attach real Ravensburger Play listings to curated calendar rows.

    python scripts/link_calendar_events.py           # dry run (default)
    python scripts/link_calendar_events.py --apply   # write the links

WHY
===
Most of the curated calendar is seeded from a fan wiki (migration 141): a name
and a date and nothing you can click. As stores actually list their events on
Ravensburger Play, the same event turns up in `lorcana_events` with a real
registration URL — and THAT is what somebody reading the calendar wants. This
walks the curated rows that still have no link and attaches the listing where
one can be matched with confidence.

It is the RPH half of "add the links as we get them". The other half — fanfinity
pages for the big Disney Lorcana Challenges — is not automatable: fanfinity has
no feed, and its slugs are not derivable from an event's name (guessing one
produces a URL that 404s or, worse, lands on a different event). Those are typed
into the editor on /calendar.

⚠ IT ONLY EVER ADDS. A row that already has a `url` or an `event_id` is skipped
entirely, so a link an admin typed by hand can never be overwritten by a guess,
and re-running is idempotent. It also never touches `confirmed`: finding a
listing is evidence, not permission to publish.

⚠ AND IT REFUSES AMBIGUITY. A wrong link is worse than no link — it sends
somebody to register for a different shop's tournament. A candidate must match
on DATE (within a day of the curated range) and share a distinctive word with the
curated title; if two candidates tie on the same evidence, both are dropped and
the row is reported as ambiguous for a human to settle.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
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

# How far an RPH listing's local day may sit from the curated date. One day, not
# three: a multi-day event is already expressed as a range, so the slack is only
# for a timezone edge or a wiki date off by a day.
DATE_SLACK_DAYS = 1

# Words that appear in half the events on the platform and so carry no evidence.
# "ccq" and "championship" are in here deliberately — matching on them is how a
# Brisbane CCQ gets linked to a Tokyo one.
STOP = {
    "lorcana", "disney", "tcg", "the", "and", "at", "of", "a", "an", "in", "on",
    "ccq", "dlc", "challenge", "championship", "qualifier", "qualifiers", "set",
    "tournament", "event", "constructed", "core", "sealed", "open", "games",
    "game", "gaming", "cards", "card", "store", "official", "weekend", "2k",
    "10k", "2026", "2027", "play", "night", "day",
}


def http_json(url: str, method: str = "GET", body=None, extra_headers=None):
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    headers.update(extra_headers or {})
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read().decode("utf-8", "ignore")
    return json.loads(raw) if raw.strip() else []


def tokens(name: str) -> set[str]:
    """Distinctive words, accents folded so 'Malmo' matches 'Malmö' — the wiki
    and the store rarely agree on those.

    ⚠ An alphanumeric token counts from 3 characters ("d23" is the D23 Expo and
    is the only distinctive word in "D23 2026 CCQ"), while a plain word needs 4.
    A bare 3-letter word is noise ("sat", "bye"); one with a digit in it is a
    name."""
    import unicodedata
    n = unicodedata.normalize("NFKD", name or "")
    n = "".join(c for c in n if not unicodedata.combining(c)).lower()
    out = set()
    for w in re.split(r"[^a-z0-9]+", n):
        if w in STOP:
            continue
        has_digit = any(c.isdigit() for c in w)
        if len(w) >= 4 or (len(w) >= 3 and has_digit and not w.isdigit()):
            out.add(w)
    return out


# ⚠ Stores run words together — "Woodzshacktcg" for "Woodzshack TCG",
# "MalmoGameWeek" for "Malmö Game Week" — so set intersection alone missed three
# of five real matches on the first pass. Containment recovers them.
#
# Five characters, not six: at six, "malmo" still failed against
# "malmogameweek". It is safe to be generous here because the NAME is not what
# discriminates — the DATE is. A candidate has already had to land within a day
# of the curated event before its name is ever looked at, so a loose word match
# costs nothing while a tight one loses real links.
MIN_CONTAIN = 5

def shared_evidence(want: set[str], have: set[str]) -> set[str]:
    out = set(want & have)
    for w in want:
        if w in out or len(w) < MIN_CONTAIN:
            continue
        if any(w in h or (len(h) >= MIN_CONTAIN and h in w) for h in have):
            out.add(w)
    return out


def local_day(row) -> date | None:
    ts = row.get("start_datetime")
    if not ts:
        return None
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        tz = row.get("timezone")
        if tz:
            try:
                dt = dt.astimezone(ZoneInfo(tz))
            except Exception:
                pass
        return dt.date()
    except Exception:
        try:
            return date.fromisoformat(ts[:10])
        except Exception:
            return None


def fetch_unlinked():
    url = (f"{SUPABASE_URL}/rest/v1/calendar_events"
           "?select=id,kind,title,starts_on,ends_on,url,event_id,source"
           "&kind=in.(ccq,dlc,product)&url=is.null&event_id=is.null"
           "&order=starts_on.asc&limit=500")
    try:
        return http_json(url)
    except Exception as e:
        raise SystemExit(f"could not read calendar_events ({e}) — is migration 139 applied?")


def fetch_window(lo: date, hi: date):
    url = (f"{SUPABASE_URL}/rest/v1/lorcana_events"
           "?select=event_id,name,start_datetime,timezone,store_name,city,state,country,url"
           f"&start_datetime=gte.{lo.isoformat()}T00:00:00Z"
           f"&start_datetime=lte.{hi.isoformat()}T23:59:59Z"
           "&order=start_datetime.asc&limit=20000")
    return http_json(url)


# Pinned pairs, drawn from the real wiki titles and the real RPH listings they
# have to match (or must not). The failure this guards is silent and expensive:
# a wrong link sends somebody to register for a different shop's tournament, and
# nothing on the page would look wrong. Runs automatically before any live work.
SELF_TEST = [
    # (curated title, RPH listing, should they link?)
    ("Brainwash Cards 2K", "Lorcana X Brainwash Cards 2K CCQ", True),
    ("Woodzshack TCG CCQ", "Woodzshacktcg multi case  ccq", True),       # run-together store name
    ("Malmö Game Week Open #3", "MalmoGameWeek BYE Qualifier", True),    # accents + run-together
    ("D23 2026 CCQ", "D23 - Sat - 10am - Challenge Championship Qualifier (CCQ)", True),  # 3-char alnum
    ("CCS Raleigh 10K", "Raleigh Lorcana Open", True),
    ("RareHunter CCQ", "Rarehunter Lorcana 2K", True),
    ("Lore League Senigallia CCQ", "Senigallia Lore League", True),
    # Different cities on the same circuit share every other word, so these are
    # the pairs that decide whether the stopword list is doing its job.
    ("Brisbane CCQ", "Tokyo CCQ", False),
    ("Sydney CCQ", "Auckland CCQ", False),
    ("Osaka CCQ", "Tokyo CCQ", False),
    ("DLC London", "Lorcana Core Constructed at Big Orbit Games", False),
    ("DLC Tampa", "Weekly Play Constructed", False),
]


def self_test() -> int:
    bad = 0
    for a, b, want in SELF_TEST:
        shared = shared_evidence(tokens(a), tokens(b))
        if bool(shared) != want:
            bad += 1
            print(f"  FAIL  {a!r} vs {b!r}: expected {'a link' if want else 'no link'}, got {sorted(shared)}")
    print(f"self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} pairs behave")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the links (default is a dry run)")
    ap.add_argument("--self-test", action="store_true", help="run the matcher checks and exit")
    args = ap.parse_args()

    # Always, before touching anything: a matcher that has drifted fails by
    # attaching wrong links, not by raising.
    if self_test():
        print("matcher self-test FAILED — refusing to touch real data")
        return 1
    if args.self_test:
        return 0

    rows = fetch_unlinked()
    if not rows:
        print("every curated row already has a link — nothing to do")
        return 0
    print(f"curated rows with no link yet: {len(rows)}")

    starts = [date.fromisoformat(r["starts_on"]) for r in rows]
    lo = min(starts) - timedelta(days=DATE_SLACK_DAYS)
    hi = max(date.fromisoformat(r.get("ends_on") or r["starts_on"]) for r in rows) + timedelta(days=DATE_SLACK_DAYS)
    # RPH only lists UPCOMING events, so anything already played is unmatchable
    # by construction — say so rather than reporting it as "no listing found".
    today = date.today()
    feed = fetch_window(max(lo, today), hi)
    print(f"Ravensburger Play listings in that window: {len(feed)}")

    by_day: dict[date, list] = {}
    for ev in feed:
        d = local_day(ev)
        if d:
            by_day.setdefault(d, []).append(ev)

    linked, ambiguous, nothing, past = [], [], [], 0
    for r in rows:
        s = date.fromisoformat(r["starts_on"])
        e = date.fromisoformat(r.get("ends_on") or r["starts_on"])
        if e < today:
            past += 1
            continue
        want = tokens(r["title"])
        if not want:
            nothing.append((r, "no distinctive words in the title"))
            continue
        best: list[tuple[int, dict]] = []
        d = s - timedelta(days=DATE_SLACK_DAYS)
        while d <= e + timedelta(days=DATE_SLACK_DAYS):
            for ev in by_day.get(d, []):
                shared = shared_evidence(want, tokens(ev.get("name") or "") | tokens(ev.get("store_name") or ""))
                if shared:
                    best.append((len(shared), ev))
            d += timedelta(days=1)
        if not best:
            nothing.append((r, "no listing matched"))
            continue
        best.sort(key=lambda x: -x[0])
        top = best[0][0]
        winners = [ev for n, ev in best if n == top]
        # Several listings of ONE event (a store running Sat and Sun sessions)
        # share an event id only if they really are one row; distinct ids on the
        # same evidence is a genuine tie, and guessing between them is exactly
        # the wrong-registration-link failure this must not have.
        if len({ev["event_id"] for ev in winners}) > 1:
            ambiguous.append((r, winners))
            continue
        linked.append((r, winners[0]))

    print(f"\n  matched:   {len(linked)}")
    for r, ev in linked:
        print(f"    {r['starts_on']}  {r['title'][:34]:<34} -> {(ev.get('name') or '')[:40]}  #{ev['event_id']}")
    if ambiguous:
        print(f"\n  ambiguous (left alone, settle by hand): {len(ambiguous)}")
        for r, evs in ambiguous:
            print(f"    {r['starts_on']}  {r['title'][:34]:<34} -> {len(evs)} equally good listings")
    if nothing:
        print(f"\n  no listing yet: {len(nothing)}")
        for r, why in nothing[:12]:
            print(f"    {r['starts_on']}  {r['title'][:34]:<34} ({why})")
    if past:
        print(f"\n  skipped {past} already-played row(s) — RPH lists upcoming events only")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to attach these links.")
        return 0

    for r, ev in linked:
        patch = {"event_id": ev["event_id"], "updated_at": datetime.utcnow().isoformat() + "Z"}
        if ev.get("url"):
            patch["url"] = ev["url"]
        http_json(f"{SUPABASE_URL}/rest/v1/calendar_events?id=eq.{r['id']}", "PATCH", patch,
                  {"Prefer": "return=minimal"})
    print(f"\nattached {len(linked)} link(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
