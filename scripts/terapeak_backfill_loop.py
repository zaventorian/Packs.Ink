"""
terapeak_backfill_loop.py — self-healing driver for the 3-year graded-sales
backfill. Designed to run UNATTENDED for days.

Runs terapeak_scrape.py (all 6 grader queries, oldest-first, resumable) over and
over, recovering from every failure mode:
  - clean non-zero exit (eBay challenge caught by assert_authenticated) -> resume
  - a HANG (scraper alive but no new rows — soft redirect / stuck page) -> a
    watchdog kills it after STALL_LIMIT and restarts (fresh navigation)
  - a HARD CAPTCHA (no progress across retries) -> escalating backoff, KEEP
    retrying; the moment it's solved in the Chrome window, the next attempt
    resumes. It never gives up.
Stops only when the scraper completes a full pass (exit 0).

Each query resumes from its own <slug>.progress.json, so kills/restarts never
lose data. Prereq: a real Chrome on :9222 with the burner logged in.

Usage:
    python scripts/terapeak_backfill_loop.py
"""
from __future__ import annotations

import glob
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "terapeak_output"
SCRAPER = HERE / "terapeak_scrape.py"

RETRY_WAIT = 90                       # pause after a productive-but-interrupted attempt
STUCK_BACKOFF = [120, 300, 600, 900]  # escalating waits on NO progress (2/5/10/15 min)
STALL_LIMIT = 240                     # no new rows for this long while running => hung
POLL = 15                             # progress poll / proc-wait interval (s)


def total_rows() -> int:
    n = 0
    for f in glob.glob(str(OUT / "*.jsonl")):
        try:
            with open(f, encoding="utf-8") as fh:
                n += sum(1 for _ in fh)
        except Exception:
            pass
    return n


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the scraper and any child (Playwright node driver). The CDP Chrome
    belongs to the user and is left untouched."""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_once(args: list[str]):
    """Run the scraper under a hang-watchdog. Returns (status, rows_gained)
    where status is 'done' (exit 0), 'exited' (non-zero), or 'stalled' (killed)."""
    before = total_rows()
    proc = subprocess.Popen(args)
    last = before
    last_change = time.monotonic()
    while True:
        try:
            rc = proc.wait(timeout=POLL)
        except subprocess.TimeoutExpired:
            rc = None
        now = total_rows()
        if now > last:
            last = now
            last_change = time.monotonic()
        if rc is not None:
            return ("done" if rc == 0 else "exited"), now - before
        if time.monotonic() - last_change > STALL_LIMIT:
            print(f"  [watchdog] no new rows for {STALL_LIMIT}s — killing hung scraper",
                  flush=True)
            kill_tree(proc)
            try:
                proc.wait(timeout=30)
            except Exception:
                pass
            return "stalled", total_rows() - before


def main() -> None:
    args = [sys.executable, str(SCRAPER), "--cdp"] + sys.argv[1:]
    attempt = 0
    stuck = 0
    while True:
        attempt += 1
        print(f"\n===== attempt {attempt} (rows: {total_rows()}) =====", flush=True)
        status, gained = run_once(args)
        print(f"===== attempt {attempt}: {status}, +{gained} rows "
              f"(total {total_rows()}) =====", flush=True)

        if status == "done":
            print("ALL QUERIES COMPLETE — backfill finished.", flush=True)
            break

        if gained > 0:
            stuck = 0
            wait = RETRY_WAIT
            print(f"Progress made; {wait}s pause then resume...", flush=True)
        else:
            wait = STUCK_BACKOFF[min(stuck, len(STUCK_BACKOFF) - 1)]
            stuck += 1
            print(f"No progress (hard CAPTCHA in the Chrome window?). Backing off "
                  f"{wait}s; will KEEP retrying — resumes automatically once cleared.",
                  flush=True)
        time.sleep(wait)


if __name__ == "__main__":
    main()
