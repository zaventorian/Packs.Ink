"""Guards which DATE the daily TCGCSV ETL files a price snapshot under.

    python scripts/test_etl_snapshot_date.py

No network, no database: TCGCSV, Supabase and the clock are all stubbed, and the
real etl_tcgcsv_daily.main() is driven through a day of cron firings.

TCGCSV publishes one file a day at ~20:00 UTC. The ETL is pinged at 20:30 and
22:30 UTC, again at 01:00 UTC, and GitHub's own fallback cron lands anywhere up to
~07:30 UTC — the last two on the NEXT UTC calendar day, while TCGCSV is still
serving the previous evening's file. Dating a run by the UTC clock filed that
file under the wrong day, and it fails silently in both directions:

  1. A day whose evening runs all failed is a permanent HOLE, and its file lands
     under the next day's date (the next evening's real file then overwrites it).
  2. When TCGCSV publishes late and the prior day is missing, the old file is
     written under today's date with a post-publish-window stamp, so the real
     file is then skipped as "already loaded" — a whole day of wrong prices.

The fix dates every run by TCGCSV's own publish stamp (last-updated.txt), and
falls back to "the newest 20:15 UTC cutoff that has passed" when that file can't
be read. Both rules, the idempotency skip, and "an explicit --date backfill never
re-fetches" are pinned here.
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))

import requests  # noqa: E402
import etl_tcgcsv_daily as etl  # noqa: E402
from tcgcsv_common import EXTRA_PRICE_GROUPS, LORCANA_CATEGORY_ID, TCGCSV_BASE  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


def utc(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


D0 = date(2026, 10, 5)          # "D" in the docstring
D_1 = D0 - timedelta(days=1)
D_2 = D0 - timedelta(days=2)
D1 = D0 + timedelta(days=1)


# ── pure rules ───────────────────────────────────────────────────────────────
print("snapshot date across the day")
snap_for = getattr(etl, "snapshot_for", None)
if snap_for is None:
    check("etl_tcgcsv_daily.snapshot_for exists", False, True)
else:
    pub_prev = utc(2026, 10, 4, 20, 6)   # yesterday's file
    pub_today = utc(2026, 10, 5, 20, 6)  # today's file
    for now, pub, want in (
        (utc(2026, 10, 5, 19, 0), pub_prev, D_1),     # before today's publish
        (utc(2026, 10, 5, 20, 30), pub_today, D0),    # primary
        (utc(2026, 10, 5, 22, 30), pub_today, D0),    # retry 1
        (utc(2026, 10, 6, 1, 0), pub_today, D0),      # retry 2: next UTC day
        (utc(2026, 10, 6, 7, 30), pub_today, D0),     # a GitHub cron 6h late
        (utc(2026, 10, 5, 20, 30), pub_prev, D_1),    # TCGCSV late: yesterday's file
    ):
        check(f"stamp {pub:%m-%d %H:%M}, now {now:%m-%d %H:%M} -> {want}", snap_for(now, pub), want)
    for now, want in (
        (utc(2026, 10, 5, 19, 0), D_1),
        (utc(2026, 10, 5, 20, 14), D_1),
        (utc(2026, 10, 5, 20, 15), D0),
        (utc(2026, 10, 5, 20, 30), D0),
        (utc(2026, 10, 5, 22, 30), D0),
        (utc(2026, 10, 6, 1, 0), D0),
        (utc(2026, 10, 6, 7, 30), D0),
    ):
        check(f"no stamp, now {now:%m-%d %H:%M} -> {want} (20:15 cutoff)", snap_for(now, None), want)
    check("a stamp from the future is not trusted",
          snap_for(utc(2026, 10, 5, 19, 0), utc(2026, 10, 9, 20, 6)), D_1)

parse = getattr(etl, "parse_publish_stamp", None)
if parse is None:
    check("etl_tcgcsv_daily.parse_publish_stamp exists", False, True)
else:
    check("TCGCSV's own stamp format parses", parse("2026-10-05T20:05:57+0000\n"),
          utc(2026, 10, 5, 20, 5).replace(second=57))
    check("a Z stamp parses", parse("2026-10-05T20:05:57Z"), utc(2026, 10, 5, 20, 5).replace(second=57))
    check("garbage is None, not a crash", parse("<html>nope</html>"), None)
    check("empty is None", parse(""), None)


# ── a simulated week of cron firings through the real main() ─────────────────
def prices(seed):
    """A TCGCSV price file: every product moves with `seed`, so files differ."""
    return [{"productId": 1000 + i, "subTypeName": "Normal",
             "lowPrice": round(1 + i + seed * 0.37, 2), "marketPrice": round(2 + i + seed * 0.41, 2)}
            for i in range(40)]


FILES = {k: prices(k) for k in range(10)}
WORLD = {}


class FakeResp:
    def __init__(self, body=None, text="", status=200):
        self._body, self.text, self.status_code = body, text, status

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def fake_get(url, headers=None, timeout=None, **kw):
    if url.endswith("last-updated.txt"):
        if WORLD.get("stamp_down"):
            raise requests.ConnectionError("stamp unreachable")
        return FakeResp(text=WORLD["stamp"].strftime("%Y-%m-%dT%H:%M:%S+0000"))
    if url == f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/groups":
        return FakeResp({"results": [{"groupId": 1, "name": "Test Group"}]})
    if url == f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}/1/prices":
        WORLD["fetches"] += 1
        return FakeResp({"results": FILES[WORLD["file"]]})
    for cat, gid, _ in EXTRA_PRICE_GROUPS:
        if url == f"{TCGCSV_BASE}/{cat}/{gid}/prices":
            return FakeResp({"results": []})
    raise AssertionError("unexpected GET " + url)


class FakeSupabase:
    """prices_daily only, with the filters/orders the ETL actually sends."""
    def __init__(self, *a, **k):
        pass

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        if table != "prices_daily":
            return []
        f = dict(filters or {})
        order = order or f.pop("order", None)
        rows = list(DB.values())
        for col in ("source", "grade"):
            if col in f:
                rows = [r for r in rows if r[col] == f[col].split(".", 1)[1]]
        if "date" in f:
            op, val = f["date"].split(".", 1)
            rows = [r for r in rows if (r["date"] == val if op == "eq" else r["date"] < val)]
        if order == "date.desc":
            rows.sort(key=lambda r: r["date"], reverse=True)
        elif order == "inserted_at.desc":
            rows.sort(key=lambda r: r.get("inserted_at") or "", reverse=True)
        return rows[:limit] if limit else rows

    def upsert(self, table, rows, on_conflict=None, batch=100):
        for r in rows:
            DB[(r["tcgplayer_product_id"], r["date"], r["printing"], r["source"], r["grade"])] = dict(r)

    def update(self, *a, **k):
        pass

    def rpc(self, name, args=None):
        return None


class Clock(datetime):
    NOW = utc(2026, 1, 1)

    @classmethod
    def now(cls, tz=None):
        return cls.NOW if tz else cls.NOW.replace(tzinfo=None)


DB: dict = {}
etl.Supabase = FakeSupabase
etl.load_dotenv = lambda *a, **k: None
etl.datetime = Clock
requests.get = fake_get


def seed_day(day, file_key, written):
    for r in FILES[file_key]:
        row = {"tcgplayer_product_id": r["productId"], "date": day.isoformat(), "printing": "Normal",
               "source": "tcgcsv", "grade": "raw", "low_price": r["lowPrice"],
               "market_price": r["marketPrice"], "inserted_at": written.isoformat()}
        DB[(row["tcgplayer_product_id"], row["date"], "Normal", "tcgcsv", "raw")] = row


def fire(now, file_key, stamp, *argv, stamp_down=False):
    Clock.NOW = now
    WORLD.update(file=file_key, stamp=stamp, stamp_down=stamp_down)
    sys.argv = ["etl_tcgcsv_daily.py", *argv]
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            etl.main()
    except SystemExit as e:
        out.write(f"\n[exit {e.code}]")
    return out.getvalue()


def day_file(day):
    """Which file's prices are stored under `day` (None if nothing)."""
    got = sorted((k[0], DB[k]["market_price"]) for k in DB if k[1] == day.isoformat())
    if not got:
        return None
    for key, entries in FILES.items():
        if got == sorted((e["productId"], e["marketPrice"]) for e in entries):
            return key
    return "mixed"


