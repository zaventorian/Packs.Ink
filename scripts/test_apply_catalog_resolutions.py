"""
test_apply_catalog_resolutions.py — guards apply_catalog_resolutions.py.

    python scripts/test_apply_catalog_resolutions.py

No network, no database, and no writes to the real catalog_watch.json /
patch_pid_overrides.py: it points the module at temp copies (built from
minimal fixtures shaped like the real files, so a change to their real
content can't make this test silently vacuous) and runs the real functions
against them.

What has to hold, and why each one is the failure mode that matters:

  - a resolved ack actually produces a REPRINT_PROMOS line — this is the
    whole point; the Rapunzel pair sat "resolved" with no line for days
    before anyone noticed.
  - re-running is a no-op — the daily workflow calls this every day, and a
    script that duplicates its own output on every run corrupts the file it
    is supposed to be maintaining.
  - a pid that's already in the file (hand-filed before this script existed,
    or written by a prior run under a different key) drops its ack WITHOUT
    adding a second line — a duplicate REPRINT_PROMOS entry for one pid is
    two tiles for one card.
  - a "reassign" resolution is left alone — this script only ever ADDS rows;
    mutating an existing row's identity is a human's call, every time.
  - a resolution missing a required field is a hard error, not a silent skip
    — a half-written resolution reaching the file would ship a broken tuple.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apply_catalog_resolutions as acr  # noqa: E402

failed = 0


def check(name: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  (got {got!r}, want {want!r})"))


OVERRIDES_FIXTURE = """\
FOO = "bar"
def main():
    REPRINT_PROMOS = [
        (111111, "set_a", "1", "crd_a_1_x", 222222),
        # === AUTO-RESOLVED — lines below this point are written by
        # scripts/apply_catalog_resolutions.py.
    ]
"""


def make_watch(acks: dict) -> dict:
    return {"acks": acks, "reviews": []}


class Sandbox:
    """Points the module at a fresh temp copy of each fixture for one test."""

    def __init__(self, acks: dict, overrides_src: str = OVERRIDES_FIXTURE):
        self.dir = tempfile.mkdtemp()
        self.watch_path = Path(self.dir) / "catalog_watch.json"
        self.overrides_path = Path(self.dir) / "patch_pid_overrides.py"
        self.watch_path.write_text(json.dumps(make_watch(acks), indent=2))
        self.overrides_path.write_text(overrides_src)
        acr.WATCH_PATH, acr.OVERRIDES_PATH = self.watch_path, self.overrides_path

    def overrides_text(self) -> str:
        return self.overrides_path.read_text()

    def watch(self) -> dict:
        return json.loads(self.watch_path.read_text())


GOOD_RES = {
    "kind": "reprint_promo",
    "base_pid": 704593, "set_id": "set_dis", "collector_number": "8",
    "new_id": "crd_dis_8_x", "promo_pid": 712043,
}

# ── a resolved ack produces a line and the ack is removed ──────────────────
sb = Sandbox({"missing_single:712043": {"why": "x", "resolution": GOOD_RES}})
changed = acr.apply()
check("apply() reports a change", changed, True)
check("the REPRINT_PROMOS line was written",
      "(704593, 'set_dis', '8', 'crd_dis_8_x', 712043)" in sb.overrides_text(), True)
check("it carries the auto marker for future re-runs",
      "# auto:712043" in sb.overrides_text(), True)
check("it landed inside the auto-resolved region, after the hand-written line",
      sb.overrides_text().index("crd_a_1_x") < sb.overrides_text().index("crd_dis_8_x"), True)
check("the ack was removed", "missing_single:712043" in sb.watch()["acks"], False)

# ── re-running is a no-op ───────────────────────────────────────────────────
before = sb.overrides_text()
changed_again = acr.apply()
check("second run reports no change (ack already gone)", changed_again, False)
check("file is byte-identical after a no-op re-run", sb.overrides_text(), before)

# ── --check reports without writing ─────────────────────────────────────────
sb2 = Sandbox({"missing_single:712043": {"why": "x", "resolution": GOOD_RES}})
before2 = sb2.overrides_text()
would = acr.apply(check=True)
check("--check reports there's something to apply", would, True)
check("--check writes nothing", sb2.overrides_text(), before2)
check("--check does not remove the ack either",
      "missing_single:712043" in sb2.watch()["acks"], True)

# ── a pid already present in the file drops the ack without duplicating ────
already_src = OVERRIDES_FIXTURE.replace(
    '"crd_a_1_x", 222222),',
    '"crd_a_1_x", 222222),\n        (704593, "set_dis", "8", "crd_dis_8_hand_filed", 712043),  # filed by hand',
)
sb3 = Sandbox({"missing_single:712043": {"why": "x", "resolution": GOOD_RES}}, already_src)
changed3 = acr.apply()
check("a hand-filed pid still reports a change (the ack drop)", changed3, True)
check("no second REPRINT_PROMOS line for the same pid",
      sb3.overrides_text().count("712043"), 1)
check("the stale ack was removed anyway", "missing_single:712043" in sb3.watch()["acks"], False)

# ── a reassign resolution is never touched ──────────────────────────────────
REASSIGN = {"kind": "reassign", "id": "crd_x", "set_id": "set_dis", "collector_number": "4"}
sb4 = Sandbox({"missing_single:999": {"why": "x", "resolution": REASSIGN}})
changed4 = acr.apply()
check("a reassign resolution triggers no change", changed4, False)
check("its ack is left in place", "missing_single:999" in sb4.watch()["acks"], True)
check("nothing was added to the overrides file", sb4.overrides_text(), OVERRIDES_FIXTURE)

# ── a resolution missing a required field is a hard error ──────────────────
bad_res = copy.deepcopy(GOOD_RES)
del bad_res["collector_number"]
sb5 = Sandbox({"missing_single:1": {"why": "x", "resolution": bad_res}})
try:
    acr.apply()
    check("a missing required field raises", False, True)
except SystemExit:
    check("a missing required field raises", True, True)

# ── no resolutions at all is a clean no-op ──────────────────────────────────
sb6 = Sandbox({"missing_single:1": {"why": "no resolution here"}})
changed6 = acr.apply()
check("no resolutions present -> no change", changed6, False)


print(f"\n{failed} FAILED" if failed else "\nall passed")
raise SystemExit(1 if failed else 0)
