"""
discord_reports.py — post the movers report into the Discord channels that
asked for it with the bot's /reports command.

    python scripts/discord_reports.py                 # dry run: what would post where
    python scripts/discord_reports.py --post          # actually post
    python scripts/discord_reports.py --post --force-weekly   # the weekly, now, to every weekly channel
    python scripts/discord_reports.py --preview out/  # dry run + write each report to out/

One post per subscribed channel, through the bot's own account
(DISCORD_BOT_TOKEN), for every row in discord_report_subscriptions (migration
173). The movers data, the standing maths ("cheapest in 6 months") and the
freshness rules come from discord_digest.py, so a report can never disagree
with the digest about a card; the LAYOUT is the report's own (2026-09-28):

  * Sections by kind of card, because one list ranked by percent was mostly
    $5 foils jumping 30% on one sale. CHASE (Enchanted / Epic / Iconic),
    PROMOS, BASE CARDS (non-foil) and FOILS (base-rarity foils) all rank by
    PERCENT (Zaven, 2026-10-02: dollar deltas are not interesting). Each has a price floor AND a minimum dollar move, so a $4
    card moving 50 cents never makes the list.
  * The weekly adds the bigger trends: the whole market, chase cards, sealed,
    the hottest and coolest set and the rarity that moved most (the
    market_index matviews), a chart of those since the newest set came out,
    a picture strip of the top chase and base movers, and a "Worth a look"
    section of cards that fell AND now sit at a multi-month low.
  * The pictures are drawn by discord_report_art.py and ATTACHED to the post.
    If one cannot be drawn, or Discord refuses the attachments, the report
    goes out without it rather than not at all.
  * Every card name links to TCGplayer through the affiliate link, the site's
    tcgUrl() exactly, and every report's footer says links may earn a
    commission.
  * No "-#" small text: Discord does not reliably draw it inside an embed.
    Secondary lines are italics, as in the bot's own replies.

Operationally:

  * The weekly posts on MONDAY MORNING, 9 AM-3 PM Chicago (weekly_open), on
    Sunday's prices — never beside the daily, which posts in the evening.
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
    Low for it on the newest date. The Discord bot's /movers applies
    the identical check (discord/src/data.js fetchMovers).
  * A channel the bot can no longer post in (removed from the server, lost
    permission, channel deleted) is recorded in last_error and skipped; /reports
    status shows it. It never stops the other channels.
  * The bot token is never printed. It is a password for the bot account.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import discord_digest as digest  # noqa: E402
import discord_report_art as art  # noqa: E402
from supabase_client import Supabase  # noqa: E402

API = "https://discord.com/api/v10"
TABLE = "discord_report_subscriptions"
LATEST_TABLE = "discord_report_latest"
REPORT_BUCKET = "discord-reports"
WINDOW = {"daily": "1d", "weekly": "7d"}
# How far into the next UTC day a report may still post. The ETL lands a
# day's prices from about 20:30 UTC; runs after midnight (a late schedule, the
# 01:00 ETL retry) still owe that day's report, and by noon it is stale.
LATE_GRACE_HOURS = 12
# The weekly goes out on Monday MORNING, Chicago time (Zaven, 2026-10-05), so
# it never lands beside the daily, which posts once the evening prices are in
# (~4:20 PM Central). It covers Monday-Sunday: at 9 AM the newest prices are
# Sunday's. The window closes at 3 PM, before Monday's prices land, so a late
# or retried run can never post it next to the daily. A Monday with no run in
# the window posts no weekly; the workflow's force_weekly sends one by hand.
WEEKLY_TZ = ZoneInfo("America/Chicago")
WEEKLY_FIRST_HOUR = 9
WEEKLY_LAST_HOUR = 15          # exclusive
WEEKLY_MAX_LAG_DAYS = 2        # Sunday's prices, or Saturday's if Sunday's ETL failed
WEEKLY_MIN_LAG_DAYS = 1        # never Monday's own: that is the daily's report
# A weekly is owed when the last one went out at least this many days of prices
# ago. In one Monday window the price date can only move Saturday -> Sunday (a
# late ETL), so 3 never posts twice; 6 let a weekly forced on a Tuesday cost
# the channel the next Monday's.
WEEKLY_REPEAT_DAYS = 3

# ── links: the site's tcgUrl, exactly (test_discord_reports.py checks Index.html) ──
TCG_AFFILIATE_BASE = "https://partner.tcgplayer.com/c/7285926/1780961/21018"
AFFILIATE_NOTE = "Links may earn packs.ink a commission"
# Index.html's SET_DISPLAY_NAMES — the names the site shows. Pinned by the test.
SET_DISPLAY_NAMES = {
    "Challenge Promo": "Lorcana Challenge Promo (C1)",
    "Lorcana Challenge Year 3": "Lorcana Challenge Promo (C2)",
    "EPCOT Festival of the Arts": "Magical Places Promos",
    "Hunny Rescue – Illumineer's Quest": "Illumineer's Quest: The Great Hunny Rescue",
}
C1_SET = "Challenge Promo"

# ── sections ────────────────────────────────────────────────────────────────
CHASE_RARITIES = {"Enchanted", "Epic", "Iconic"}
# rank: what the list is ordered by, and what the bold number leads with.
# min_price / min_usd: the floor. Both have to clear, so a $4 card moving
# 50 cents is out however big its percent is (Zaven, 2026-09-28: "raise the floor").
# The reports rank and quote TCGplayer's LOW, as the site does (Zaven,
# 2026-10-04). The standing notes ("12-mo low") still judge NM Market history,
# the site's own priceStanding rule — a phantom Low must never read as a bargain.
REPORT_PRICE_COL = "low_today"       # price_movers
REPORT_PCT_PREFIX = "pct_"           # price_movers: pct_1d, pct_7d, ...
REPORT_DAILY_COL = "low_price"       # prices_daily

SECTIONS = {
    "chase": {"title": "✦ CHASE", "rank": "pct", "min_price": 10.0, "min_usd": 2.0,
              "color": 0xE3B341, "lines": {"1d": 4, "7d": 5}},
    "base": {"title": "◆ BASE CARDS", "rank": "pct", "min_price": 5.0, "min_usd": 1.0,
             "color": 0x5B9CF5, "lines": {"1d": 4, "7d": 5}},
    "promo": {"title": "★ PROMOS", "rank": "pct", "min_price": 10.0, "min_usd": 2.0,
              "color": 0xC77DFF, "lines": {"1d": 3, "7d": 4}},
    "foil": {"title": "✧ FOILS", "rank": "pct", "min_price": 5.0, "min_usd": 1.0,
             "color": 0x9AA0AB, "lines": {"1d": 3, "7d": 4}},
}
SECTION_ORDER = ("chase", "base", "promo", "foil")
HEADER_COLOR = 0xE3B341
WORTH_COLOR = 0x5CC480
WORTH_LINES = 4
# Candidates per section before the stale-row check, as a multiple of the
# lines shown. A stale row cut FIRST would cost a real mover its slot.
OVERFETCH = 3
# A mover's standing needs its history, which is the expensive read, so only
# this many of each section's candidates get one (the shown rows are a subset).
STANDING_PER_SECTION = 10
# Discord refuses a message whose embeds hold more than 6000 characters. Every
# card link is ~160 of them, so the weekly trims its last sections to fit.
EMBED_TOTAL_LIMIT = 5900
FOOTER = "packs.ink"
RARITY_ORDER = ("Common", "Uncommon", "Rare", "Super Rare", "Legendary", "Enchanted", "Epic", "Iconic")
MAINLINE_MIN_COMPONENTS = 100   # a set index this wide is a booster set, not a promo run


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
    """Is this subscription owed a post for price date `today`? WHEN a cadence
    may post at all is fresh_enough / weekly_open's business, not this."""
    last = sub.get("last_posted_on")
    last = dt.date.fromisoformat(str(last)[:10]) if last else None
    if sub["cadence"] == "daily":
        return last != today
    if sub["cadence"] == "weekly":
        # force_weekly is a person asking for it now: it posts even to a
        # channel that already has this week's.
        return force_weekly or last is None or (today - last).days >= WEEKLY_REPEAT_DAYS
    return False


