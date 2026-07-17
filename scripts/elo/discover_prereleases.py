"""Discover upcoming set-launch Prerelease events on RPH (Ravensburger Play) and
upsert them into the Supabase `prerelease_events` table — the sibling of
`discover_wu_scs.py` (which handles Set Championships).

Same data source and pulling infrastructure as the SC discovery: pull EVERY
upcoming Lorcana event with no server-side name filter (the RPH `name=` param is
a lossy relevance search, see discover_wu_scs.py), then classify locally.

WHAT COUNTS AS A PRERELEASE — three rules, strongest first, because prerelease
events are the launch-weekend phenomenon for one set at a time and stores name
them wildly (and in every language):

  1. TEMPLATE (authoritative — the RPH "category"): every event carries an
     `event_configuration_template` UUID. Ravensburger publishes an official
     Prerelease event template per set (measured: one for Sealed, one for Pack
     Rush), and stores that create their event from it all share that UUID. Those
     templates are 100% pure (every event using them is a prerelease) and
     language-independent, so an event carrying one IS a prerelease no matter what
     its title says. The UUIDs are per-set (a new set gets fresh ones), so we
     DERIVE them each run from the name-confirmed prereleases (see
     derive_prerelease_templates) instead of hardcoding — it auto-adapts at
     rotation. This is the rule that catches the localized launch events
     ("Avant-première", "Presentación", "售前賽", "Release Event") cleanly.

  2. STRICT NAME (any date/country): the title contains explicit prerelease
     wording ("prerelease", "pre-release", "pre release"). Catches English stores
     + the "Tuesday after release" stragglers, and (crucially) SEEDS rule 1.

  3. LOOSE (launch window only): within a set's release window
     [released_at - BEFORE, released_at + AFTER], any Sealed / Pack Rush / Draft
     event is treated as that set's prerelease even without a template or the
     word "prerelease" — a fallback for stores that hand-build their event
     instead of using the official template. A small negative-word list drops
     obvious non-prerelease sealed events (learn-to-play, casual, league).

Set Championships are excluded from all rules (they're the other table).

Set assignment: detect the set from the title (reusing discover_wu_scs's
detect_set); else the launch-window set; else the current/imminent launch set.

Re-runnable: PostgREST upsert on event_id (merge-duplicates). Past events fall
out of the site's `start_datetime >= today` query on their own, so no pruning is
needed — a launch weekend's rows simply stop showing once the weekend passes.

Usage:
    python discover_prereleases.py                 # all launches -> Supabase (daily job)
    python discover_prereleases.py --country US
    python discover_prereleases.py --dry-run --json out.json
"""
from __future__ import annotations
import argparse, datetime, json, os, sys, time, urllib.request, urllib.error
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Reuse the SC discovery's RPH pulling + set-detection helpers so the two stay
# in lockstep (same event source, same set-name matching, same field cleaning).
from discover_wu_scs import (
    API, EVENT_URL, HDR, SUPABASE_URL, SERVICE_KEY,
    fetch_all, fetch_set_names, build_aliases, detect_set, to_row,
)

# Days of slack around a set's release_at that still count as its "launch window"
# for the LOOSE (format-based) rule. Prereleases run the launch weekend; a few
# stores run "the Tuesday after" (release is a Friday -> +4 days). Give generous
# room on both sides so early-bird Thursday events and the Tuesday tail are both
# caught. Outside this window, only the STRICT name rule applies.
WINDOW_BEFORE = 3
WINDOW_AFTER = 6

# Explicit prerelease wording (strict rule). Kept English/near-universal — the
# localized names are handled by the loose format rule instead.
PRERELEASE_NAME_TOKENS = ("prerelease", "pre-release", "pre release", "prelease")

# Formats that a launch-weekend event uses. A set's launch is played Sealed or
# Pack Rush (a few stores label it Draft). Constructed events in the window are
# NOT prereleases (they're regular play using the new set), so Core Constructed
# is deliberately excluded.
LAUNCH_FORMATS = ("Sealed", "Pack Rush", "Draft")

# Sealed/Pack-Rush events inside the launch window that are clearly NOT the
# prerelease. English-only (localized titles won't contain these, and we WANT to
# keep the localized launch events). Set Championship is excluded separately.
# NOTE: only applied to the LOOSE rule — a template match is authoritative and
# bypasses this (RPH itself tagged the event with the prerelease config).
NEGATIVE_TOKENS = (
    "set championship", "learn to play", "learn-to-play", "how to play",
    "casual", "league", "constructed", "practice", "demo", "teaching",
    "beginner", "core constructed",
)

