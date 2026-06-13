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
        """Upsert rows into a table. on_conflict is the PK column(s) for merging.

        Dedupes by the on_conflict key before sending: PostgREST's
        ON CONFLICT DO UPDATE rejects batches with duplicate conflict-target
        rows ("cannot affect row a second time"), so we keep the last
        occurrence of each key.
        """
        if not rows:
            return
        if on_conflict:
            key_cols = [c.strip() for c in on_conflict.split(",") if c.strip()]
            seen: dict[tuple, dict] = {}
            for row in rows:
                seen[tuple(row.get(c) for c in key_cols)] = row
            deduped = list(seen.values())
            if len(deduped) != len(rows):
                print(f"  deduped {table}: {len(rows)} -> {len(deduped)} rows by ({on_conflict})")
            rows = deduped
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

    def update(self, table: str, match: dict, patch: dict, params: dict | None = None) -> None:
        """Partial update: PATCH /rest/v1/{table}?col=eq.val with body {col: val, ...}.
        Use this when you only want to change a subset of columns without
        triggering NOT NULL constraints on the unchanged ones.

        `match` is the simple-eq form ({col: val} -> col=eq.val); pass `params`
        instead (raw PostgREST filter strings, e.g. {"id": "in.(1,2,3)"}) when
        you need a non-eq operator. The two merge; `params` wins on key clash.

        Retries on 5xx / 429 (transient) the same way upsert does — Supabase's
        statement timeout (57014) and rate limiter are intermittent."""
        if not patch:
            return
        endpoint = f"{self.url}/rest/v1/{table}"
        q = {k: f"eq.{v}" for k, v in match.items()}
        if params:
            q.update(params)
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.patch(
                    endpoint,
                    headers=self._headers("return=minimal"),
                    params=q,
                    json=patch,
                    timeout=60,
                )
                if r.ok:
                    return
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise RuntimeError(
                        f"Patch {table} {match} failed ({r.status_code}): {r.text[:500]}"
                    )
                last_err = RuntimeError(
                    f"Patch {table} {match} returned {r.status_code}: {r.text[:200]}"
                )
            except requests.RequestException as e:
                last_err = e
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/4 in {wait}s ({last_err})")
            time.sleep(wait)
        if last_err is not None:
            raise last_err

    def delete(self, table: str, filters: dict[str, str]) -> list[dict]:
        """Delete rows matching `filters` (eq/in/gte/etc, PostgREST syntax).
        Returns the deleted rows when Prefer=return=representation is set.
        Requires at least one filter — guards against accidental table wipes.

        Retries on 5xx / 429 (transient) the same way upsert does."""
        if not filters:
            raise ValueError("delete requires at least one filter to prevent table-wide deletes")
        endpoint = f"{self.url}/rest/v1/{table}"
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.delete(
                    endpoint,
                    headers=self._headers("return=representation"),
                    params=filters,
                    timeout=60,
                )
                if r.ok:
                    try:
                        return r.json() if r.text else []
                    except Exception:
                        return []
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise RuntimeError(
                        f"Delete {table} {filters} failed ({r.status_code}): {r.text[:500]}"
                    )
                last_err = RuntimeError(
                    f"Delete {table} {filters} returned {r.status_code}: {r.text[:200]}"
                )
            except requests.RequestException as e:
                last_err = e
            wait = 2 ** attempt
            print(f"  retry {attempt + 1}/4 in {wait}s ({last_err})")
            time.sleep(wait)
        if last_err is not None:
            raise last_err
        return []

    def rpc(self, name: str, args: dict | None = None) -> dict | list | None:
        """Call a Postgres function exposed via PostgREST RPC."""
        endpoint = f"{self.url}/rest/v1/rpc/{name}"
        r = requests.post(endpoint, headers=self._headers(), json=args or {}, timeout=120)
        if not r.ok:
            raise RuntimeError(f"RPC {name} failed ({r.status_code}): {r.text[:500]}")
        if not r.text:
            return None
        try:
            return r.json()
        except Exception:
            return r.text

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
