"""The set_championships mirror sends only columns that table has.

to_row() is shared with lorcana_events, which is wider. When `description`
was added there, the mirror started naming a column set_championships lacks,
PostgREST answered PGRST204, and Discover Lorcana events went red for three
nights while the Elo pipeline's SC table stopped updating. No network: the
upsert is driven against a stubbed urlopen, and SC_COLS is checked against
the table as migration 66 creates it.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_wu_scs as m  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    ok = got == want
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))


# The table's columns, read from the migration that creates it, minus the two
# server-side timestamps the client never sends.
sql = (HERE.parent.parent / "supabase" / "66_set_championships_and_elo_store_report.sql").read_text()
body = re.search(r"create table if not exists public\.set_championships \((.*?)\n\);", sql, re.S).group(1)
table_cols = set()
for line in body.splitlines():
    line = line.strip().rstrip(",")
    for part in line.split(","):
        w = part.strip().split()
        if w and re.fullmatch(r"[a-z_]+", w[0]):
            table_cols.add(w[0])
table_cols -= {"scraped_at", "updated_at"}
check("SC_COLS is exactly the table's client-written columns", set(m.SC_COLS), table_cols)

ev = {"id": 42, "name": "SC", "description": "<b>Entry $10</b>",
      "store": {"id": 7, "name": "Shop", "city": "Chicago"},
      "start_datetime": "2026-10-01T18:00:00Z"}
row = m.to_row(ev, "Attack of the Vine!")
check("to_row still carries description for lorcana_events", "description" in row, True)

sent = []


class _Resp:
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def read(self): return b""


def fake_urlopen(req, timeout=None):
    sent.append((req.full_url, json.loads(req.data.decode())))
    return _Resp()


real = m.urllib.request.urlopen
m.urllib.request.urlopen = fake_urlopen
try:
    m.upsert([row])
finally:
    m.urllib.request.urlopen = real

url, payload = sent[0]
check("the mirror writes to set_championships", url.endswith("/rest/v1/set_championships"), True)
check("description is not sent to set_championships", "description" in payload[0], False)
check("every sent key is a real column", set(payload[0]) <= table_cols, True)
check("the row's identity survives", payload[0]["event_id"], 42)
check("the caller's row is not mutated", "description" in row, True)

print(f"\n{failed} FAILED" if failed else "\nall passed")
raise SystemExit(1 if failed else 0)
