"""Guards how the daily ETL judges the OPTIONAL market-index refresh.

    python scripts/test_etl_market_index.py

No network: Supabase is stubbed and sleeping is a no-op.

refresh_market_index() is the slowest refresh on the site and outlives the ETL's
120-second HTTP read timeout, so every day the ETL logged

    WARN: refresh_market_index failed (run supabase/128_market_index.sql ...)

while the server went on to finish it. Both halves were wrong: the warning
cried wolf daily (which teaches everyone to skip it), and its hint named a
migration that must NEVER be re-run — 128's flat coverage floor empties every
narrow index scope; 131 is the one that pins the timeout. The ETL now judges the
refresh by what the index actually holds afterwards, waits a bounded while when
the call merely timed out, and names 131 when it really is stale.
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))

import requests  # noqa: E402
import etl_tcgcsv_daily as etl  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


SNAP = "2026-10-05"
etl.time.sleep = lambda s: None


class FakeSb:
    """Required refreshes succeed; the market index behaves per scenario."""
    def __init__(self, rpc_error=None, dates=(), unpopulated=False):
        self.rpc_error, self.dates, self.unpopulated = rpc_error, list(dates), unpopulated
        self.reads = 0

    def rpc(self, name, args=None):
        if name == "refresh_market_index" and self.rpc_error is not None:
            raise self.rpc_error
        return None

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        assert table in ("market_index_latest", "market_index_daily"), table
        self.reads += 1
        if self.unpopulated:
            raise RuntimeError('Select market_index_latest failed (500): {"code":"55000"}')
        d = self.dates[min(self.reads - 1, len(self.dates) - 1)] if self.dates else None
        return [{"date": d}] if d else []


def run(sb):
    out = io.StringIO()
    try:
        with redirect_stdout(out):
            try:
                etl._refresh_matviews(sb, SNAP)
            except TypeError:
                etl._refresh_matviews(sb)          # the pre-fix signature
    except SystemExit as e:
        out.write(f"\n[exit {e.code}]")
    return out.getvalue()


print("the HTTP call times out but the server finishes the refresh")
o = run(FakeSb(rpc_error=requests.ReadTimeout("read timed out (120s)"),
               dates=["2026-10-04", "2026-10-04", SNAP]))
check("no WARN once the index shows the new day", "WARN" in o, False)
check("says the index is current", "current through 2026-10-05" in o, True)
check("never sends anyone to re-run 128", "128_market_index" in o, False)
check("the run is not failed over it", "[exit" in o, False)

print("\nthe call succeeds but the index did not move")
o = run(FakeSb(dates=["2026-10-04"]))
check("a stale index is a WARN even when the call returned 200", "WARN" in o, True)
check("the hint names migration 131", "131_market_index_timeout_pin.sql" in o, True)
check("...and never 128", "128_market_index" in o, False)
check("still optional: the run is not failed", "[exit" in o, False)

print("\ntimed out and never caught up")
sb = FakeSb(rpc_error=requests.ReadTimeout("read timed out"), dates=["2026-10-04"])
o = run(sb)
check("WARN after the bounded wait", "WARN" in o, True)
check("the wait is bounded (polled more than once, not forever)", 1 < sb.reads < 100, True)
check("the hint names 131", "131_market_index_timeout_pin.sql" in o, True)

print("\na fast 4xx is not waited on")
sb = FakeSb(rpc_error=RuntimeError("RPC refresh_market_index failed (404): no such function"),
            dates=["2026-10-04"])
o = run(sb)
check("only one read of the index", sb.reads, 1)
check("WARN with the 131 hint", ("WARN" in o, "131_market_index_timeout_pin.sql" in o), (True, True))

print("\nthe matview was never populated")
o = run(FakeSb(unpopulated=True))
check("an unreadable index is a WARN, not a crash", ("WARN" in o, "[exit" in o), (True, False))
check("the hint includes the populate step", "select public.refresh_market_index()" in o, True)

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
