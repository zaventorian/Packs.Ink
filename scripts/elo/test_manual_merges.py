"""Guards for apply_manual_merges.py — no network, temp SQLite."""
import csv, sqlite3, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  got={got!r} want={want!r}"))
    if not ok:
        FAILS.append(label)


def fixture(td, rows):
    db = Path(td) / "m.db"
    c = sqlite3.connect(db)
    c.executescript((HERE / "schema.sql").read_text())
    for pid, name, plat in rows:
        c.execute("INSERT INTO players (player_id,display_name,platform) VALUES (?,?,?)",
                  (pid, name, plat))
    c.commit(); c.close()
    return db


def write_csv(td, rows, name="m.csv"):
    p = Path(td) / name
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["src_platform", "src_name", "dst_platform", "dst_name", "why"])
        w.writerows(rows)
    return p


def run(db, csvp, apply=True):
    cmd = [sys.executable, str(HERE / "apply_manual_merges.py"), "--db", str(db), "--csv", str(csvp)]
    if apply:
        cmd.append("--apply")
    return subprocess.run(cmd, capture_output=True, text=True)


def merged_of(db, pid):
    c = sqlite3.connect(db)
    v = c.execute("SELECT merged_into_id FROM players WHERE player_id=?", (pid,)).fetchone()[0]
    c.close()
    return v


PLAYERS = [(1, "heyzeusvee", "melee"), (2, "heyzeus", "rph"),
           (3, "SomeoneElse", "melee"), (4, "Primary", "rph"), (5, "OldAlt", "rph")]

print("resolving by name")
with tempfile.TemporaryDirectory() as td:
    db = fixture(td, PLAYERS)
    r = run(db, write_csv(td, [["melee", "heyzeusvee", "rph", "heyzeus", "asked"]]))
    check("a merge by name links the two", merged_of(db, 1), 2)
    check("...and exits clean", r.returncode, 0)
    check("...and touches nobody else", merged_of(db, 3), None)

print("case and idempotence")
with tempfile.TemporaryDirectory() as td:
    db = fixture(td, PLAYERS)
    # the person types their handle how they say it, not how the platform stored it
    c = sqlite3.connect(db)
    c.execute("UPDATE players SET display_name='HeyZeusVee' WHERE player_id=1")
    c.execute("UPDATE players SET display_name='HeyZeus' WHERE player_id=2")
    c.commit(); c.close()
    p = write_csv(td, [["melee", "heyzeusvee", "rph", "heyzeus", "asked"]])
    check("case-insensitive resolution", (run(db, p).returncode, merged_of(db, 1)), (0, 2))
    r2 = run(db, p)
    check("re-running is a no-op, not an error", r2.returncode, 0)
    check("...and says so", "already linked" in r2.stdout, True)

print("chains")
with tempfile.TemporaryDirectory() as td:
    db = fixture(td, PLAYERS)
    c = sqlite3.connect(db)
    c.execute("UPDATE players SET merged_into_id=4 WHERE player_id=5")  # OldAlt -> Primary
    c.commit(); c.close()
    run(db, write_csv(td, [["melee", "heyzeusvee", "rph", "OldAlt", "asked"]]))
    check("points at the CANONICAL, never a merged-away target", merged_of(db, 1), 4)

print("the loud failures")
with tempfile.TemporaryDirectory() as td:
    db = fixture(td, PLAYERS)
    r = run(db, write_csv(td, [["melee", "nobody-by-that-name", "rph", "heyzeus", "asked"]]))
    check("an unresolved name fails the run", r.returncode, 1)
    check("...and names the nearest handles, so the log IS the lookup",
          "nearest on melee" in r.stderr or "no similar name" in r.stderr, True)

    r = run(db, write_csv(td, [["melee", "heyzeusvee", "rph", "heyzeus", ""]]))
    check("a merge with no reason fails", r.returncode, 1)
    check("...and nothing is written", merged_of(db, 1), None)

    # already linked somewhere else: silently repointing would move a whole history
    c = sqlite3.connect(db)
    c.execute("UPDATE players SET merged_into_id=4 WHERE player_id=1")
    c.commit(); c.close()
    r = run(db, write_csv(td, [["melee", "heyzeusvee", "rph", "heyzeus", "asked"]]))
    check("a conflicting existing merge fails rather than repointing", r.returncode, 1)
    check("...and leaves the old link alone", merged_of(db, 1), 4)

print("dry run")
with tempfile.TemporaryDirectory() as td:
    db = fixture(td, PLAYERS)
    r = run(db, write_csv(td, [["melee", "heyzeusvee", "rph", "heyzeus", "asked"]]), apply=False)
    check("dry run writes nothing", merged_of(db, 1), None)
    check("...and is the default", "add --apply" in r.stdout, True)

print("the shipped file")
rows = list(csv.DictReader(open(HERE / "manual_merges.csv", encoding="utf-8")))
check("every shipped merge carries a reason",
      all((r.get("why") or "").strip() for r in rows), True)
check("...and a src and dst on both platforms",
      all(r.get("src_name") and r.get("dst_name") and r.get("src_platform") and r.get("dst_platform")
          for r in rows), True)

print("\n" + ("FAILED: " + ", ".join(FAILS) if FAILS else "all passed"))
sys.exit(1 if FAILS else 0)
