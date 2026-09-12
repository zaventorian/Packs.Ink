"""Guards that an EXCLUDED store actually leaves the board, in sync_elo_tracked_stores.py.

    python scripts/elo/test_excluded_stores.py

No network — _page, upsert and the DELETE are stubbed.

This exists because of a ruling that never took effect. Good Games - Indianapolis
(store 2237, ~165 mi out) was declared out of scope for this Chicagoland board and
written into EXCLUDED_STORE_IDS. It was still on the Scout tab months later
(reported 2026-09-12), for two independent reasons, either of which is enough on
its own and neither of which raises anything:

  1. THE LIST REACHED ONE CONSUMER. EXCLUDED_STORE_IDS lived inside
     discover_store_scs.py, which gates the Elo INGEST. `sync_elo_tracked_stores`
     writes `elo_tracked_stores` — the table that gates the Upcoming SCs tab, the
     Scout tab, whether a scouting sheet opens at all, the roster scrape and the
     Stores tab's history — and it had never heard of the list. Exactly the split
     elo_scope.py was created to prevent for ONE_OFF_EVENT_IDS.
  2. THE SYNC COULD ONLY ADD. Its write is an upsert with no delete anywhere, so
     a store that qualified once stayed tracked forever. Even a perfect rule
     change could not take a row back out.

So both halves are pinned here, plus the one thing that must NOT happen: a store
that merely failed to match this run is reported, never deleted. Pass 2 resolves
store_ids over the live RPH API, so one 404 would otherwise drop a real shop off
four surfaces on a green run.
"""
from __future__ import annotations
import os, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import elo_scope                      # noqa: E402
import sync_elo_tracked_stores as m   # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


def ok(label, cond):
    check(label, bool(cond), True)


EXCLUDED = 2237          # Good Games - Indianapolis
IN_REGION = 9001         # an ordinary tracked shop
CHICAGO_LAT, CHICAGO_LNG = 41.85, -87.65


# ── 1. one list, both consumers ───────────────────────────────────────────
print("the ruling lives in one place")
import discover_store_scs as d  # noqa: E402
ok("elo_scope owns EXCLUDED_STORE_IDS", hasattr(elo_scope, "EXCLUDED_STORE_IDS"))
ok("Good Games - Indianapolis is in it", EXCLUDED in elo_scope.EXCLUDED_STORE_IDS)
# `is` — not ==. A local copy that happens to hold the same ids today is exactly
# how the two sides drifted in the first place, and it compares equal.
ok("discover_store_scs shares the object", d.EXCLUDED_STORE_IDS is elo_scope.EXCLUDED_STORE_IDS)
ok("sync_elo_tracked_stores shares the object", m.EXCLUDED_STORE_IDS is elo_scope.EXCLUDED_STORE_IDS)
src = (HERE / "sync_elo_tracked_stores.py").read_text(encoding="utf-8")
ok("the sync defines no copy of its own", "EXCLUDED_STORE_IDS = {" not in src)


# ── 2. an excluded store never matches ────────────────────────────────────
print("\nan excluded store is never tracked")


def run(*, scs, tracked_now, history=None, dry=False, no_history=True):
    """Drive main() over stubbed tables; return (upserted, deleted, printed)."""
    hist = history or {}
    pages = {"set_championships": scs, "elo_tracked_stores": tracked_now,
             "elo_events": hist.get("elo_events", [])}
    sent, killed, out = {}, [], []

    m._page = lambda table, select, where="": list(pages.get(table, []))
    m.upsert = lambda rows: sent.update({"rows": rows})
    m._delete_ids = killed.append
    m.rph_store_of = lambda eid: hist.get("rph", {}).get(eid)
    # A module-global `print` shadows the builtin inside this module's functions
    # (local -> module -> builtins), so main()'s output is capturable without
    # touching sys.stdout. The module has no such attribute normally, hence del.
    m.print = lambda *a, **k: out.append(" ".join(str(x) for x in a))
    argv = sys.argv
    sys.argv = ["sync", *(["--dry-run"] if dry else []), *(["--no-history"] if no_history else [])]
    try:
        m.main()
    finally:
        sys.argv = argv
        del m.print
    return sent.get("rows", []), killed, "\n".join(out)


