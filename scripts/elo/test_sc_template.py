"""Guards Set Championship recognition by RPH's own SC template.

    python scripts/elo/test_sc_template.py

No network — the RPH feed is stubbed.

is_sc() used to need the words "set championship" in the title, and stores don't
always type them: "Twisted - Lorcana Set Champs", "Attack of the Vine Store
Championship". RPH's SC event template stamps one phase_template_group on every
event made from it, whatever the title. Across all 4,723 events at the 103
tracked stores since 2025-08-01 that group sat on 470 events, every one a real
SC and 26 of them untitled — and 5 of the 6 untitled ones played since
Winterspell never reached the Elo board. Three things are locked down:

  1. THE RULE. Title OR template makes an SC; side-event words veto both; a
     "championship"-titled local on another template stays a local.
  2. THE SEASON. A title naming a set decides it; a setless title is placed by
     date inside that set's release window, and nowhere without one.
  3. THE FEED. A tracked store's own feed surfaces the SC the name nets can't,
     re-checks store.id locally (RPH's two store filters disagree), and never
     reaches back before the season began.
"""
from __future__ import annotations
import datetime, os, sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))
import discover_store_scs as m  # noqa: E402

d = m.d
failures = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


TPL = next(iter(d.SC_PHASE_TEMPLATE_GROUPS))
LEAGUE_TPL = "d3289156-dc49-4c89-ba2e-f5f06c2e59f0"   # what two real "Championship" locals used


def ev(eid, name, group=None, date="2026-09-13", store=5171):
    return {"id": eid, "name": name, "phase_template_group": group,
            "start_datetime": f"{date}T16:00:00+00:00", "display_status": "complete",
            "store": {"id": store, "name": f"Store {store}"}}


print("is_sc: the title OR RPH's SC template, and side events veto both")
for label, e, want in [
    ("titled SC", ev(1, "Saturday Afternoon Attack of the Vine! Set Championship", TPL), True),
    ("titled SC without the template still counts", ev(1, "Lorcana - Set Championship"), True),
    ("'Set Champs' built from the SC template", ev(1, "Twisted - Lorcana Set Champs", TPL), True),
    ("'Store Championship' built from it", ev(1, "Attack of the Vine Store Championship", TPL), True),
    ("a typo'd title built from it", ev(1, "Winterspell Set Chamionship @ Evo", TPL), True),
    ("a 'Championships' local on another template",
     ev(1, "Lorcana League Play last week before Championships", LEAGUE_TPL), False),
    ("a league finale on another template",
     ev(1, "Lorcana League Season Finale - Single Elimination Championship", LEAGUE_TPL), False),
    ("a prerelease built from the SC template is still a prerelease",
     ev(1, "Attack of the Vine! Prerelease (Sealed)", TPL), False),
    ("a titled side event", ev(1, "Set Championship Draft Night", TPL), False),
]:
    check(label, d.is_sc(e), want)
check("is_sc_by_name ignores the template",
      d.is_sc_by_name(ev(1, "Twisted - Lorcana Set Champs", TPL)), False)

print("\nsc_set_for: a title naming a set decides; a setless title goes by date")
AOTV = "Attack of the Vine!"
RELEASES = [("Wilds Unknown", datetime.date(2026, 5, 8)), (AOTV, datetime.date(2026, 7, 17))]
WIN = m.set_window(AOTV, RELEASES)
check("the current set's window is open-ended", WIN, (datetime.date(2026, 7, 17), None))
check("a set's window ends where the next one begins", m.set_window("Wilds Unknown", RELEASES),
      (datetime.date(2026, 5, 8), datetime.date(2026, 7, 17)))
check("a set with no release date has no window", m.set_window("Hyperia City", RELEASES), None)
SETS = sorted(({"canonical": n, "norm": d._norm(n)} for n, _ in RELEASES),
              key=lambda s: len(s["norm"]), reverse=True)
ALIASES = d.build_aliases(SETS)
SETLESS = "Twisted - Lorcana Set Champs"
check("a setless title inside the window",
      m.sc_set_for(ev(1, SETLESS, TPL, "2026-09-13"), WIN, AOTV, SETS, ALIASES), AOTV)
check("a setless title on release day",
      m.sc_set_for(ev(1, SETLESS, TPL, "2026-07-17"), WIN, AOTV, SETS, ALIASES), AOTV)
check("a setless title before the window belongs to no set",
      m.sc_set_for(ev(1, SETLESS, TPL, "2026-06-14"), WIN, AOTV, SETS, ALIASES), None)
check("the previous set's window stops at the next release",
      m.sc_set_for(ev(1, SETLESS, TPL, "2026-07-17"), m.set_window("Wilds Unknown", RELEASES),
                   "Wilds Unknown", SETS, ALIASES), None)
check("a title naming another set keeps that set",
      m.sc_set_for(ev(1, "Wilds Unknown Set Championship", None, "2026-07-20"), WIN, AOTV,
                   SETS, ALIASES), "Wilds Unknown")
check("no window, no date fallback",
      m.sc_set_for(ev(1, SETLESS, TPL), None, AOTV, SETS, ALIASES), None)

print("\npull_store_scs: a tracked store's own feed finds what the name nets can't")
PSEUDO_TODAY = "2026-09-10"
FEED = {
    5171: [ev(894902, SETLESS, TPL, "2026-09-13"),
           ev(916500, "Attack of the Vine Store Championship", TPL, "2026-09-20"),
           ev(894894, "Twisted Lorcana League", LEAGUE_TPL, "2026-09-04"),
           ev(690961, "Sunday Afternoon Wilds Unknown Set Championship", TPL, "2026-06-14")],
    # RPH's store filters disagree, so a row for some OTHER store can come back.
    10: [ev(700001, "Attack of the Vine Store Championship", TPL, "2026-09-20", store=99)],
}
asked = []


def fake_http(url):
    q = parse_qs(urlparse(url).query)
    sid = int((q.get("store") or q.get("store_id"))[0])
    status = q["display_statuses"][0]
    after = (q.get("start_date_after") or [None])[0]
    asked.append((sid, status, after))
    rows = [e for e in FEED.get(sid, [])
            if (e["start_datetime"][:10] >= PSEUDO_TODAY) == (status == "upcoming")]
    if after:
        rows = [e for e in rows if e["start_datetime"][:10] >= after]
    return {"results": rows, "next": None}


orig = d.http_json
d.http_json = fake_http
try:
    got = m.pull_store_scs({5171, 10}, AOTV, WIN, SETS, ALIASES)
finally:
    d.http_json = orig
check("the setless SC and the Store Championship, nothing else", sorted(got), [894902, 916500])
check("both store-filter spellings are asked", {s for s, _, _ in asked} == {5171, 10}
      and len(asked) == 8, True)
check("the past feed never reaches back before the season began",
      {a for _, s, a in asked if s == "past"}, {"2026-07-17"})
check("no window, no pull", m.pull_store_scs({5171}, AOTV, None, SETS, ALIASES), {})

print()
if failures:
    print(f"{len(failures)} FAILED: " + ", ".join(failures))
    sys.exit(1)
print("all SC-template guards pass")
