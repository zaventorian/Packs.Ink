"""
discord_digest.py — the daily Lorcana movers digest, posted to Discord.

    python scripts/discord_digest.py               # dry run, prints the embed
    python scripts/discord_digest.py --post        # actually posts
    python scripts/discord_digest.py --window 7d --post

WHY THIS SHAPE, and not a restock feed:

The restock-alert accounts (TrackaLacker's @LorcanaRestocks and friends) already
own "this is in stock at Walmart for $6.00". They have native apps, push, a paid
priority queue and 150k users; competing on speed of that alert is a losing
game and we have no push infrastructure at all.

What none of them can say is whether $6.00 is a good price. We have daily prices
back to 2024-02-08. So this digest is NOT "today's top movers" — a bare mover
list is a commodity too. It leads with the JUDGEMENT:

  * "Worth a look" — cards that fell AND are now sitting at a multi-month low.
    A faller that is merely off its high is noise; a faller at the bottom of its
    own year is the actual opportunity, and it is the one line in this post that
    nobody else in the space can write.
  * "Heating up" — the risers, with a caution when one is near its 12-month high.

⚠ THE STANDING MATHS MUST MATCH THE SITE. `priceStanding` in Index.html renders
the same claim next to a buy button; two implementations of "is this a good
price" that disagree destroys the only thing the claim has going for it. The
constants below are the same numbers, and `test_discord_digest.py` reads them
back OUT of Index.html and fails if they have drifted apart. Same reasoning as
buildCustomIndex vs migration 130.

Operationally:

  * DRY RUN BY DEFAULT. Posting is public and irreversible; `--post` is the
    deliberate act. Same asymmetry as flag_intentional_draws.py.
  * NO WEBHOOK CONFIGURED IS A CLEAN EXIT 0, not a failure — the workflow stays
    green on a fork or before the secret is set.
  * ⚠ FRESHNESS GATE, and it is what makes duplicate posts impossible. The ETL
    fires up to three times a day (20:30 / 22:30 / 01:00 retries). This refuses
    to post unless the newest price date IS today, so a retry cannot re-post
    yesterday's digest, and a day the ETL never landed produces silence rather
    than a stale digest presented as today's. That is why it also lives in its
    own workflow on ONE cron rather than chaining off the prices job.
  * The webhook URL is never logged. It is a bearer credential in a URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import requests

from supabase_client import Supabase

SITE = "https://packs.ink"

# ── Standing: mirrors priceStanding() in Index.html. Do not retune one alone. ──
STANDING_WINDOWS = [(365, "12-month", "12 months"),
                    (180, "6-month", "6 months"),
                    (90, "3-month", "3 months")]
STANDING_MIN_POINTS = 30
STANDING_MIN_SPAN_RATIO = 0.8
STANDING_MIN_SPREAD = 1.15
STANDING_LOW = 0.10
STANDING_NEAR_LOW = 0.25
STANDING_HIGH = 0.90

WINDOWS = {"1d": "1D", "7d": "1W", "30d": "1M", "90d": "3M"}
# Market, not Low. Low is a published aggregate a single listing can move, and a
# digest that cries "cheapest ever" off a phantom is worse than no digest.
PRICE_COL = "market_today"
PCT_PREFIX = "mkt_pct_"
MIN_PRICE = 5.0          # matches the Screener's default floor
MOVERS_PER_SIDE = 12
HISTORY_DAYS = 400       # a little past 365 so the 12-month window is coverable


def price_standing(points):
    """points: [(date, value)] ascending. Returns (tone, label) or None.

    Mirrors priceStanding() in Index.html exactly — see the module docstring.
    """
    pts = [(d, float(v)) for d, v in points if v is not None and float(v) > 0]
    if len(pts) < STANDING_MIN_POINTS:
        return None
    last_d, last_v = pts[-1]
    for days, adj, noun in STANDING_WINDOWS:
        cutoff = last_d - dt.timedelta(days=days)
        win = [p for p in pts if p[0] >= cutoff]
        if len(win) < STANDING_MIN_POINTS:
            continue
        span = (win[-1][0] - win[0][0]).days
        if span < days * STANDING_MIN_SPAN_RATIO:
            continue
        lo = min(v for _, v in win)
        hi = max(v for _, v in win)
        if lo <= 0 or hi / lo < STANDING_MIN_SPREAD:
            continue
        pct = sum(1 for _, v in win if v <= last_v) / len(win)
        if pct <= STANDING_LOW:
            return ("low", f"cheapest in {noun}")
        if pct <= STANDING_NEAR_LOW:
            return ("near-low", f"near its {adj} low")
        if pct >= STANDING_HIGH:
            return ("high", f"near its {adj} high")
        return None
    return None


def latest_price_date(sb):
    rows = sb.select("card_prices_latest", columns="price_date",
                     order="price_date.desc", limit=1)
    if not rows:
        return None
    return dt.date.fromisoformat(str(rows[0]["price_date"])[:10])


def fetch_movers(sb, window, direction, limit):
    pct = PCT_PREFIX + window
    cols = ("card_id,name,version,rarity,set_id,printing,tcgplayer_product_id,"
            f"{PRICE_COL},{pct}")
    rows = sb.select(
        "price_movers",
        columns=cols,
        filters={pct: "gt.0" if direction == "up" else "lt.0",
                 PRICE_COL: f"gte.{MIN_PRICE}"},
        order=f"{pct}.{'desc' if direction == 'up' else 'asc'}",
        limit=limit,
    )
    return [r for r in rows if r.get(pct) is not None]


def fetch_history(sb, pids, since):
    """market_price history for a pid list, bucketed by (pid, printing)."""
    if not pids:
        return {}
    ids = ",".join(str(p) for p in sorted(set(pids)))
    rows = sb.select(
        "prices_daily",
        columns="tcgplayer_product_id,printing,date,market_price",
        filters={"tcgplayer_product_id": f"in.({ids})", "date": f"gte.{since}"},
        order="tcgplayer_product_id.asc,date.asc",
    )
    out: dict[tuple, list] = {}
    for r in rows:
        if r.get("market_price") is None:
            continue
        key = (r["tcgplayer_product_id"], r.get("printing") or "Normal")
        out.setdefault(key, []).append(
            (dt.date.fromisoformat(str(r["date"])[:10]), r["market_price"]))
    for v in out.values():
        v.sort(key=lambda p: p[0])
    return out


def card_url(card_id):
    return f"{SITE}/cards?card={requests.utils.quote(str(card_id), safe='')}"


def fmt_price(v):
    if v is None:
        return "—"
    v = float(v)
    return f"${v:,.0f}" if v >= 1000 else f"${v:.2f}"


def fmt_pct(p):
    p = float(p)
    return f"{'+' if p > 0 else ''}{p:.1f}%"


def line(row, window, standing):
    """One digest line. Discord markdown; the name is the link."""
    pct = row[PCT_PREFIX + window]
    name = row.get("name") or "Unknown"
    ver = row.get("version")
    title = f"{name} — {ver}" if ver else name
    finish = row.get("printing")
    tag = " *(foil)*" if finish and finish not in ("Normal", "Non-Foil") else ""
    bit = f" · **{standing[1]}**" if standing else ""
    return (f"[{title}]({card_url(row['card_id'])}){tag} · "
            f"{fmt_price(row.get(PRICE_COL))} · {fmt_pct(pct)}{bit}")


def build_embed(price_date, window, risers, fallers, standings):
    win_label = WINDOWS.get(window, window.upper())

    def standing_of(r):
        return standings.get((r.get("tcgplayer_product_id"),
                              r.get("printing") or "Normal"))

    # The lead section: fell AND is now at the bottom of its own range. This is
    # the line nobody else in the space can write, so it goes first and it is
    # the only one allowed to be empty without the post looking broken.
    worth = [r for r in fallers if (standing_of(r) or ("", ""))[0] in ("low", "near-low")]
    fields = []
    if worth:
        fields.append({
            "name": f"💡 Worth a look — fell on {win_label}, and now at a multi-month low",
            "value": "\n".join(line(r, window, standing_of(r)) for r in worth[:6])[:1024],
            "inline": False,
        })
    if risers:
        fields.append({
            "name": f"📈 Heating up — {win_label}",
            "value": "\n".join(line(r, window, standing_of(r)) for r in risers[:6])[:1024],
            "inline": False,
        })
    if fallers and not worth:
        fields.append({
            "name": f"📉 Falling — {win_label}",
            "value": "\n".join(line(r, window, standing_of(r)) for r in fallers[:6])[:1024],
            "inline": False,
        })
    return {
        # .day, not %-d: the no-padding flag is glibc-only and raises on Windows.
        "title": f"Lorcana movers — {price_date:%b} {price_date.day}, {price_date:%Y}",
        "url": f"{SITE}/screener",
        "description": (
            "Percent moves are NM Market. **Bold** notes say where today's price sits "
            "against that card's own history — that is the part that says whether a "
            "move is worth acting on."),
        "color": 0xC9A227,
        "fields": fields,
        "footer": {"text": "packs.ink · prices via TCGCSV · not financial advice"},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--post", action="store_true",
                    help="actually send it (default is a dry run)")
    ap.add_argument("--window", default="1d", choices=sorted(WINDOWS),
                    help="mover window (default 1d)")
    ap.add_argument("--allow-stale", action="store_true",
                    help="post even when the newest price date is not today")
    args = ap.parse_args()

    # Every sibling ETL script loads scripts/.env, and supabase_client's own
    # "missing SUPABASE_URL" message tells you to fill that file in — which only
    # helps if something reads it. Guarded because this is the one script meant
    # to be run by hand from a bare checkout, and in CI the values come from
    # secrets rather than a file.
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    webhook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if args.post and not webhook:
        print("No DISCORD_WEBHOOK_URL set — nothing to post. Exiting 0.")
        return 0

    sb = Supabase()
    price_date = latest_price_date(sb)
    if not price_date:
        print("No price date available; refusing to post.")
        return 0
    today = dt.datetime.now(dt.timezone.utc).date()
    if price_date != today and not args.allow_stale:
        print(f"Newest price date is {price_date}, not {today} — "
              "the ETL has not landed yet. Skipping (use --allow-stale to override).")
        return 0

    risers = fetch_movers(sb, args.window, "up", MOVERS_PER_SIDE)
    fallers = fetch_movers(sb, args.window, "down", MOVERS_PER_SIDE)
    if not risers and not fallers:
        print("No movers cleared the filters; nothing to say. Exiting 0.")
        return 0

    since = (price_date - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    pids = [r["tcgplayer_product_id"] for r in risers + fallers
            if r.get("tcgplayer_product_id")]
    hist = fetch_history(sb, pids, since)
    standings = {}
    for key, pts in hist.items():
        st = price_standing(pts)
        if st:
            standings[key] = st

    embed = build_embed(price_date, args.window, risers, fallers, standings)
    if not embed["fields"]:
        print("Nothing worth posting. Exiting 0.")
        return 0

    if not args.post:
        print("DRY RUN — would post:\n")
        print(embed["title"])
        for f in embed["fields"]:
            print("\n" + f["name"])
            print(f["value"])
        print(f"\n({len(standings)} of {len(hist)} tracked prices had a standing "
              f"worth stating)")
        return 0

    r = requests.post(webhook, json={"embeds": [embed]}, timeout=30)
    if r.status_code >= 300:
        # Never echo the URL — it is a bearer credential.
        print(f"Discord rejected the post: HTTP {r.status_code} {r.text[:300]}")
        return 1
    print(f"Posted the {price_date} digest ({len(embed['fields'])} sections).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
