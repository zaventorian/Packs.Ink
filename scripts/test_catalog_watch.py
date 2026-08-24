"""
test_catalog_watch.py — guards the acknowledgement + review layers of the watch.

    python scripts/test_catalog_watch.py

No network, no database: it imports the real ack functions out of
reconcile_catalog and checks them against hand-built inputs, then validates the
committed catalog_watch.json.

Why this exists. The whole point of the watch is that a red run means something
NEW, and that only holds if acknowledgement behaves exactly as advertised. Two
failure modes would quietly destroy it:

  - an ack that matches too much (a sloppy rule regex swallowing a real
    finding), so a genuinely missing set never alerts;
  - an `until` date that doesn't actually expire, so "revisit when Q3 ships"
    becomes "never";
  - a scheduled review that never comes due, which is the whole difference
    between a reminder and a note somebody wrote down once.

Both are invisible in production — the run is green either way. The only place
to catch them is here.

It also enforces that every entry carries a `why`. An acknowledgement without a
stated reason is indistinguishable from hiding the problem, and six months later
nobody can tell whether it is still true.
"""
from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reconcile_catalog import (  # noqa: E402
    ACK_PATH, KIND_LABEL, ack_reason, due_reviews, load_ack,
)

failed = 0


def check(name: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))


# ── ack_reason ────────────────────────────────────────────────────────────
ACK = {
    "acks": {
        "missing_single:111": {"why": "decided"},
        "missing_single:222": {"why": "later", "until": "2999-01-01"},
        "missing_single:333": {"why": "lapsed", "until": "2020-01-01"},
        "missing_single:444": {},
    },
    "rules": [
        {"kind": "missing_sealed", "name_matches": "(?i)puzzle insert", "why": "inserts"},
        {"kind": "missing_sealed", "name_matches": "(?i)temporary", "why": "for now",
         "until": "2020-01-01"},
        {"name_matches": "(?i)^anykind", "why": "kindless rule"},
    ],
}
TODAY = "2026-08-24"
r = lambda kind, key, name="": ack_reason(ACK, kind, key, name, TODAY)  # noqa: E731

check("exact key is acknowledged", r("missing_single", "111"), "decided")
check("unknown key is not", r("missing_single", "999"), None)
check("future `until` still holds", r("missing_single", "222"), "later")
check("past `until` has lapsed", r("missing_single", "333"), None)
check("entry with no why still counts but is labelled",
      r("missing_single", "444"), "(no reason recorded)")

check("rule matches by name", r("missing_sealed", "1", "Fabled Puzzle Insert (Top Left)"), "inserts")
check("rule is scoped to its kind",
      r("missing_single", "1", "Fabled Puzzle Insert (Top Left)"), None)
check("rule that doesn't match the name is ignored",
      r("missing_sealed", "1", "Booster Box"), None)
check("expired rule stops covering", r("missing_sealed", "1", "Temporary thing"), None)
check("kindless rule applies to any kind", r("card_no_pid", "x", "anykind card"), "kindless rule")

# The key is kind-scoped: the same id under a different kind must not be
# covered by accident.
check("kind is part of the key", r("missing_sealed", "111"), None)

# ── the committed file ────────────────────────────────────────────────────
print()
real = load_ack(ACK_PATH)
check("ack file parses", isinstance(real.get("acks"), dict), True)

missing_why = [k for k, v in real["acks"].items() if not (v.get("why") or "").strip()]
check("every ack has a reason", missing_why, [])

bad_kind = sorted({k.split(":", 1)[0] for k in real["acks"] if k.split(":", 1)[0] not in KIND_LABEL})
check("every ack key uses a real finding kind", bad_kind, [])

no_colon = [k for k in real["acks"] if ":" not in k]
check("every ack key is kind:id", no_colon, [])

rules_no_why = [i for i, x in enumerate(real["rules"]) if not (x.get("why") or "").strip()]
check("every rule has a reason", rules_no_why, [])

rules_no_pat = [i for i, x in enumerate(real["rules"]) if not x.get("name_matches")]
check("every rule has a pattern", rules_no_pat, [])

import re  # noqa: E402
bad_re = []
for i, x in enumerate(real["rules"]):
    try:
        re.compile(x["name_matches"])
    except re.error:
        bad_re.append(i)
check("every rule regex compiles", bad_re, [])

# A rule with no `kind` silences that pattern across every finding kind, which
# is almost never what someone means — it is how a missing SET gets swallowed by
# a rule written for sealed inserts.
kindless = [x["name_matches"] for x in real["rules"] if not x.get("kind")]
check("no accidental kindless rule in the committed file", kindless, [])

bad_dates = []
for k, v in list(real["acks"].items()) + [(f"rule[{i}]", x) for i, x in enumerate(real["rules"])]:
    u = v.get("until")
    if u and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(u)):
        bad_dates.append(k)
check("every `until` is YYYY-MM-DD", bad_dates, [])


# ── scheduled reviews ─────────────────────────────────────────────────────
print()
SCHED = {"reviews": [
    {"id": "past", "what": "overdue", "due": "2020-01-01", "how": "do it"},
    {"id": "today", "what": "due today", "due": TODAY, "how": "do it"},
    {"id": "future", "what": "not yet", "due": "2999-01-01", "how": "do it"},
    {"id": "undated", "what": "no due date", "how": "do it"},
]}
fired = {f["key"] for f in due_reviews(SCHED, TODAY)}
check("an overdue review fires", "past" in fired, True)
check("a review due today fires", "today" in fired, True)
check("a future review stays quiet", "future" in fired, False)
check("a review with no due date never fires", "undated" in fired, False)
check("a fired review is kind review_due",
      {f["kind"] for f in due_reviews(SCHED, TODAY)}, {"review_due"})
check("the steps travel with the alert",
      due_reviews(SCHED, TODAY)[0]["hint"], "do it")

reviews = real.get("reviews", [])
check("the committed file has reviews", len(reviews) > 0, True)

ids = [r.get("id") for r in reviews]
check("every review has an id", [i for i in ids if not i], [])
check("review ids are unique", len(set(ids)), len(ids))

for field in ("what", "why", "how", "due"):
    missing = [r.get("id") for r in reviews if not (r.get(field) or "")]
    check(f"every review has `{field}`", missing, [])

bad_due = [r.get("id") for r in reviews
           if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("due", "")))]
check("every review `due` is YYYY-MM-DD", bad_due, [])

# --done with no --next needs every_days to roll; without either, the review
# would be marked done and then never come back.
bad_every = [r.get("id") for r in reviews
             if r.get("every_days") is not None and not isinstance(r["every_days"], int)]
check("every_days is an int when present", bad_every, [])

# A review that is already overdue in the committed file means we shipped a red
# workflow — nearly always a mistake in the seed dates rather than intent.
overdue = [r.get("id") for r in reviews if str(r.get("due", "")) < TODAY]
check("no review ships already overdue", overdue, [])

print(f"\n{failed} FAILED" if failed else "\nall passed")
raise SystemExit(1 if failed else 0)
