"""
test_discord_reports.py — offline guard for scripts/discord_reports.py.

    python scripts/test_discord_reports.py

No network: a fake Supabase, a fake Discord and a fake TCGplayer CDN. Pins the
ways the reporter could go wrong silently — posting twice, posting stale
movers, posting yesterday's numbers, calling a chase card a foil, ranking a
$6 Epic above a $2,839 Iconic, a card link that is not the affiliate link,
and a message Discord refuses for being too long — plus that it never pings
anyone and never prints the bot token.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import re
import sys
from contextlib import redirect_stdout
from types import SimpleNamespace

os.environ.setdefault("SUPABASE_URL", "http://stub")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import discord_reports as rep  # noqa: E402
import discord_report_art as art  # noqa: E402

FAILS = 0


def check(cond, msg):
    global FAILS
    if not cond:
        FAILS += 1
        print("FAIL", msg)


TODAY = dt.date(2026, 9, 28)      # a Monday
UTC = dt.timezone.utc


def at(day, hour, minute=0):
    return dt.datetime.combine(day, dt.time(hour, minute), tzinfo=UTC)


EVENING = at(TODAY, 21, 20)       # when the report is meant to go out


def mover(cid, name, version, rarity, printing, pid, price, p1, p7, set_id="s_fab"):
    return {"card_id": cid, "name": name, "version": version, "rarity": rarity, "set_id": set_id,
            "printing": printing, "tcgplayer_product_id": pid, "market_today": price,
            "mkt_pct_1d": p1, "mkt_pct_7d": p7}


MOVERS = [
    # chase: an Iconic up $145 on +5.4% must lead a $6 Epic down 18%
    mover("c_minnie", "Minnie Mouse", "Sweetheart Princess", "Iconic", "Holofoil", 11, 2838.89, 1.0, 5.4),
    mover("c_buzz", "Buzz Lightyear", "Space Ranger", "Epic", "Holofoil", 12, 6.86, -18.0, -18.0),
    mover("c_eeyore", "Eeyore", "In the Way", "Enchanted", "Holofoil", 13, 613.15, -2.0, -6.4),
    # base: big % on a real card; a $4 card and a 50-cent move stay out
    mover("b_max", "Max Goof", "Chart Topper", "Legendary", "Normal", 21, 22.17, 7.8, 148.3),
    # $4.49 moving $1.92 clears the dollar floor, so only the PRICE floor keeps it out
    mover("b_cheap", "Cheap", "Card", "Rare", "Normal", 22, 4.49, -30.0, -26.8),
    mover("b_small", "Small", "Move", "Super Rare", "Normal", 23, 8.36, -4.7, -4.7),
    mover("b_elinor", "Elinor", "Renowned Diplomat", "Super Rare", "Normal", 24, 8.28, -10.0, -25.3),
    mover("b_cin", "Cinderella", "Dream Come True", "Legendary", "Normal", 25, 24.65, 1.0, 67.2),
    mover("b_dumbo", "Dumbo", "Ninth Wonder of the Universe", "Legendary", "Normal", 26, 39.99, -1.0, -24.4),
    # promo: a Challenge (C1) card, two markets on one card_id
    mover("p_rap", "Rapunzel", "Gifted with Healing", "Promo", "Normal", 31, 125.87, -2.4, -2.4, set_id="s_c1"),
    mover("p_woody", "Woody", "Jungle Guide", "Promo", "Holofoil", 32, 70.78, -8.1, -19.7, set_id="s_p3"),
    # foil: a base-rarity foil, and a stale row whose price is not today's
    mover("f_trump", "Mickey Mouse", "Trumpeter", "Legendary", "Cold Foil", 41, 23.45, 9.7, 24.9),
    mover("f_stale", "Stale", "Two", "Rare", "Cold Foil", 42, 30.0, 90.0, 90.0),
]
STALE_PIDS = {42}
LOW_PIDS = {24}     # history well above today's price: "cheapest in 6 months"
SETS = [{"id": "s_fab", "name": "Fabled", "released_at": "2025-08-29"},
        {"id": "s_aotv", "name": "Attack of the Vine!", "released_at": "2026-07-19"},
        {"id": "s_c1", "name": "Challenge Promo", "released_at": "2024-05-01"},
        {"id": "s_p3", "name": "Promo Set 3", "released_at": "2025-01-01"}]


def index_rows(latest=TODAY):
    """all / chase / sealed / two mainline sets / rarities, 40 days, gently trending."""
    out = []
    for i in range(40):
        d = latest - dt.timedelta(days=39 - i)
        for scope, key, n, drift in (("all", "", 5860, 0.0005), ("chase", "", 324, -0.002),
                                     ("sealed", "", 162, 0.001), ("set", "s_fab", 452, 0.004),
                                     ("set", "s_aotv", 452, -0.005), ("rarity", "Epic", 90, -0.006),
                                     ("rarity", "Common", 1880, 0.001), ("rarity", "Legendary", 316, -0.002),
                                     ("set", "s_p3", 58, -0.02)):
            out.append({"scope": scope, "scope_key": key, "date": d.isoformat(),
                        "value": 100 * (1 + drift) ** i, "n_components": n})
    return out


class FakeSb:
    def __init__(self, subs, price_date=TODAY, table_missing=False, movers=None, index_latest=TODAY, latest=None):
        self.subs = subs
        self.latest = latest          # None: migration 175 not applied
        self.upserts = []
        self.url = "https://example.supabase.co"
        self.price_date = price_date
        self.table_missing = table_missing
        self.movers = MOVERS if movers is None else movers
        self.index = index_rows(index_latest) if index_latest else []
        self.updates = []

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        filters = filters or {}
        if table == rep.TABLE:
            if self.table_missing:
                raise RuntimeError("Select discord_report_subscriptions failed (404): relation does not exist")
            return [dict(s) for s in self.subs]
        if table == rep.LATEST_TABLE:
            if self.latest is None:
                raise RuntimeError("Select discord_report_latest failed (404): relation does not exist")
            return [dict(r) for r in self.latest]
        if table == "card_prices_latest":
            return [{"price_date": self.price_date.isoformat()}]
        if table == "sets":
            return [dict(s) for s in SETS]
        if table == "price_movers":
            pct = next(k for k in filters if k.startswith("mkt_pct_"))
            floor = float(filters[rep.digest.PRICE_COL].split(".", 1)[1])
            return [dict(m) for m in self.movers if m[pct] not in (None, 0) and m["market_today"] >= floor]
        if table == "prices_daily" and filters.get("date", "").startswith("eq."):
            return [{"tcgplayer_product_id": m["tcgplayer_product_id"], "printing": m["printing"],
                     "market_price": (m["market_today"] - 1 if m["tcgplayer_product_id"] in STALE_PIDS else m["market_today"])}
                    for m in self.movers]
        if table == "prices_daily":      # history: a year of prices, today's at the end
            out = []
            for m in self.movers:
                for i in range(200):
                    d = self.price_date - dt.timedelta(days=199 - i)
                    if i == 199:
                        v = m["market_today"]
                    elif m["tcgplayer_product_id"] in LOW_PIDS:
                        v = m["market_today"] * 1.3
                    else:
                        v = m["market_today"] * (0.9 + 0.2 * ((i * 7) % 13) / 13)
                    out.append({"tcgplayer_product_id": m["tcgplayer_product_id"], "printing": m["printing"],
                                "date": d.isoformat(), "market_price": v})
            return out
        if table == "market_index_daily":
            rows = self.index
            if filters.get("scope", "").startswith("eq."):
                sc = filters["scope"][3:]
                key = filters.get("scope_key", "eq.")[3:]
                rows = [r for r in rows if r["scope"] == sc and r["scope_key"] == key]
            since = filters.get("date", "gte.0000-00-00")[4:]
            return [dict(r) for r in rows if r["date"] >= since]
        return []

    def update(self, table, match, patch, params=None):
        self.updates.append((table, dict(match), dict(patch)))

    def upsert(self, table, rows, on_conflict=None, batch=100):
        self.upserts.append((table, [dict(r) for r in rows], on_conflict))

    def auth_headers(self):
        return {"apikey": "service", "Authorization": "Bearer service"}


def tiny_jpeg():
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (72, 100), (200, 120, 60)).save(buf, format="JPEG")
    return buf.getvalue()


JPEG = tiny_jpeg()


class FakeCdn:
    """What discord_report_art fetches card art from."""
    def __init__(self, ok=True):
        self.ok = ok

    def get(self, url, timeout=None):
        return SimpleNamespace(status_code=200 if self.ok else 404, content=JPEG if self.ok else b"")


class FakeDiscord(FakeCdn):
    def __init__(self, status=200, refuse_files=False):
        super().__init__()
        self.status = status
        self.refuse_files = refuse_files
        self.posts = []

    def post(self, url, headers=None, json=None, data=None, files=None, timeout=None):
        body = json if json is not None else __import__("json").loads(data["payload_json"])
        self.posts.append({"url": url, "headers": headers, "json": body, "files": files})
        status = 400 if (files and self.refuse_files) else self.status
        return SimpleNamespace(status_code=status, text="{}")


class FakeStorage(FakeDiscord):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail
        self.stored, self.deleted = [], []

    def post(self, url, headers=None, json=None, data=None, files=None, timeout=None):
        if "/storage/v1/object/" in url:
            self.stored.append(url)
            return SimpleNamespace(status_code=500 if self.fail else 200, ok=not self.fail, text="{}")
        return super().post(url, headers=headers, json=json, data=data, files=files, timeout=timeout)

    def delete(self, url, headers=None, json=None, timeout=None):
        self.deleted.append((url, json))
        return SimpleNamespace(status_code=200, ok=True, text="{}")


def args(**kw):
    base = dict(post=True, allow_stale=False, force_weekly=False, preview=None)
    base.update(kw)
    return SimpleNamespace(**base)


def run(sb, disc, now=EVENING, **kw):
    out = io.StringIO()
    with redirect_stdout(out):
        code = rep.run(args(**kw), sb=sb, session=disc, now=now)
    return code, out.getvalue()


def all_text(embeds):
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in embeds)


os.environ["DISCORD_BOT_TOKEN"] = "secret-bot-token-value"

# ── 1. posts once to a daily + a weekly subscriber, stale row dropped, nobody pinged ──
sb = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None},
             {"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}])
disc = FakeDiscord()
code, out = run(sb, disc)
check(code == 0, "exit 0")
check(len(disc.posts) == 2, f"two posts ({len(disc.posts)})")
daily = next((p for p in disc.posts if p["url"].endswith("/channels/c1/messages")), {})
weekly = next((p for p in disc.posts if p["url"].endswith("/channels/c2/messages")), {})
dtext, wtext = all_text(daily.get("json", {}).get("embeds", [])), all_text(weekly.get("json", {}).get("embeds", []))
check("Stale" not in dtext and "Stale" not in wtext, "the stale mover is dropped")
check(all(p["json"].get("allowed_mentions") == {"parse": []} for p in disc.posts), "posts never ping anyone")
check("secret-bot-token-value" not in out, "the bot token is never printed")
check(sum(1 for u in sb.updates if u[2].get("last_posted_on") == TODAY.isoformat()) == 2, "last_posted_on recorded")

# ── 2. the sections ──
d_emb = daily["json"]["embeds"]
authors = [(e.get("author") or {}).get("name", "") for e in d_emb]
check(d_emb[0]["title"] == "Lorcana movers · Mon, Sep 28, 2026", f"daily title ({d_emb[0]['title']})")
check([a.split(" ·")[0] for a in authors[1:]] == ["✦ CHASE", "◆ BASE CARDS", "★ PROMOS", "✧ FOILS"],
      f"daily sections in order ({authors})")
chase = d_emb[1]["description"]
check(chase.index("Minnie Mouse") < chase.index("Eeyore"), "chase ranks by DOLLARS, not percent")
check("Buzz Lightyear" not in chase, "a $6.86 Epic is under the chase floor")
base = d_emb[2]["description"]
check("Max Goof" in base and "Cheap" not in base, "a $4.49 card is under the base floor")
check("Cheap" not in wtext, "the price floor holds on the weekly too")
check("Small" not in base, "a 39-cent move is under the base floor")
check("(foil)" not in dtext and "(foil)" not in wtext, "nothing is labelled (foil) — a chase card is one printing")
check("Rapunzel — Gifted with Healing (Prize Wall)" in dtext, "a C1 card says which of its two markets it is")
check("-#" not in dtext and "-#" not in wtext, "no -# small text inside an embed")

# ── 3. every card link is the affiliate link, and the footer says so ──
for label, text in (("daily", dtext), ("weekly", wtext)):
    links = re.findall(r"\]\((https?://[^)]+)\)", text)
    check(links, f"{label} links its cards")
    check(all(u.startswith(rep.TCG_AFFILIATE_BASE + "?u=") for u in links), f"{label}: every card link is the affiliate link")
foot = d_emb[-1].get("footer", {}).get("text", "")
check(rep.AFFILIATE_NOTE in foot and "/reports" in foot, f"the footer carries the disclosure and names /reports ({foot})")
check(rep.tcg_url(649228, "Cold Foil") == rep.TCG_AFFILIATE_BASE + "?u=https%3A%2F%2Fwww.tcgplayer.com%2Fproduct%2F649228%2F%3FLanguage%3DEnglish%26Printing%3DCold%2520Foil",
      "tcg_url matches the site's encodeURIComponent form")
check(rep.tcg_url(649228, "Normal").endswith("%3FLanguage%3DEnglish"), "a Normal printing carries no Printing param")

# ── 4. the weekly: pulse, pictures, worth a look ──
w_emb = weekly["json"]["embeds"]
check(w_emb[0]["title"] == "Lorcana week in review · Sep 22–28, 2026", f"weekly title ({w_emb[0]['title']})")
fields = [f["name"] for f in w_emb[0].get("fields", [])]
check(fields[:3] == ["Whole market", "Chase cards", "Sealed"], f"weekly header carries the market pulse ({fields})")
check("🔥 Hottest set" in fields and "Fabled" in json.dumps(w_emb[0], ensure_ascii=False), "the hottest set is named")
check("Promo Set 3" not in json.dumps(w_emb[0].get("fields"), ensure_ascii=False), "a promo set is not a 'set' in the pulse")
imgs = [((e.get("image") or {}).get("url")) for e in w_emb]
check("attachment://market.png" in imgs and "attachment://chase.png" in imgs and "attachment://base.png" in imgs,
      f"the weekly attaches its three pictures ({imgs})")
sent = list((weekly.get("files") or {}).values())
check(sorted(v[0] for v in sent) == ["base.png", "chase.png", "market.png"], f"the three pictures are sent ({[v[0] for v in sent]})")
check(sent and all(v[1][:8] == b"\x89PNG\r\n\x1a\n" for v in sent), "the pictures are PNGs")
worth = next((e for e in w_emb if (e.get("author") or {}).get("name", "").startswith("💡")), None)
check(worth is not None and "Elinor" in worth["description"], "a faller at a multi-month low is Worth a look")
check(worth and w_emb.index(worth) == 3, "Worth a look sits after the base cards")
check(worth and "**−" in worth["description"] and "%" in worth["description"].split("\n")[0],
      "a base card in Worth a look leads with its percent")
check(sum(rep.embed_chars(e) for e in w_emb) <= 6000, "the weekly fits Discord's 6000-character cap")

# ── 5. Discord refuses the pictures -> the words still go out ──
sb5 = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}])
disc5 = FakeDiscord(refuse_files=True)
run(sb5, disc5)
check(len(disc5.posts) == 2, f"a refused multipart post is re-sent once ({len(disc5.posts)})")
plain = disc5.posts[-1] if disc5.posts else {}
check(not plain.get("files") and "attachment://" not in all_text(plain.get("json", {}).get("embeds", [])),
      "the re-send carries no attachment references")
check(any(u[2].get("last_posted_on") for u in sb5.updates), "the text-only re-send counts as posted")

# ── 6. no pictures when the art cannot be fetched, and no crash ──
strip = art.card_strip([{"pid": 1, "name": "A", "version": "B", "price": 10, "pct": 5, "usd": 0.5, "spark": []}] * 4,
                       "pct", session=FakeCdn(ok=False))
check(strip is None, "a strip with no art is skipped, not drawn empty")
check(art.market_chart([("x", [(TODAY, 0.0)], art.GOLD)], "t", "s") is None, "a chart with one series is skipped")

# ── 7. a stale market index -> no pulse, not yesterday's market as today's ──
sb7 = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}],
             index_latest=TODAY - dt.timedelta(days=1))
disc7 = FakeDiscord()
run(sb7, disc7)
h7 = disc7.posts[0]["json"]["embeds"][0] if disc7.posts else {}
check(not h7.get("fields") and "attachment://market.png" not in json.dumps(h7), "a stale index adds no pulse and no chart")
check("biggest moves" in h7.get("description", ""), "the header still says what it is")

# ── 8. fitting: trims the LAST sections, keeps the header ──
big = [{"title": "H", "description": "x" * 100, "_keep": True}] + [
    {"author": {"name": f"S{i}"}, "description": "\n".join(["y" * 290] * 5), "_lines": ["y" * 290] * 5}
    for i in range(5)]
big[-1]["footer"] = {"text": "foot"}
fit = rep.fit_embeds(big)
check(sum(rep.embed_chars(e) for e in fit) <= rep.EMBED_TOTAL_LIMIT, "fit_embeds gets under the cap")
check(fit[0]["description"] == "x" * 100, "the header is never trimmed")
check(fit[1]["_lines"] == big[1]["_lines"], "the first section is trimmed last")
check((fit[-1].get("footer") or {}).get("text") == "foot", "the footer survives trimming")
# ...and build_report really applies it: squeeze the cap and build a weekly
saved = rep.EMBED_TOTAL_LIMIT
rep.EMBED_TOTAL_LIMIT = 2600
with redirect_stdout(io.StringIO()):
    squeezed = rep.build_report(FakeSb([]), TODAY, "7d", session=FakeCdn())
rep.EMBED_TOTAL_LIMIT = saved
check(squeezed and sum(rep.embed_chars(e) for e in squeezed["embeds"]) <= 2600, "build_report fits the report under the cap")
check(squeezed and squeezed["embeds"][0]["title"].startswith("Lorcana week in review"), "the squeezed report keeps its header")
check(squeezed and rep.AFFILIATE_NOTE in (squeezed["embeds"][-1].get("footer") or {}).get("text", ""),
      "the squeezed report keeps its disclosure footer")

# ── 9. pure pieces ──
check(rep.bucket_of({"rarity": "Epic", "printing": "Holofoil"}) == "chase", "an Epic is chase")
check(rep.bucket_of({"rarity": "Promo", "printing": "Holofoil"}) == "promo", "a promo is a promo")
check(rep.bucket_of({"rarity": "Legendary", "printing": "Cold Foil"}) == "foil", "a base-rarity foil is a foil")
check(rep.bucket_of({"rarity": "Legendary", "printing": "Normal"}) == "base", "a non-foil is a base card")
check(abs(rep.dollar_move(110, 10) - 10.0) < 1e-9 and rep.dollar_move(5, -100) is None, "dollar_move")
check(rep.short_standing(("low", "cheapest in 6 months")) == "6-mo low", "short standing, low")
check(rep.short_standing(("high", "near its 12-month high")) == "near 12-mo high", "short standing, high")
series = {TODAY - dt.timedelta(days=i): 100 + i for i in range(10)}
check(abs(rep.index_change(series, TODAY, 7) - (100 / 107 - 1) * 100) < 1e-9, "index_change")
check(rep.index_change(series, TODAY, 30) is None, "index_change with no prior value")

# ── 10. the site's constants, read back out of Index.html ──
html = (HERE.parent / "Index.html").read_text(encoding="utf-8")
m = re.search(r'const TCG_AFFILIATE_BASE = "([^"]+)"', html)
check(m and m.group(1) == rep.TCG_AFFILIATE_BASE, "TCG_AFFILIATE_BASE matches Index.html")
tcg = html[html.index("const tcgUrl"):html.index("const tcgUrl") + 400]
check("https://www.tcgplayer.com/product/${productId}/?Language=English" in tcg
      and '"&Printing=" + encodeURIComponent(printing)' in tcg and 'printing !== "Normal"' in tcg,
      "tcgUrl in Index.html still builds the link tcg_url copies")
block = html[html.index("const SET_DISPLAY_NAMES"):html.index("};", html.index("const SET_DISPLAY_NAMES"))]
site = dict(re.findall(r'"([^"]+)":\s*"([^"]+)"', block))
check(site == rep.SET_DISPLAY_NAMES, f"SET_DISPLAY_NAMES matches Index.html ({site})")
check(rep.digest.PRICE_COL == "market_today", "reports read NM Market, never Low")

# ── 11. the old delivery rules, unchanged ──
sb2 = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": TODAY.isoformat()}])
disc2 = FakeDiscord()
run(sb2, disc2)
check(not disc2.posts, "a channel that already has today's report is skipped")

tue = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}], price_date=TODAY + dt.timedelta(days=1),
             index_latest=TODAY + dt.timedelta(days=1))
disc3 = FakeDiscord()
with redirect_stdout(io.StringIO()):
    rep.run(args(), sb=tue, session=disc3, now=at(TODAY + dt.timedelta(days=1), 21, 20))
check(not disc3.posts, "weekly reports wait for Monday")
with redirect_stdout(io.StringIO()):
    rep.run(args(force_weekly=True), sb=tue, session=disc3, now=at(TODAY + dt.timedelta(days=1), 21, 20))
check(len(disc3.posts) == 1, "--force-weekly posts the weekly report")

old = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}], price_date=TODAY - dt.timedelta(days=1))
disc4 = FakeDiscord()
run(old, disc4)
check(not disc4.posts, "yesterday's prices never post as today's")

# A run that slips past midnight UTC still owes the day's report (the 2026-09-28
# lesson), dated the price date; by noon it is too late; and never twice.
late = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None},
               {"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}])
disc_late = FakeDiscord()
run(late, disc_late, now=at(TODAY + dt.timedelta(days=1), 1, 45))
check(len(disc_late.posts) == 2, f"a run after midnight still sends the day's daily and weekly reports ({len(disc_late.posts)})")
check(all(u[2].get("last_posted_on") == TODAY.isoformat() for u in late.updates if "last_posted_on" in u[2]),
      "a late post records the price date it covers, not the day it was sent")
check("Sep 28, 2026" in all_text(disc_late.posts[0]["json"]["embeds"]) if disc_late.posts else False,
      "a late report says which day it covers")
stale = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}])
disc_stale = FakeDiscord()
run(stale, disc_stale, now=at(TODAY + dt.timedelta(days=1), 12, 0))
check(not disc_stale.posts, "a report more than half a day old is not sent")
again = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": TODAY.isoformat()}])
disc_again = FakeDiscord()
run(again, disc_again, now=at(TODAY + dt.timedelta(days=1), 1, 45))
check(not disc_again.posts, "a late run never re-sends a report the channel already has")

code5, out5 = run(FakeSb([], table_missing=True), FakeDiscord())
check(code5 == 0 and "migration 173" in out5, "missing table is a clean exit 0")
os.environ["DISCORD_BOT_TOKEN"] = ""
disc6 = FakeDiscord()
code6, _ = run(FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}]), disc6)
check(code6 == 0 and not disc6.posts, "no token is a clean exit 0")
os.environ["DISCORD_BOT_TOKEN"] = "secret-bot-token-value"

sb8 = FakeSb([{"guild_id": "g", "channel_id": "c9", "cadence": "daily", "last_posted_on": None}])
run(sb8, FakeDiscord(status=403))
errs = [u for u in sb8.updates if u[2].get("last_error")]
check(errs and "can't post" in errs[0][2]["last_error"], "a 403 is recorded in last_error")
check(not any(u[2].get("last_posted_on") for u in sb8.updates), "a failed post is not marked posted")

sb9 = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}])
disc9 = FakeDiscord()
_, out9 = run(sb9, disc9, post=False)
check(not disc9.posts and "DRY RUN" in out9, "a dry run posts nothing")

# ── /reports send: the latest report is kept, with its pictures stored ──
yesterday = (TODAY - dt.timedelta(days=1)).isoformat()
sb10 = FakeSb([], latest=[{"cadence": "daily", "price_date": yesterday, "files": []},
                          {"cadence": "weekly", "price_date": yesterday, "files": ["weekly/%s/market.png" % yesterday]}])
st10 = FakeStorage()
code10, out10 = run(sb10, st10)
check(code10 == 0 and "No servers have asked" in out10, "no subscribers still exits 0")
kept = {rows[0]["cadence"]: rows[0] for (t, rows, oc) in sb10.upserts if t == rep.LATEST_TABLE}
check(set(kept) == {"daily", "weekly"} and all(r["price_date"] == TODAY.isoformat() for r in kept.values()),
      f"both reports are kept for /reports send even with no subscribers ({sorted(kept)})")
check(all((t, oc) == (rep.LATEST_TABLE, "cadence") for (t, _, oc) in sb10.upserts), "kept one row per cadence")
wk = kept.get("weekly", {})
pics = [(e.get("image") or {}).get("url", "") for e in wk.get("embeds", [])]
check(wk.get("files") and all(u.startswith("https://example.supabase.co/storage/v1/object/public/discord-reports/weekly/" + TODAY.isoformat() + "/") for u in pics if u),
      f"the weekly report's pictures point at their stored, dated copies ({[u for u in pics if u][:2]})")
check(not any(u.startswith("attachment://") for e in wk.get("embeds", []) for u in [(e.get("image") or {}).get("url", ""), (e.get("thumbnail") or {}).get("url", "")]),
      "a kept report has no attachment:// left in it")
check(st10.deleted and st10.deleted[0][1] == {"prefixes": ["weekly/%s/market.png" % yesterday]}, "yesterday's pictures are deleted once today's are kept")
check(not st10.posts, "keeping a report posts nothing to Discord")

sb11 = FakeSb([], latest=[{"cadence": "daily", "price_date": TODAY.isoformat(), "files": []},
                          {"cadence": "weekly", "price_date": TODAY.isoformat(), "files": []}])
run(sb11, FakeStorage())
check(not sb11.upserts, "a report already kept today is not built or kept again")

sb12 = FakeSb([], latest=[])
st12 = FakeStorage(fail=True)
run(sb12, st12)
wk12 = next((rows[0] for (t, rows, oc) in sb12.upserts if t == rep.LATEST_TABLE and rows[0]["cadence"] == "weekly"), {})
check(wk12 and not any((e.get("image") or {}).get("url", "") for e in wk12["embeds"]) and wk12["files"] == [],
      "if a picture can't be stored, the kept report is the plain one (no broken picture)")

sb13 = FakeSb([], latest=[])
run(sb13, FakeStorage(), post=False)
check(not sb13.upserts, "a dry run keeps nothing")

_, out14 = run(FakeSb([]), FakeStorage())
check("migration 175" in out14, "before migration 175 it says so and carries on")

print("FAILS:", FAILS)
sys.exit(1 if FAILS else 0)
