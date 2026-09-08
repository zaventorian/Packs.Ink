"""Guards the store-driven ingest across a SET ROTATION, in discover_store_scs.py.

    python scripts/elo/test_season_seed.py

No network — pull_set_scs and ingest_event are stubbed, the DB is a temp SQLite.

This exists because of a silent freeze: when the current set rotated to Attack
of the Vine!, discover_store_scs found all 68 SCs at tracked stores and then
refused to ingest a single one, because season_label_for() found no existing
"Attack of the Vine! …" label in the DB and the code skipped the whole set. The
weekly refresh stayed GREEN — ingest.py skipped its 50 already-ingested Wilds
Unknown events, the discovery step is deliberately soft — so the board simply
stopped moving with nothing red anywhere. Four things are locked down:

  1. SEEDING. A set with no events yet must be ingested, not skipped. This is
     the whole bug; every other case here already worked.
  2. SCOPE. Seeding must not widen who counts. A candidate still has to sit at
     a tracked store_id, and EXCLUDED_STORE_IDS still wins.
  3. LABEL SHAPE. The derived label must start with the set name, because the
     UI's eloSeasonSetLabel() longest-prefix matches it against MAINLINE_SETS
     to head the Stores columns. A label that doesn't match reads "Unsorted".
  4. EXISTING SETS. A set we already have events for keeps its stored label —
     backfilling Wilds Unknown must never invent a second season for it.
"""
from __future__ import annotations
import os, sqlite3, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_store_scs as m  # noqa: E402

failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


def ev(eid, date, store_id, name="Set Championship"):
    return {"id": eid, "start_datetime": f"{date}T15:00:00+00:00", "name": name,
            "display_status": "complete", "registered_user_count": 12,
            "store": {"id": store_id, "name": f"Store {store_id}"}}


def run_main(argv, candidates, tracked, ingested=()):
    """Drive main() with the network and the DB replaced. Returns the
    (event_id, season) pairs it tried to ingest, in call order."""
    got = []
    orig = (m.pull_set_scs, m.tracked_store_ids, m.ingested_event_ids,
            m.sibling_location, m.ing.ingest_event, m.d.fetch_set_names,
            m.d.build_aliases, m.d.fetch_current_set, sys.argv)
    m.pull_set_scs = lambda s, nets, ss, al: {e["id"]: e for e in candidates}
    m.tracked_store_ids = lambda refresh: (set(tracked), {i: {f"Store {i}"} for i in tracked})
    m.ingested_event_ids = lambda: set(ingested)
    m.sibling_location = lambda n: "Chicago, IL"
    m.ing.ingest_event = lambda eid, store=None, location=None, season=None: (
        got.append((eid, season)) or (eid, "ok", "stubbed"))
    m.d.fetch_set_names = lambda: []
    m.d.build_aliases = lambda ss: {}
    m.d.fetch_current_set = lambda: "Attack of the Vine!"
    sys.argv = ["discover_store_scs.py", *argv]
    try:
        m.main()
    finally:
        (m.pull_set_scs, m.tracked_store_ids, m.ingested_event_ids,
         m.sibling_location, m.ing.ingest_event, m.d.fetch_set_names,
         m.d.build_aliases, m.d.fetch_current_set, sys.argv) = orig
    return got


def seed_db(path, rows):
    conn = sqlite3.connect(path)
    conn.executescript((HERE / "schema.sql").read_text())
    conn.executemany(
        "INSERT INTO events (event_id, name, store, season, is_ignored, platform) "
        "VALUES (?,?,?,?,0,'rph')", rows)
    conn.commit(); conn.close()


print("season_label_from_date reproduces the labels already in the DB")
for s, iso, want in [("Wilds Unknown", "2026-06-20", "Wilds Unknown Summer 2026"),
                     ("Fabled", "2025-10-04", "Fabled Fall 2025"),
                     ("Whispers in the Well", "2026-03-14",
                      "Whispers in the Well Spring 2026")]:
    check(f"{s} @ {iso}", m.season_label_from_date(s, iso), want)

print("\nseason boundaries (a December window names the winter that ENDS next year)")
for iso, want in [("2026-09-05T15:00:00+00:00", "X Fall 2026"), ("2026-11-30", "X Fall 2026"),
                  ("2026-12-06", "X Winter 2027"), ("2027-02-28", "X Winter 2027"),
                  ("2026-03-01", "X Spring 2026"), ("2026-08-31", "X Summer 2026")]:
    check(iso, m.season_label_from_date("X", iso), want)

print("\nname_nets is unchanged for the sets that had hand-written entries")
check("Wilds Unknown", m.name_nets("Wilds Unknown"),
      ["Wilds Unknown Set Championship", "Wilds Unknown - Set Championship",
       "Set Championship Wilds Unknown"])
check("Winterspell", m.name_nets("Winterspell"),
      ["Winterspell Set Championship", "Winterspell - Set Championship",
       "Set Championship Winterspell"])
check("a rotation needs no edit", len(m.name_nets("Attack of the Vine!")), 3)

with tempfile.TemporaryDirectory() as td:
    m.DB = Path(td) / "elo.db"
    m.STORE_ID_CACHE = Path(td) / "cache.json"
    # A DB that only knows about last set, exactly like the live one at rotation.
    seed_db(m.DB, [(1, "WU SC", "Store 10", "Wilds Unknown Summer 2026")])

    print("\nrotation: a set with no events yet is SEEDED, not skipped")
    got = run_main(["--ingest"],
                   [ev(811279, "2026-09-05", 10), ev(788052, "2026-09-06", 11)],
                   tracked=[10, 11])
    check("both SCs ingested", [e for e, _ in got], [811279, 788052])
    check("derived from the FIRST SC date", sorted({s for _, s in got}),
          ["Attack of the Vine! Fall 2026"])
    check("label starts with the set name (eloSeasonSetLabel)",
          got[0][1].startswith("Attack of the Vine!"), True)

    print("\n--season-label names it by hand")
    got = run_main(["--ingest", "--season-label", "Attack of the Vine! Autumn 2026"],
                   [ev(811279, "2026-09-05", 10)], tracked=[10])
    check("override used", [s for _, s in got], ["Attack of the Vine! Autumn 2026"])

    print("\nseeding does NOT widen scope")
    got = run_main(["--ingest"],
                   [ev(811279, "2026-09-05", 10),      # tracked
                    ev(999001, "2026-09-05", 4242),    # never counted
                    ev(999002, "2026-09-05", 2237),    # EXCLUDED_STORE_IDS
                    ev(999003, "2026-09-05", 11)],     # tracked but already ingested
                   tracked=[10, 11, 2237], ingested=[999003])
    check("untracked / excluded / already-ingested all dropped",
          [e for e, _ in got], [811279])

    print("\na set we already have keeps its stored label")
    got = run_main(["--ingest", "--sets", "Wilds Unknown"],
                   [ev(700001, "2026-09-05", 10)], tracked=[10])
    check("no second season invented", [s for _, s in got],
          ["Wilds Unknown Summer 2026"])
    got = run_main(["--ingest", "--sets", "Wilds Unknown",
                    "--season-label", "Wilds Unknown Fall 2026"],
                   [ev(700002, "2026-09-05", 10)], tracked=[10])
    check("--season-label can't rename an existing season", [s for _, s in got],
          ["Wilds Unknown Summer 2026"])

    print("\nwithout --ingest nothing is written")
    check("read-only", run_main([], [ev(811279, "2026-09-05", 10)], tracked=[10]), [])

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all season-seed guards pass")
