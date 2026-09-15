"""
ingest_social_feed.py — fill the home page's community feed from YouTube RSS.

    python scripts/ingest_social_feed.py                 # dry run, prints what it would write
    python scripts/ingest_social_feed.py --commit
    python scripts/ingest_social_feed.py --reap --commit # mark vanished items dead
    python scripts/ingest_social_feed.py --self-test     # no network, no DB

WHY YOUTUBE RSS AND NOT THE X API:

X retired its Basic and Pro tiers (2026-06-01 / 2026-09-01), so every new
developer is on pay-per-use at $0.005 per post read with no free tier. Polling
15 creators every 15 minutes is ~$2,160/month; even hourly is ~$540. Meanwhile
`https://www.youtube.com/feeds/videos.xml?channel_id=UC...` needs **no API key,
no quota, no OAuth and no registration**, and it is where Lorcana creator
content actually lives — deck techs, set reviews, pack openings.

X is still in the feed, but curated: an admin pastes a post URL and it is
hydrated through the free oEmbed endpoint. See scripts/SOCIAL_FEED_RESEARCH.md
for the full costing and the oEmbed notes.

Operationally, and each of these is a lesson from a sibling script:

  * DRY RUN BY DEFAULT. These rows render on the home page, so writing is the
    deliberate act. Same asymmetry as discord_digest.py and
    flag_intentional_draws.py.
  * NO SOURCES CONFIGURED IS A CLEAN EXIT 0, not a failure — the feed is empty
    until somebody picks creators, and an empty feed renders as nothing.
  * ⚠ IDEMPOTENT on (platform, source_id). The hourly sweep re-reads the same
    15 videos every time; the unique index is what stops that becoming 15 new
    rows an hour.
  * ⚠ A ROW IS NEVER RE-CONFIRMED. If an item already exists we touch only
    `hydrated_at` — never `confirmed`, `note` or `card_id`. Those are editorial
    fields a person (or a curation routine) may have set, and an ingest that
    overwrote them would silently undo the only work that makes a tile worth
    having. This is the same rule link_calendar_events.py follows: only ever
    ADD, never overwrite what a human put there.
  * ⚠ `auto_confirm` ON THE SOURCE is the only thing that can publish. It
    defaults false, so a new creator's videos land as candidates. Never infer
    it from anything in the feed itself.
"""
from __future__ import annotations

import argparse
import os
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

YT_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"

# The Atom namespaces YouTube's feed uses. It is a stable, long-published
# format, but parsing by namespace rather than by tag-name suffix means a feed
# that adds an unrelated <title> somewhere cannot be misread.
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

# How far back a first sweep reaches. Without this, adding a creator dumps
# their last 15 uploads into the feed at once — which on a quiet week is the
# entire panel, all from one person, all months old.
MAX_AGE_DAYS = 30

# Per-run cap. A creator on a posting spree must not be able to fill the panel.
MAX_NEW_PER_SOURCE = 3

HTTP_TIMEOUT = 30


def _txt(node, path):
    el = node.find(path, NS)
    return (el.text or "").strip() if el is not None and el.text else ""


def parse_feed(xml_bytes):
    """Atom XML -> list of dicts, newest first. Raises on malformed XML.

    ⚠ Returns the video's own `published`, never the fetch time. A feed can
    list an older upload (a channel re-publishing a draft), and stamping those
    with now() would float them to the top of the panel as if they were new.
    """
    root = ET.fromstring(xml_bytes)
    out = []
    for entry in root.findall("atom:entry", NS):
        vid = _txt(entry, "yt:videoId")
        published = _txt(entry, "atom:published")
        if not vid or not published:
            continue
        link = entry.find("atom:link", NS)
        url = (link.get("href") if link is not None else "") or \
            f"https://www.youtube.com/watch?v={vid}"
        author = entry.find("atom:author", NS)
        thumb = entry.find("media:group/media:thumbnail", NS)
        desc = _txt(entry, "media:group/media:description")
        out.append({
            "source_id": vid,
            "url": url,
            "title": _txt(entry, "atom:title"),
            # A description is often a wall of affiliate links and socials. The
            # tile shows our own note, so this is context for whoever writes it
            # rather than display text; keep the head and drop the link farm.
            "body": (desc[:600].strip() or None),
            "author_name": (_txt(author, "atom:name") if author is not None else None),
            "author_url": (_txt(author, "atom:uri") if author is not None else None),
            "thumb_url": (thumb.get("url") if thumb is not None else None),
            "posted_at": published,
        })
    return out


