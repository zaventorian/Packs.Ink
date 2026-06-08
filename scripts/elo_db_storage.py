"""Up/download the SQLite ELO DB from a Supabase Storage bucket.

Reads SUPABASE_URL + SUPABASE_SERVICE_KEY from env (same as the rest of the
ELO tooling). Storage bucket name + object key are configurable.

Usage:
    python scripts/elo_db_storage.py download
    python scripts/elo_db_storage.py upload
    python scripts/elo_db_storage.py download --to /tmp/elo.db
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

DEFAULT_LOCAL = Path(__file__).parent / "elo" / "lorcana_elo.db"
BUCKET = os.environ.get("ELO_DB_BUCKET", "elo")
OBJECT_KEY = os.environ.get("ELO_DB_OBJECT", "lorcana_elo.db")


def storage_url() -> tuple[str, dict]:
    load_dotenv(Path(__file__).parent / ".env")
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not base or not key:
        sys.exit("missing SUPABASE_URL / SUPABASE_SERVICE_KEY")
    return base + "/storage/v1", {"apikey": key, "Authorization": f"Bearer {key}"}


def download(dst: Path) -> None:
    base, hdr = storage_url()
    url = f"{base}/object/{BUCKET}/{OBJECT_KEY}"
    r = requests.get(url, headers=hdr, timeout=120)
    if r.status_code == 404:
        sys.exit(f"object {BUCKET}/{OBJECT_KEY} not found — upload an initial DB first")
    r.raise_for_status()
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(r.content)
    print(f"downloaded {len(r.content)/1024:.1f} KB -> {dst}")


def upload(src: Path) -> None:
    if not src.exists():
        sys.exit(f"local DB not found: {src}")
    base, hdr = storage_url()
    url = f"{base}/object/{BUCKET}/{OBJECT_KEY}"
    # POST with x-upsert handles both create + overwrite. PUT was hitting
    # connection-reset on the upload side for files this size.
    headers = {**hdr, "Content-Type": "application/octet-stream", "x-upsert": "true"}
    data = src.read_bytes()
    r = requests.post(url, headers=headers, data=data, timeout=300)
    if not r.ok:
        sys.exit(f"upload failed: {r.status_code} {r.text[:200]}")
    print(f"uploaded {len(data)/1024:.1f} KB -> {BUCKET}/{OBJECT_KEY}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["download", "upload"])
    ap.add_argument("--to", type=Path, default=DEFAULT_LOCAL,
                    help="local path (default scripts/elo/lorcana_elo.db)")
    args = ap.parse_args()

    if args.action == "download":
        download(args.to)
    else:
        upload(args.to)


if __name__ == "__main__":
    main()