def weekly_open(price_date, now):
    """May the weekly post at `now` (UTC)? Monday 9 AM - 3 PM Chicago, on the
    weekend's prices. ⚠ Never on MONDAY's: from November (CST) the ETL lands
    ~14:40 Chicago, inside the window, and an ETL-triggered run would rebuild
    the weekly from Monday's prices and post it beside the daily."""
    local = now.astimezone(WEEKLY_TZ)
    if local.weekday() != 0 or not (WEEKLY_FIRST_HOUR <= local.hour < WEEKLY_LAST_HOUR):
        return False
    return WEEKLY_MIN_LAG_DAYS <= (local.date() - price_date).days <= WEEKLY_MAX_LAG_DAYS


def fresh_enough(price_date, now):
    """May a report for price_date post at `now` (UTC)?"""
    today = now.date()
    if price_date == today:
        return True
    return price_date == today - dt.timedelta(days=1) and now.hour < LATE_GRACE_HOURS


def drop_stale(sb, rows, price_date):
    """Keep only movers whose Low is really today's. An eBay row passes: it is
    there because the card sold inside the window."""
    keep = {id(r) for r in rows if r.get("ebay")}
    pids = sorted({r["tcgplayer_product_id"] for r in rows if r.get("tcgplayer_product_id") and not r.get("ebay")})
    if not pids:
        return [r for r in rows if id(r) in keep]
    live = sb.select(
        "prices_daily",
        columns=f"tcgplayer_product_id,printing,{REPORT_DAILY_COL}",
        filters={"source": "eq.tcgcsv", "grade": "eq.raw", "date": f"eq.{price_date.isoformat()}",
                 "tcgplayer_product_id": "in.(" + ",".join(str(p) for p in pids) + ")"},
        order="tcgplayer_product_id.asc,printing.asc",
    )
    today = {(r["tcgplayer_product_id"], r.get("printing") or "Normal"): r.get(REPORT_DAILY_COL) for r in live}
    out = []
    for r in rows:
        if id(r) in keep:
            out.append(r)
            continue
        v = today.get((r.get("tcgplayer_product_id"), r.get("printing") or "Normal"))
        mine = r.get(REPORT_PRICE_COL)
        if v is not None and mine is not None and abs(float(v) - float(mine)) < 0.005:
            out.append(r)
    return out


# ── pure helpers ─────────────────────────────────────────────────────────────
def tcg_url(pid, printing=None):
    """Index.html's tcgUrl(productId, printing), character for character."""
    if not pid:
        return None
    dest = f"https://www.tcgplayer.com/product/{int(pid)}/?Language=English"
    if printing and printing != "Normal":
        dest += "&Printing=" + quote(printing, safe="")
    return TCG_AFFILIATE_BASE + "?u=" + quote(dest, safe="")


def bucket_of(row):
    """chase | promo | base | foil, or None for a card no section reports. A
    chase or promo card is one printing, so it is never called a foil (the
    site's printingBadge rule). An Illumineer's Quest card is a board-game
    piece, not a card anyone plays or chases, so it is in no section."""
    rarity = row.get("rarity")
    if rarity == "Quest":
        return None
    if rarity in CHASE_RARITIES:
        return "chase"
    if rarity == "Promo":
        return "promo"
    if (row.get("printing") or "Normal") in ("Normal", "Non-Foil"):
        return "base"
    return "foil"


def dollar_move(price, pct):
    """What the move was in dollars, from today's price and its percent."""
    base = 1 + float(pct) / 100
    if base <= 0:
        return None
    return float(price) - float(price) / base


def qualifies(row, key):
    """The floor holds at BOTH ends of the window — today's price and the price
    the card started at — the home movers banners' rule. On Low that is what
    keeps a card that jumped from $0.50 to $6.00 ("+1100%") out of the report:
    one cheap listing selling through is not a market move."""
    cfg = SECTIONS[key]
    start = row["price"] - row["usd"]
    return (row["price"] >= cfg["min_price"] and start >= cfg["min_price"]
            and abs(row["usd"]) >= cfg["min_usd"])


def rank(rows, key):
    by = "usd" if SECTIONS[key]["rank"] == "usd" else "pct"
    return sorted(rows, key=lambda r: -abs(r[by]))


def sectioned(rows, window, ebay=()):
    """price_movers rows -> {section: [ranked, floored rows]} with pct / usd / price.
    `ebay` rows arrive already priced (ebay_rows) and face the same floors."""
    pct_col = REPORT_PCT_PREFIX + window
    out = {k: [] for k in SECTION_ORDER}
    for row in ebay:
        key = bucket_of(row)
        if key and qualifies(row, key):
            out[key].append(row)
    for r in rows:
        p, price = r.get(pct_col), r.get(REPORT_PRICE_COL)
        if p is None or price is None or float(p) == 0:
            continue
        usd = dollar_move(price, p)
        if usd is None:
            continue
        row = {**r, "pct": float(p), "usd": usd, "price": float(price)}
        key = bucket_of(r)
        if key and qualifies(row, key):
            out[key].append(row)
    return {k: rank(v, k) for k, v in out.items()}


# ── promos we track eBay sales for ──────────────────────────────────────────
# TCGplayer barely trades these, so its Low is one asking price: Golden Mickey's
# "+1233%" to $200,000 led the Promos section on 2026-10-05. Zaven: "for those
# cards, we should use the ebay sales data and ignore the tcgp for changes in
# price." Any card in raw_sales_rollup leaves the TCGplayer movers entirely, and
# comes back only when NEW eBay sales of it reached us since the last report:
# its move is the average of its last 5 eBay sales now against the same average
# before them — the site's "Avg of last 5", so a report and a card page agree.
#
# ⚠ "New" is when we LEARNED of a sale (scraped_at), not when it sold. The
# scrape runs once a day and Terapeak lists a sale a day or more after it
# sells, so "sold on the price date" (the first rule) almost never held and the
# daily carried no eBay moves at all; a sale that sold Saturday and reached us
# Tuesday fell between two weeklies. The window runs from the previous report
# of the same cadence (discord_report_latest.built_at) to now, and a sale that
# sold more than EBAY_FRESH_DAYS before the price date is never "new" — a
# backfill of old sales must not read as this week's market.
EBAY_MIN_BEFORE = 3            # a baseline of one or two sales is not a price
EBAY_FRESH_DAYS = 14
EBAY_MAX_GAP_DAYS = 2          # past one missed report, a window stops growing
EBAY_FOIL = {"foil", "cold foil", "holofoil", "holo"}
EBAY_NONFOIL = {"normal", "non-foil", "nonfoil"}