def _parse_ts(s):
    """RFC3339 -> aware datetime. YouTube emits a trailing Z that pre-3.11
    fromisoformat refuses, so normalise it rather than depending on the runner's
    Python version."""
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def fresh_items(items, now=None, max_age_days=MAX_AGE_DAYS, cap=MAX_NEW_PER_SOURCE):
    """Newest-first, inside the age window, capped. Undated items are dropped:
    posted_at is NOT NULL in the table and guessing a date would misorder the
    panel."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)
    dated = []
    for it in items:
        ts = _parse_ts(it.get("posted_at") or "")
        if ts is None or ts < cutoff or ts > now + timedelta(hours=12):
            # A timestamp in the future is a feed bug or a scheduled premiere;
            # either way it would pin itself to the top of the panel forever.
            continue
        dated.append((ts, it))
    dated.sort(key=lambda p: p[0], reverse=True)
    return [it for _, it in dated[:cap]]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "packs.ink social feed ingest"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
        return r.read()


def build_rows(source, items):
    """Map feed items onto social_posts rows for one source."""
    rows = []
    for it in items:
        rows.append({
            "platform": source["platform"],
            "source_id": it["source_id"],
            "source_ref": source["id"],
            "url": it["url"],
            "author_name": it.get("author_name") or source["name"],
            "author_url": it.get("author_url"),
            "title": it.get("title"),
            "body": it.get("body"),
            "thumb_url": it.get("thumb_url"),
            "posted_at": it["posted_at"],
            # The ONLY thing that can publish. See the module docstring.
            "confirmed": bool(source.get("auto_confirm")),
            "dead": False,
            "hydrated_at": datetime.now(timezone.utc).isoformat(),
        })
    return rows


def run(sb, commit, verbose=True):
    sources = sb.select(
        "social_sources", "id,platform,source_key,name,enabled,auto_confirm",
        filters={"platform": "eq.youtube", "enabled": "is.true"}, order="name.asc",
    )
    if not sources:
        print("No enabled YouTube sources in social_sources — nothing to do.")
        print("Add creators there first; which ones to carry is an editorial call.")
        return 0

    existing = {
        (r["platform"], r["source_id"])
        for r in sb.select("social_posts", "platform,source_id", order="source_id.asc")
    }

    new_rows, touched = [], []
    for src in sources:
        try:
            raw = fetch(YT_FEED.format(cid=src["source_key"]))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            # One unreachable channel must not sink the sweep. The others are
            # independent, and the next hourly run retries this one.
            print(f"  WARN: {src['name']}: fetch failed ({e}) — skipped", file=sys.stderr)
            continue
        try:
            items = parse_feed(raw)
        except ET.ParseError as e:
            print(f"  WARN: {src['name']}: unparseable feed ({e}) — skipped", file=sys.stderr)
            continue

        for it in fresh_items(items):
            key = (src["platform"], it["source_id"])
            if key in existing:
                touched.append(key)
                continue
            new_rows.extend(build_rows(src, [it]))
            existing.add(key)

    if verbose:
        for r in new_rows:
            flag = "PUBLISH" if r["confirmed"] else "candidate"
            print(f"  [{flag}] {r['author_name']}: {(r['title'] or '')[:70]}")
        print(f"\n{len(new_rows)} new, {len(touched)} already held, {len(sources)} source(s).")

    if not commit:
        print("Dry run — nothing written. Re-run with --commit.")
        return 0
    if new_rows:
        # ⚠ Only ever ADDS. An existing row keeps its note, card_id and
        # confirmed — see the module docstring.
        sb.upsert("social_posts", new_rows, on_conflict="platform,source_id")
        print(f"Wrote {len(new_rows)} row(s).")
    return 0


def reap(sb, commit):
    """Mark rows dead whose item no longer resolves.

    For YouTube this is the hygiene half. For X it is a CONTRACT: the developer
    policy requires stored content be kept current with the platform within 24
    hours, and a 404 from the free oEmbed endpoint is how a deleted post
    announces itself at zero API cost.
    """
    rows = sb.select("social_posts", "id,platform,url,dead",
                     filters={"dead": "is.false"}, order="id.asc")
    gone = []
    for r in rows:
        try:
            req = urllib.request.Request(
                r["url"], method="HEAD",
                headers={"User-Agent": "packs.ink social feed reaper"})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                if resp.status in (404, 410):
                    gone.append(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                gone.append(r)
            # Any other status (403, 429, 5xx) is NOT evidence the item is
            # gone. Marking dead on a rate-limit would silently empty the feed.
        except (urllib.error.URLError, TimeoutError):
            pass

    print(f"{len(gone)} of {len(rows)} live row(s) no longer resolve.")
    if not commit:
        print("Dry run — nothing written. Re-run with --commit.")
        return 0
    for r in gone:
        sb.update("social_posts", {"id": r["id"]}, {"dead": True})
    return 0


# ── self-test ──────────────────────────────────────────────────────────────
# Runs the real parser over a fixture. No network, no DB, no credentials, so it
# is safe in CI and safe to run before touching anything.
FIXTURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/">
  <entry>
    <yt:videoId>abc12345678</yt:videoId>
    <title>Set 14 first impressions</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc12345678"/>
    <author><name>A Creator</name><uri>https://www.youtube.com/channel/UCxxx</uri></author>
    <published>{recent}</published>
    <media:group>
      <media:description>Talking about Heihei.</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/abc12345678/hqdefault.jpg"/>
    </media:group>
  </entry>
  <entry>
    <yt:videoId>old99999999</yt:videoId>
    <title>Ancient video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=old99999999"/>
    <author><name>A Creator</name></author>
    <published>2024-01-01T00:00:00+00:00</published>
  </entry>
  <entry>
    <yt:videoId>future00000</yt:videoId>
    <title>Scheduled premiere</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=future00000"/>
    <author><name>A Creator</name></author>
    <published>{future}</published>
  </entry>
</feed>
"""


