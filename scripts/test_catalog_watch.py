"""
test_catalog_watch.py — guards the acknowledgement layer of the catalog watch.

    python scripts/test_catalog_watch.py

No network, no database: it imports the real ack functions out of
reconcile_catalog and checks them against hand-built inputs, then validates the
committed catalog_watch_ack.json.

Why this exists. The whole point of the watch is that a red run means something
NEW, and that only holds if acknowledgement behaves exactly as advertised. Two
failure modes would quietly destroy it:

  - an ack that matches too much (a sloppy rule regex swallowing a real
    finding), so a genuinely missing set never alerts;
  - an `until` date that doesn't actually expire, so "revisit when Q3 ships"
    becomes "never".

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
from reconcile_catalog import ACK_PATH, KIND_LABEL, ack_reason, load_ack  # noqa: E402

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

print(f"\n{failed} FAILED" if failed else "\nall passed")
raise SystemExit(1 if failed else 0)