def sale_pkey(printing, split, foil_split):
    """graded_sale_pkey() in SQL, the bucket raw_sales_rollup groups by:
    '' = the card has one market; 'Unknown' = a split card's sale nobody
    labelled, which can never stand for either printing."""
    if split:
        return printing or "Unknown"
    if foil_split:
        return "Foil" if (printing or "").lower() in EBAY_FOIL else "Non-Foil"
    return ""


def catalog_bucket(printing):
    """Index.html's gradedSlotBucket: which bucket a catalog printing reads."""
    s = (printing or "").lower().strip()
    if not s or s == "unknown":
        return None
    if s in EBAY_FOIL:
        return "Foil"
    if s in EBAY_NONFOIL:
        return "Non-Foil"
    return s


def _utc(ts):
    """An ISO timestamp as an aware UTC datetime (a naive one is taken as
    UTC), or None."""
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def ebay_window(sb, price_date, window, now):
    """(cutoff, end): a sale scraped after cutoff and by end is NEW to this
    report. cutoff is when the previous report of this cadence was built; a
    rebuild of a report already kept for this price date (a second run the
    same day) reuses that report's own window, so both say the same thing."""
    span = dt.timedelta(days=digest.WINDOW_DAYS[window])
    cadence = "daily" if window == "1d" else "weekly"
    end, cutoff = now, None
    try:
        row = (load_latest(sb) or {}).get(cadence) or {}
    except Exception:
        row = {}
    built = _utc(row.get("built_at"))
    if built and built <= now:
        if str(row.get("price_date") or "")[:10] == price_date.isoformat():
            end, cutoff = built, built - span
        else:
            cutoff = built
    if cutoff is None:
        cutoff = end - span
    return max(cutoff, end - span - dt.timedelta(days=EBAY_MAX_GAP_DAYS)), end


def ebay_moves(sales, flags, cutoff, end, floor):
    """{(card_id, bucket): move} for every bucket with a sale NEW to this
    report — scraped after cutoff and by end, sold on or after floor — and a
    real baseline from what was known before. Pure — the test drives it."""
    groups = {}
    for s in sales:
        cid, price, day = s.get("card_id"), s.get("sale_price"), s.get("sold_date")
        if not cid or price is None or not day:
            continue
        f = flags.get(cid) or {}
        key = (cid, sale_pkey(s.get("printing"), f.get("split_printing"), f.get("foil_split")))
        if key[1] == "Unknown":
            continue
        seen = _utc(s.get("scraped_at"))
        if seen and seen > end:
            continue                  # reached us after this report: the next one's
        d = dt.date.fromisoformat(str(day)[:10])
        fresh = bool(seen and seen > cutoff and d >= floor)
        old = not (seen and seen > cutoff)
        if fresh or old:
            groups.setdefault(key, []).append((d, str(s.get("scraped_at") or ""), float(price), fresh))
    out = {}
    for key, rows in groups.items():
        rows.sort()
        new = [r for r in rows if r[3]]
        before = [r for r in rows if not r[3]][-5:]
        if not new or len(before) < EBAY_MIN_BEFORE:
            continue
        now = [r[2] for r in rows[-5:]]
        avg_now, avg_was = sum(now) / len(now), sum(r[2] for r in before) / len(before)
        if avg_was <= 0 or avg_now == avg_was:
            continue
        out[key] = {"now": avg_now, "was": avg_was, "sold": len(new), "n": len(now),
                    "pct": (avg_now / avg_was - 1) * 100}
    return out


def ebay_rows(moves, flags, catalog):
    """Report rows for the moves: one per catalog printing the bucket stands for
    (Index.html's rawSaleMatch — '' matches any printing, else the printing's
    own bucket), carrying the eBay numbers in place of TCGplayer's."""
    buckets = {}
    for cid, b in moves:
        buckets.setdefault(cid, set()).add(b)
    out = []
    for r in catalog:
        cid = r.get("card_id")
        have = buckets.get(cid)
        if not have:
            continue
        b = "" if "" in have else catalog_bucket(r.get("printing"))
        m = moves.get((cid, b))
        if not m:
            continue
        out.append({**r, "pct": m["pct"], "usd": m["now"] - m["was"], "price": m["now"],
                    "ebay": {"sold": m["sold"], "n": m["n"]}})
        moves = {k: v for k, v in moves.items() if k != (cid, b)}   # one row per bucket
    return out


def fetch_ebay(sb, price_date, window, now=None):
    """(card ids we track on eBay, report rows), or None when the eBay tables
    can't be read — the report then runs on TCGplayer alone, as before."""
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        roll = sb.select("raw_sales_rollup", columns="card_id", order="card_id.asc,printing.asc")
        ids = sorted({r["card_id"] for r in roll if r.get("card_id")})
        if not ids:
            return set(), []
        inlist = "in.(" + ",".join('"' + i.replace('"', "") + '"' for i in ids) + ")"
        flags = {r["id"]: r for r in sb.select("cards", columns="id,split_printing,foil_split",
                                               filters={"id": inlist}, order="id.asc")}
        sales = sb.select("raw_sales", columns="card_id,printing,sale_price,sold_date,scraped_at",
                          filters={"card_id": inlist, "excluded": "is.false"},
                          order="card_id.asc,sold_date.asc,item_id.asc")
        catalog = sb.select("price_movers", columns="card_id,name,version,rarity,set_id,printing,tcgplayer_product_id",
                            filters={"card_id": inlist}, order="card_id.asc,printing.asc")
    except Exception as e:
        print(f"  (eBay sales unavailable, promos stay on TCGplayer: {type(e).__name__}: {str(e)[:160]})")
        return None
    cutoff, end = ebay_window(sb, price_date, window, now)
    moves = ebay_moves(sales, flags, cutoff, end, price_date - dt.timedelta(days=EBAY_FRESH_DAYS))
    return set(ids), ebay_rows(moves, flags, catalog)


def card_title(row, set_name=""):
    name = row.get("name") or "Unknown"
    ver = row.get("version")
    title = f"{name} — {ver}" if ver and ver != "None" else name
    if set_name == C1_SET:   # one card_id, two markets
        title += " (Prize Wall)" if (row.get("printing") or "Normal") == "Normal" else " (Top Prize)"
    return title.replace("[", "(").replace("]", ")")


def set_display(name):
    return SET_DISPLAY_NAMES.get(name, name or "")


def fmt_money(v, sign=False):
    return art.fmt_money(float(v), sign=sign)


def fmt_pct(p):
    return art.fmt_pct(float(p))


SHORT_STANDING = {
    "cheapest in 12 months": "12-mo low", "cheapest in 6 months": "6-mo low",
    "cheapest in 3 months": "3-mo low",
}