def reset():
    DB.clear()
    WORLD.clear()
    WORLD["fetches"] = 0


P_PREV, P_D0, P_D1 = utc(2026, 10, 4, 20, 6), utc(2026, 10, 5, 20, 6), utc(2026, 10, 6, 20, 6)

print("\nan ordinary day: every cron firing, files on time")
reset()
seed_day(D_1, 1, utc(2026, 10, 4, 20, 31))
fire(utc(2026, 10, 5, 19, 0), 1, P_PREV)
fire(utc(2026, 10, 5, 20, 30), 2, P_D0)
fire(utc(2026, 10, 5, 22, 30), 2, P_D0)
fire(utc(2026, 10, 6, 1, 0), 2, P_D0)
fire(utc(2026, 10, 6, 7, 30), 2, P_D0)
check("D-1 keeps its own file", day_file(D_1), 1)
check("D holds D's file", day_file(D0), 2)
check("nothing is filed under D+1 before D+1's publish", day_file(D1), None)
check("one publish is fetched once, however many pings land", WORLD["fetches"], 1)

print("\nthe evening runs all failed; the 01:00 UTC retry is the first to see D's file")
reset()
seed_day(D_1, 1, utc(2026, 10, 4, 20, 31))
fire(utc(2026, 10, 6, 1, 0), 2, P_D0)
check("D's file lands under D (not under D+1)", day_file(D0), 2)
check("D+1 is left for D+1's own file", day_file(D1), None)
fire(utc(2026, 10, 6, 20, 30), 3, P_D1)
check("D+1's file then lands under D+1", day_file(D1), 3)
check("...and D still holds D's file (no hole)", day_file(D0), 2)

