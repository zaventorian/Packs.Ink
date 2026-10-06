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


EVENING = at(TODAY, 21, 20)       # when the daily is meant to go out
MORNING = at(TODAY, 14, 5)        # 9:05 AM Chicago (CDT): the weekly's slot


def mover(cid, name, version, rarity, printing, pid, price, p1, p7, set_id="s_fab"):
    return {"card_id": cid, "name": name, "version": version, "rarity": rarity, "set_id": set_id,
            "printing": printing, "tcgplayer_product_id": pid, "low_today": price,
            "pct_1d": p1, "pct_7d": p7}


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
    def __init__(self, subs, price_date=TODAY, table_missing=False, movers=None, index_latest=TODAY, latest=None,
                 ebay=None):
        self.subs = subs
        self.ebay = ebay or {}        # {"roll": [...], "cards": [...], "sales": [...]}
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
        if table == "raw_sales_rollup":
            return [dict(r) for r in self.ebay.get("roll", [])]
        if table == "cards":
            return [dict(r) for r in self.ebay.get("cards", [])]
        if table == "raw_sales":
            return [dict(r) for r in self.ebay.get("sales", [])]
        if table == "price_movers" and "card_id" in filters:
            ids = set(re.findall(r'"([^"]+)"', filters["card_id"]))
            return [dict(m) for m in self.movers if m["card_id"] in ids]
        if table == "price_movers":
            pct = next(k for k in filters if k.startswith("pct_"))
            floor = float(filters[rep.REPORT_PRICE_COL].split(".", 1)[1])
            return [dict(m) for m in self.movers if m[pct] not in (None, 0) and m["low_today"] >= floor]
        if table == "prices_daily" and filters.get("date", "").startswith("eq."):
            return [{"tcgplayer_product_id": m["tcgplayer_product_id"], "printing": m["printing"],
                     "low_price": (m["low_today"] - 1 if m["tcgplayer_product_id"] in STALE_PIDS else m["low_today"])}
                    for m in self.movers]
        if table == "prices_daily":      # history: a year of prices, today's at the end
            out = []
            for m in self.movers:
                for i in range(200):
                    d = self.price_date - dt.timedelta(days=199 - i)
                    if i == 199:
                        v = m["low_today"]
                    elif m["tcgplayer_product_id"] in LOW_PIDS:
                        v = m["low_today"] * 1.3
                    else:
                        v = m["low_today"] * (0.9 + 0.2 * ((i * 7) % 13) / 13)
                    out.append({"tcgplayer_product_id": m["tcgplayer_product_id"], "printing": m["printing"],
                                "date": d.isoformat(), "market_price": v, "low_price": v})
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
sb = FakeSb([{"guild_id": "g", "channel_id": "c1", "cadence": "daily", "last_posted_on": None}])
sbw = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": None}])
disc = FakeDiscord()
code, out = run(sb, disc)
codew, outw = run(sbw, disc, now=MORNING)
out += outw
check(code == 0 and codew == 0, "exit 0")
check(len(disc.posts) == 2, f"two posts ({len(disc.posts)})")
daily = next((p for p in disc.posts if p["url"].endswith("/channels/c1/messages")), {})
weekly = next((p for p in disc.posts if p["url"].endswith("/channels/c2/messages")), {})
dtext, wtext = all_text(daily.get("json", {}).get("embeds", [])), all_text(weekly.get("json", {}).get("embeds", []))
check("Stale" not in dtext and "Stale" not in wtext, "the stale mover is dropped")
check(all(p["json"].get("allowed_mentions") == {"parse": []} for p in disc.posts), "posts never ping anyone")
check("secret-bot-token-value" not in out, "the bot token is never printed")
check(sum(1 for u in sb.updates + sbw.updates if u[2].get("last_posted_on") == TODAY.isoformat()) == 2, "last_posted_on recorded")

# ── 2. the sections ──
d_emb = daily["json"]["embeds"]
authors = [(e.get("author") or {}).get("name", "") for e in d_emb]
check(d_emb[0]["title"] == "Lorcana movers · Mon, Sep 28, 2026", f"daily title ({d_emb[0]['title']})")
check([a.split(" ·")[0] for a in authors[1:]] == ["✦ CHASE", "◆ BASE CARDS", "★ PROMOS", "✧ FOILS"],
      f"daily sections in order ({authors})")
