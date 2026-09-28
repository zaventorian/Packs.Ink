"""
discord_reports.py — post the movers report into the Discord channels that
asked for it with the bot's /reports command.

    python scripts/discord_reports.py                 # dry run: what would post where
    python scripts/discord_reports.py --post          # actually post
    python scripts/discord_reports.py --post --force-weekly

The report IS the daily digest (scripts/discord_digest.py): the same embed,
built by the same functions, so a server's report and the digest can never
disagree about a card. What this adds is the delivery: one post per
subscribed channel, through the bot's own account (DISCORD_BOT_TOKEN), for
every row in discord_report_subscriptions (migration 173).

  * DRY RUN BY DEFAULT, like the digest. `--post` is the deliberate act.
  * No bot token, or migration 173 not applied: a clean exit 0 that says so —
    the workflow stays green until the feature is switched on.
  * ⚠ Freshness gate: a report for price date D posts on D, or in the first
    LATE_GRACE_HOURS of D+1 (UTC), and never later — so an evening run that
    slips past midnight still sends the day's report, and nothing posts a
    day-old report the next evening. Each row records last_posted_on (the price
    date it got), so a second run skips a channel that already has its report —
    safe BY CONSTRUCTION, not by timing.
  * It runs when an ETL run finishes (the workflow's workflow_run trigger), not
    only on GitHub's schedule, which has started this repo's evening jobs 2-3
    hours late: a 21:20 UTC run landed near midnight, and the old "prices must
    be dated today" rule skipped the whole day when it crossed it. Found
    2026-09-28, the first day a report was due, when none had arrived by 22:45
    UTC.
  * ⚠ Stale rows are dropped before anything is posted. price_movers carries a
    SKU's last change forever once its listing disappears, so "today's" move
    can be months old; a mover only counts when prices_daily holds the same
    market price for it on the newest date. The Discord bot's /movers applies
    the identical check (discord/src/data.js fetchMovers).
  * A channel the bot can no longer post in (removed from the server, lost
    permission, channel deleted) is recorded in last_error and skipped; /reports
    status shows it. It never stops the other channels.
  * The bot token is never printed. It is a password for the bot account.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_digest as digest  # noqa: E402
from supabase_client import Supabase  # noqa: E402

API = "https://discord.com/api/v10"
TABLE = "discord_report_subscriptions"
WINDOW = {"daily": "1d", "weekly": "7d"}
# How far into the next UTC day a report may still post. The ETL lands a
# day's prices from about 20:30 UTC; runs after midnight (a late schedule, the
# 01:00 ETL retry) still owe that day's report, and by noon it is stale.
LATE_GRACE_HOURS = 12


def load_subscriptions(sb):
    """Rows, or None when migration 173 is not applied yet."""
    try:
        return sb.select(TABLE, columns="guild_id,channel_id,cadence,last_posted_on",
                         order="guild_id.asc,channel_id.asc,cadence.asc")
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "42P01" in msg or "PGRST205" in msg or "does not exist" in msg:
            return None
        raise


def due(sub, today, force_weekly=False):
    """Is this subscription owed a post today?"""
    last = sub.get("last_posted_on")
    last = dt.date.fromisoformat(str(last)[:10]) if last else None
    if sub["cadence"] == "daily":
        return last != today
    if sub["cadence"] == "weekly":
        if today.weekday() != 0 and not force_weekly:   # Mondays
            return False
        return last is None or (today - last).days >= 6
    return False


def fresh_enough(price_date, now):
    """May a report for price_date post at `now` (UTC)?"""
    today = now.date()
    if price_date == today:
        return True
    return price_date == today - dt.timedelta(days=1) and now.hour < LATE_GRACE_HOURS


def drop_stale(sb, rows, price_date):
    """Keep only movers whose market price is really today's."""
    pids = sorted({r["tcgplayer_product_id"] for r in rows if r.get("tcgplayer_product_id")})
    if not pids:
        return []
    live = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,market_price",
        filters={"source": "eq.tcgcsv", "grade": "eq.raw", "date": f"eq.{price_date.isoformat()}",
                 "tcgplayer_product_id": "in.(" + ",".join(str(p) for p in pids) + ")"},
        order="tcgplayer_product_id.asc,printing.asc",
    )
    today = {(r["tcgplayer_product_id"], r.get("printing") or "Normal"): r.get("market_price") for r in live}
    out = []
    for r in rows:
        v = today.get((r.get("tcgplayer_product_id"), r.get("printing") or "Normal"))
        mine = r.get(digest.PRICE_COL)
        if v is not None and mine is not None and abs(float(v) - float(mine)) < 0.005:
            out.append(r)
    return out