def short_standing(st):
    if not st:
        return ""
    label = st[1]
    if label in SHORT_STANDING:
        return SHORT_STANDING[label]
    return label.replace("near its ", "near ").replace("-month", "-mo")


def is_worth(st):
    return bool(st) and st[0] in CHEAP_TONES


CHEAP_TONES = ("low", "near-low")


def agreed_standing(market, low):
    """The note a line may carry. A line QUOTES TCGplayer's Low, and the note
    used to be judged on NM Market alone, so one cheap listing printed "-48%
    ... near 12-mo high" (Cruella: Low $299.99 -> $155.33 while Market sat
    flat at $200.16 — davidpineapple, 2026-10-05). A note now prints only when
    the Low history says the same thing, so it is true of the price beside it;
    Market still has to agree too, so one phantom Low listing can never read
    "cheapest in 12 months" or reach Worth a look. When the two disagree in
    strength, the weaker claim is printed."""
    if not market or not low:
        return None
    if market[0] == "high":
        return market if low[0] == "high" else None
    if market[0] in CHEAP_TONES and low[0] in CHEAP_TONES:
        return low if (low[0] == "near-low" and market[0] == "low") else market
    return None


def standing_note(st, pct):
    """The short note, with "still" when it runs against the move: a card down
    15% this week can still be near its 12-month high, and should say so."""
    note = short_standing(st)
    if not note:
        return ""
    against = (st[0] == "high" and pct < 0) or (st[0] in CHEAP_TONES and pct > 0)
    if not against:
        return note
    return "still " + note if note.startswith("near ") else "still at a " + note


def lead_number(row, key):
    return fmt_money(row["usd"], sign=True) if SECTIONS[key]["rank"] == "usd" else fmt_pct(row["pct"])


def arrow(row):
    return "▲" if row["pct"] > 0 else "▼"


def ebay_note(row, weekly):
    """What an eBay row's price is: the average of its last N eBay sales, and
    how many NEW sales moved it — a move made by one sale should say so. "New"
    is new to us since the last report, not sold in a calendar window (see
    ebay_window), so the line does not claim a sale date it doesn't know."""
    e = row["ebay"]
    return f"eBay avg of last {e['n']} sales · {e['sold']} new sale{'' if e['sold'] == 1 else 's'}"


def daily_line(row, key, sets, standing):
    title = card_title(row, sets.get(row.get("set_id"), ""))
    url = tcg_url(row.get("tcgplayer_product_id"), row.get("printing"))
    link = f"[{title}]({url})" if url else title
    note = standing_note(standing, row["pct"])
    tail = f" · *{note}*" if note else ""
    if row.get("ebay"):
        tail = f" · *{ebay_note(row, False)}*"
    return f"{arrow(row)} **{lead_number(row, key)}** {link} · {fmt_money(row['price'])}{tail}"


def weekly_line(row, key, sets, standing):
    set_raw = sets.get(row.get("set_id"), "")
    title = card_title(row, set_raw)
    url = tcg_url(row.get("tcgplayer_product_id"), row.get("printing"))
    link = f"[{title}]({url})" if url else title
    other = fmt_pct(row["pct"]) if SECTIONS[key]["rank"] == "usd" else fmt_money(row["usd"], sign=True)
    detail = f"{fmt_money(row['price'])} ({other}) · {row.get('rarity') or ''}"
    if row.get("ebay"):
        detail = f"{fmt_money(row['price'])} ({other}) · {ebay_note(row, True)}"
    if set_raw:
        detail += f" · {set_display(set_raw)}"
    note = standing_note(standing, row["pct"])
    tail = f" · **{note}**" if note else ""
    return f"{arrow(row)} **{lead_number(row, key)}** {link}\n*{detail}*{tail}"


def embed_chars(e):
    n = len(e.get("title") or "") + len(e.get("description") or "")
    n += len((e.get("author") or {}).get("name") or "") + len((e.get("footer") or {}).get("text") or "")
    for f in e.get("fields") or []:
        n += len(f.get("name") or "") + len(f.get("value") or "")
    return n


def fit_embeds(embeds, limit=None):
    """Drop lines from the LAST section embeds until the whole message fits
    Discord's 6000-character cap. An embed that loses every line is removed.
    The header (index 0) and any embed marked `_keep` are never trimmed."""
    limit = EMBED_TOTAL_LIMIT if limit is None else limit
    embeds = [dict(e) for e in embeds]
    while sum(embed_chars(e) for e in embeds) > limit:
        for i in range(len(embeds) - 1, 0, -1):
            e = embeds[i]
            if e.get("_keep") or not e.get("description"):
                continue
            lines = e["_lines"]
            if len(lines) > 1:
                lines = lines[:-1]
                e["_lines"] = lines
                e["description"] = "\n".join(lines)
            else:
                foot = e.get("footer")
                embeds.pop(i)
                if foot:
                    embeds[-1]["footer"] = foot
            break
        else:
            break
    return embeds