chase = d_emb[1]["description"]
check(chase.index("Eeyore") < chase.index("Minnie Mouse"), "chase ranks by PERCENT, not dollars")
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
    # The calendar section links to the site's own calendar; everything else is a card.
    cal = rep.digest.SITE + "/calendar"
    check(all(u.startswith(rep.TCG_AFFILIATE_BASE + "?u=") or u.startswith(cal) for u in links),
          f"{label}: every card link is the affiliate link")
    check(not any("tcgplayer.com" in u and not u.startswith(rep.TCG_AFFILIATE_BASE) for u in links),
          f"{label}: no bare TCGplayer link")
foot = d_emb[-1].get("footer", {}).get("text", "")
check(foot == "packs.ink · /reports", f"the footer is just the brand and /reports ({foot})")
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
run(sb5, disc5, now=MORNING)
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
run(sb7, disc7, now=MORNING)
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
check(squeezed and "/reports" in (squeezed["embeds"][-1].get("footer") or {}).get("text", ""),
      "the squeezed report keeps its footer")

# ── 9. pure pieces ──
check(rep.bucket_of({"rarity": "Epic", "printing": "Holofoil"}) == "chase", "an Epic is chase")
check(rep.bucket_of({"rarity": "Promo", "printing": "Holofoil"}) == "promo", "a promo is a promo")
check(rep.bucket_of({"rarity": "Legendary", "printing": "Cold Foil"}) == "foil", "a base-rarity foil is a foil")
check(rep.bucket_of({"rarity": "Legendary", "printing": "Normal"}) == "base", "a non-foil is a base card")
check(rep.bucket_of({"rarity": "Quest", "printing": "Normal"}) is None, "an Illumineer's Quest card is in no section")
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
# A card that started the window under the floor is not news, however far it
# climbed (the home banners' rule): $0.50 -> $6.00 is "+1100%" off one listing.
cheap = {"rarity": "Super Rare", "printing": "Normal", "pct": 1100.0, "price": 6.0,
         "usd": rep.dollar_move(6.0, 1100.0)}
check(not rep.qualifies(cheap, "base"), "a card that started under the floor never qualifies")
check(rep.qualifies({**cheap, "pct": 20.0, "usd": rep.dollar_move(6.0, 20.0)}, "base"),
      "a card above the floor at both ends does")
check(rep.REPORT_PRICE_COL == "low_today" and rep.REPORT_PCT_PREFIX == "pct_" and rep.REPORT_DAILY_COL == "low_price",
      "reports rank and quote TCGplayer's Low, as the site does")
check(rep.digest.PRICE_COL == "market_today", "the shared digest still reads NM Market")

# A note must be true of the price beside it (davidpineapple, 2026-10-05):
# the line quotes Low, so Low has to agree with Market before anything prints.
HIGH12, LOW12, NEAR6 = ("high", "near its 12-month high"), ("low", "cheapest in 12 months"), ("near-low", "near its 6-month low")
check(rep.agreed_standing(HIGH12, None) is None, "Market near its high, Low in the middle: no note (the Cruella line)")
check(rep.agreed_standing(HIGH12, HIGH12) == HIGH12, "both near the high: the note prints")
check(rep.agreed_standing(None, LOW12) is None, "a Low-only low is a phantom listing, never 'cheapest'")
check(rep.agreed_standing(LOW12, NEAR6) == NEAR6, "on a disagreement in strength the weaker claim prints")
check(rep.agreed_standing(NEAR6, LOW12) == NEAR6, "...whichever side is weaker")
check(rep.agreed_standing(HIGH12, LOW12) is None and rep.agreed_standing(LOW12, HIGH12) is None,
      "opposite notes print nothing")
check(rep.standing_note(HIGH12, -18.8) == "still near 12-mo high", "a faller near its high says 'still'")
check(rep.standing_note(HIGH12, 12.0) == "near 12-mo high", "a riser near its high does not")
check(rep.standing_note(LOW12, 4.0) == "still at a 12-mo low", "a riser at its low says 'still at a'")
check(rep.standing_note(None, -5) == "", "no standing, no note")


class SplitSb(FakeSb):
    """Max Goof's Market history sits far below today (-> "near its high")
    while his Low history does not."""
    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        rows = super().select(table, columns, limit, filters, page_size, order)
        if table == "prices_daily" and not (filters or {}).get("date", "").startswith("eq."):
            for r in rows:
                if r["tcgplayer_product_id"] == 21 and r["date"] != self.price_date.isoformat():
                    r["market_price"] = 5.0
        return rows


