"""Guards that Range-paginated reads order on a UNIQUE key.

    python scripts/test_select_pagination.py

No network: a fake PostgREST stands behind requests.get and is run through the
real Supabase.select(). Like Postgres, it promises nothing about the order of
rows that TIE on the ORDER BY — this one breaks ties differently on every request,
the worst case a real database is allowed to produce.

Supabase.select() pages 1,000 rows at a time with Range headers. With no explicit
order it orders on the first selected column, and an ORDER BY that isn't unique
lets a page boundary that falls inside a tie group return some rows twice and
others never. retire_prestaged.repoint_decks read deck_cards ordered by deck_id
alone (~40 rows per deck), so a deck straddling a page boundary could lose its
stand-in row from the read; the row was never re-pointed, the stand-in card was
deleted, and that deck showed "(unknown)". deck_versions had the same shape.

  1. retire_prestaged's deck reads see every row, at any page boundary.
  2. Every read of a table with a composite key orders on the WHOLE key, wherever
     it is in scripts/ (an AST scan, so a new call site can't regress silently).
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))

import requests  # noqa: E402
import supabase_client  # noqa: E402
import retire_prestaged as rp  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


TABLES: dict[str, list[dict]] = {}
STATE = {"requests": 0}


class Resp:
    def __init__(self, rows):
        self.status_code, self._rows, self.text = 206, rows, "x"

    def json(self):
        return self._rows


def fake_get(url, headers=None, params=None, timeout=None):
    table = url.rsplit("/", 1)[-1]
    rows = list(TABLES[table])
    params = dict(params or {})
    for col, f in params.items():
        if col in ("select", "order", "limit", "offset"):
            continue
        op, val = f.split(".", 1)
        if op == "eq":
            rows = [r for r in rows if str(r.get(col)) == val]
        elif op == "in":
            vals = set(unquote(val)[1:-1].split(","))
            rows = [r for r in rows if str(r.get(col)) in vals]
    STATE["requests"] += 1
    flip = STATE["requests"] % 2 == 0
    # Ties: a different order on every request (hidden row id, alternating).
    rows.sort(key=lambda r: r["_rowid"], reverse=flip)
    for part in reversed([p for p in params.get("order", "").split(",") if p]):
        col, _, direction = part.partition(".")
        rows.sort(key=lambda r: (r.get(col) is None, r.get(col)), reverse=direction.startswith("desc"))
    lo, hi = (int(x) for x in headers["Range"].split("-"))
    cols = params["select"].split(",")
    return Resp([{c: r.get(c) for c in cols} for r in rows[lo:hi + 1]])


requests.get = fake_get


class RecordingSb(supabase_client.Supabase):
    """The real select(), keeping what each table's reads actually returned."""
    seen: dict[str, list[dict]] = {}

    def select(self, table, *a, **k):
        rows = super().select(table, *a, **k)
        self.seen.setdefault(table, []).extend(rows)
        return rows


sb = RecordingSb("https://stub.supabase.co", "stub-key")


def keys(rows, cols):
    return sorted(tuple(r[c] for c in cols) for r in rows)

STAND_IN, REAL = "crd_prestage_x_7", "crd_real_7"
# 70 decks of 37 rows: page boundaries fall inside decks. The stand-in sits at a
# different position in each deck (as in real data), in two printings.
deck_rows, rowid = [], 0
for d in range(70):
    cards = [f"crd_{d}_{i}" for i in range(35)]
    pos = (d * 7) % 35
    cards[pos] = STAND_IN
    for i, cid in enumerate(cards):
        deck_rows.append({"deck_id": f"deck-{d:03d}", "card_id": cid, "printing": "Normal",
                          "quantity": 1, "_rowid": rowid})
        rowid += 1
    for cid in (STAND_IN, f"crd_{d}_x"):
        deck_rows.append({"deck_id": f"deck-{d:03d}", "card_id": cid, "printing": "Foil",
                          "quantity": 1, "_rowid": rowid})
        rowid += 1
TABLES["deck_cards"] = deck_rows
truth = sum(1 for r in deck_rows if r["card_id"] == STAND_IN)

print("1. retire_prestaged sees every deck row across page boundaries")
check(f"fixture spans pages ({len(deck_rows)} rows)", len(deck_rows) > 2000, True)
RecordingSb.seen.clear()
moved = rp.repoint_decks(sb, {STAND_IN: REAL}, commit=False)
check("the read returned every deck row exactly once (no page skipped or repeated one)",
      keys(RecordingSb.seen["deck_cards"], ("deck_id", "card_id", "printing")),
      keys(deck_rows, ("deck_id", "card_id", "printing")))
check("every stand-in deck row is found exactly once", moved.get(STAND_IN, 0), truth)

ver_rows, rowid = [], 0
for d in range(80):
    for v in range(1, 31):
        cards = [{"card_id": STAND_IN if v % 3 == 0 else f"crd_{v}", "printing": "Normal", "quantity": 1}]
        ver_rows.append({"deck_id": f"deck-{d:03d}", "version": v, "cards": cards, "_rowid": rowid})
        rowid += 1
TABLES["deck_versions"] = ver_rows
want_versions = sum(1 for r in ver_rows if r["version"] % 3 == 0)
RecordingSb.seen.clear()
got_versions = rp.repoint_versions(sb, {STAND_IN: REAL}, commit=False)
check("the read returned every deck version exactly once",
      keys(RecordingSb.seen["deck_versions"], ("deck_id", "version")),
      keys(ver_rows, ("deck_id", "version")))
check("every deck version holding the stand-in is found exactly once", got_versions, want_versions)

print("\n2. every read of a composite-key table orders on the whole key")
KEYS = {
    "deck_cards": ("deck_id", "card_id", "printing"),
    "deck_versions": ("deck_id", "version"),
    "card_localizations": ("card_id", "lang"),
}
seen = 0
for path in sorted(HERE.rglob("*.py")):
    if path.name.startswith("test_") or "backfill_cache" in path.parts:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "select" and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value in KEYS):
            continue
        seen += 1
        table = node.args[0].value
        kw = {k.arg: k.value for k in node.keywords}
        order = kw.get("order")
        order_s = order.value if isinstance(order, ast.Constant) else ""
        cols = {p.split(".")[0] for p in order_s.split(",") if p}
        check(f"{path.relative_to(HERE)}:{node.lineno} {table} orders on {'/'.join(KEYS[table])}",
              set(KEYS[table]) <= cols, True)
check("the scan found the call sites it is meant to police", seen >= 5, True)

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