def sc(store_id, name, *, lat=CHICAGO_LAT, lng=CHICAGO_LNG, state="IL"):
    return {"store_id": store_id, "store_name": name, "state": state,
            "country": "US", "latitude": lat, "longitude": lng}


# Both sit on top of downtown Chicago, so the geo rule would take either — the
# only thing separating them is the exclusion.
rows, killed, out = run(
    scs=[sc(EXCLUDED, "Good Games - Indianapolis"), sc(IN_REGION, "Dice Dojo")],
    tracked_now=[])
ids = {r["store_id"] for r in rows}
check("the ordinary store is tracked", IN_REGION in ids, True)
check("the excluded store is not", EXCLUDED in ids, False)

# ⚠ The geo rule is an OR, so an exclusion has to beat every rule, not just the
# history one that put Indianapolis there originally.
m.MANUAL_TRACKED = {**m.MANUAL_TRACKED, EXCLUDED: "curated by mistake"}
rows, _, _ = run(scs=[sc(EXCLUDED, "Good Games - Indianapolis")], tracked_now=[])
check("not even a curated entry overrides the exclusion",
      EXCLUDED in {r["store_id"] for r in rows}, False)
m.MANUAL_TRACKED = {k: v for k, v in m.MANUAL_TRACKED.items() if k != EXCLUDED}

# Pass 2 resolves a store_id from RPH, so it needs its own guard — the shape that
# tracked Indianapolis in the first place was history-with-no-upcoming-SC.
rows, _, _ = run(
    scs=[], tracked_now=[], no_history=False,
    history={"elo_events": [{"event_id": 50, "store": "Good Games - Indianapolis"}],
             "rph": {50: {"id": EXCLUDED, "name": "Good Games - Indianapolis", "state": "IN"}}})
check("pass 2 refuses it too", EXCLUDED in {r["store_id"] for r in rows}, False)


# ── 3. …and is REMOVED, not merely not re-added ───────────────────────────
print("\nan exclusion removes a row that is already there")
rows, killed, out = run(
    scs=[sc(IN_REGION, "Dice Dojo")],
    tracked_now=[{"store_id": EXCLUDED, "store_name": "Good Games - Indianapolis"},
                 {"store_id": IN_REGION, "store_name": "Dice Dojo"}])
check("the excluded row is deleted", killed, [str(EXCLUDED)])
ok("and the removal is printed", "Good Games - Indianapolis" in out and "removing" in out)

# The whole point: an upsert can never do this.
ok("the delete is a DELETE, not an upsert",
    EXCLUDED not in {r["store_id"] for r in rows})

_, killed, out = run(scs=[sc(IN_REGION, "Dice Dojo")],
                     tracked_now=[{"store_id": IN_REGION, "store_name": "Dice Dojo"}])
check("nothing to remove deletes nothing", killed, [])

# ⚠ A dry run must be a dry run on BOTH writes. An exclusion that deletes during
# --dry-run makes the flag a lie in the one direction that loses data.
_, killed, out = run(
    scs=[sc(IN_REGION, "Dice Dojo")],
    tracked_now=[{"store_id": EXCLUDED, "store_name": "Good Games - Indianapolis"}],
    dry=True)
check("--dry-run deletes nothing", killed, [])
ok("…and says so", "dry run" in out)


# ── 4. drift is REPORTED, never deleted ───────────────────────────────────
print("\na store that merely failed to match is left alone")
# This is the dangerous direction. Pass 2 asks the live RPH API, so a 404 or a
# timeout makes a real shop look unmatched for one run; deleting on that evidence
# would drop it off the Upcoming SCs tab, the Scout tab, its scouting sheets and
# the Stores tab, silently, on a green run.
_, killed, out = run(
    scs=[sc(IN_REGION, "Dice Dojo")],
    tracked_now=[{"store_id": IN_REGION, "store_name": "Dice Dojo"},
                 {"store_id": 4242, "store_name": "Blipped Out Games"}])
check("an unmatched store is NOT deleted", killed, [])
ok("but it is named in the output", "Blipped Out Games" in out)
ok("and the report says how to remove it", "EXCLUDED_STORE_IDS" in out)

print("\n" + (f"{len(failures)} FAILED" if failures else "all passed"))
sys.exit(1 if failures else 0)