with redirect_stdout(io.StringIO()):
    split = rep.build_report(SplitSb([]), TODAY, "1d", session=FakeCdn())
    plain_max = rep.build_report(FakeSb([]), TODAY, "1d", session=FakeCdn())
NL = chr(10)


def max_line(r):
    return next((ln for e in r["embeds"] for ln in (e.get("description") or "").split(NL) if "Max Goof" in ln), "")


check(max_line(split) and "high" not in max_line(split),
      "a Market-only high puts no note on a line that quotes Low")
check(max_line(plain_max), "the control report lists Max Goof too")


def wk_posts(now, price_date=TODAY, force=False, last=None):
    sbx = FakeSb([{"guild_id": "g", "channel_id": "c2", "cadence": "weekly", "last_posted_on": last}],
                 price_date=price_date, index_latest=price_date)
    dx = FakeDiscord()
    with redirect_stdout(io.StringIO()):
        rep.run(args(force_weekly=force), sb=sbx, session=dx, now=now)
    return len(dx.posts)


# ── the weekly's slot: Monday 9 AM - 3 PM Chicago, never beside the daily ──
SUNDAY = TODAY - dt.timedelta(days=1)
check(wk_posts(MORNING, SUNDAY) == 1, "Monday 9:05 AM Chicago on Sunday's prices posts the weekly")
check(wk_posts(at(TODAY, 13, 55), SUNDAY) == 0, "8:55 AM Chicago is too early")
check(wk_posts(at(TODAY, 19, 55), SUNDAY) == 1, "2:55 PM Chicago is still in the window")
check(wk_posts(at(TODAY, 20, 5), SUNDAY) == 0, "3:05 PM Chicago is past it")
check(wk_posts(EVENING) == 0, "the weekly never posts beside the evening daily")
WINTER = dt.date(2026, 12, 7)     # a Monday on standard time (CST, UTC-6)
check(wk_posts(at(WINTER, 14, 5), WINTER - dt.timedelta(days=1)) == 0, "in winter 14:05 UTC is 8:05 AM Chicago: too early")
check(wk_posts(at(WINTER, 15, 5), WINTER - dt.timedelta(days=1)) == 1, "in winter 15:05 UTC is 9:05 AM Chicago: posts")
check(wk_posts(MORNING, TODAY - dt.timedelta(days=4)) == 0, "a weekly on prices four days old does not post")
check(wk_posts(MORNING, SUNDAY, last=SUNDAY.isoformat()) == 0, "a channel that already has this week's is skipped")
check(wk_posts(EVENING, SUNDAY, force=True, last=SUNDAY.isoformat()) == 1,
      "force_weekly sends it now, even outside the window and to a channel that had it")
check(wk_posts(dt.datetime(2026, 10, 12, 14, 5, tzinfo=UTC), dt.date(2026, 10, 11), last="2026-10-05") == 1,
      "the first Monday-morning weekly follows the last Monday-evening one")

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
check(len(disc_late.posts) == 1 and disc_late.posts[0]["url"].endswith("/channels/c1/messages"),
      f"a run after midnight still sends the day's daily, and never the weekly ({len(disc_late.posts)})")
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
code10, out10 = run(sb10, st10, now=MORNING)
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
run(sb11, FakeStorage(), now=MORNING)
check(not sb11.upserts, "a report already kept today is not built or kept again")

sb12 = FakeSb([], latest=[])
st12 = FakeStorage(fail=True)
run(sb12, st12, now=MORNING)
wk12 = next((rows[0] for (t, rows, oc) in sb12.upserts if t == rep.LATEST_TABLE and rows[0]["cadence"] == "weekly"), {})
check(wk12 and not any((e.get("image") or {}).get("url", "") for e in wk12["embeds"]) and wk12["files"] == [],
      "if a picture can't be stored, the kept report is the plain one (no broken picture)")

sb13 = FakeSb([], latest=[])
run(sb13, FakeStorage(), post=False)
check(not sb13.upserts, "a dry run keeps nothing")

sb15 = FakeSb([], latest=[])
run(sb15, FakeStorage())
check({rows[0]["cadence"] for (t, rows, oc) in sb15.upserts if t == rep.LATEST_TABLE} == {"daily"},
      "the evening run keeps only the daily: /reports send weekly stays Monday's report")

