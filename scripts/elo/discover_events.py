"""Discover EVERY upcoming Lorcana event on RPH (Ravensburger Play) in ONE scan,
classify each as Set Championship / Prerelease / regular event, and upsert the
whole lot into Supabase `lorcana_events`.

This replaces the two-scan daily job (discover_wu_scs.py + discover_prereleases.py),
which pulled the same ~17k-row upcoming index twice and kept only the two
classified subsets — so the site could show Set Championships and prereleases but
had no idea a store ran a Thursday league night.

WHAT THIS WRITES
  * public.lorcana_events  — every upcoming event, tagged kind='sc'|'prerelease'|
    'other'. This is what the site's "Upcoming near me" box reads (all three modes
    are just a kind filter), so All / Set Champs / Prereleases can never disagree.
  * public.set_championships — the SC subset, UNCHANGED in shape and content.
    Not redundant: the whole Elo pipeline binds to that table (elo_upcoming_scs
    view, elo_event_roster FK, get_event_roster / get_roster_scout,
    sync_elo_tracked_stores.py, scrape_rosters.py, the refresh-elo-rosters edge
    function). Writing it from the same scan keeps Elo working untouched while
    the site moves to the new table.

CLASSIFICATION lives in the two existing scripts and is imported, not
reimplemented, so there is exactly one definition of "is this an SC" and "is this
a prerelease":
  * is_sc()  from discover_wu_scs      — title says "set championship", minus side events
  * classify() from discover_prereleases — template / strict-name / launch-window
Everything the two reject is kind='other' (the locals, league nights, drafts,
demo days, convention side events). RPH's own event_type cannot do this job: it
reads "LOCALS" for ~99% of events (measured 2026-07-30, 1972 of the soonest 1991).

PRUNING (new — the subset tables never did this). Every upserted row stamps
last_seen_at. Events that have already happened are copied into
public.lorcana_events_history before the sweep removes them from the live feed,
so "every event this store has run" stays answerable (RPH store tiers score
Total Events / Unique Fans / Event Tickets across ALL event types). After a pull
that passes a completeness guard, upcoming rows that
this run did NOT see are deleted: RPH events get cancelled and locals churn far
more than SCs did, so "never prune" would leave dead weeklies on the map forever.
Long-past rows are swept too so the table stays bounded. The guard refuses to
prune off a pull that looks partial (network flake, API hiccup) — a bad pull can
skip rows, and silently deleting live events is worse than keeping a stale one.

Usage:
    python discover_events.py                  # the daily job
    python discover_events.py --dry-run        # classify + report, write nothing
    python discover_events.py --json out.json
    python discover_events.py --no-prune       # upsert only
"""
from __future__ import annotations
import argparse, datetime, json, sys, time, urllib.request, urllib.error
from collections import Counter
from pathlib import Path
from urllib.parse import quote

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from discover_wu_scs import (
    SUPABASE_URL, SERVICE_KEY,
    fetch_all, fetch_set_names, build_aliases, detect_set, fetch_current_set,
    is_sc, to_row,
    upsert as upsert_set_championships,
)
from discover_prereleases import (
    classify as classify_prerelease,
    derive_prerelease_templates, fetch_launch_sets,
)

# A pull is trusted enough to prune from only if it found at least this many
# events AND at least this fraction of the upcoming rows already on file. Both
# floors matter: the absolute one catches a totally broken pull, the ratio one
# catches a pull that silently lost half the index to pagination drift.
MIN_PULL_ABSOLUTE = 4000
MIN_PULL_RATIO = 0.7

# Past events are invisible to the site (it only queries start_datetime >= today)
# but would grow the table without bound, so sweep them after a grace period.
KEEP_PAST_DAYS = 30


def _sb_headers(extra: dict | None = None) -> dict:
    h = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
    }
    h.update(extra or {})
    return h


def count_upcoming(table: str) -> int:
    """How many not-yet-started rows are on file. Used by the prune guard."""
    if not (SUPABASE_URL and SERVICE_KEY):
        return 0
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    url = (f"{SUPABASE_URL}/rest/v1/{table}?select=event_id"
           f"&start_datetime=gte.{quote(now)}&limit=1")
    try:
        req = urllib.request.Request(url, headers=_sb_headers(
            {"Prefer": "count=exact", "Range": "0-0"}))
        with urllib.request.urlopen(req, timeout=40) as r:
            rng = r.headers.get("Content-Range") or ""
        return int(rng.split("/")[-1]) if "/" in rng else 0
    except Exception as e:
        print(f"  ! couldn't count {table} ({e})")
        return 0