print("\nTCGCSV is late and yesterday is a hole")
reset()
seed_day(D_2, 0, utc(2026, 10, 3, 20, 31))
fire(utc(2026, 10, 5, 20, 30), 1, P_PREV)          # still serving D-1's file
fire(utc(2026, 10, 5, 22, 30), 2, utc(2026, 10, 5, 22, 10))
check("D-1's file fills the D-1 hole under its own date", day_file(D_1), 1)
check("D's real file is not locked out by the late one", day_file(D0), 2)

print("\nTCGCSV re-publishes the same day")
reset()
seed_day(D_1, 1, utc(2026, 10, 4, 20, 31))
fire(utc(2026, 10, 5, 20, 30), 2, P_D0)
fire(utc(2026, 10, 5, 22, 30), 3, utc(2026, 10, 5, 21, 0))
check("the newer publish replaces the older one for that day", day_file(D0), 3)

print("\nrows claimed before the publish (the 2026-07-26 regression)")
reset()
seed_day(D_1, 1, utc(2026, 10, 4, 20, 31))
seed_day(D0, 1, utc(2026, 10, 5, 1, 0))               # yesterday's numbers under D
fire(utc(2026, 10, 5, 20, 30), 2, P_D0)
check("a pre-publish claim is re-fetched", day_file(D0), 2)

print("\nan explicit --date backfill never re-fetches over existing rows")
reset()
seed_day(D_2, 0, utc(2026, 10, 3, 1, 0))
fire(utc(2026, 10, 5, 20, 30), 2, P_D0, "--date", D_2.isoformat())
check("--date D-2 left alone", (day_file(D_2), WORLD["fetches"]), (0, 0))

print("\nlast-updated.txt unreachable: the 20:15 UTC cutoff dates the run")
reset()
seed_day(D_1, 1, utc(2026, 10, 4, 20, 31))
fire(utc(2026, 10, 5, 19, 0), 1, P_PREV, stamp_down=True)
fire(utc(2026, 10, 5, 20, 30), 2, P_D0, stamp_down=True)
fire(utc(2026, 10, 6, 1, 0), 2, P_D0, stamp_down=True)
check("D holds D's file", day_file(D0), 2)
check("nothing under D+1", day_file(D1), None)
check("D-1 untouched", day_file(D_1), 1)

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