def clean_embed(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


# ── the market pulse (market_index_daily) ────────────────────────────────────
def index_change(series, day, back_days):
    """% change of an index series between the value on `day` and the latest
    value on or before `day - back_days`. None when either end is missing."""
    now = series.get(day)
    if now is None:
        return None
    cut = day - dt.timedelta(days=back_days)
    prior = [v for d, v in series.items() if d <= cut]
    if not prior:
        return None
    then = series[max(d for d in series if d <= cut)]
    return (now / then - 1) * 100 if then else None


def market_pulse(sb, price_date, window, sets):
    """{all, chase, sealed, sets:[(name, week, month)], rarities:[(r, change)]} or None.

    None whenever the index is not current for price_date — the ETL refreshes
    it with the prices, but it is optional there, and a stale index would
    report yesterday's market as today's."""
    days = 1 if window == "1d" else 7
    try:
        rows = sb.select(
            "market_index_daily", columns="scope,scope_key,date,value,n_components",
            filters={"scope": "in.(all,chase,sealed,rarity,set)",
                     "date": f"gte.{(price_date - dt.timedelta(days=32)).isoformat()}"},
            order="scope.asc,scope_key.asc,date.asc")
    except RuntimeError as e:
        print(f"  (market index unavailable: {str(e)[:160]})")
        return None
    series, width = {}, {}
    for r in rows:
        key = (r["scope"], r.get("scope_key") or "")
        d = dt.date.fromisoformat(str(r["date"])[:10])
        series.setdefault(key, {})[d] = float(r["value"])
        if d == price_date:
            width[key] = r.get("n_components") or 0
    if price_date not in series.get(("all", ""), {}):
        return None

    def ch(key, back):
        s = series.get(key)
        return index_change(s, price_date, back) if s else None

    out = {"all": (ch(("all", ""), days), ch(("all", ""), 30)),
           "chase": (ch(("chase", ""), days), ch(("chase", ""), 30)),
           "sealed": (ch(("sealed", ""), days), ch(("sealed", ""), 30))}
    set_moves = []
    for (scope, key), s in series.items():
        if scope != "set" or width.get((scope, key), 0) < MAINLINE_MIN_COMPONENTS:
            continue
        wk = index_change(s, price_date, days)
        if wk is not None and key in sets:
            set_moves.append((sets[key], wk, index_change(s, price_date, 30), key))
    set_moves.sort(key=lambda t: -t[1])
    out["sets"] = set_moves
    rar = []
    for r in RARITY_ORDER:
        c = ch(("rarity", r), days)
        if c is not None:
            rar.append((r, c))
    rar.sort(key=lambda t: -abs(t[1]))
    out["rarities"] = rar
    return out


def move_verb(p):
    if abs(p) < 0.3:
        return "held flat at"
    if p > 0:
        return "rose"
    return "slipped" if p > -3 else "fell"


def pulse_sentence(pulse, window):
    if not pulse or pulse["all"][0] is None:
        return ""
    span = "today" if window == "1d" else "this week"
    a, c = pulse["all"][0], pulse["chase"][0]
    if abs(a) < 0.3 and (c is None or abs(c) < 0.3):
        # Two "held flat at"s in one sentence read as a stutter.
        s = f"A quiet {'day' if window == '1d' else 'week'}: the whole market moved **{fmt_pct(a)}**"
        s += f" and chase cards **{fmt_pct(c)}**." if c is not None else "."
    else:
        s = f"The whole market {move_verb(a)} **{fmt_pct(a)}** {span}"
        s += f" and chase cards {move_verb(c)} **{fmt_pct(c)}**." if c is not None else "."
    if window != "1d" and len(pulse["sets"]) >= 2:
        hot, cold = pulse["sets"][0], pulse["sets"][-1]
        month = f", {fmt_pct(hot[2])} this month" if hot[2] is not None else ""
        s += f" **{hot[0]}** led the sets (**{fmt_pct(hot[1])}**{month}); **{cold[0]}** trailed at **{fmt_pct(cold[1])}**."
    return s


def pulse_fields(pulse):
    def two(label, pair):
        wk, mo = pair
        if wk is None:
            return None
        second = f"\n{fmt_pct(mo)} this month" if mo is not None else ""
        return {"name": label, "value": f"**{fmt_pct(wk)}** this week{second}", "inline": True}

    fields = [f for f in (two("Whole market", pulse["all"]), two("Chase cards", pulse["chase"]),
                          two("Sealed", pulse["sealed"])) if f]
    sets = pulse["sets"]
    if len(sets) >= 2:
        hot, cold = sets[0], sets[-1]
        fields.append({"name": "🔥 Hottest set", "inline": True,
                       "value": f"**{hot[0]}** {fmt_pct(hot[1])}" + (f"\n{sets[1][0]} {fmt_pct(sets[1][1])}" if len(sets) > 2 else "")})
        fields.append({"name": "🧊 Coolest set", "inline": True,
                       "value": f"**{cold[0]}** {fmt_pct(cold[1])}" + (f"\n{sets[-2][0]} {fmt_pct(sets[-2][1])}" if len(sets) > 2 else "")})
    if pulse["rarities"]:
        top = pulse["rarities"][0]
        rest = " · ".join(f"{r} {fmt_pct(c)}" for r, c in pulse["rarities"][1:3])
        fields.append({"name": "By rarity", "inline": True,
                       "value": f"{top[0]} **{fmt_pct(top[1])}**" + (f"\n{rest}" if rest else "")})
    return fields


def market_chart_series(sb, price_date, pulse, sets_meta):
    """(title, subtitle, series) for the weekly chart, or None."""
    mainline = {key for _, _, _, key in pulse["sets"]}
    released = sorted((m["released_at"], sid) for sid, m in sets_meta.items()
                      if sid in mainline and m.get("released_at") and m["released_at"] <= price_date)
    newest = released[-1] if released else None
    if newest and 28 <= (price_date - newest[0]).days <= 150:
        start, title = newest[0], f"Since {sets_meta[newest[1]]['name']} came out"
    else:
        start, title = price_date - dt.timedelta(days=90), "The last 3 months"
    picks = [("Whole market", ("all", ""), art.TEXT), ("Chase cards", ("chase", ""), art.GOLD)]
    hot = pulse["sets"][0] if pulse["sets"] else None
    if hot:
        picks.insert(0, (hot[0], ("set", hot[3]), art.TEAL))
    if newest and (not hot or newest[1] != hot[3]):
        picks.append((sets_meta[newest[1]]["name"], ("set", newest[1]), art.CORAL))
    elif len(pulse["sets"]) >= 2:
        cold = pulse["sets"][-1]
        picks.append((cold[0], ("set", cold[3]), art.CORAL))
    series = []
    for label, (scope, key), color in picks:
        try:
            rows = sb.select("market_index_daily", columns="date,value",
                             filters={"scope": f"eq.{scope}", "scope_key": f"eq.{key}",
                                      "date": f"gte.{start.isoformat()}"},
                             order="date.asc")
        except RuntimeError:
            continue
        pts = [(dt.date.fromisoformat(str(r["date"])[:10]), float(r["value"])) for r in rows if r.get("value")]
        pts = [p for p in pts if p[0] <= price_date]
        if len(pts) >= 2:
            series.append((label, pts, color))
    if len(series) < 2:
        return None
    common = max(pts[0][0] for _, pts, _ in series)
    rebased = []
    for label, pts, color in series:
        pts = [p for p in pts if p[0] >= common]
        if len(pts) < 2:
            continue
        base = pts[0][1]
        rebased.append((label, [(d, (v / base - 1) * 100) for d, v in pts], color))
    if len(rebased) < 2:
        return None
    return title, f"% change since {common:%b} {common.day}", rebased


# ── the report ───────────────────────────────────────────────────────────────
def fetch_candidates(sb, window):
    pct_col = REPORT_PCT_PREFIX + window
    floor = min(s["min_price"] for s in SECTIONS.values())
    cols = ("card_id,name,version,rarity,set_id,printing,tcgplayer_product_id,"
            f"{REPORT_PRICE_COL},{pct_col}")
    return sb.select("price_movers", columns=cols,
                     filters={REPORT_PRICE_COL: f"gte.{floor}", pct_col: "neq.0"},
                     order="card_id.asc,printing.asc")


def load_sets(sb):
    try:
        rows = sb.select("sets", columns="id,name,released_at", order="id.asc")
    except RuntimeError:
        return {}
    out = {}
    for r in rows:
        rel = r.get("released_at")
        out[r["id"]] = {"name": r.get("name") or "",
                        "released_at": dt.date.fromisoformat(str(rel)[:10]) if rel else None}
    return out


def key_of(row):
    return (row.get("tcgplayer_product_id"), row.get("printing") or "Normal")


# ── what's new, and what's on this week ──────────────────────────────────────
# Two short embeds after the price sections. Neither may ever cost the report:
# every read is wrapped, and a failure simply leaves the embed out.
REVEAL_COLOR = 0x8E7CC3
CALENDAR_COLOR = 0x4FA3D1
REVEAL_DAYS = {"1d": 1, "7d": 7}
REVEAL_SETS = 4            # sets named in the embed
REVEAL_NAMES = 6           # card names listed per set
CALENDAR_DAYS = 7
CALENDAR_LINES = 8
KIND_LABEL = {"dlc": "Challenge", "ccq": "Qualifier", "set": "Set", "product": "Product"}
INDEX_HTML = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Index.html")
PHASE_LABEL = {"lgs": "LGS release", "retail": "Retail release"}


def card_label(row):
    v = row.get("version")
    return row.get("name") or "" if v in (None, "", "None") else f"{row.get('name')} - {v}"


def new_reveals(sb, now, days, sets):
    """[(set name, [card label, ...])] for cards first added in the last `days`
    days, newest set first. A name that already existed before the cutoff is a
    new PRINTING, not a reveal, and is left out."""
    cutoff = (now - dt.timedelta(days=days)).isoformat()
    rows = sb.select("cards", columns="id,name,version,set_id,inserted_at", order="id.asc")
    old = {card_label(r) for r in rows if str(r.get("inserted_at") or "") < cutoff}
    by_set, seen = {}, set()
    for r in sorted(rows, key=lambda r: str(r.get("inserted_at") or ""), reverse=True):
        label = card_label(r)
        if str(r.get("inserted_at") or "") < cutoff or not label or label in old or label in seen:
            continue
        seen.add(label)
        by_set.setdefault(set_display(sets.get(r.get("set_id"), "")) or "Other", []).append(label)
    return list(by_set.items())


def reveals_embed(groups, weekly):
    if not groups:
        return None
    lines = []
    for name, cards in groups[:REVEAL_SETS]:
        shown = ", ".join(cards[:REVEAL_NAMES])
        more = len(cards) - REVEAL_NAMES
        lines.append(f"**{name}** · {len(cards)} new: {shown}" + (f" and {more} more" if more > 0 else ""))
    total = sum(len(c) for _, c in groups)
    label = f"🆕 NEW CARDS · {total} added " + ("this week" if weekly else "since yesterday")
    return {"author": {"name": label, "url": f"{digest.SITE}/cards"}, "color": REVEAL_COLOR,
            "description": "\n".join(lines), "_lines": lines, "_keep": True}


def derived_releases(path=None):
    """Set and product release dates out of Index.html's own consts, the same
    ones the site's calendar derives its rows from. [] if the file or the
    consts cannot be read."""
    try:
        src = open(path or INDEX_HTML, encoding="utf8").read()
    except OSError:
        return []
    out = []
    m = re.search(r"const SET_RELEASE_DATES = \{(.*?)\n\};", src, re.S)
    for name, lgs, retail in re.findall(r'"([^"]+)":\s*\{lgs:"(\d{4}-\d\d-\d\d)",\s*retail:"(\d{4}-\d\d-\d\d)"', m.group(1) if m else ""):
        out.append({"id": f"set:{name}:lgs", "kind": "set", "title": name, "subtitle": PHASE_LABEL["lgs"], "starts_on": lgs})
        out.append({"id": f"set:{name}:retail", "kind": "set", "title": name, "subtitle": PHASE_LABEL["retail"], "starts_on": retail})
    m = re.search(r"const PRODUCT_RELEASE_DATES = \[(.*?)\n\];", src, re.S)
    for title, sub, on in re.findall(r'\{title:\s*"([^"]+)"(?:,\s*subtitle:\s*"([^"]+)")?,\s*on:\s*"(\d{4}-\d\d-\d\d)"', m.group(1) if m else ""):
        out.append({"id": f"product:{title}", "kind": "product", "title": title, "subtitle": sub or None, "starts_on": on})
    return out


def week_ahead(sb, day, derived=None):
    """Confirmed calendar rows starting in the next CALENDAR_DAYS days, plus the
    derived releases a curated row does not already cover."""
    end = day + dt.timedelta(days=CALENDAR_DAYS)
    rows = sb.select("calendar_events", columns="id,kind,title,subtitle,starts_on,ends_on,location",
                     filters={"confirmed": "is.true", "starts_on": f"gte.{day.isoformat()}",
                              "and": f"(starts_on.lte.{end.isoformat()})"}, order="starts_on.asc")
    have = {(r.get("kind"), r.get("title"), r.get("subtitle") if r.get("kind") == "set" else None) for r in rows}
    for d in (derived_releases() if derived is None else derived):
        key = (d["kind"], d["title"], d["subtitle"] if d["kind"] == "set" else None)
        if key not in have and day.isoformat() <= d["starts_on"] <= end.isoformat():
            rows.append(dict(d))
    return sorted(rows, key=lambda r: (str(r.get("starts_on")), str(r.get("title"))))


def calendar_embed(rows):
    if not rows:
        return None
    lines = []
    for r in rows[:CALENDAR_LINES]:
        d0 = dt.date.fromisoformat(str(r["starts_on"])[:10])
        when = f"{d0:%a}, {d0:%b} {d0.day}"
        if r.get("ends_on") and str(r["ends_on"])[:10] != str(r["starts_on"])[:10]:
            d1 = dt.date.fromisoformat(str(r["ends_on"])[:10])
            when += f"–{d1.day}" if d1.month == d0.month else f" – {d1:%b} {d1.day}"
        title = r.get("title") or ""
        if r.get("kind") == "set" and r.get("subtitle"):
            title += " " + r["subtitle"]
        elif r.get("kind") == "product" and r.get("subtitle"):
            title += ": " + r["subtitle"]
        url = f"{digest.SITE}/calendar" + (f"?ce={quote(str(r['id']), safe='')}" if r.get("id") else "")
        place = (r.get("location") or "").split(" · ")[-1].strip()
        lines.append(f"**{when}** · [{title}]({url}) · {KIND_LABEL.get(r.get('kind'), 'Event')}"
                     + (f" · {place}" if place else ""))
    more = len(rows) - CALENDAR_LINES
    if more > 0:
        lines.append(f"*and {more} more on the calendar*")
    return {"author": {"name": "📅 THIS WEEK ON THE CALENDAR", "url": f"{digest.SITE}/calendar"},
            "color": CALENDAR_COLOR, "description": "\n".join(lines), "_lines": lines, "_keep": True}


def extra_embeds(sb, price_date, window, sets, now=None):
    """The reveals embed (daily and weekly) and the calendar embed (weekly)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    weekly = window != "1d"
    out = []
    try:
        e = reveals_embed(new_reveals(sb, now, REVEAL_DAYS.get(window, 1), sets), weekly)
        if e:
            out.append(e)
    except Exception as ex:   # never the report's problem
        print(f"  (no reveals section: {type(ex).__name__})")
    if weekly:
        try:
            e = calendar_embed(week_ahead(sb, price_date))
            if e:
                out.append(e)
        except Exception as ex:
            print(f"  (no calendar section: {type(ex).__name__})")
    return out


def build_report(sb, price_date, window, session=requests, now=None):
    """{"embeds", "files", "plain"} for one window, or None when nothing
    cleared the floors. "plain" is the same report with no attachments — what
    goes out if Discord refuses the pictures."""
    weekly = window != "1d"
    sets_meta = load_sets(sb)
    sets = {sid: m["name"] for sid, m in sets_meta.items()}
    now = now or dt.datetime.now(dt.timezone.utc)
    cands = fetch_candidates(sb, window)
    eb = fetch_ebay(sb, price_date, window, now=now)
    tracked, ebay = eb if eb is not None else (set(), [])
    ranked = sectioned([r for r in cands if r.get("card_id") not in tracked], window, ebay)
    fresh = {}
    for key in SECTION_ORDER:
        want = SECTIONS[key]["lines"][window]
        fresh[key] = drop_stale(sb, ranked[key][:want * OVERFETCH], price_date)
    if not any(fresh.values()):
        return None

    look = {}
    for key in SECTION_ORDER:
        for r in fresh[key][:STANDING_PER_SECTION]:
            if not r.get("ebay"):
                look[key_of(r)] = r
    since = (price_date - dt.timedelta(days=digest.HISTORY_DAYS)).isoformat()
    pids = sorted({k[0] for k in look if k[0]})
    hist = {}
    for i in range(0, len(pids), 40):
        hist.update(digest.fetch_history(sb, pids[i:i + 40], since))
    # Low history: the picture strips draw each card's LOW trend, matching the
    # price beside it, and a standing note has to hold on it too. Without it,
    # agreed_standing prints no note at all.
    low_hist = {}
    for i in range(0, len(pids), 40):
        try:
            low_hist.update(digest.fetch_history(sb, pids[i:i + 40], since, col=REPORT_DAILY_COL))
        except Exception as e:  # a missing trend line must never cost the report
            print(f"  (low history unavailable: {str(e)[:160]})")
    standing = {k: agreed_standing(digest.price_standing(hist.get(k, [])),
                                   digest.price_standing(low_hist.get(k, [])))
                for k in look}

    worth = []
    if weekly:
        worth = [r for key in SECTION_ORDER for r in fresh[key][:STANDING_PER_SECTION]
                 if r["pct"] < 0 and is_worth(standing.get(key_of(r)))]
        worth.sort(key=lambda r: r["pct"])
        worth = worth[:WORTH_LINES]
    taken = {key_of(r) for r in worth}
    shown = {key: [r for r in fresh[key] if key_of(r) not in taken][:SECTIONS[key]["lines"][window]]
             for key in SECTION_ORDER}

    pulse = market_pulse(sb, price_date, window, sets)
    files = {}
    line = weekly_line if weekly else daily_line

    wk0 = price_date - dt.timedelta(days=6)
    if weekly:
        span = (f"{wk0:%b} {wk0.day}–{price_date.day}" if wk0.month == price_date.month
                else f"{wk0:%b} {wk0.day} – {price_date:%b} {price_date.day}")
        title = f"Lorcana week in review · {span}, {price_date:%Y}"
    else:
        title = f"Lorcana movers · {price_date:%a}, {price_date:%b} {price_date.day}, {price_date:%Y}"
    desc = pulse_sentence(pulse, window) or (
        "This week's biggest moves, by kind of card." if weekly else "Today's biggest moves, by kind of card.")
    if not weekly:
        desc += "\n*Italic notes say where a price sits against that card's own history.*"
    header = {"title": title, "url": f"{digest.SITE}/screener", "color": HEADER_COLOR,
              "description": desc, "_keep": True}
    if weekly and pulse:
        header["fields"] = pulse_fields(pulse)
        chart = market_chart_series(sb, price_date, pulse, sets_meta)
        if chart:
            png = art.market_chart(chart[2], chart[0], chart[1])
            if png:
                files["market.png"] = png
                header["image"] = {"url": "attachment://market.png"}
    embeds = [header]

    def section_embed(key, rows, label=None, color=None):
        # Each row leads with ITS OWN section's number, so a base card in
        # "Worth a look" still says -25.3%, not -$2.81.
        lines = [line(r, bucket_of(r), sets, standing.get(key_of(r))) for r in rows]
        cfg = SECTIONS[key]
        if not label:
            label = cfg["title"] + (" · biggest $ moves" if cfg["rank"] == "usd" else " · biggest % moves")
            label += " this week" if weekly else ""
        return {"author": {"name": label}, "color": color or cfg["color"],
                "description": "\n".join(lines), "_lines": lines}

    for key in SECTION_ORDER:
        rows = shown[key]
        if not rows:
            continue
        e = section_embed(key, rows)
        lead_pid = rows[0].get("tcgplayer_product_id")
        e["_thumb"] = {"url": art.art_url(lead_pid)} if lead_pid else None
        if weekly and key in ("chase", "base"):
            strip = art.card_strip([{
                "pid": r.get("tcgplayer_product_id"), "name": r.get("name") or "",
                "version": r.get("version") if r.get("version") not in (None, "None") else set_display(sets.get(r.get("set_id"), "")),
                "price": r["price"], "pct": r["pct"], "usd": r["usd"],
                "spark": low_hist.get(key_of(r), [])} for r in rows if r.get("tcgplayer_product_id")],
                SECTIONS[key]["rank"], session=session)
            if strip:
                files[f"{key}.png"] = strip
                e["image"] = {"url": f"attachment://{key}.png"}
        if "image" not in e and e["_thumb"]:
            e["thumbnail"] = e["_thumb"]
        embeds.append(e)
        if key == "base" and worth:
            w = section_embed("chase", worth, label="💡 WORTH A LOOK · fell this week, now at a multi-month low",
                              color=WORTH_COLOR)
            pid = worth[0].get("tcgplayer_product_id")
            if pid:
                w["thumbnail"] = {"url": art.art_url(pid)}
            embeds.append(w)
    if len(embeds) == 1:
        return None
    embeds.extend(extra_embeds(sb, price_date, window, sets, now=now))
    embeds[-1]["footer"] = {"text": FOOTER + " · /reports"}

    fitted = fit_embeds(embeds)
    names = set(files)
    plain = []
    for e in fitted:
        p = dict(e)
        img = (p.get("image") or {}).get("url", "")
        if img.startswith("attachment://"):
            p.pop("image")
            if p.get("_thumb"):
                p["thumbnail"] = p["_thumb"]
        plain.append(clean_embed(p))
    used = {(e.get("image") or {}).get("url", "")[len("attachment://"):] for e in fitted}
    return {"embeds": [clean_embed(e) for e in fitted],
            "files": [(n, files[n]) for n in sorted(names) if n in used],
            "plain": plain}


def post(token, channel_id, report, session=requests):
    """Post one report; a report whose attachments Discord refuses is re-sent
    without them, so the words still arrive."""
    url = f"{API}/channels/{channel_id}/messages"
    auth = {"Authorization": f"Bot {token}"}

    def as_json(embeds):
        return session.post(url, headers={**auth, "Content-Type": "application/json"},
                            json={"embeds": embeds, "allowed_mentions": {"parse": []}}, timeout=30)

    files = report.get("files") or []
    if not files:
        return as_json(report["embeds"])
    payload = {"embeds": report["embeds"], "allowed_mentions": {"parse": []},
               "attachments": [{"id": i, "filename": n} for i, (n, _) in enumerate(files)]}
    r = session.post(url, headers=auth, data={"payload_json": json.dumps(payload)},
                     files={f"files[{i}]": (n, b, "image/png") for i, (n, b) in enumerate(files)},
                     timeout=60)
    if r.status_code == 400:
        print("  (Discord refused the pictures; sending the report without them)")
        return as_json(report["plain"])
    return r


def write_preview(folder, cadence, report):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, f"{cadence}.json"), "w", encoding="utf-8") as f:
        json.dump({"embeds": report["embeds"], "files": [n for n, _ in report["files"]]}, f,
                  indent=1, ensure_ascii=False)
    for name, data in report["files"]:
        with open(os.path.join(folder, f"{cadence}-{name}"), "wb") as f:
            f.write(data)


def load_latest(sb):
    """{cadence: row} for the stored reports, or None when migration 175 is
    not applied yet."""
    try:
        rows = sb.select(LATEST_TABLE, columns="cadence,price_date,files,built_at", order="cadence.asc")
    except RuntimeError as e:
        msg = str(e)
        if "404" in msg or "42P01" in msg or "PGRST205" in msg or "does not exist" in msg:
            return None
        raise
    return {r["cadence"]: r for r in rows}


def stored_embeds(report, urls):
    """The report's embeds with each attachment:// picture pointing at its
    stored copy. If any picture failed to store, the plain version (no
    attachments, card-art thumbnails instead) rather than a broken image."""
    names = {n for n, _ in report["files"]}
    if names - set(urls):
        return report["plain"]
    out = []
    for e in report["embeds"]:
        e = dict(e)
        for slot in ("image", "thumbnail"):
            u = (e.get(slot) or {}).get("url", "")
            if u.startswith("attachment://"):
                e[slot] = {"url": urls[u[len("attachment://"):]]}
        out.append(e)
    return out


def store_latest(sb, price_date, report_for, session=requests, cadences=("daily", "weekly")):
    """Keep the report each cadence last went out with, for /reports send: the
    daily whenever a daily may post, the weekly only when the weekly may — so
    "/reports send weekly" is exactly Monday's report, not seven days rebuilt
    every evening. Built once per price date per cadence (this job runs
    several times a day). The pictures go to a
    public bucket under a DATED path: Discord caches an image by its URL, so
    yesterday's chart must not come back under today's."""
    have = load_latest(sb)
    if have is None:
        print(f"{LATEST_TABLE} does not exist yet (migration 175 not applied); /reports send stays off.")
        return 0
    stored = 0
    base = f"{sb.url}/storage/v1/object"
    for cadence in cadences:
        old = have.get(cadence) or {}
        if str(old.get("price_date") or "")[:10] == price_date.isoformat():
            continue
        rep = report_for(cadence)
        if not rep:
            continue
        paths, urls = [], {}
        for name, data in rep["files"]:
            path = f"{cadence}/{price_date.isoformat()}/{name}"
            r = session.post(f"{base}/{REPORT_BUCKET}/{path}", data=data, timeout=60,
                             headers={**sb.auth_headers(), "Content-Type": "image/png", "x-upsert": "true"})
            if not r.ok:
                print(f"  could not store {path}: HTTP {r.status_code}")
                continue
            paths.append(path)
            urls[name] = f"{base}/public/{REPORT_BUCKET}/{path}"
        sb.upsert(LATEST_TABLE, [{
            "cadence": cadence, "price_date": price_date.isoformat(),
            "embeds": stored_embeds(rep, urls), "plain": rep["plain"], "files": paths,
            "built_at": dt.datetime.now(dt.timezone.utc).isoformat()}], on_conflict="cadence")
        stored += 1
        print(f"  stored the {cadence} report for /reports send ({len(paths)} pictures)")
        gone = [p for p in (old.get("files") or []) if p not in paths]
        if gone:
            r = session.delete(f"{base}/{REPORT_BUCKET}", json={"prefixes": gone}, timeout=60,
                               headers={**sb.auth_headers(), "Content-Type": "application/json"})
            if not r.ok:
                print(f"  could not delete yesterday's pictures: HTTP {r.status_code}")
    return stored


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
    preview = getattr(args, "preview", None)
    price_date = digest.latest_price_date(sb)
    now = now or dt.datetime.now(dt.timezone.utc)
    if not price_date:
        print("No price date available; refusing to post.")
        return 0
    open_now = []
    if fresh_enough(price_date, now) or args.allow_stale:
        open_now.append("daily")
    if weekly_open(price_date, now) or args.force_weekly:
        open_now.append("weekly")
    if not open_now:
        print(f"Newest price date is {price_date} at {now:%Y-%m-%d %H:%M} UTC: no daily is due "
              "(today's ETL has not landed) and it is outside the weekly's Monday 9 AM-3 PM "
              "Chicago window. Skipping.")
        return 0
    print(f"Open now: {', '.join(open_now)} (price date {price_date}).")

    built = {}

    def report_for(cadence):
        if cadence not in built:
            built[cadence] = build_report(sb, price_date, WINDOW[cadence], session=session, now=now)
        return built[cadence]

    # Kept whether or not any channel subscribes: /reports send posts it.
    if args.post:
        try:
            store_latest(sb, price_date, report_for, session=session, cadences=open_now)
        except Exception as e:   # never let it cost a subscriber their post
            print(f"  could not store the latest report ({type(e).__name__}: {str(e)[:200]})")
    if not subs and not preview:
        print("No servers have asked for reports. Exiting 0.")
        return 0

    owed = [s for s in subs if s["cadence"] in open_now and due(s, price_date, args.force_weekly)]
    if preview:
        for cadence in ("daily", "weekly"):
            rep = report_for(cadence)
            if rep:
                write_preview(preview, cadence, rep)
                print(f"  preview {cadence}: {len(rep['embeds'])} embeds, "
                      f"{sum(embed_chars(e) for e in rep['embeds'])} chars, pictures {[n for n, _ in rep['files']]}")
            else:
                print(f"  preview {cadence}: nothing cleared the floors")
    if not owed:
        print(f"Nothing owed: every {'/'.join(open_now)} subscription already has its report.")
        return 0
    reports = {cadence: report_for(cadence) for cadence in sorted({s["cadence"] for s in owed})}

    posted = failed = 0
    for s in owed:
        rep = reports.get(s["cadence"])
        where = f"{s['cadence']} → channel {s['channel_id']} (server {s['guild_id']})"
        if not rep:
            print(f"  skip {where}: nothing cleared the filters today")
            continue
        if not args.post:
            print(f"  DRY RUN {where}: {rep['embeds'][0]['title']} — {len(rep['embeds'])} embeds, "
                  f"{len(rep['files'])} pictures")
            continue
        r = post(token, s["channel_id"], rep, session=session)
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
    if failed:
        # One channel refusing is that server's business (the bot was removed,
        # the channel deleted) and is already on /reports status. EVERY post
        # failing is ours - a bad token, Discord refusing the app - and used to
        # end a green run with nobody receiving a report.
        print(f"::warning::{failed} Discord report post(s) failed; /reports status in that "
              f"server shows why.")
        if not posted:
            print("::error::Every report post failed. Check DISCORD_BOT_TOKEN and the app's access.")
            return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true", help="actually post (default is a dry run)")
    ap.add_argument("--allow-stale", action="store_true", help="post even when today's prices have not landed")
    ap.add_argument("--force-weekly", action="store_true",
                    help="post the weekly now to every weekly channel, even outside Monday morning")
    ap.add_argument("--preview", metavar="DIR", help="also write both reports (JSON + pictures) to DIR")
    args = ap.parse_args()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