def upsert_events(rows: list[dict], chunk: int = 200) -> None:
    """Upsert into lorcana_events. Same small-batch + retry shape as the SC
    upsert — the Supabase TLS endpoint intermittently throws
    SSLV3_ALERT_BAD_RECORD_MAC on large back-to-back POSTs."""
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    endpoint = f"{SUPABASE_URL}/rest/v1/lorcana_events"
    headers = _sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    done = 0
    for i in range(0, len(rows), chunk):
        batch = rows[i:i + chunk]
        body = json.dumps(batch).encode()
        for attempt in range(5):
            try:
                req = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=60) as r:
                    _ = r.read()
                break
            except urllib.error.HTTPError as e:
                raise SystemExit(f"upsert failed [{e.code}]: {e.read().decode('utf-8','ignore')[:400]}")
            except Exception as e:
                if attempt == 4:
                    raise SystemExit(f"upsert batch failed after retries: {e}")
                time.sleep(1.5 * (attempt + 1))
        done += len(batch)
        sys.stdout.write(f"\r  upserted {done}/{len(rows)}")
        sys.stdout.flush()
    print()


def _delete(where: str) -> int:
    """DELETE lorcana_events rows matching a PostgREST filter string. Returns the
    row count (Prefer: return=representation + count)."""
    endpoint = f"{SUPABASE_URL}/rest/v1/lorcana_events?{where}"
    req = urllib.request.Request(endpoint, headers=_sb_headers(
        {"Prefer": "return=representation,count=exact"}), method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            rng = r.headers.get("Content-Range") or ""
            body = json.loads(r.read().decode("utf-8", "ignore") or "[]")
        if "/" in rng:
            try:
                return int(rng.split("/")[-1])
            except ValueError:
                pass
        return len(body)
    except urllib.error.HTTPError as e:
        print(f"  ! delete failed [{e.code}]: {e.read().decode('utf-8','ignore')[:300]}")
        return 0


# Columns are copied straight through, so this list must match
# supabase/121_lorcana_events_history.sql. Anything added to lorcana_events and
# not added here is silently dropped from the archive.
HISTORY_COLS = (
    "event_id,name,kind,set_name,store_id,store_name,store_website,"
    "start_datetime,end_datetime,timezone,full_address,city,state,country,"
    "latitude,longitude,registered_user_count,capacity,cost_cents,currency,"
    "gameplay_format,display_status,url,last_seen_at"
)


def _select_past(cutoff_iso: str, limit: int, offset: int) -> list[dict]:
    """One page of already-happened rows, oldest first so paging is stable."""
    url = (f"{SUPABASE_URL}/rest/v1/lorcana_events?select={HISTORY_COLS}"
           f"&start_datetime=lt.{quote(cutoff_iso)}"
           f"&order=start_datetime.asc,event_id.asc&limit={limit}&offset={offset}")
    req = urllib.request.Request(url, headers=_sb_headers())
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8", "ignore") or "[]")


def archive_past_events() -> bool:
    """Copy every event that has already happened into lorcana_events_history.

    Runs BEFORE the sweep, and the sweep is skipped unless this returns True —
    delete-then-archive would strand the rows permanently, and this table is the
    only record that a store ran a Tuesday league night at all. RPH's upcoming
    feed stops listing an event once it starts, so a row's values are frozen at
    the last pull that saw it; re-archiving is an idempotent upsert on event_id.

    Returns False on any failure, including the archive table not existing yet
    (PGRST205 / 42P01 before migration 121 is applied). That's deliberate: until
    there is somewhere to put them, past rows accumulate in lorcana_events rather
    than being thrown away.
    """
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    endpoint = f"{SUPABASE_URL}/rest/v1/lorcana_events_history"
    headers = _sb_headers({"Prefer": "resolution=merge-duplicates,return=minimal"})
    moved = 0
    offset = 0
    page = 500
    while True:
        try:
            batch = _select_past(now_iso, page, offset)
        except Exception as e:
            print(f"  ! archive READ failed ({e}) — sweep will be skipped")
            return False
        if not batch:
            break
        try:
            req = urllib.request.Request(
                endpoint, data=json.dumps(batch).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as r:
                _ = r.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (404, 400) and ("lorcana_events_history" in detail or "PGRST205" in detail):
                print("  ! lorcana_events_history missing — apply supabase/121_"
                      "lorcana_events_history.sql. Sweep skipped; nothing deleted.")
            else:
                print(f"  ! archive WRITE failed [{e.code}]: {detail} — sweep will be skipped")
            return False
        except Exception as e:
            print(f"  ! archive WRITE failed ({e}) — sweep will be skipped")
            return False
        moved += len(batch)
        # Rows stay in lorcana_events until the sweep, so the window doesn't
        # shift under us — keep paging rather than re-reading from 0.
        offset += len(batch)
        sys.stdout.write(f"\r  archived {moved} past events")
        sys.stdout.flush()
    if moved:
        print()
    print(f"  archived {moved} past events into lorcana_events_history")
    return True


def prune(run_start_iso: str, pulled: int, before_upcoming: int) -> None:
    """Delete upcoming rows this run didn't see (cancelled/removed on RPH) plus
    long-past rows. Guarded: a partial pull must never mass-delete live events."""
    if pulled < MIN_PULL_ABSOLUTE:
        print(f"  ! prune SKIPPED — pull of {pulled} is below the {MIN_PULL_ABSOLUTE} floor")
        return
    if before_upcoming and pulled < before_upcoming * MIN_PULL_RATIO:
        print(f"  ! prune SKIPPED — pulled {pulled} vs {before_upcoming} upcoming on file "
              f"(< {MIN_PULL_RATIO:.0%}); treating this pull as partial")
        return

    now = datetime.datetime.now(datetime.timezone.utc)
    gone = _delete(f"last_seen_at=lt.{quote(run_start_iso)}"
                   f"&start_datetime=gte.{quote(now.isoformat())}")
    print(f"  pruned {gone} upcoming events no longer listed on RPH")

    # Archive first. The sweep is the only thing that deletes history, so it
    # must not run unless the rows are safely copied.
    if not archive_past_events():
        print("  ! past-event sweep SKIPPED — archive did not succeed")
        return
    cutoff = (now - datetime.timedelta(days=KEEP_PAST_DAYS)).isoformat()
    old = _delete(f"start_datetime=lt.{quote(cutoff)}")
    print(f"  swept {old} events older than {KEEP_PAST_DAYS} days (kept in lorcana_events_history)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="also dump the rows to this path")
    ap.add_argument("--dry-run", action="store_true", help="don't write to Supabase")
    ap.add_argument("--no-prune", action="store_true", help="upsert only, never delete")
    ap.add_argument("--skip-set-championships", action="store_true",
                    help="don't mirror the SC subset into set_championships")
    args = ap.parse_args()

    run_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    before_upcoming = 0 if args.dry_run else count_upcoming("lorcana_events")

    print("Pulling ALL upcoming Lorcana events from RPH (one scan, no name gate)...")
    sets_sorted = fetch_set_names()
    aliases_sorted = build_aliases(sets_sorted)
    current_set = fetch_current_set()
    launch_sets = fetch_launch_sets()
    print(f"  current set: {current_set}")
    if launch_sets:
        print("  launch windows:", ", ".join(
            f"{ls['name']} ({ls['release_date']})" for ls in launch_sets))

    # The relevance net is folded in for SC recall parity with the old job (see
    # the `name=` warning in discover_wu_scs) — it is a supplement, never the gate.
    raw = fetch_all(name_net="Set Championship")
    templates = derive_prerelease_templates(raw)
    if templates:
        print("  prerelease templates (derived):",
              ", ".join(f"{t[:8]}…({c})" for t, c in
                        sorted(templates.items(), key=lambda kv: -kv[1])))

    rows: list[dict] = []
    sc_rows: list[dict] = []
    kinds: Counter = Counter()
    for ev in raw:
        if is_sc(ev):
            kind = "sc"
            # An upcoming SC is for the current set; a title naming no set still
            # gets one rather than being dropped (matches the old --all-sets job).
            set_name = detect_set(ev.get("name") or "", sets_sorted, aliases_sorted) or current_set
        else:
            pre_set, via = classify_prerelease(
                ev, sets_sorted, aliases_sorted, launch_sets, templates)
            # Gate on `via` (the REASON it matched), not on the set name. classify()
            # returns (None, "name") for "definitely a prerelease, but I can't tell
            # which set" — which is the normal case OUTSIDE a launch window, where
            # fetch_launch_sets() is empty so there's no default set to fall back
            # on. Gating on the name instead silently demoted clearly-titled
            # prereleases to 'other' ("Second Chance PreRelease (Sealed)",
            # "Hyperia City PreRelease"). set_name is nullable for exactly this.
            if via:
                kind, set_name = "prerelease", pre_set
            else:
                # Regular play. set_name stays NULL unless the title names a set —
                # a Thursday league night belongs to no set and must not claim one.
                kind = "other"
                set_name = detect_set(ev.get("name") or "", sets_sorted, aliases_sorted)

        row = to_row(ev, set_name)
        if kind == "sc":
            sc_rows.append(dict(row))
        row["kind"] = kind
        row["last_seen_at"] = run_start
        row["updated_at"] = run_start
        rows.append(row)
        kinds[kind] += 1

    by_country = Counter((r.get("country") or "?") for r in rows)
    fmts = Counter((r.get("gameplay_format") or "?") for r in rows)
    print(f"\n{len(rows)} upcoming Lorcana events")
    print("  by kind:", dict(kinds))
    print("  by format:", dict(fmts.most_common(8)))
    print("  by country:", dict(sorted(by_country.items(), key=lambda kv: -kv[1])[:12]))

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"  wrote {len(rows)} rows to {args.json}")

    if args.dry_run:
        print("  (dry run — not writing to Supabase)")
        for r in rows[:12]:
            print(f"    {(r['start_datetime'] or '')[:10]}  {r['kind']:11}"
                  f"{(r.get('gameplay_format') or '')[:10]:12}"
                  f"{(r['name'] or '')[:44]:46}  {r.get('country')}")
        return

    upsert_events(rows)
    if sc_rows and not args.skip_set_championships:
        print(f"  mirroring {len(sc_rows)} Set Championships into set_championships "
              f"(the Elo pipeline reads that table)")
        upsert_set_championships(sc_rows)

    if not args.no_prune:
        prune(run_start, len(rows), before_upcoming)

    print(f"\nDone — {len(rows)} events in public.lorcana_events "
          f"({kinds['sc']} SC / {kinds['prerelease']} prerelease / {kinds['other']} other)")


if __name__ == "__main__":
    main()
