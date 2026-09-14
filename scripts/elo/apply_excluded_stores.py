"""Enforce EXCLUDED_STORE_IDS against the local SQLite: flag every event at an
out-of-scope store `is_ignored = 1`.

    python scripts/elo/apply_excluded_stores.py            # dry run (default)
    python scripts/elo/apply_excluded_stores.py --apply
    python scripts/elo/apply_excluded_stores.py --apply --unflag   # reverse it

Why this is a script and not a one-off UPDATE. elo_scope.py already says the
exclusion list is the RECORD and `is_ignored` is only the applied state — but
nothing applied it. The two Indiana stores were flagged by hand in 2026-09, so
the ruling lived in a shell history rather than anywhere that runs again, and the
next person to widen the list would have had to know to go and do the same thing.
That is the shape this repo has already been bitten by twice (manual_merges.csv,
draw_overrides.py): a hand-edit of the DB is not a decision, it is a decision
that happens to be true right now.

Run from refresh_elo.py on every refresh, BEFORE elo.py — it is idempotent and
reconciles in one direction only (it never clears a flag unless --unflag says so,
because plenty of events are ignored for reasons that have nothing to do with
geography: a did-not-run event, a duplicate, a hand ruling).

⚠ Scope is derived from the event -> RPH store_id map, the same one
discover_store_scs builds and caches. An event whose store_id can't be resolved
is LEFT ALONE and reported, never guessed at: flagging on a failed lookup would
silently drop a real store off the board on a network blip, which is exactly the
failure prune_excluded() refuses to make on the Supabase side.
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import discover_wu_scs as d          # noqa: E402  http_json
from elo_scope import EXCLUDED_STORE_IDS  # noqa: E402

DB = HERE / "lorcana_elo.db"
STORE_ID_CACHE = HERE / "_store_id_cache.json"
META = "https://api.ravensburgerplay.com/api/v2/events/{eid}/"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def store_id_map(conn, refresh: bool) -> tuple[dict[int, int], list[int]]:
    """event_id -> RPH store_id for every rph event. Returns the map plus the
    events whose store could not be resolved (reported, never acted on)."""
    rows = [r[0] for r in conn.execute("SELECT event_id FROM events WHERE platform='rph'")]
    cache: dict[str, int | None] = {}
    if STORE_ID_CACHE.exists() and not refresh:
        cache = json.loads(STORE_ID_CACHE.read_text())

    todo = [e for e in rows if str(e) not in cache]
    if todo:
        print(f"  resolving store_id for {len(todo)} events (cached {len(cache)})...")

        def fetch(eid):
            try:
                m = d.http_json(META.format(eid=eid))
                return eid, (m.get("store") or {}).get("id"), True
            except Exception:
                return eid, None, False

        with ThreadPoolExecutor(max_workers=8) as ex:
            for eid, sid, ok in (f.result() for f in as_completed(
                    [ex.submit(fetch, e) for e in todo])):
                if ok:                       # never cache a transient failure
                    cache[str(eid)] = sid
        STORE_ID_CACHE.write_text(json.dumps(cache))

    out, unresolved = {}, []
    for e in rows:
        sid = cache.get(str(e))
        if sid is None:
            unresolved.append(e)
        else:
            out[e] = sid
    return out, unresolved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write the flags (default is a dry run)")
    ap.add_argument("--unflag", action="store_true",
                    help="clear is_ignored on excluded stores instead of setting it")
    ap.add_argument("--refresh-store-ids", action="store_true",
                    help="re-resolve every event's store_id instead of using the cache")
    args = ap.parse_args()

    if not EXCLUDED_STORE_IDS:
        print("EXCLUDED_STORE_IDS is empty — nothing to enforce.")
        return

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    by_event, unresolved = store_id_map(conn, args.refresh_store_ids)

    want = 0 if args.unflag else 1
    targets = [e for e, sid in by_event.items() if sid in EXCLUDED_STORE_IDS]
    if not targets:
        print("no events at any excluded store.")
        return

    q = ",".join("?" * len(targets))
    rows = conn.execute(
        f"SELECT event_id, event_date, store, season, is_ignored FROM events "
        f"WHERE event_id IN ({q}) ORDER BY event_date", targets).fetchall()

    changing = [r for r in rows if r["is_ignored"] != want]
    by_store: dict[int, list] = {}
    for r in rows:
        by_store.setdefault(by_event[r["event_id"]], []).append(r)

    verb = "unflag" if args.unflag else "flag"
    print(f"\n{len(EXCLUDED_STORE_IDS)} excluded store_id(s); "
          f"{len(rows)} event(s) at them, {len(changing)} to {verb}\n")
    for sid, evs in sorted(by_store.items(), key=lambda kv: -len(kv[1])):
        name = next((e["store"] for e in evs if e["store"]), "?")
        todo = sum(1 for e in evs if e["is_ignored"] != want)
        print(f"  store {sid:<6} {name[:34]:<35} {len(evs):>3} events, {todo:>3} to {verb}")

    if unresolved:
        # Never guessed at — see the module docstring.
        print(f"\n  ! {len(unresolved)} event(s) have no resolved store_id and were left alone")

    if not changing:
        print("\nalready consistent — nothing to do.")
        return
    if not args.apply:
        print(f"\ndry run — pass --apply to {verb} {len(changing)} event(s).")
        return

    ids = [r["event_id"] for r in changing]
    q2 = ",".join("?" * len(ids))
    with conn:
        conn.execute(f"UPDATE events SET is_ignored = ? WHERE event_id IN ({q2})",
                     [want, *ids])
    print(f"\n{verb}ged {len(ids)} event(s). Re-run elo.py to recompute, then export.")
    conn.close()


if __name__ == "__main__":
    main()