def build_report(sb, price_date, window):
    """The digest's embed for one window, with stale movers removed."""
    risers = drop_stale(sb, digest.fetch_movers(sb, window, "up", digest.MOVERS_PER_SIDE * 2), price_date)
    fallers = drop_stale(sb, digest.fetch_movers(sb, window, "down", digest.MOVERS_PER_SIDE * 2), price_date)
    risers, fallers = risers[:digest.MOVERS_PER_SIDE], fallers[:digest.MOVERS_PER_SIDE]
    if not risers and not fallers:
        return None
    since = (price_date - dt.timedelta(days=digest.HISTORY_DAYS)).isoformat()
    pids = [r["tcgplayer_product_id"] for r in risers + fallers if r.get("tcgplayer_product_id")]
    hist = digest.fetch_history(sb, pids, since)
    standings = {k: s for k, s in ((k, digest.price_standing(p)) for k, p in hist.items()) if s}
    embed = digest.build_embed(price_date, window, risers, fallers, standings)
    if not embed.get("fields"):
        return None
    return dress_report(embed, price_date, window, risers, fallers, standings)


def dress_report(embed, price_date, window, risers, fallers, standings):
    """The digest's embed, dressed for a server channel: the card the report
    leads with as its picture, a title that says when a WEEKLY report covers
    a week, and a footer naming the command that put it there — so a member
    who has never seen it knows where it comes from. Only the wrapper changes;
    the digest's own layout (shared with the site's webhook) is untouched."""
    out = dict(embed)
    if window != "1d":
        out["title"] = f"Lorcana movers — week to {price_date:%b} {price_date.day}, {price_date:%Y}"

    def worth(r):
        s = standings.get((r.get("tcgplayer_product_id"), r.get("printing") or "Normal"))
        return bool(s) and s[0] in ("low", "near-low")

    lead = next((r for r in fallers if worth(r)), None) or (risers[0] if risers else None) or (fallers[0] if fallers else None)
    pid = lead and lead.get("tcgplayer_product_id")
    if pid:
        out["thumbnail"] = {"url": f"https://tcgplayer-cdn.tcgplayer.com/product/{int(pid)}_in_1000x1000.jpg"}
    foot = (out.get("footer") or {}).get("text") or ""
    out["footer"] = {"text": (foot + " · " if foot else "") + "posted by the packs.ink bot — /reports"}
    return out


def post(token, channel_id, embed, session=requests):
    return session.post(
        f"{API}/channels/{channel_id}/messages",
        headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
        json={"embeds": [embed], "allowed_mentions": {"parse": []}},
        timeout=30,
    )


def run(args, sb=None, session=requests, now=None):
    token = os.environ.get("DISCORD_BOT_TOKEN", "").strip()
    if args.post and not token:
        print("No DISCORD_BOT_TOKEN set — nothing can be posted. Exiting 0.")
        return 0
    sb = sb or Supabase()
    subs = load_subscriptions(sb)
    if subs is None:
        print(f"{TABLE} does not exist yet (migration 173 not applied). Exiting 0.")
        return 0
    if not subs:
        print("No servers have asked for reports. Exiting 0.")
        return 0
    price_date = digest.latest_price_date(sb)
    now = now or dt.datetime.now(dt.timezone.utc)
    if not price_date:
        print("No price date available; refusing to post.")
        return 0
    if not fresh_enough(price_date, now) and not args.allow_stale:
        print(f"Newest price date is {price_date}, too old at {now:%Y-%m-%d %H:%M} UTC — today's ETL has not landed yet. Skipping.")
        return 0

    owed = [s for s in subs if due(s, price_date, args.force_weekly)]
    if not owed:
        print(f"All {len(subs)} subscriptions already have today's report.")
        return 0
    reports = {}
    for cadence in sorted({s["cadence"] for s in owed}):
        reports[cadence] = build_report(sb, price_date, WINDOW[cadence])

    posted = failed = 0
    for s in owed:
        embed = reports.get(s["cadence"])
        where = f"{s['cadence']} → channel {s['channel_id']} (server {s['guild_id']})"
        if not embed:
            print(f"  skip {where}: nothing cleared the filters today")
            continue
        if not args.post:
            print(f"  DRY RUN {where}: {embed['title']} — {len(embed['fields'])} sections")
            continue
        r = post(token, s["channel_id"], embed, session=session)
        match = {"guild_id": s["guild_id"], "channel_id": s["channel_id"], "cadence": s["cadence"]}
        if r.status_code < 300:
            posted += 1
            sb.update(TABLE, match, {"last_posted_on": price_date.isoformat(), "last_error": None,
                                     "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            print(f"  posted {where}")
        else:
            failed += 1
            # The bot's own words about why — never the token, never the URL.
            reason = {403: "the bot can't post in that channel (missing access or permission)",
                      404: "that channel no longer exists"}.get(r.status_code, f"Discord said HTTP {r.status_code}")
            sb.update(TABLE, match, {"last_error": reason[:300],
                                     "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()})
            print(f"  FAILED {where}: {reason}")
        time.sleep(0.4)   # well under Discord's per-route rate limits
    print(f"Done: {posted} posted, {failed} failed, {len(owed) - posted - failed} skipped.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true", help="actually post (default is a dry run)")
    ap.add_argument("--allow-stale", action="store_true", help="post even when today's prices have not landed")
    ap.add_argument("--force-weekly", action="store_true", help="treat today as a weekly-report day")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