# A template is adopted as an official "prerelease template" only if at least
# this many name-confirmed prereleases use it (guards against a one-off store
# building a prerelease from some unrelated template) AND that many are at least
# this fraction of ALL events using the template (guards against adopting a
# generic/shared template — the real prerelease templates measured ~0.8-0.9 pure,
# the Set Championship template shares ~0 prereleases).
MIN_TEMPLATE_EVIDENCE = 8
TEMPLATE_PURITY_MIN = 0.5


def _fmt_name(ev: dict):
    g = ev.get("gameplay_format")
    return g.get("name") if isinstance(g, dict) else (g or None)


def _event_date(ev: dict) -> datetime.date | None:
    s = ev.get("start_datetime") or ""
    try:
        return datetime.date.fromisoformat(s[:10])
    except Exception:
        return None


def fetch_launch_sets() -> list[dict]:
    """Sets whose release window overlaps the near future, newest first. Each is
    {name, release_date}. Source: Supabase `sets` (numbered sets only — promo
    sets have non-numeric codes and don't get prereleases). We keep any set whose
    launch window could still contain an UPCOMING event, i.e. release_at is not
    far in the past, so a set that dropped a few days ago still classifies its
    tail-end (Tuesday-after) events."""
    out: list[dict] = []
    if not (SUPABASE_URL and SERVICE_KEY):
        print("  ! no Supabase creds; loose launch-window rule disabled")
        return out
    try:
        url = f"{SUPABASE_URL}/rest/v1/sets?select=name,code,released_at&order=released_at.desc.nullslast"
        req = urllib.request.Request(url, headers={
            "apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}",
            "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            rows = json.loads(r.read().decode("utf-8", "ignore"))
        today = datetime.date.today()
        for row in rows:
            code = str(row.get("code") or "")
            rel = row.get("released_at") or ""
            if not (code.isdigit() and row.get("name") and rel):
                continue
            try:
                rd = datetime.date.fromisoformat(rel[:10])
            except Exception:
                continue
            # keep launches whose window could still hold an upcoming event
            if rd + datetime.timedelta(days=WINDOW_AFTER) >= today - datetime.timedelta(days=1):
                out.append({"name": row["name"], "release_date": rd})
    except Exception as e:
        print(f"  ! couldn't read `sets` ({e}); loose launch-window rule disabled")
    return out


def launch_set_for_date(d: datetime.date | None, launch_sets: list[dict]) -> str | None:
    """The launch set whose window [release-BEFORE, release+AFTER] contains d.
    If several match (unlikely), pick the closest release date."""
    if d is None:
        return None
    best, best_gap = None, None
    for ls in launch_sets:
        rd = ls["release_date"]
        if rd - datetime.timedelta(days=WINDOW_BEFORE) <= d <= rd + datetime.timedelta(days=WINDOW_AFTER):
            gap = abs((d - rd).days)
            if best_gap is None or gap < best_gap:
                best, best_gap = ls["name"], gap
    return best


def _has_prerelease_name(ev: dict) -> bool:
    name = (ev.get("name") or "").lower()
    return bool(name) and any(tok in name for tok in PRERELEASE_NAME_TOKENS)


def derive_prerelease_templates(raw: list[dict]) -> dict[str, int]:
    """Discover the current set's official Prerelease event-template UUID(s) from
    the data itself. Seed with events that say "prerelease" in the title (and
    aren't a Set Championship), tally their event_configuration_template, and
    adopt a template as a prerelease template if enough confirmed prereleases use
    it AND they're a big enough share of the template's total usage (purity —
    keeps a generic/shared template from being adopted). Returns {uuid: seed_count}.

    Why derive instead of hardcode: the UUIDs change every set rotation, so this
    keeps working with zero edits when the next set's prereleases post."""
    seeds = [ev for ev in raw
             if _has_prerelease_name(ev)
             and "set championship" not in (ev.get("name") or "").lower()
             and ev.get("event_configuration_template")]
    seed_ct = Counter(ev["event_configuration_template"] for ev in seeds)
    total_ct = Counter(ev.get("event_configuration_template") for ev in raw
                       if ev.get("event_configuration_template"))
    adopted: dict[str, int] = {}
    for tpl, c in seed_ct.items():
        tot = total_ct.get(tpl, 0)
        if c >= MIN_TEMPLATE_EVIDENCE and tot and (c / tot) >= TEMPLATE_PURITY_MIN:
            adopted[tpl] = c
    return adopted


def classify(ev: dict, sets_sorted, aliases_sorted, launch_sets,
             prerelease_templates: dict[str, int]) -> tuple[str | None, str]:
    """Return (set_name, via) — via ∈ {template, name, window, ""} — or
    (None, "") if this event isn't a prerelease."""
    name = (ev.get("name") or "").lower()
    if not name:
        return None, ""
    # Never claim a Set Championship (it lives in the other table), even if it
    # somehow shares wording — the SC template is distinct so this is belt-only.
    if "set championship" in name:
        return None, ""

    detected = detect_set(ev.get("name") or "", sets_sorted, aliases_sorted)
    d = _event_date(ev)
    win_set = launch_set_for_date(d, launch_sets)
    default_set = detected or win_set or (launch_sets[0]["name"] if launch_sets else None)

    # 1. TEMPLATE — authoritative RPH category; bypasses the negative-word filter.
    if ev.get("event_configuration_template") in prerelease_templates:
        return default_set, "template"

    # From here the negative-word filter applies (fuzzier signals).
    if any(neg in name for neg in NEGATIVE_TOKENS):
        return None, ""

    # 2. STRICT NAME — explicit prerelease wording anywhere in the title.
    if any(tok in name for tok in PRERELEASE_NAME_TOKENS):
        return default_set, "name"

    # 3. LOOSE — a launch-format event inside a set's release window.
    if win_set and _fmt_name(ev) in LAUNCH_FORMATS:
        return detected or win_set, "window"

    return None, ""


def upsert(rows: list[dict], chunk: int = 200) -> None:
    if not (SUPABASE_URL and SERVICE_KEY):
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not set (scripts/.env)")
    endpoint = f"{SUPABASE_URL}/rest/v1/prerelease_events"
    headers = {
        "apikey": SERVICE_KEY,
        "Authorization": f"Bearer {SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
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
        print(f"  upserted {done}/{len(rows)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default=None, help="optional client-side ISO country filter, e.g. US")
    ap.add_argument("--json", default=None, help="also dump the rows to this path")
    ap.add_argument("--dry-run", action="store_true", help="don't write to Supabase")
    args = ap.parse_args()

    print("Pulling ALL upcoming Lorcana events from RPH (no name filter), "
          "classifying launch Prereleases...")
    sets_sorted = fetch_set_names()
    aliases_sorted = build_aliases(sets_sorted)
    launch_sets = fetch_launch_sets()
    if launch_sets:
        print("  launch windows:", ", ".join(
            f"{ls['name']} ({ls['release_date']} -{WINDOW_BEFORE}/+{WINDOW_AFTER}d)" for ls in launch_sets))
    else:
        print("  [!] no active launch windows — only strict prerelease-named events will match")

    raw = fetch_all(name_net="Prerelease")
    prerelease_templates = derive_prerelease_templates(raw)
    if prerelease_templates:
        print("  prerelease templates (derived from name-confirmed events):")
        for tpl, c in sorted(prerelease_templates.items(), key=lambda kv: -kv[1]):
            print(f"      {tpl}  (seed {c})")
    else:
        print("  [!] no prerelease template met the adoption bar — falling back to "
              "name + launch-window rules only")
    rows, via_counts = [], Counter()
    for ev in raw:
        s, via = classify(ev, sets_sorted, aliases_sorted, launch_sets, prerelease_templates)
        if s:
            rows.append(to_row(ev, s))
            via_counts[via] += 1

    if args.country:
        rows = [r for r in rows if (r.get("country") or "").upper() == args.country.upper()]
    rows.sort(key=lambda r: (r.get("start_datetime") or "", r.get("set_name") or "", r.get("country") or ""))

    by_country = Counter((r.get("country") or "?") for r in rows)
    by_set = Counter((r.get("set_name") or "?") for r in rows)
    print(f"\n{len(rows)} Prerelease events ({len(raw)} upcoming Lorcana events scanned)")
    print("  matched via:", dict(via_counts))
    print("  by set:", dict(sorted(by_set.items(), key=lambda kv: -kv[1])))
    print("  by country:", dict(sorted(by_country.items(), key=lambda kv: -kv[1])[:12]))

    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"  wrote {len(rows)} rows to {args.json}")

    if args.dry_run:
        print("  (dry run — not writing to Supabase)")
        for r in rows[:12]:
            print(f"    {(r['start_datetime'] or '????-??-??')[:10]}  "
                  f"{(r.get('gameplay_format') or '')[:10]:11}  {(r['name'] or '')[:44]:46}  "
                  f"{(r['store_name'] or '')[:18]:20}  {r.get('country')}")
        return

    upsert(rows)
    print(f"\nDone — {len(rows)} events in public.prerelease_events")


if __name__ == "__main__":
    main()
