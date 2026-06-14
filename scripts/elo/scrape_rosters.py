"""Scrape signed-up rosters for the tracked upcoming Set Championships and store
them in Supabase (elo_event_roster + elo_event_roster_members) so the gated
get_event_roster() RPC can join them to current ELO.

The RPH registrations endpoint is PUBLIC but CORS-blocked (no ACAO header), so
it can only be fetched server-side — this script is the cron safety net; the
admin "run scraper" button hits the same logic in the refresh-elo-rosters Edge
Function.

    GET https://api.ravensburgerplay.com/api/v2/events/{event_id}/registrations/?page_size=100

paginated via the `next` envelope url. Each result row carries:
    best_identifier        TV/tournament display name — the join key into elo_players
    user.id                stable RPH account id  -> rph_user_id
    user.best_identifier   account display name   -> account_name
    registration_status    we keep only "COMPLETE"

Reads which events to scrape from the elo_upcoming_scs view (= set_championships
⋈ elo_tracked_stores) scoped to start_datetime >= today. For each event we
upsert the roster header (registered_count = COMPLETE count, capacity,
scraped_at = now) and REPLACE its members (delete-then-insert) so dropped
registrations disappear.

Fail SOFT per event: a single bad event logs + continues; the process exits
non-zero only if EVERY event failed (or the initial event list couldn't load).

    python scrape_rosters.py
    python scrape_rosters.py --dry-run
    python scrape_rosters.py --event 646568       # one event only (debugging)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Match discover_wu_scs.py: load scripts/.env if present (no-op in CI).
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

# Windows consoles default to cp1252 and choke on the ⟡ in org names / em-dashes.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# scripts/ is the parent of scripts/elo/ — import the shared REST helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from supabase_client import Supabase  # noqa: E402

REG_API = "https://api.ravensburgerplay.com/api/v2/events/{event_id}/registrations/?page_size=100"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def http_json(url: str, retries: int = 5) -> dict:
    """GET + parse JSON with retry on transient errors / 5xx (mirrors the other
    elo scripts). Raises the last error after exhausting retries."""
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HDR)
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode("utf-8", "ignore"))
        except urllib.error.HTTPError as e:
            # Retry only on 5xx / 429; 4xx (e.g. 404 for a deleted event) is terminal.
            if e.code not in (429,) and not (500 <= e.code < 600):
                raise
            last = e
        except Exception as e:
            last = e
        time.sleep(0.8 * (i + 1))
    assert last is not None
    raise last


def fetch_registrations(event_id: int) -> list[dict]:
    """Page through every registration for one event via the `next` envelope."""
    out: list[dict] = []
    url = REG_API.format(event_id=event_id)
    while url:
        d = http_json(url)
        out.extend(d.get("results") or [])
        url = d.get("next")
        if url:
            time.sleep(0.12)
    return out


def member_rows(event_id: int, regs: list[dict]) -> list[dict]:
    """Turn COMPLETE registrations into elo_event_roster_members rows, deduped on
    (event_id, best_identifier) since that's the PK."""
    seen: dict[str, dict] = {}
    for reg in regs:
        if (reg.get("registration_status") or "").upper() != "COMPLETE":
            continue
        ident = reg.get("best_identifier")
        if not ident:
            continue
        user = reg.get("user") or {}
        if not isinstance(user, dict):
            user = {}
        seen[ident] = {
            "event_id": event_id,
            "rph_user_id": user.get("id"),
            "best_identifier": ident,
            "account_name": user.get("best_identifier"),
            "registration_status": reg.get("registration_status"),
        }
    return list(seen.values())


def scrape_event(sb: Supabase, ev: dict, dry_run: bool) -> int:
    """Scrape + store one event's roster. Returns the COMPLETE member count.
    Raises on failure so the caller can fail soft."""
    eid = ev["event_id"]
    regs = fetch_registrations(eid)
    members = member_rows(eid, regs)
    now_iso = datetime.now(timezone.utc).isoformat()
    header = {
        "event_id": eid,
        "registered_count": len(members),
        "capacity": ev.get("capacity"),
        "scraped_at": now_iso,
    }

    name = (ev.get("name") or "")[:48]
    print(f"  [{eid}] {name:<50} {len(members)} signed up "
          f"(of {len(regs)} registrations)")

    if dry_run:
        return len(members)

    # Header first (FK target for members), then REPLACE members: delete the old
    # set, insert the fresh one. delete() requires a filter (guards table wipes).
    sb.upsert("elo_event_roster", [header], on_conflict="event_id")
    sb.delete("elo_event_roster_members", {"event_id": f"eq.{eid}"})
    if members:
        sb.upsert("elo_event_roster_members", members, on_conflict="event_id,best_identifier")
    return len(members)


def upcoming_events(sb: Supabase, only_event: int | None) -> list[dict]:
    """Tracked upcoming SCs to scrape: elo_upcoming_scs with start_datetime today
    or later. `only_event` short-circuits to a single set_championships row."""
    if only_event is not None:
        rows = sb.select(
            "set_championships",
            columns="event_id,name,capacity,start_datetime",
            filters={"event_id": f"eq.{only_event}"},
        )
        return rows
    today = datetime.now(timezone.utc).date().isoformat()
    return sb.select(
        "elo_upcoming_scs",
        columns="event_id,name,capacity,registered_user_count,start_datetime",
        filters={"start_datetime": f"gte.{today}", "order": "start_datetime.asc"},
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="scrape but don't write to Supabase")
    ap.add_argument("--event", type=int, default=None, help="scrape only this event_id (debugging)")
    args = ap.parse_args()

    sb = Supabase()  # exits if SUPABASE_URL / SUPABASE_SERVICE_KEY missing

    try:
        events = upcoming_events(sb, args.event)
    except Exception as e:
        sys.exit(f"FATAL: couldn't load upcoming events: {e}")

    if not events:
        print("No tracked upcoming Set Championships to scrape — nothing to do.")
        return

    print(f"Scraping rosters for {len(events)} tracked upcoming Set Championship(s)"
          f"{' (dry run)' if args.dry_run else ''}...")

    ok = 0
    failed: list[tuple[int, str]] = []
    total_members = 0
    for ev in events:
        try:
            total_members += scrape_event(sb, ev, args.dry_run)
            ok += 1
        except Exception as e:  # fail SOFT per event
            failed.append((ev.get("event_id"), str(e)))
            print(f"  ! [{ev.get('event_id')}] FAILED: {e}")

    print(f"\nDone — {ok}/{len(events)} events scraped, {total_members} total members"
          f"{', ' + str(len(failed)) + ' failed' if failed else ''}.")

    # Non-zero only on TOTAL failure (one bad event shouldn't break the cron).
    if failed and ok == 0:
        sys.exit(f"All {len(failed)} event(s) failed.")


if __name__ == "__main__":
    main()
