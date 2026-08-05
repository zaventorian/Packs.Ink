"""
cleanup_scan_samples.py — enforces the card scanner's photo-retention promise.

The public-beta notice (and the privacy page's "Card scanner" section) tells
users their scan photos are deleted after 12 months, and deleted sooner on
request. This script is the thing that makes both of those true. If it stops
running, the promise silently becomes false — so it exits non-zero on failure
rather than shrugging, and the workflow that calls it is expected to alert.

Two modes:

  retention (default)   delete every scan_samples row older than --months
                        (default 12) and the storage objects it points at.

  --user <uuid>         delete EVERYTHING for one account, regardless of age.
                        This is the erasure path: account deletion, or a user
                        who wants their photos gone but is keeping the feature.
                        Also sweeps the account's storage folder directly, so
                        orphans (an upload whose row insert failed) go too.

Storage first, rows second, deliberately. The row is the only index of where
the photos live: drop it first and a failed storage call strands the JPEGs with
nothing left pointing at them. Deleting storage first means a crash in between
leaves a row whose image_path 404s — ugly, retried on the next run, and the
photo (the thing we actually promised to delete) is already gone.

Each sample can own up to three objects: the rectified card, `_raw` (the full
camera frame), and `_strip` (the approach filmstrip). The last two are recorded
in the debug JSON, not in image_path — miss them and you delete the crop while
keeping the wider shot, which is exactly backwards from a privacy standpoint.

Usage:
    python cleanup_scan_samples.py [--months 12] [--dry-run] [--verbose]
    python cleanup_scan_samples.py --user <uuid> [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from supabase_client import Supabase

BUCKET = "scan-samples"
DEFAULT_MONTHS = 12
# PostgREST/storage both dislike enormous request bodies; delete in chunks.
CHUNK = 200


def storage_delete(sb: Supabase, paths: list[str], dry: bool, verbose: bool) -> int:
    """Delete objects from the scan-samples bucket. Returns the count removed."""
    paths = [p for p in dict.fromkeys(paths) if p]
    if not paths:
        return 0
    if dry:
        if verbose:
            for p in paths[:20]:
                print(f"    would delete object {p}")
            if len(paths) > 20:
                print(f"    … and {len(paths) - 20} more")
        return len(paths)
    removed = 0
    endpoint = f"{sb.url}/storage/v1/object/{BUCKET}"
    for i in range(0, len(paths), CHUNK):
        chunk = paths[i : i + CHUNK]
        r = requests.delete(
            endpoint,
            headers={
                "apikey": sb.key,
                "Authorization": f"Bearer {sb.key}",
                "Content-Type": "application/json",
            },
            json={"prefixes": chunk},
            timeout=120,
        )
        if not r.ok:
            raise RuntimeError(f"Storage delete failed ({r.status_code}): {r.text[:400]}")
        # The API reports per-object results; a path that's already gone simply
        # isn't listed, which is fine (idempotent re-runs hit this constantly).
        try:
            removed += len(r.json())
        except Exception:
            removed += len(chunk)
    return removed


def storage_list_folder(sb: Supabase, folder: str) -> list[str]:
    """List every object under `<folder>/` (used by the per-user sweep)."""
    out: list[str] = []
    offset = 0
    endpoint = f"{sb.url}/storage/v1/object/list/{BUCKET}"
    while True:
        r = requests.post(
            endpoint,
            headers={
                "apikey": sb.key,
                "Authorization": f"Bearer {sb.key}",
                "Content-Type": "application/json",
            },
            json={"prefix": folder, "limit": 1000, "offset": offset},
            timeout=60,
        )
        if not r.ok:
            raise RuntimeError(f"Storage list failed ({r.status_code}): {r.text[:400]}")
        batch = r.json() or []
        if not batch:
            break
        for obj in batch:
            name = obj.get("name")
            if name:
                out.append(f"{folder}/{name}")
        if len(batch) < 1000:
            break
        offset += len(batch)
    return out


def paths_for(rows: list[dict]) -> list[str]:
    """Every storage object owned by these rows — including the raw frame and
    filmstrip, which live in the debug JSON rather than image_path."""
    paths: list[str] = []
    for row in rows:
        if row.get("image_path"):
            paths.append(row["image_path"])
        dbg = row.get("debug")
        if isinstance(dbg, dict):
            for key in ("rawPath", "stripPath"):
                if dbg.get(key):
                    paths.append(dbg[key])
    return paths


def purge(sb: Supabase, rows: list[dict], filters: dict[str, str], dry: bool, verbose: bool) -> None:
    if not rows:
        print("  nothing to delete")
        return
    paths = paths_for(rows)
    print(f"  {len(rows)} sample rows, {len(set(paths))} storage objects")
    n = storage_delete(sb, paths, dry, verbose)
    print(f"  {'would delete' if dry else 'deleted'} {n} storage objects")
    if dry:
        print(f"  would delete {len(rows)} rows matching {filters}")
        return
    sb.delete("scan_samples", filters)
    print(f"  deleted {len(rows)} rows")


def main() -> int:
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    ap = argparse.ArgumentParser(description="Delete aged-out or user-requested scan samples.")
    ap.add_argument("--months", type=int, default=DEFAULT_MONTHS,
                    help=f"retention window in months (default {DEFAULT_MONTHS})")
    ap.add_argument("--user", help="delete ALL samples for this user id, ignoring age")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sb = Supabase()
    cols = "id,user_id,created_at,image_path,debug"

    if args.user:
        print(f"Erasure request: every scan sample for {args.user}")
        filters = {"user_id": f"eq.{args.user}"}
        rows = sb.select("scan_samples", cols, filters=dict(filters), order="id")
        purge(sb, rows, filters, args.dry_run, args.verbose)
        # Sweep the account's folder too — an upload whose row insert failed
        # (migration 105 fixed one such class) leaves a photo with no row.
        orphans = [p for p in storage_list_folder(sb, args.user) if p not in set(paths_for(rows))]
        if orphans:
            print(f"  {len(orphans)} orphaned objects with no row")
            storage_delete(sb, orphans, args.dry_run, args.verbose)
        print("Done." if not args.dry_run else "Dry run — nothing changed.")
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=30 * args.months)).date().isoformat()
    print(f"Retention sweep: scan samples created before {cutoff} ({args.months} months)")
    filters = {"created_at": f"lt.{cutoff}"}
    rows = sb.select("scan_samples", cols, filters=dict(filters), order="id")
    purge(sb, rows, filters, args.dry_run, args.verbose)
    print("Done." if not args.dry_run else "Dry run — nothing changed.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001 — a silent failure here breaks a promise
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)
