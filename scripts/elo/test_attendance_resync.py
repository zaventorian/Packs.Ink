"""Guards what a RE-READ of an event's roster does to the rows we already hold, and
when an attendance run is allowed to stay green.

    python scripts/elo/test_attendance_resync.py

No network: urlopen is stubbed with an in-memory RPH and an in-memory PostgREST
(rph_event_attendance + rph_event_attendance_scans), and target_events is fixed.

  1. STALE ROWS. The scrape upserted on (event_id, best_identifier) and never
     removed anything, so a player renamed between two reads, or a registration
     withdrawn, stayed in the table beside the new row: two tickets for one seat.
     After a COMPLETE read, rows the read no longer contains are deleted — and
     only then. A failed or partial read deletes nothing; an EMPTY read of an
     event we hold rows for is not trusted (it neither deletes nor overwrites the
     scan); a read that would drop more than half an event's roster is held back.
     Deletes name rows positively (in.(...)), never not.in, so a quoting slip can
     only fail to delete — and names with commas, quotes and parens round-trip.
  2. GREEN RUNS. Unreadable events used to be printed and forgotten. Every run
     with any now leaves a ::warning::, and a run where a quarter or more of the
     reads failed on network/5xx errors (with at least 5 of them) exits 1 after
     writing everything it could read. 403/404 (withdrawn or private rosters) are
     permanent, so they warn but never fail the run.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import scrape_event_attendance as m  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


m.time.sleep = lambda s: None


class Resp(io.BytesIO):
    def __init__(self, body=b"[]", headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def postgrest_in(value: str) -> list[str]:
    """Parse a PostgREST in.(...) list the way PostgREST does: double-quoted
    items with backslash escapes, or bare items split on commas."""
    assert value.startswith("in.(") and value.endswith(")"), value
    body, out, i = value[4:-1], [], 0
    while i < len(body):
        if body[i] == '"':
            i += 1
            buf = []
            while body[i] != '"':
                if body[i] == "\\":
                    i += 1
                buf.append(body[i])
                i += 1
            out.append("".join(buf))
            i += 1
        else:
            j = body.find(",", i)
            j = len(body) if j < 0 else j
            out.append(body[i:j])
            i = j
        if i < len(body) and body[i] == ",":
            i += 1
    return out


ATT: dict[tuple[int, str], dict] = {}
SCANS: dict[int, dict] = {}
RPH: dict[int, object] = {}     # eid -> list of identifiers | "404" | "err" | ("partial", [...])
DELETE_URLS: list[str] = []


def reg(eid, ident):
    return {"best_identifier": ident, "user": {"id": hash(ident) % 1000, "best_identifier": ident},
            "registration_status": "COMPLETE", "final_place_in_standings": 1,
            "matches_won": 1, "matches_lost": 0, "matches_drawn": 0}


def fake_urlopen(req, timeout=None):
    url = req.full_url if hasattr(req, "full_url") else req
    method = req.get_method() if hasattr(req, "get_method") else "GET"
    if "ravensburgerplay.com" in url:
        eid = int(re.search(r"/events/(\d+)/registrations", url).group(1))
        page = int(parse_qs(urlparse(url).query).get("page", ["1"])[0])
        spec = RPH[eid]
        if spec == "404":
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))
        if spec == "err":
            raise urllib.error.URLError("connection reset")
        if isinstance(spec, tuple):                     # page 1 fine, page 2 fails
            if page == 2:
                raise urllib.error.URLError("connection reset")
            return Resp(json.dumps({"results": [reg(eid, i) for i in spec[1]],
                                    "next": "page2"}).encode())
        return Resp(json.dumps({"results": [reg(eid, i) for i in spec], "next": None}).encode())

    parsed = urlparse(url)
    table = parsed.path.rsplit("/", 1)[-1]
    q = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
    if method == "POST":
        rows = json.loads(req.data.decode())
        for r in rows:
            if table == "rph_event_attendance":
                ATT[(r["event_id"], r["best_identifier"])] = r
            elif table == "rph_event_attendance_scans":
                SCANS[r["event_id"]] = r
        return Resp(b"")
    if method == "DELETE":
        assert table == "rph_event_attendance", table
        DELETE_URLS.append(url)
        assert "not.in" not in url, "deletes must name rows positively"
        eid = int(q["event_id"].split(".", 1)[1])
        idents = postgrest_in(q["best_identifier"])
        gone = [k for k in list(ATT) if k[0] == eid and k[1] in idents]
        for k in gone:
            del ATT[k]
        return Resp(b"[]")
    if method == "GET" and table == "rph_event_attendance":
        eids = [int(x) for x in re.findall(r"\d+", q["event_id"])]
        rows = sorted(({"event_id": e, "best_identifier": i} for (e, i) in ATT if e in eids),
                      key=lambda r: (r["event_id"], r["best_identifier"]))
        off, lim = int(q.get("offset", 0)), int(q.get("limit", 1000))
        return Resp(json.dumps(rows[off:off + lim]).encode())
    raise AssertionError(f"unexpected {method} {url}")


urllib.request.urlopen = fake_urlopen


def seed(eid, idents):
    for i in idents:
        ATT[(eid, i)] = {"event_id": eid, "best_identifier": i}
    SCANS[eid] = {"event_id": eid, "player_count": len(idents), "row_count": len(idents),
                  "scraped_at": "2026-09-01T00:00:00+00:00"}


def run(events, *argv):
    m.target_events = lambda refresh, limit, recheck_days=0, now=None: [
        {"event_id": e, "store_id": 1, "store_name": "S", "start_datetime": "2026-09-30T18:00:00+00:00",
         "_recheck": True} for e in events]
    sys.argv = ["scrape_event_attendance.py", "--recheck-days", "3", *argv]
    out = io.StringIO()
    code = 0
    try:
        with redirect_stdout(out):
            m.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue()


def held(eid):
    return sorted(i for (e, i) in ATT if e == eid)


print("1. a complete re-read replaces the roster")
seed(1, ["Alice", "Bob", "Carol"])
RPH[1] = ["Alice", "Bob", "Dana"]                  # Carol withdrew / renamed to Dana
seed(2, ["Erin", "Finn"])
RPH[2] = "err"                                     # unreadable: nothing may change
seed(3, ["G1", "G2", "G3", "G4", "G5", "G6"])
RPH[3] = ["G1"]                                    # would drop 5 of 6: held back
seed(4, ["Hal", "Ivy"])
RPH[4] = []                                        # empty read of a held event
seed(5, ["Smith, J. (Jr)", 'Quo"te\\d', "Zed"])
RPH[5] = ["Zed", "New"]
seed(6, ["Kim", "Lee"])
RPH[6] = ("partial", ["Kim"])                      # page 2 fails
code, out = run([1, 2, 3, 4, 5, 6])
check("stale row deleted, renamed row kept", held(1), ["Alice", "Bob", "Dana"])
check("an unreadable event keeps every row", held(2), ["Erin", "Finn"])
check("a read that would drop most of the roster deletes nothing", held(3),
      ["G1", "G2", "G3", "G4", "G5", "G6"])
check("an empty read of a held event deletes nothing", held(4), ["Hal", "Ivy"])
check("...and does not overwrite its scan row", SCANS[4]["row_count"], 2)
check("names with commas, quotes, backslashes and parens are deleted exactly", held(5), ["New", "Zed"])
check("a partial read deletes nothing", held(6), ["Kim", "Lee"])
check("no delete was ever sent as not.in", any("not.in" in u for u in DELETE_URLS), False)
check("the held-back event is called out", "::warning" in out and "3" in out, True)

print("\n2. dry run deletes nothing")
ATT.clear(); SCANS.clear(); DELETE_URLS.clear()
seed(1, ["Alice", "Bob", "Carol"])
RPH[1] = ["Alice", "Bob"]
run([1], "--dry-run")
check("--dry-run leaves the stale row", held(1), ["Alice", "Bob", "Carol"])
check("--dry-run sends no DELETE", DELETE_URLS, [])

print("\n3. when the run is allowed to stay green")
ATT.clear(); SCANS.clear()
for e in range(10, 20):
    RPH[e] = ["P"]
code, out = run(list(range(10, 20)))
check("all readable: exit 0, no warning", (code, "::warning" in out), (0, False))
for e in range(10, 20):
    RPH[e] = "404"
code, out = run(list(range(10, 20)))
check("withdrawn/private rosters (404) warn but never fail", (code, "::warning" in out), (0, True))
for e in range(10, 20):
    RPH[e] = "err" if e < 15 else ["P"]
code, out = run(list(range(10, 20)))
check("half the reads failing on network errors exits 1", code, 1)
check("...after writing what it could read", all((e, "P") in ATT for e in range(15, 20)), True)
for e in range(10, 30):
    RPH[e] = "err" if e < 12 else ["P"]
code, out = run(list(range(10, 30)))
check("two network failures in twenty is a warning, not a red run", (code, "::warning" in out), (0, True))

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