def self_test():
    now = datetime.now(timezone.utc)
    xml = FIXTURE.decode().format(
        recent=(now - timedelta(days=2)).isoformat(),
        future=(now + timedelta(days=5)).isoformat(),
    ).encode()

    items = parse_feed(xml)
    checks = []

    checks.append(("parses every entry", len(items) == 3))
    checks.append(("reads the video id", items[0]["source_id"] == "abc12345678"))
    checks.append(("reads the thumbnail",
                   items[0]["thumb_url"] == "https://i.ytimg.com/vi/abc12345678/hqdefault.jpg"))
    checks.append(("reads the author", items[0]["author_name"] == "A Creator"))

    fresh = fresh_items(items, now=now)
    ids = [i["source_id"] for i in fresh]
    checks.append(("drops items older than the window", "old99999999" not in ids))
    checks.append(("drops future-dated premieres", "future00000" not in ids))
    checks.append(("keeps the recent one", ids == ["abc12345678"]))

    capped = fresh_items(items * 5, now=now, cap=2)
    checks.append(("honours the per-source cap", len(capped) <= 2))

    # The trust flag is the whole publish gate — pin both directions.
    src_off = {"id": "s1", "platform": "youtube", "name": "A Creator", "auto_confirm": False}
    src_on = dict(src_off, auto_confirm=True)
    checks.append(("a source without auto_confirm yields candidates",
                   build_rows(src_off, fresh)[0]["confirmed"] is False))
    checks.append(("a source with auto_confirm publishes",
                   build_rows(src_on, fresh)[0]["confirmed"] is True))

    # ⚠ The ingest must never carry an editorial field. If these ever appear in
    # a built row, an hourly sweep would wipe a human's note on every pass.
    built = build_rows(src_on, fresh)[0]
    checks.append(("never writes `note`", "note" not in built))
    checks.append(("never writes `card_id`", "card_id" not in built))

    checks.append(("posted_at is the video's own time",
                   built["posted_at"] == fresh[0]["posted_at"]))

    bad = 0
    for name, ok in checks:
        print(("  PASS  " if ok else "  FAIL  ") + name)
        bad += 0 if ok else 1
    print(f"\n{len(checks) - bad}/{len(checks)} checks passed.")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--reap", action="store_true", help="mark vanished items dead instead of ingesting")
    ap.add_argument("--self-test", action="store_true", help="run the parser checks; no network, no DB")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    # Imported here so --self-test needs neither the dependency nor credentials.
    from dotenv import load_dotenv
    from supabase_client import Supabase
    load_dotenv()
    sb = Supabase()

    return reap(sb, args.commit) if args.reap else run(sb, args.commit)


if __name__ == "__main__":
    sys.exit(main())
