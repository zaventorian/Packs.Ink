"""
Tiny Supabase REST client. Avoids the official SDK to dodge its heavy
transitive deps (pyiceberg, etc) that don't have prebuilt wheels for newer
Python versions on Windows.

Only implements what our ETL needs: bulk upsert into a single table.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Iterable

import requests


class Supabase:
    def __init__(self, url: str | None = None, key: str | None = None) -> None:
        self.url = (url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
        self.key = key or os.environ.get("SUPABASE_SERVICE_KEY", "")
        if not self.url or not self.key:
            sys.exit(
                "Missing SUPABASE_URL or SUPABASE_SERVICE_KEY. "
                "Copy scripts/.env.example to scripts/.env and fill it in."
            )

    def _headers(self, prefer: str = "") -> dict[str, str]:
        h = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    def upsert(self, table: str, rows: list[dict], on_conflict: str | None = None, batch: int = 100) -> None:
        """Upsert rows into a table. on_conflict is the PK column(s) for merging."""
        if not rows:
            return
        endpoint = f"{self.url}/rest/v1/{table}"
        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        prefer = "resolution=merge-duplicates,return=minimal"

        total = len(rows)
        for i in range(0, total, batch):
            chunk = rows[i : i + batch]
            last_err: Exception | None = None
            for attempt in range(4):
                try:
                    r = requests.post(
                        endpoint,
                        headers=self._headers(prefer),
                        params=params,
                        json=chunk,
                        timeout=60,
                    )
                    if r.ok:
                        last_err = None
                        break
                    # Non-OK status: don't retry on client errors (4xx) except 429
                    if 400 <= r.status_code < 500 and r.status_code != 429:
                        raise RuntimeError(
                            f"Upsert into {table} failed ({r.status_code}): {r.text[:500]}"
                        )
                    last_err = RuntimeError(
                        f"Upsert into {table} returned {r.status_code}: {r.text[:200]}"
                    )
                except requests.RequestException as e:
                    last_err = e
                wait = 2 ** attempt
                print(f"  retry {attempt + 1}/4 in {wait}s ({last_err})")
                time.sleep(wait)
            if last_err is not None:
                raise last_err
            done = min(i + batch, total)
            print(f"  upserted {table}: {done}/{total}")

    def update(self, table: str, match: dict, patch: dict) -> None:
        """Partial update: PATCH /rest/v1/{table}?col=eq.val with body {col: val, ...}.
        Use this when you only want to change a subset of columns without
        triggering NOT NULL constraints on the unchanged ones."""
        if not patch:
            return
        endpoint = f"{self.url}/rest/v1/{table}"
        params = {k: f"eq.{v}" for k, v in match.items()}
        r = requests.patch(
            endpoint,
            headers=self._headers("return=minimal"),
            params=params,
            json=patch,
            timeout=60,
        )
        if not r.ok:
            raise RuntimeError(
                f"Patch {table} {match} failed ({r.status_code}): {r.text[:500]}"
            )

    def select(
        self,
        table: str,
        columns: str = "*",
        limit: int | None = None,
        filters: dict[str, str] | None = None,
        page_size: int = 1000,
    ) -> list[dict]:
        """Select rows with automatic pagination via Range headers.
        PostgREST caps responses at ~1000 rows by default; we page through them."""
        endpoint = f"{self.url}/rest/v1/{table}"
        params: dict[str, str] = {"select": columns}
        if filters:
            params.update(filters)
        out: list[dict] = []
        start = 0
        while True:
            headers = dict(self._headers())
            end = start + page_size - 1
            headers["Range-Unit"] = "items"
            headers["Range"] = f"{start}-{end}"
            r = requests.get(endpoint, headers=headers, params=params, timeout=60)
            if r.status_code not in (200, 206):
                r.raise_for_status()
            chunk = r.json()
            out.extend(chunk)
            if limit is not None and len(out) >= limit:
                return out[:limit]
            if len(chunk) < page_size:
                return out
            start += page_size
