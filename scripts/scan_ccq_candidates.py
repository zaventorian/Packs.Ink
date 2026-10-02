"""Propose Challenge Championship Qualifiers for the curated calendar.

    python scripts/scan_ccq_candidates.py            # dry run (default)
    python scripts/scan_ccq_candidates.py --apply    # write candidates

WHY THIS IS A PROPOSER AND NOT A CLASSIFIER
===========================================
Set Championships are detectable because Ravensburger Play stamps
`phase_template_group` f6a76808-… on every event made from the official SC
template, whatever the store titled it (see discover_wu_scs.is_sc).

**There is no such marker for a CCQ, and this was measured, not assumed**
(2026-09-12). Of the 11 CCQ-ish events on RPH at the time, two shared template
7ffe1457-…; a 992-event sample showed that template also covers Set
Championships and "Sunday Evening Weekly Play" — 10 hits, mixed. It is a generic
Swiss template, not a CCQ signal. RPH's own `event_type` is no help either: it
reads LOCALS for ~99% of all events.

So a CCQ is only findable by what a store typed, and stores type things like:

    Lorcana X Brainwash Cards 2K CCQ
    Tournament Lorcana Core - possible CCQ          <- "possible"
    Woodzshacktcg multi case  ccq
    Charlie's Collectible Show $10,000 Weekend & Official CCQ
    Legendz League German Championship Qualifier    <- a GERMAN championship

That last pair is the whole problem: the name net cannot tell an official
Challenge Championship Qualifier from a store saying "possible" or from a
national qualifier for something else. Judging them is a human call.

So the default is: write rows with **confirmed = false**, which migration 139
keeps out of everyone's calendar but an admin's, and a person rules on them in
the editor on /calendar. Same shape as the acks in scripts/catalog_watch.json.

AUTO-PUBLISH (2026-10-02, Zaven's call: qualifiers should appear on their own).
A listing is published straight away (confirmed = true, source 'ccq-scan-auto',
note saying so) ONLY when every gate holds -- see auto_publish_ok():
  * the title says CCQ / championship qualifier, with no hedge, no exclude word
    and no national/other-championship word ("German Championship Qualifier");
  * capacity >= AUTO_MIN_CAPACITY. Both qualifiers confirmed by hand that day
    from Ravensburger's own graphics ran capacity 128; a store's own weekly
    "Saturday CCQ" runs 20-64. Capacity is the one field that separates them;
  * it has coordinates and a country (the calendar's region filter and map need
    them; an ungeocoded row falls into "Elsewhere");
  * it has not already started.
Everything else stays an unconfirmed proposal for a person. An auto row is
distinguishable (source) so it can be audited, and a person overriding one
should set source to something else, which freezes it against this script.
Known limit: nothing UNPUBLISHES an auto row if the store later cancels it.

IDEMPOTENT: rows are keyed on calendar_events.event_id (unique), which is the
RPH event id, so re-running proposes nothing twice and never disturbs a row a
person has already ruled on — an UPDATE only refreshes the date/title of a row
still sitting at confirmed=false and source='ccq-scan'.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
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

# Positive net. Deliberately broad — a missed CCQ is invisible, while a false
# positive costs one glance in the review queue.
INCLUDE = (
    "ccq",
    "championship qualifier",
    "challenge qualifier",
)
# Words that mean this is NOT the official qualifier track, even though the
# title matched. Checked against the lowercased title.
EXCLUDE = (
    "side event",
    "practice",
    "mock",
    "watch party",
)
# Titles that hedge. Kept (they are usually real) but flagged in the note, so
# whoever reviews knows the STORE was unsure, not us.
HEDGES = ("possible", "maybe", "tentative", "tbc", "tbd")
# Titles naming some OTHER championship's qualifier (a national league, not the
# official Challenge track). Blocks auto-publish only; still proposed.
NOT_OFFICIAL = ("german championship", "national championship", "league championship",
                "-side", "side)", "side event", "legendz")
AUTO_MIN_CAPACITY = 128


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


def fetch_candidates():
    """Upcoming lorcana_events whose title trips the CCQ net."""
    ors = ",".join(f"name.ilike.*{urllib.parse.quote(term)}*" for term in INCLUDE)
    url = (
        f"{SUPABASE_URL}/rest/v1/lorcana_events"
        "?select=event_id,name,start_datetime,end_datetime,timezone,store_name,"
        "city,state,country,latitude,longitude,capacity,url,gameplay_format"
        f"&or=({ors})"
        "&start_datetime=gte.now()"
        "&order=start_datetime.asc&limit=500"
    )
    return http_json(url)


def fetch_existing():
    """Everything already proposed or ruled on, keyed by RPH event id."""
    url = (
        f"{SUPABASE_URL}/rest/v1/calendar_events"
        "?select=id,event_id,confirmed,source,starts_on,title&event_id=not.is.null&limit=2000"
    )
    try:
        return {r["event_id"]: r for r in http_json(url)}
    except Exception as e:
        # Migration 139 not applied yet — say so plainly instead of dying with a
        # PostgREST stack trace.
        raise SystemExit(f"could not read calendar_events ({e}) — is migration 139 applied?")


def local_day(row) -> str | None:
    """The event's own calendar day. The client does exactly this (calTzYmd);
    a UTC slice would move a 7pm Friday event in Los Angeles to Saturday."""
    ts = row.get("start_datetime")
    if not ts:
        return None
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        tz = row.get("timezone")
        if tz:
            try:
                dt = dt.astimezone(ZoneInfo(tz))
            except Exception:
                pass
        return dt.date().isoformat()
    except Exception:
        return ts[:10]


def local_end_day(ev, start_day):
    """Last day of a multi-day event, or None. An event that runs past midnight
    into the small hours (ends before 06:00 local) is still one day."""
    ts = ev.get("end_datetime")
    if not ts:
        return None
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        tz = ev.get("timezone")
        if tz:
            try:
                dt = dt.astimezone(ZoneInfo(tz))
            except Exception:
                pass
        day = dt.date().isoformat()
        return day if day > start_day and dt.hour >= 6 else None
    except Exception:
        return None


def auto_publish_ok(ev, row) -> bool:
    low = (ev.get("name") or "").lower()
    if any(h in low for h in HEDGES) or any(n in low for n in NOT_OFFICIAL):
        return False
    if (ev.get("capacity") or 0) < AUTO_MIN_CAPACITY:
        return False
    if ev.get("latitude") is None or ev.get("longitude") is None or not ev.get("country"):
        return False
    return bool(ev.get("start_datetime")) and ev["start_datetime"] > _now_iso()


def _now_iso():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def to_row(ev) -> dict | None:
    title = (ev.get("name") or "").strip()
    low = title.lower()
    if any(bad in low for bad in EXCLUDE):
        return None
    day = local_day(ev)
    if not day:
        return None
    where = ", ".join(x for x in (ev.get("city"), ev.get("state"), ev.get("country")) if x)
    note_bits = ["Proposed by scan_ccq_candidates.py from the Ravensburger Play listing."]
    if any(h in low for h in HEDGES):
        note_bits.append("⚠ The store's own title hedges — confirm before publishing.")
    row = {
        "kind": "ccq",
        "title": title,
        "subtitle": ev.get("store_name") or None,
        "starts_on": day,
        "starts_at": ev.get("start_datetime"),
        "timezone": ev.get("timezone"),
        "location": " · ".join(x for x in (ev.get("store_name"), where) if x) or None,
        "url": ev.get("url"),
        "source": "ccq-scan",
        "event_id": ev.get("event_id"),
        "confirmed": False,
        "notes": " ".join(note_bits),
        "country": ev.get("country"),
        "latitude": ev.get("latitude"),
        "longitude": ev.get("longitude"),
    }
    end = local_end_day(ev, day)
    if end:
        row["ends_on"] = end
    if auto_publish_ok(ev, row):
        row["confirmed"] = True
        row["source"] = "ccq-scan-auto"
        row["notes"] = ("Auto-published from the Ravensburger Play listing "
                        "(a qualifier-sized event whose title names a CCQ); not yet "
                        "checked against an official announcement.")
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="write candidates (default is a dry run)")
    args = ap.parse_args()

    events = fetch_candidates()
    existing = fetch_existing()
    print(f"RPH upcoming events matching the CCQ net: {len(events)}")

    new_rows, refresh, promote, skipped = [], [], [], 0
    for ev in events:
        row = to_row(ev)
        if row is None:
            skipped += 1
            continue
        prior = existing.get(row["event_id"])
        if prior is None:
            new_rows.append(row)
        elif prior.get("source") == "ccq-scan" and not prior.get("confirmed") and row["confirmed"]:
            promote.append((prior["id"], row))
        elif (prior.get("source") == "ccq-scan" and not prior.get("confirmed")) or prior.get("source") == "ccq-scan-auto":
            # Still un-ruled: refresh the date/title in case the store edited it.
            if prior.get("starts_on") != row["starts_on"] or prior.get("title") != row["title"]:
                refresh.append((prior["id"], row))

    print(f"  rejected by the exclude list: {skipped}")
    print(f"  already ruled on or proposed: {len(events) - skipped - len(new_rows)}")
    print(f"  NEW candidates: {len(new_rows)}")
    for r in new_rows:
        flag = " ⚠hedged" if "hedges" in (r["notes"] or "") else ""
        print(f"    {r['starts_on']}  {r['title'][:58]}{flag}")
    if promote:
        print(f"  PROMOTED to the public calendar (auto-publish gates passed): {len(promote)}")
        for _id, r in promote:
            print(f"    {r['starts_on']}  {r['title'][:58]}")
    if refresh:
        print(f"  candidates whose listing changed: {len(refresh)}")
        for _id, r in refresh:
            print(f"    {r['starts_on']}  {r['title'][:58]}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to propose these.")
        print("They land as UNCONFIRMED: only an admin sees them, and only a person")
        print("can publish one, from the editor on /calendar.")
        return 0

    for _id, row in promote:
        patch = {k: row[k] for k in ("title", "starts_on", "starts_at", "timezone", "location",
                                      "url", "source", "confirmed", "notes", "country",
                                      "latitude", "longitude")}
        patch["ends_on"] = row.get("ends_on")
        http_json(f"{SUPABASE_URL}/rest/v1/calendar_events?id=eq.{_id}", "PATCH",
                  patch, {"Prefer": "return=minimal"})
    if promote:
        print(f"published {len(promote)} qualifier(s)")
    if new_rows:
        http_json(f"{SUPABASE_URL}/rest/v1/calendar_events", "POST", new_rows,
                  {"Prefer": "resolution=ignore-duplicates,return=minimal"})
        print(f"proposed {len(new_rows)} candidate(s)")
    for _id, row in refresh:
        http_json(f"{SUPABASE_URL}/rest/v1/calendar_events?id=eq.{_id}", "PATCH",
                  {"starts_on": row["starts_on"], "title": row["title"],
                   "starts_at": row["starts_at"], "url": row["url"]},
                  {"Prefer": "return=minimal"})
    if refresh:
        print(f"refreshed {len(refresh)} changed listing(s)")
    if not new_rows and not refresh and not promote:
        print("nothing to do")
    return 0


if __name__ == "__main__":
    sys.exit(main())
