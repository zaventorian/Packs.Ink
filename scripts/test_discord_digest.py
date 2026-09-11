"""
test_discord_digest.py — guards the Discord digest. No network.

    python scripts/test_discord_digest.py

The headline check is CROSS-LANGUAGE. `priceStanding` in Index.html renders the
same claim next to a buy button that this bot posts to Discord; if the two
implementations drift, the site and the feed start disagreeing about whether a
price is good, which destroys the only thing that claim has going for it. So
this reads the constants back OUT of Index.html and fails if they differ —
retuning one alone is exactly the mistake it exists to catch. (Same reasoning as
buildCustomIndex vs migration 130.)
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))

import discord_digest as dd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
INDEX = (ROOT / "Index.html").read_text(encoding="utf-8")

FAILED = 0


def ok(name, cond, detail=""):
    global FAILED
    if not cond:
        FAILED += 1
    print(("PASS  " if cond else "FAIL  ") + name + ("" if cond else "  " + str(detail)))


def js_const(name):
    m = re.search(r"const " + name + r"\s*=\s*([0-9.]+)\s*;", INDEX)
    if not m:
        raise AssertionError("not found in Index.html: " + name)
    return float(m.group(1))


# ── The site and the bot must agree, number for number ──────────────────────
for js_name, py_val in [
    ("PRICE_STANDING_MIN_POINTS", dd.STANDING_MIN_POINTS),
    ("PRICE_STANDING_MIN_SPAN_RATIO", dd.STANDING_MIN_SPAN_RATIO),
    ("PRICE_STANDING_MIN_SPREAD", dd.STANDING_MIN_SPREAD),
    ("PRICE_STANDING_LOW", dd.STANDING_LOW),
    ("PRICE_STANDING_NEAR_LOW", dd.STANDING_NEAR_LOW),
    ("PRICE_STANDING_HIGH", dd.STANDING_HIGH),
]:
    ok(f"{js_name} matches the site", js_const(js_name) == py_val,
       f"Index.html={js_const(js_name)} bot={py_val}")

js_days = [int(d) for d in re.findall(r"\{days:\s*(\d+),", INDEX)[:3]]
ok("the standing windows match the site",
   js_days == [d for d, _, _ in dd.STANDING_WINDOWS], f"{js_days} vs {dd.STANDING_WINDOWS}")

# The bot must read Market, never Low — a phantom Low crying "cheapest ever" is
# the failure this whole feature is designed around.
ok("the bot reads market, not low", dd.PRICE_COL == "market_today" and
   dd.PCT_PREFIX == "mkt_pct_", f"{dd.PRICE_COL} / {dd.PCT_PREFIX}")

# ── The standing itself, same fixtures as the JS suite ──────────────────────
END = dt.date(2026, 9, 10)


def series(days, fn):
    return [(END - dt.timedelta(days=days - 1 - i), fn(i, days)) for i in range(days)]


falling = dd.price_standing(series(365, lambda i, n: 100 - (i / (n - 1)) * 50))
ok("a year of decline reads as cheapest", falling and falling[0] == "low", falling)
ok("…and names the 12-month window", falling and "12 months" in falling[1], falling)

rising = dd.price_standing(series(365, lambda i, n: 50 + (i / (n - 1)) * 50))
ok("a year of rise reads as near the high", rising and rising[0] == "high", rising)

ok("a flat year says nothing", dd.price_standing(series(365, lambda i, n: 20)) is None)
ok("mid-range says nothing", dd.price_standing(
    series(365, lambda i, n: 100 - (i / (n - 1)) * 50 if i < n / 2 else 75)) is None)
ok("too few points says nothing", dd.price_standing(series(10, lambda i, n: 100 - i)) is None)
ok("empty says nothing", dd.price_standing([]) is None)
ok("a short history falls back to a TRUE window, not 12 months",
   (dd.price_standing(series(100, lambda i, n: 100 - (i / (n - 1)) * 50)) or ("", ""))[1]
   == "cheapest in 3 months",
   dd.price_standing(series(100, lambda i, n: 100 - (i / (n - 1)) * 50)))
ok("None values are skipped, not crashed on",
   dd.price_standing([(END - dt.timedelta(days=i), None) for i in range(60)]) is None)

# ── Formatting ──────────────────────────────────────────────────────────────
ok("prices under 1000 keep cents", dd.fmt_price(42.1) == "$42.10", dd.fmt_price(42.1))
ok("prices over 1000 lose them", dd.fmt_price(1707.0) == "$1,707", dd.fmt_price(1707.0))
ok("no price renders a dash", dd.fmt_price(None) == "—")
ok("a rise is signed", dd.fmt_pct(12.34) == "+12.3%", dd.fmt_pct(12.34))
ok("a fall carries its own sign", dd.fmt_pct(-8.0) == "-8.0%", dd.fmt_pct(-8.0))

# A card_id with a slash or space must not break the markdown link.
ok("card ids are URL-escaped",
   "%2F" in dd.card_url("set/1 2") and " " not in dd.card_url("set/1 2"),
   dd.card_url("set/1 2"))

row = {"card_id": "azu-1", "name": "Elsa", "version": "Spirit of Winter",
       "printing": "Cold Foil", "market_today": 42.1, "mkt_pct_1d": -9.4,
       "tcgplayer_product_id": 1}
ln = dd.line(row, "1d", ("low", "cheapest in 6 months"))
ok("a line links the name", ln.startswith("[Elsa — Spirit of Winter](https://packs.ink/cards?card="), ln)
ok("a foil is marked", "*(foil)*" in ln, ln)
ok("the standing is the bolded part", "**cheapest in 6 months**" in ln, ln)
ok("a normal printing is not marked",
   "(foil)" not in dd.line({**row, "printing": "Normal"}, "1d", None))

# ── The embed, against Discord's actual limits ──────────────────────────────
many = [{**row, "card_id": f"c{i}", "name": f"Card {i}", "mkt_pct_1d": -20 + i}
        for i in range(12)]
standings = {(1, "Cold Foil"): ("low", "cheapest in 12 months")}
emb = dd.build_embed(dt.date(2026, 9, 10), "1d", many, many, standings)
ok("the embed has a title and fields", emb["title"] and emb["fields"], emb["title"])
ok("no field value exceeds Discord's 1024",
   all(len(f["value"]) <= 1024 for f in emb["fields"]),
   [len(f["value"]) for f in emb["fields"]])
ok("no more than 25 fields", len(emb["fields"]) <= 25)
ok("the total embed is under 6000 chars",
   len(emb["title"]) + len(emb["description"])
   + sum(len(f["name"]) + len(f["value"]) for f in emb["fields"]) < 6000)
# The lead section is the differentiator, so it must be first when it exists.
ok("'Worth a look' leads when anything qualifies",
   emb["fields"][0]["name"].startswith("💡"), emb["fields"][0]["name"])
# …and its absence must not leave the post empty.
emb2 = dd.build_embed(dt.date(2026, 9, 10), "1d", many, many, {})
ok("with no standings it still says something", len(emb2["fields"]) >= 1)
ok("…and falls back to a plain faller list",
   any("Falling" in f["name"] for f in emb2["fields"]),
   [f["name"] for f in emb2["fields"]])
ok("an empty day yields no fields (so main() can bail)",
   dd.build_embed(dt.date(2026, 9, 10), "1d", [], [], {})["fields"] == [])

print()
print(f"{FAILED} FAILED" if FAILED else "all passed")
sys.exit(1 if FAILED else 0)