_, out14 = run(FakeSb([]), FakeStorage())
check("migration 175" in out14, "before migration 175 it says so and carries on")

# ── the two extra sections: new cards, and the week ahead ──
NOW = dt.datetime(2026, 9, 28, 22, 0, tzinfo=dt.timezone.utc)


class ExtraSb:
    def __init__(self, cards=(), events=(), boom=False):
        self.cards, self.events, self.boom = list(cards), list(events), boom

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        if self.boom:
            raise RuntimeError("down")
        return [dict(r) for r in (self.cards if table == "cards" else self.events if table == "calendar_events" else [])]


CARDS = [
    {"id": "a", "name": "Old Card", "version": "Here Already", "set_id": "s1", "inserted_at": "2026-08-01T00:00:00+00:00"},
    {"id": "b", "name": "Old Card", "version": "Here Already", "set_id": "s2", "inserted_at": "2026-09-28T10:00:00+00:00"},
    {"id": "c", "name": "Fresh", "version": "Today", "set_id": "s1", "inserted_at": "2026-09-28T12:00:00+00:00"},
    {"id": "d", "name": "Fresh", "version": "This Week", "set_id": "s1", "inserted_at": "2026-09-24T12:00:00+00:00"},
    {"id": "e", "name": "Song", "version": None, "set_id": "s1", "inserted_at": "2026-09-28T13:00:00+00:00"},
]
sets_x = {"s1": "Hyperia City", "s2": "Lorcana Challenge Year 3"}
day = rep.new_reveals(ExtraSb(CARDS), NOW, 1, sets_x)
check(day == [("Hyperia City", ["Song", "Fresh - Today"])], f"daily reveals: only names first seen in the last day ({day})")
week = rep.new_reveals(ExtraSb(CARDS), NOW, 7, sets_x)
check(sum(len(c) for _, c in week) == 3, "weekly reveals reach back seven days")
check(not any("Old Card" in " ".join(c) for _, c in week), "a new printing of an existing card is not a reveal")
check(rep.reveals_embed([], False) is None, "no reveals, no embed")
big = rep.reveals_embed([("Hyperia City", [f"Card {i}" for i in range(20)])], True)
check("and 14 more" in big["description"] and "20 added this week" in big["author"]["name"], "a long list is cut and counted")

EVENTS = [
    {"id": "u1", "kind": "ccq", "title": "Game Grid Open CCQ", "subtitle": "Challenge Championship Qualifier",
     "starts_on": "2026-10-03", "ends_on": None, "location": "Expo Center · Sandy, UT"},
    {"id": "u2", "kind": "set", "title": "Hyperia City", "subtitle": "LGS release", "starts_on": "2026-10-02", "ends_on": None, "location": None},
]
DERIVED = [
    {"kind": "set", "title": "Hyperia City", "subtitle": "LGS release", "starts_on": "2026-10-01"},
    {"kind": "product", "title": "Quest Box", "subtitle": None, "starts_on": "2026-10-02"},
    {"kind": "product", "title": "Far Off", "subtitle": None, "starts_on": "2026-12-01"},
]
ahead = rep.week_ahead(ExtraSb(events=EVENTS), TODAY, derived=DERIVED)
check([r["title"] for r in ahead] == ["Hyperia City", "Quest Box", "Game Grid Open CCQ"],
      f"the week ahead: a curated set date replaces the derived one, far dates stay out ({[r['title'] for r in ahead]})")
cal_e = rep.calendar_embed(ahead)
check("?ce=u1" in cal_e["description"] and "Sandy, UT" in cal_e["description"] and "Hyperia City LGS release" in cal_e["description"],
      "calendar lines link the event, name the place and the phase")
check(rep.calendar_embed([]) is None, "an empty week, no embed")
real = rep.derived_releases()
check(any(r["title"] == "Hyperia City" and r["subtitle"] == "Retail release" for r in real) and any(r["kind"] == "product" for r in real),
      "the release consts still parse out of Index.html")
check(rep.extra_embeds(ExtraSb(boom=True), TODAY, "7d", sets_x, now=NOW) == [], "a failed read costs the section, never the report")
both = rep.extra_embeds(ExtraSb(CARDS, EVENTS), TODAY, "7d", sets_x, now=NOW)
check(len(both) == 2 and all(e.get("_keep") for e in both), "weekly carries both sections, and trimming never touches them")
check(len(rep.extra_embeds(ExtraSb(CARDS, EVENTS), TODAY, "1d", sets_x, now=NOW)) == 1, "the daily carries reveals only")
check(all(rep.embed_chars(e) < 1500 for e in both), "the extra sections stay short")

