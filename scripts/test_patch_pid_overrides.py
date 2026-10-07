"""Guards that patch_pid_overrides.py can FAIL, and that the ETL runs it anyway.

    python scripts/test_patch_pid_overrides.py

No network: Supabase is stubbed.

load_lorcast.py writes Lorcast's tcgplayer_id over cards.tcgplayer_product_id every
night — NULL for every promo it hasn't linked — and this script is what puts the
overrides, synthetic rows, connecting foils, oversized cards and promo reprints
back. Every block used to be wrapped in `except: print`, and the script always
exited 0, so a failed patch left those cards priceless on a green run. Locked down:

  1. Each block still runs when an earlier one fails (one bad block must not cost
     the rest), and the script then exits NON-ZERO.
  2. A clean run exits 0.
  3. In etl.yml the re-apply and link steps run even when load_lorcast failed
     part-way (it may already have nulled pids), and retire still waits on a
     successful Lorcast load + link.
"""
from __future__ import annotations

import io
import os
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub-key")
sys.path.insert(0, str(HERE))

import patch_pid_overrides as m  # noqa: E402

failures: list[str] = []


def check(label, got, want):
    if got == want:
        print(f"  ok   {label}")
    else:
        failures.append(label)
        print(f"  FAIL {label}\n         got  {got!r}\n         want {want!r}")


class FakeSb:
    """Every override's card exists; clone sources exist for every pid asked."""
    def __init__(self, fail=()):
        self.fail = set(fail)
        self.log: list[str] = []

    def select(self, table, columns="*", limit=None, filters=None, page_size=1000, order=None):
        f = filters or {}
        if "select" in self.fail and "collector_number" in f:
            raise RuntimeError("Select cards failed (500)")
        if "tcgplayer_product_id" in f:                      # clone sources
            pids = [int(x) for x in re.findall(r"\d+", f["tcgplayer_product_id"])]
            return [{"tcgplayer_product_id": p, "set_id": "set_x", "name": "N",
                     "collector_number": "1"} for p in pids]
        return [{"id": "crd_1", "name": f.get("name", "")[3:], "version": None,
                 "collector_number": "1", "tcgplayer_product_id": None}]

    def update(self, table, match, patch, params=None):
        self.log.append("update")
        if "update" in self.fail:
            raise RuntimeError("Patch cards failed (500)")

    def upsert(self, table, rows, on_conflict=None, batch=100):
        ids = [r["id"] for r in rows]
        kind = ("synthetic" if any(i.startswith("crd_custom_647091") for i in ids) else
                "foil" if all(i.endswith("_foil") for i in ids) else
                "oversized" if all(i.endswith("_oversized") for i in ids) else "reprint")
        self.log.append(kind)
        if kind in self.fail:
            raise RuntimeError(f"Upsert into cards failed (409): {kind}")

    def rpc(self, name, args=None):
        self.log.append(name)
        if "rpc" in self.fail:
            raise RuntimeError("RPC refresh_card_prices_latest failed (500)")


def run(sb):
    m.Supabase = lambda *a, **k: sb
    m.load_dotenv = lambda *a, **k: None
    out = io.StringIO()
    code = 0
    try:
        with redirect_stdout(out):
            m.main()
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    return code, out.getvalue()


print("a clean run")
sb = FakeSb()
code, out = run(sb)
check("exits 0", code, 0)
check("every block ran", [k for k in sb.log if k != "update"],
      ["synthetic", "foil", "oversized", "reprint", "refresh_card_prices_latest"])

for block in ("synthetic", "foil", "oversized", "reprint", "rpc", "update", "select"):
    print(f"\nthe {block} step fails")
    sb = FakeSb(fail={block})
    code, out = run(sb)
    check("exits non-zero", code != 0, True)
    check("the later blocks still ran", "refresh_card_prices_latest" in sb.log, True)
    check("names what failed", "FAIL" in out or "failed" in out.lower(), True)

print("\netl.yml: the repair steps run after a failed Lorcast load")
wf = (HERE.parent / ".github" / "workflows" / "etl.yml").read_text(encoding="utf-8")
meta = wf.split("\n  metadata:", 1)[1].split("\n  selfheal:", 1)[0]
steps = {s.split("\n", 1)[0].strip(): s for s in re.split(r"\n      - name: ", meta)[1:]}


def step_if(name):
    s = steps.get(name, "")
    hit = re.search(r"^\s+if:\s*(.+)$", s, re.M)
    return hit.group(1).strip() if hit else ""


check("Re-apply pid overrides runs unless cancelled", "!cancelled()" in step_if("Re-apply pid overrides"), True)
check("Link pre-order pids runs unless cancelled", "!cancelled()" in step_if("Link pre-order pids"), True)
retire = step_if("Retire superseded prestage cards")
check("Retire still requires the Lorcast load AND the link to have succeeded",
      all(x in retire for x in ("steps.lorcast.outcome == 'success'", "steps.link.outcome == 'success'")), True)
check("...and the steps it names have those ids",
      ("id: lorcast" in steps.get("Run Lorcast loader", ""), "id: link" in steps.get("Link pre-order pids", "")),
      (True, True))
link_job = wf.split("\n  link:", 1)[1].split("\n    steps:", 1)[0]
check("the prices-triggered link job also runs after a FAILED prices job",
      "needs.prices.result == 'failure'" in link_job, True)

if failures:
    print(f"\n{len(failures)} check(s) FAILED")
    sys.exit(1)
print("\nall checks passed")
