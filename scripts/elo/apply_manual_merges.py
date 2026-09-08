"""Link two accounts the same person plays under, when nothing can infer it.

`suggest_aliases.py` only proposes exact/normalized matches and fuzzy pairs at
ratio >= 0.85. A player whose handles differ by more than that — heyzeusvee on
melee against heyzeus on RPH — will never be suggested, so somebody has to say
so. This applies those rulings.

⚠ It runs on EVERY refresh, from a committed file, and that is the point. The
canonical SQLite is downloaded from Supabase Storage at the top of
refresh_elo.py and uploaded at the bottom, so a merge applied anywhere else is
silently overwritten by the next refresh — the same trap as the one-off event
ingest. The merge does persist in the DB once applied; re-applying it every run
is what makes it survive a rebuild too, and costs one lookup per row.

Keyed on (platform, display_name) — the table's own UNIQUE constraint, so it
survives a rebuild. player_id would NOT: it is a bare autoincrement rowid, so a
rebuilt DB renumbers it and every row here would quietly point at a different
person. Names resolve case-insensitively, and also against external_username,
because the person reporting their own handle types it how they say it, not how
the platform stored it.

A row that resolves to nobody is an ERROR, not a shrug: two accounts silently
coming apart again is exactly the complaint this fixes. The failure prints the
nearest names on that platform, so one failed run tells you the real spelling.
"""
import argparse, csv, difflib, sqlite3, sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = Path(__file__).resolve().parent
DB_PATH = HERE / "lorcana_elo.db"
CSV_PATH = HERE / "manual_merges.csv"


def follow(conn, pid, seen=None):
    seen = seen or set()
    if pid in seen:
        return pid
    seen.add(pid)
    row = conn.execute("SELECT merged_into_id FROM players WHERE player_id=?", (pid,)).fetchone()
    return follow(conn, row[0], seen) if row and row[0] else pid


def resolve(conn, platform, name):
    """(player_id, error). Case-insensitive over display_name then external_username."""
    want = (name or "").strip()
    if not want:
        return None, "blank name"
    rows = conn.execute(
        "SELECT player_id, display_name FROM players WHERE platform=? COLLATE NOCASE"
        " AND (display_name=? COLLATE NOCASE OR external_username=? COLLATE NOCASE)",
        (platform, want, want)).fetchall()
    if len(rows) == 1:
        return rows[0][0], None
    if len(rows) > 1:
        got = ", ".join(f"{r[0]}:{r[1]!r}" for r in rows[:6])
        return None, f"{want!r} is ambiguous on {platform} — matches {got}"
    pool = [r[0] for r in conn.execute(
        "SELECT display_name FROM players WHERE platform=? COLLATE NOCASE", (platform,))]
    near = difflib.get_close_matches(want, pool, n=5, cutoff=0.5)
    hint = ("  nearest on " + platform + ": " + ", ".join(repr(n) for n in near)) if near \
        else f"  no similar name on {platform} ({len(pool)} players there)"
    return None, f"{want!r} not found on {platform}\n{hint}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--csv", default=str(CSV_PATH))
    ap.add_argument("--apply", action="store_true", help="write (default is a dry run)")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"no manual merges file at {path} — nothing to do")
        return

    conn = sqlite3.connect(args.db)
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    merged = already = 0
    errors = []

    for ln, row in enumerate(rows, 2):
        if not (row.get("src_name") or "").strip():
            continue
        if not (row.get("why") or "").strip():
            errors.append(f"line {ln}: every merge needs a why — it is a decision record")
            continue

        src, e1 = resolve(conn, (row.get("src_platform") or "melee").strip(), row["src_name"])
        dst, e2 = resolve(conn, (row.get("dst_platform") or "rph").strip(), row["dst_name"])
        if e1 or e2:
            errors += [f"line {ln}: {e}" for e in (e1, e2) if e]
            continue

        canonical = follow(conn, dst)
        if canonical == src:
            already += 1
            print(f"  ok      {row['src_name']!r} is already the canonical of {row['dst_name']!r}")
            continue

        cur = conn.execute("SELECT merged_into_id FROM players WHERE player_id=?", (src,)).fetchone()
        if cur and cur[0]:
            if follow(conn, cur[0]) == canonical:
                already += 1
                print(f"  ok      {row['src_name']!r} -> {row['dst_name']!r} (already linked)")
            else:
                errors.append(f"line {ln}: {row['src_name']!r} is already merged into player_id="
                              f"{cur[0]}, not {row['dst_name']!r} — resolve by hand")
            continue

        if args.apply:
            conn.execute("UPDATE players SET merged_into_id=? WHERE player_id=?", (canonical, src))
        merged += 1
        print(f"  MERGE   {row['src_platform']}:{row['src_name']!r} -> "
              f"{row['dst_platform']}:{row['dst_name']!r}  (player {src} -> {canonical})")

    if args.apply and not errors:
        conn.commit()
    conn.close()

    print(f"\nmerged={merged} already={already} errors={len(errors)}")
    if errors:
        print("\n".join("ERROR: " + e for e in errors), file=sys.stderr)
        sys.exit(1)
    if not args.apply:
        print("dry run — add --apply to write")


if __name__ == "__main__":
    main()