# ── promos we track on eBay: eBay's sales decide the move, TCGplayer's Low never does ──
def sale(cid, price, day, printing=None, seen=None):
    """A sale sold on `day`, reaching us (scraped_at) at `seen` — by default
    noon the day it sold."""
    return {"card_id": cid, "printing": printing, "sale_price": price, "sold_date": day.isoformat(),
            "scraped_at": (seen or at(day, 12)).isoformat()}


D = lambda n: TODAY - dt.timedelta(days=n)  # noqa: E731
FLAGS = {"p_gold": {"id": "p_gold", "split_printing": True, "foil_split": False},
         "p_rap": {"id": "p_rap", "split_printing": True, "foil_split": False},
         "p_one": {"id": "p_one", "split_printing": False, "foil_split": False},
         "p_late": {"id": "p_late", "split_printing": False, "foil_split": False}}
SALES = ([sale("p_one", 100, D(20 + i)) for i in range(5)]               # baseline $100
         + [sale("p_one", 60, D(2))]                                    # one sale this week
         + [sale("p_rap", 6000, D(40 + i), "Foil") for i in range(4)]   # Top Prize, nothing this week
         + [sale("p_rap", 100, D(30 + i), "Non-Foil") for i in range(5)]
         + [sale("p_rap", 160, D(0), "Non-Foil")]                       # Prize Wall sold this week
         + [sale("p_gold", 9800, D(3))]                                 # unlabelled: never a price
         + [sale("p_one", 999, TODAY + dt.timedelta(days=1))]           # reached us after the report: ignored
         + [sale("p_late", 40, D(10 + i)) for i in range(5)]            # baseline $40...
         + [sale("p_late", 90, D(3), seen=at(TODAY, 17))])              # ...sold Friday, scraped today
WEEK = (EVENING - dt.timedelta(days=7), EVENING, TODAY - dt.timedelta(days=rep.EBAY_FRESH_DAYS))
DAY = (EVENING - dt.timedelta(days=1), EVENING, TODAY - dt.timedelta(days=rep.EBAY_FRESH_DAYS))
mv = rep.ebay_moves(SALES, FLAGS, *WEEK)
check(set(mv) == {("p_one", ""), ("p_rap", "Non-Foil"), ("p_late", "")}, f"eBay moves: only buckets with new sales ({sorted(mv)})")
one = mv.get(("p_one", ""), {})
check(abs(one.get("now", 0) - (60 + 400) / 5) < 1e-9 and one.get("was") == 100 and one.get("sold") == 1,
      "the move is the average of the last 5 sales now against the average before them")
check(("p_gold", "Unknown") not in mv, "an unlabelled split-card sale stands for neither printing")
check(not mv.get(("p_rap", "Foil")), "a bucket with no new sale has no move")
thin = [sale("p_one", 100, D(20)), sale("p_one", 100, D(21)), sale("p_one", 300, D(1))]
check(not rep.ebay_moves(thin, FLAGS, *WEEK), "a baseline of two sales is not a price")
check(rep.sale_pkey("Holofoil", False, True) == "Foil" and rep.sale_pkey(None, True, False) == "Unknown"
      and rep.sale_pkey("Foil", False, False) == "", "sale_pkey matches graded_sale_pkey")
# ⚠ "New" is when a sale REACHED us, not when it sold: Terapeak lists a sale a
# day or more late, so "sold on the price date" left the daily with no eBay
# moves at all.
dmv = rep.ebay_moves(SALES, FLAGS, *DAY)
check(("p_late", "") in dmv, "a sale that sold three days ago but reached us today moves the daily")
check(("p_one", "") not in dmv, "a sale we already knew of at the last daily is baseline, not news")
base5 = [sale("p_one", 100, D(20 + i)) for i in range(5)]
backfill = base5 + [sale("p_one", 900, D(60), seen=at(TODAY, 17))]
check(not rep.ebay_moves(backfill, FLAGS, *DAY), "a backfilled old sale never reads as a fresh move")
# The window runs from the previous report of the same cadence.
yest = TODAY - dt.timedelta(days=1)


