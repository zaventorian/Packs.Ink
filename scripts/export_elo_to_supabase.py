"""Export Chicagoland Lorcana ELO data from local SQLite into Supabase.

Reads:  scripts/elo/lorcana_elo.db (the canonical project SQLite DB)
Writes: public.elo_events, elo_players, elo_matches, elo_ratings on Supabase.

Idempotent: every table upserts on its natural PK. Re-run after adding seasons
or merging aliases — the leaderboard view always reflects the latest state.

Prerequisites:
  1. Apply supabase/56_elo.sql in your Supabase SQL editor (one-time DDL).
  2. scripts/.env has SUPABASE_URL + SUPABASE_SERVICE_KEY (already in place
     for the existing ETL).

Usage:
    python scripts/export_elo_to_supabase.py
    python scripts/export_elo_to_supabase.py --dry-run    # count + first row preview
    python scripts/export_elo_to_supabase.py --table events  # one table only
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from supabase_client import Supabase

SQLITE_PATH = Path(__file__).parent / "elo" / "lorcana_elo.db"


def fetch_all(conn: sqlite3.Connection, sql: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql)]


def to_bool(x) -> bool:
    return bool(x) if x is not None else False


def export_events(conn, sb: Supabase, dry: bool) -> int:
    rows = fetch_all(
        conn,
        """
        SELECT event_id, name, store, location, event_date, season,
               num_players, status, platform, is_ignored, notes
        FROM events
        """,
    )
    for r in rows:
        r["is_ignored"] = to_bool(r["is_ignored"])
    if dry:
        print(f"  events:  {len(rows)} rows; first: {rows[0] if rows else None}")
        return len(rows)
    sb.upsert("elo_events", rows, on_conflict="event_id")
    return len(rows)


def export_players(conn, sb: Supabase, dry: bool) -> int:
    # Two-pass because merged_into_id is a self-FK — insert all rows with NULL
    # merge first (avoids FK ordering issues since A→B can happen within a batch),
    # then re-upsert merged players with FULL fields (PostgREST treats a row
    # missing NOT NULL columns as an INSERT attempt → 23502).
    rows = fetch_all(
        conn,
        """
        SELECT player_id, display_name, platform, external_username,
               NULL AS merged_into_id, first_event_id
        FROM players
        """,
    )
    if dry:
        merged = fetch_all(conn, "SELECT COUNT(*) AS n FROM players WHERE merged_into_id IS NOT NULL")
        print(f"  players: {len(rows)} rows ({merged[0]['n']} have merge targets); first: {rows[0] if rows else None}")
        return len(rows)

    # --- Park moved names first (defeats the (platform,display_name) UNIQUE key) ---
    # A bulk upsert can't replicate SQLite's transactional stash-then-rename, so a
    # player taking a name another not-yet-updated remote row still holds 23505s on
    # elo_players_platform_display_name_key (e.g. a RENAME+MERGE where the absorbed
    # player still holds the new name in Supabase). Park every player whose name
    # changed since the last export onto a unique sentinel, freeing all contested
    # names before we assign the real ones. This is sufficient: apply_renames
    # guarantees no two LOCAL players share a name, so any remote holder of a
    # contested name is necessarily one of these moved players.
    remote = {r["player_id"]: r["display_name"]
              for r in sb.select("elo_players", "player_id,display_name")}
    moved = [r for r in rows if remote.get(r["player_id"]) != r["display_name"]]
    if moved:
        park = [{**r, "display_name": f"__migrate__{r['player_id']}"} for r in moved]
        print(f"  parking {len(park)} moved name(s) on sentinels first")
        sb.upsert("elo_players", park, on_conflict="player_id")

    sb.upsert("elo_players", rows, on_conflict="player_id")

    merge_rows = fetch_all(
        conn,
        """
        SELECT player_id, display_name, platform, external_username,
               merged_into_id, first_event_id
        FROM players WHERE merged_into_id IS NOT NULL
        """,
    )
    if merge_rows:
        sb.upsert("elo_players", merge_rows, on_conflict="player_id")
    return len(rows)


def export_matches(conn, sb: Supabase, dry: bool) -> int:
    rows = fetch_all(
        conn,
        """
        SELECT match_id, event_id, round_id, round_number, round_type,
               table_number, player1_id, player2_id, winner_id,
               games_won_p1, games_won_p2, is_bye, source
        FROM matches
        """,
    )
    for r in rows:
        r["is_bye"] = to_bool(r["is_bye"])
    if dry:
        print(f"  matches: {len(rows)} rows; first: {rows[0] if rows else None}")
        return len(rows)
    sb.upsert("elo_matches", rows, on_conflict="match_id", batch=200)
    return len(rows)


def export_event_standings(conn, sb: Supabase, dry: bool) -> int:
    """Push the official per-event standings backfilled by
    backfill_official_standings.py. Idempotent on (event_id, player_id)."""
    rows = fetch_all(conn, """
        SELECT event_id, player_id, place, matches_won, matches_lost, matches_drawn,
               match_points, mw_pct, omw_pct, gw_pct, locked
        FROM event_standings_official
    """)
    for r in rows:
        r["locked"] = to_bool(r["locked"])
    if dry:
        print(f"  standings: {len(rows)} rows; first: {rows[0] if rows else None}")
        return len(rows)
    sb.upsert("elo_event_standings_official", rows,
              on_conflict="event_id,player_id", batch=500)
    return len(rows)


def export_ratings(conn, sb: Supabase, dry: bool) -> int:
    # rating_id is bigserial on the Supabase side; we don't send it. We dedupe
    # on (player_id, match_id) — UNIQUE constraint in the schema.
    rows = fetch_all(
        conn,
        """
        SELECT player_id, match_id, rating_before, rating_after,
               opponent_id, opponent_rating, k_factor, score
        FROM ratings
        """,
    )
    if dry:
        print(f"  ratings: {len(rows)} rows; first: {rows[0] if rows else None}")
        return len(rows)
    sb.upsert("elo_ratings", rows, on_conflict="player_id,match_id", batch=500)
    return len(rows)


def delete_orphans(conn, sb: Supabase, dry: bool) -> None:
    """Remove rows from Supabase that no longer exist in local SQLite.

    Without this, every previous re-export accumulates stale rows. Matches we
    deleted locally (e.g. dropped Emporium QF) stayed in Supabase as orphans,
    polluting the leaderboard views that JOIN through them. Cascade-delete on
    matches→ratings keeps things tidy automatically once the orphan match goes."""
    import requests

    # Pull all local IDs
    local_event_ids = {r["event_id"] for r in fetch_all(conn, "SELECT event_id FROM events")}
    local_player_ids = {r["player_id"] for r in fetch_all(conn, "SELECT player_id FROM players")}
    local_match_ids = {r["match_id"] for r in fetch_all(conn, "SELECT match_id FROM matches")}

    # For each table, fetch IDs from Supabase and diff. PostgREST caps page
    # size at 1000 server-side; Range must use that ceiling and we paginate.
    def fetch_ids(table, col):
        ids = set()
        PAGE = 1000
        start = 0
        while True:
            r = requests.get(
                f"{sb.url}/rest/v1/{table}?select={col}&order={col}.asc",
                headers={**sb._headers(), "Range-Unit": "items",
                         "Range": f"{start}-{start+PAGE-1}"},
                timeout=60,
            )
            if not r.ok and r.status_code != 206:
                raise RuntimeError(f"fetch_ids {table} failed: {r.status_code} {r.text[:200]}")
            data = r.json()
            if not data: break
            ids.update(row[col] for row in data)
            if len(data) < PAGE: break
            start += PAGE
        return ids

    def delete_in(table, col, ids_to_delete):
        if not ids_to_delete: return 0
        deleted = 0
        ids = list(ids_to_delete)
        for i in range(0, len(ids), 200):
            batch = ids[i:i+200]
            r = requests.delete(
                f"{sb.url}/rest/v1/{table}?{col}=in.({','.join(str(x) for x in batch)})",
                headers={**sb._headers(), "Prefer": "return=minimal"},
                timeout=60,
            )
            if not r.ok:
                raise RuntimeError(f"delete {table} failed: {r.status_code} {r.text[:200]}")
            deleted += len(batch)
        return deleted

    for table, col, local_set in [
        ("elo_matches", "match_id", local_match_ids),
        ("elo_players", "player_id", local_player_ids),
        ("elo_events", "event_id", local_event_ids),
    ]:
        sb_ids = fetch_ids(table, col)
        orphans = sb_ids - local_set
        # Safety guard against catastrophic wipes. An empty local set (or a
        # huge orphan fraction) almost always means the local SQLite was
        # empty/corrupt/partial — e.g. a truncated Storage download — NOT that
        # the user genuinely deleted nearly every row. Sweeping here would
        # delete the entire remote table and cascade matches→ratings. The
        # weekly CI exits 0 on an empty-but-valid DB, so nothing else stops it.
        suspicious = (not local_set) or (bool(sb_ids) and len(orphans) > 0.6 * len(sb_ids))
        if suspicious and not dry:
            raise RuntimeError(
                f"refusing to sweep {table}: {len(orphans)}/{len(sb_ids)} remote rows "
                f"flagged as orphans (local has {len(local_set)} ids). Local SQLite "
                f"looks empty/corrupt/partial — aborting before it deletes real data."
            )
        if dry:
            flag = "  ⚠ SUSPICIOUS — real run would REFUSE" if suspicious else ""
            print(f"  {table}: {len(orphans)} orphans (would delete){flag}")
        elif orphans:
            # elo_players.first_event_id has no ON DELETE behavior on its FK to
            # elo_events. Before deleting orphan events, clear any first_event_id
            # references pointing to them — otherwise the DELETE blows up with
            # 23503 (FK violation).
            if table == "elo_events":
                for i in range(0, len(orphans), 200):
                    batch = list(orphans)[i:i+200]
                    rr = requests.patch(
                        f"{sb.url}/rest/v1/elo_players?first_event_id=in.({','.join(str(x) for x in batch)})",
                        headers={**sb._headers(), "Content-Type": "application/json",
                                 "Prefer": "return=minimal"},
                        json={"first_event_id": None},
                        timeout=60,
                    )
                    if not rr.ok:
                        raise RuntimeError(f"clear first_event_id failed: {rr.status_code} {rr.text[:200]}")
            n = delete_in(table, col, orphans)
            print(f"  {table}: deleted {n} orphan rows")

    # elo_ratings has its own orphan class: after an alias merge, local recompute
    # writes ratings under the CANONICAL player_id only — but Supabase still
    # holds the rows under the merged-source player_id from prior exports.
    # FK cascade doesn't fire (the source player_id row still exists). Sweep them
    # by deleting any rating whose player_id corresponds to a merged-source player.
    merged_pids = [r["player_id"] for r in fetch_all(conn,
        "SELECT player_id FROM players WHERE merged_into_id IS NOT NULL")]
    if dry:
        # Approximate the count via a HEAD on each batch (could exceed 200 ids per
        # batch but a single count probe is enough to tell the user the magnitude).
        r = requests.get(
            f"{sb.url}/rest/v1/elo_ratings?player_id=in.({','.join(str(x) for x in merged_pids[:500])})&select=rating_id",
            headers={**sb._headers(), "Prefer": "count=exact", "Range": "0-0", "Range-Unit": "items"},
            timeout=60,
        )
        approx = int(r.headers.get("Content-Range", "0/0").split("/")[1] or 0)
        print(f"  elo_ratings (under merged-source player_ids): ~{approx} orphans (would delete)")
    elif merged_pids:
        total = 0
        for i in range(0, len(merged_pids), 200):
            batch = merged_pids[i:i+200]
            r = requests.delete(
                f"{sb.url}/rest/v1/elo_ratings?player_id=in.({','.join(str(x) for x in batch)})",
                headers={**sb._headers(), "Prefer": "return=minimal"},
                timeout=60,
            )
            if not r.ok:
                raise RuntimeError(f"delete elo_ratings failed: {r.status_code} {r.text[:200]}")
            total += len(batch)
        print(f"  elo_ratings: deleted ratings under {total} merged-source player_ids")

    # elo_ratings orphans from IGNORED events: elo.py never produces ratings for
    # matches in is_ignored events, but a prior export (when the event was live)
    # left their ratings in Supabase. The upsert won't overwrite them (different
    # rows) and the orphan passes above won't catch them (the match/event still
    # exist locally, just flagged ignored). Without this, dropping a store from
    # scope via is_ignored leaves it on the leaderboard + in player history.
    ignored_match_ids = [r["match_id"] for r in fetch_all(conn,
        "SELECT m.match_id FROM matches m JOIN events e ON e.event_id=m.event_id WHERE e.is_ignored=1")]
    if dry:
        print(f"  elo_ratings (in ignored events): {len(ignored_match_ids)} matches' ratings (would delete)")
    elif ignored_match_ids:
        total = 0
        for i in range(0, len(ignored_match_ids), 200):
            batch = ignored_match_ids[i:i+200]
            r = requests.delete(
                f"{sb.url}/rest/v1/elo_ratings?match_id=in.({','.join(str(x) for x in batch)})",
                headers={**sb._headers(), "Prefer": "return=minimal"},
                timeout=60,
            )
            if not r.ok:
                raise RuntimeError(f"delete ignored-event ratings failed: {r.status_code} {r.text[:200]}")
            total += len(batch)
        print(f"  elo_ratings: swept ratings for {total} matches in ignored events")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--table", choices=["events", "players", "matches", "ratings", "standings"], default=None,
                    help="export only this table")
    args = ap.parse_args()

    if not SQLITE_PATH.exists():
        sys.exit(f"SQLite DB not found at {SQLITE_PATH}")

    load_dotenv(Path(__file__).parent / ".env")
    sb = Supabase()
    conn = sqlite3.connect(SQLITE_PATH)

    plan = ["events", "players", "matches", "ratings", "standings"]
    if args.table:
        plan = [args.table]

    funcs = {
        "events": export_events,
        "players": export_players,
        "matches": export_matches,
        "ratings": export_ratings,
        "standings": export_event_standings,
    }

    print(f"{'DRY-RUN ' if args.dry_run else ''}exporting {', '.join(plan)} from {SQLITE_PATH.name}")
    for t in plan:
        n = funcs[t](conn, sb, args.dry_run)
        if not args.dry_run:
            print(f"  {t}: upserted {n} rows")

    # Always sweep orphans after a full export (or in dry-run, report the count).
    if args.table is None:
        print("\norphan cleanup:")
        delete_orphans(conn, sb, args.dry_run)

    conn.close()
    print("done.")


if __name__ == "__main__":
    main()
