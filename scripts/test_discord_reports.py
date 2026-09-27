"""
test_discord_reports.py — offline guard for scripts/discord_reports.py.

    python scripts/test_discord_reports.py

No network: a fake Supabase and a fake Discord. Pins the three ways the
reporter could go wrong silently — posting twice, posting stale movers, and
posting yesterday's numbers — plus that it never pings anyone and never
prints the bot token.
"""
from __future__ import annotations

import datetime as dt
import io
import os
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "http://stub")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_reports as rep  # noqa: E402

FAILS = 0


def check(cond, msg):
    global FAILS
    if not cond:
        FAILS += 1
        print("FAIL", msg)


TODAY = dt.date(2026, 9, 28)      # a Monday


class FakeSb:
    def __init__(self, subs, price_date=TODAY, table_missing=False):
        self.subs = subs
        self.price_date = price_date
        self.table_missing = table_missing
        self.updates = []

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        filters = filters or {}
        if table == rep.TABLE:
            if self.table_missing:
                raise RuntimeError("Select discord_report_subscriptions failed (404): relation does not exist")
            return [dict(s) for s in self.subs]
        if table == "card_prices_latest":
            return [{"price_date": self.price_date.isoformat()}]
        if table == "price_movers":
            up = next(iter(k for k in filters if k.startswith("mkt_pct_")))
            if filters[up] == "gt.0":
                return [
                    {"card_id": "crd_fresh", "name": "Fresh", "version": "One", "rarity": "Rare", "set_id": "s",
                     "printing": "Normal", "tcgplayer_product_id": 1, "market_today": 20, up: 50},
                    {"card_id": "crd_stale", "name": "Stale", "version": "Two", "rarity": "Rare", "set_id": "s",
                     "printing": "Normal", "tcgplayer_product_id": 2, "market_today": 30, up: 90},
                ]
            return []
        if table == "prices_daily" and filters.get("date", "").startswith("eq."):
            # pid 2's market today is NOT what the matview calls today
            return [{"tcgplayer_product_id": 1, "printing": "Normal", "market_price": 20},
                    {"tcgplayer_product_id": 2, "printing": "Normal", "market_price": 11}]
        if table == "prices_daily":
            return []
        return []

    def update(self, table, match, patch, params=None):
        self.updates.append((table, dict(match), dict(patch)))


class FakeDiscord:
    def __init__(self, status=200):
        self.status = status
        self.posts = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(status_code=self.status, text="{}")


def args(**kw):
    base = dict(post=True, allow_stale=False, force_weekly=False)
    base.update(kw)
    return SimpleNamespace(**base)


def run(sb, disc, **kw):
    out = io.StringIO()
    with redirect_stdout(out):
        code = rep.run(args(**kw), sb=sb, session=disc, today=TODAY)
    return code, out.getvalue()


os.environ["DISCORD_BOT_TOKEN"] = "secret-bot-token-value"

# 1. posts once to a daily + a weekly subscriber, stale row dropped, nobody pinged
sb = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None},
             {"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}])
disc = FakeDiscord()
code, out = run(sb, disc)
check(code == 0, "exit 0")
check(len(disc.posts) == 2, f"two posts ({len(disc.posts)})")
body = disc.posts[0]["json"] if disc.posts else {}
text = str(body)
check("Fresh" in text and "Stale" not in text, "the stale mover is dropped")
check(body.get("allowed_mentions") == {"parse": []}, "posts never ping anyone")
check(disc.posts and disc.posts[0]["url"].endswith("/channels/c1/messages"), "posts to the subscribed channel")
check("secret-bot-token-value" not in out, "the bot token is never printed")
check(sum(1 for u in sb.updates if u[2].get("last_posted_on") == TODAY.isoformat()) == 2, "last_posted_on recorded")

# 2. already posted today -> nothing
sb2 = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": TODAY.isoformat()}])
disc2 = FakeDiscord()
run(sb2, disc2)
check(not disc2.posts, "a channel that already has today's report is skipped")

# 3. weekly on a Tuesday -> nothing; with --force-weekly -> posts
tue = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}], price_date=TODAY + dt.timedelta(days=1))
disc3 = FakeDiscord()
out3 = io.StringIO()
with redirect_stdout(out3):
    rep.run(args(), sb=tue, session=disc3, today=TODAY + dt.timedelta(days=1))
check(not disc3.posts, "weekly reports wait for Monday")
with redirect_stdout(io.StringIO()):
    rep.run(args(force_weekly=True), sb=tue, session=disc3, today=TODAY + dt.timedelta(days=1))
check(len(disc3.posts) == 1, "--force-weekly posts the weekly report")

# 4. prices not in yet -> nothing
old = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}], price_date=TODAY - dt.timedelta(days=1))
disc4 = FakeDiscord()
run(old, disc4)
check(not disc4.posts, "yesterday's prices never post as today's")

# 5. table missing / no token -> clean exit 0, nothing posted
code5, out5 = run(FakeSb([], table_missing=True), FakeDiscord())
check(code5 == 0 and "migration 172" in out5, "missing table is a clean exit 0")
os.environ["DISCORD_BOT_TOKEN"] = ""
disc6 = FakeDiscord()
code6, _ = run(FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}]), disc6)
check(code6 == 0 and not disc6.posts, "no token is a clean exit 0")
os.environ["DISCORD_BOT_TOKEN"] = "secret-bot-token-value"

# 6. a channel the bot lost access to is recorded, not retried as success
sb7 = FakeSb([{"guild_id": "g", "channel_id": "c9", "cadence": "daily", "last_posted_on": None}])
run(sb7, FakeDiscord(status=403))
errs = [u for u in sb7.updates if u[2].get("last_error")]
check(errs and "can't post" in errs[0][2]["last_error"], "a 403 is recorded in last_error")
check(not any(u[2].get("last_posted_on") for u in sb7.updates), "a failed post is not marked posted")

# 7. dry run posts nothing
sb8 = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}])
disc8 = FakeDiscord()
_, out8 = run(sb8, disc8, post=False)
check(not disc8.posts and "DRY RUN" in out8, "a dry run posts nothing")

print("FAILS:", FAILS)
sys.exit(1 if FAILS else 0)