def win(latest, now=EVENING, window="1d"):
    return rep.ebay_window(FakeSb([], latest=latest), TODAY, window, now)


prev = at(yest, 21, 5)
check(win([{"cadence": "daily", "price_date": yest.isoformat(), "built_at": prev.isoformat()}]) == (prev, EVENING),
      "the daily's window opens at the previous daily's build")
first = at(TODAY, 21, 0)
check(win([{"cadence": "daily", "price_date": TODAY.isoformat(), "built_at": first.isoformat()}], now=at(TODAY, 23, 0))
      == (first - dt.timedelta(days=1), first), "a second run the same day rebuilds the first run's window")
check(win(None) == (EVENING - dt.timedelta(days=1), EVENING), "with nothing kept, the window is the last day")
check(win(None, window="7d") == (EVENING - dt.timedelta(days=7), EVENING), "...or the last week for the weekly")
long_ago = at(TODAY - dt.timedelta(days=20), 21)
check(win([{"cadence": "daily", "price_date": "2026-09-08", "built_at": long_ago.isoformat()}])[0]
      == EVENING - dt.timedelta(days=1 + rep.EBAY_MAX_GAP_DAYS), "a long gap never dumps weeks of sales into one report")
check(win([{"cadence": "weekly", "price_date": yest.isoformat(), "built_at": prev.isoformat()}])[0]
      == EVENING - dt.timedelta(days=1), "another cadence's report never opens this one's window")

EB_MOVERS = MOVERS + [
    mover("p_gold", "Mickey Mouse", "Brave Little Tailor", "Promo", "Holofoil", 51, 200000.0, 50.0, 1233.3, set_id="s_c1"),
    mover("p_rap", "Rapunzel", "Gifted with Healing", "Promo", "Holofoil", 52, 6000.0, 40.0, 40.0, set_id="s_c1"),
    {**mover("p_rap", "Rapunzel", "Gifted with Healing", "Promo", "Normal", 52, 100.0, 0.0, -30.0, set_id="s_c1")},
    mover("p_one", "Elsa", "Snow Queen", "Promo", "Holofoil", 53, 5999.99, 0.0, 0.0, set_id="s_p3"),
    mover("p_late", "Belle", "Strange but Special", "Promo", "Holofoil", 54, 12.0, 0.0, 0.0, set_id="s_p3"),
]
ebay_sb = FakeSb([], movers=EB_MOVERS, ebay={"roll": [{"card_id": c} for c in FLAGS],
                                            "cards": list(FLAGS.values()), "sales": SALES})
with redirect_stdout(io.StringIO()):
    erep = rep.build_report(ebay_sb, TODAY, "7d", session=FakeCdn(), now=EVENING)
promo = next((e["description"] for e in erep["embeds"] if "PROMOS" in (e.get("author") or {}).get("name", "")), "")
check("200,000" not in promo and "Brave Little Tailor" not in promo,
      "a tracked card's TCGplayer spike never reaches the report (the $200,000 Golden Mickey)")
check("Elsa — Snow Queen" in promo and "−8.0%" in promo and "eBay avg of last 5 sales · 1 new sale" in promo,
      "a tracked card with a new eBay sale moves by its eBay sales, and says so")
check("Rapunzel — Gifted with Healing (Prize Wall)" in promo and "+12.0%" in promo,
      "a Challenge card's Prize Wall moves by its own bucket's sales")
check("(Top Prize)" not in promo, "a printing with no new eBay sale is left out, not priced off TCGplayer")
check("Woody" in promo, "an untracked promo still moves by TCGplayer")
with redirect_stdout(io.StringIO()):
    drep = rep.build_report(ebay_sb, TODAY, "1d", session=FakeCdn(), now=EVENING)
dpromo = next((e["description"] for e in drep["embeds"] if "PROMOS" in (e.get("author") or {}).get("name", "")), "")
check("Rapunzel — Gifted with Healing (Prize Wall)" in dpromo and "1 new sale" in dpromo,
      "the daily carries an eBay sale from the last day")
check("Belle — Strange but Special" in dpromo and "+25.0%" in dpromo,
      "the daily carries a sale that sold days ago but reached us since the last report")
check("Elsa — Snow Queen" not in dpromo, "the daily leaves out a sale the last daily already knew of")

print("FAILS:", FAILS)
sys.exit(1 if FAILS else 0)
