"""
test_smooth_low_prices.py — synthetic test cases for the phantom-spike
smoothing algorithm in smooth_low_prices.py.

The four cases mirror the contract documented in CLAUDE.md ("Synthetic test
cases (run before changing the algorithm)"):

  1. 13-day phantom (Black Cauldron shape)  -> all 13 days smoothed to baseline
  2. 30-day sustained move ($3 -> $30 -> $3) -> 0 days smoothed (duration > 14)
  3. 3-day pump ($3 -> $100 -> $3)           -> all 3 days smoothed
  4. step-up ($3 -> $30 forever)             -> 0 days smoothed (no snap-back)

Runs two ways:
  - pytest:                 pytest scripts/test_smooth_low_prices.py
  - plain python (no deps): python scripts/test_smooth_low_prices.py
    (prints PASS/FAIL per case and exits non-zero if any case fails, so the
     CI step doesn't strictly need pytest installed.)

Input shape matches compute_smoothed_for_series's contract: `series` is a list
of {"date": "YYYY-MM-DD", "low_price": <number|None>} dicts sorted ascending;
the return is a dict mapping each in-eval-window date to a smoothed float or
None (None = raw low_price passes through).
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

# Allow `python scripts/test_smooth_low_prices.py` from the repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from smooth_low_prices import compute_smoothed_for_series  # noqa: E402

# Fixed anchor so the synthetic dates are deterministic.
ANCHOR = date(2026, 1, 1)


def _iso(day_offset: int) -> str:
    return (ANCHOR + timedelta(days=day_offset)).isoformat()


def build_series(values_by_offset: dict[int, float]) -> list[dict]:
    """Build a sorted series of {"date", "low_price"} from {day_offset: price}."""
    return [
        {"date": _iso(off), "low_price": price}
        for off, price in sorted(values_by_offset.items())
    ]


def _flat(start_off: int, end_off_inclusive: int, price: float) -> dict[int, float]:
    """Continuous daily run at a constant price."""
    return {off: price for off in range(start_off, end_off_inclusive + 1)}


def smoothed_days(out: dict[str, float | None]) -> list[str]:
    """Dates whose output is a (non-None) smoothed value."""
    return sorted(d for d, v in out.items() if v is not None)


# --- Geometry ---------------------------------------------------------------
#
# We give every series a long baseline run BEFORE the event (so the per-day
# Phase-1 pre window [D-30, D-1] and the Phase-3 pre window [S-30, S-1] both
# have >= PRE_MIN_SAMPLES samples) and a long tail AFTER (so the Phase-3 post
# window [E+8, E+21] has >= POST_MIN_SAMPLES samples).
#
#   baseline:  offsets 0..49   (50 continuous days)
#   event:     starts at offset 50
#   tail:      runs well past event_end + 21


def case1_13_day_phantom() -> tuple[list[dict], date, date, list[str]]:
    """Black Cauldron shape: ~$14 baseline, a 13-day phantom spike, then back
    to ~$14. All 13 spike days must be smoothed."""
    base = 14.0
    vals = _flat(0, 49, base)
    spike_start, spike_end = 50, 62  # 13 days inclusive
    spike_shape = [2140, 99, 119, 13, 61, 200, 90, 110, 75, 130, 95, 88, 102]
    for i, off in enumerate(range(spike_start, spike_end + 1)):
        vals[off] = float(spike_shape[i])
    # Long tail back at baseline so the post window is well-populated.
    vals.update(_flat(spike_end + 1, spike_end + 40, base))
    series = build_series(vals)
    expected = [_iso(off) for off in range(spike_start, spike_end + 1)]
    eval_start = ANCHOR + timedelta(days=spike_start)
    eval_end = ANCHOR + timedelta(days=spike_end)
    return series, eval_start, eval_end, expected


def case2_30_day_sustained_move() -> tuple[list[dict], date, date, list[str]]:
    """$3 baseline -> $30 for 30 days -> $3. Duration > 14 → real move, 0
    days smoothed even though post snaps back to baseline."""
    base = 3.0
    vals = _flat(0, 49, base)
    move_start, move_end = 50, 79  # 30 days inclusive
    vals.update(_flat(move_start, move_end, 30.0))
    vals.update(_flat(move_end + 1, move_end + 40, base))
    series = build_series(vals)
    eval_start = ANCHOR + timedelta(days=move_start)
    eval_end = ANCHOR + timedelta(days=move_end)
    return series, eval_start, eval_end, []  # nothing smoothed


def case3_3_day_pump() -> tuple[list[dict], date, date, list[str]]:
    """$3 baseline -> $100 for 3 days -> $3. All 3 pump days smoothed."""
    base = 3.0
    vals = _flat(0, 49, base)
    pump_start, pump_end = 50, 52  # 3 days inclusive
    vals.update(_flat(pump_start, pump_end, 100.0))
    vals.update(_flat(pump_end + 1, pump_end + 40, base))
    series = build_series(vals)
    expected = [_iso(off) for off in range(pump_start, pump_end + 1)]
    eval_start = ANCHOR + timedelta(days=pump_start)
    eval_end = ANCHOR + timedelta(days=pump_end)
    return series, eval_start, eval_end, expected


def case4_step_up_no_return() -> tuple[list[dict], date, date, list[str]]:
    """$3 baseline -> $30 forever (no return). Post never snaps back to pre →
    real move, 0 days smoothed."""
    base = 3.0
    vals = _flat(0, 49, base)
    step_start = 50
    # Step up to $30 and stay there for the rest of the series.
    vals.update(_flat(step_start, step_start + 40, 30.0))
    series = build_series(vals)
    eval_start = ANCHOR + timedelta(days=step_start)
    # Only evaluate the first few step days (enough post-data exists for them).
    eval_end = ANCHOR + timedelta(days=step_start + 5)
    return series, eval_start, eval_end, []  # nothing smoothed


def _run_case(name: str, builder) -> bool:
    series, eval_start, eval_end, expected = builder()
    out = compute_smoothed_for_series(series, eval_start, eval_end)
    got = smoothed_days(out)
    ok = got == sorted(expected)
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}: smoothed {len(got)} day(s), expected {len(expected)}")
    if not ok:
        print(f"        expected: {sorted(expected)}")
        print(f"        got:      {got}")
        # Show the actual smoothed values for debugging.
        for d in got:
            print(f"          {d} -> {out[d]}")
    return ok


# --- pytest entry points ----------------------------------------------------

def test_case1_13_day_phantom_all_smoothed():
    series, eval_start, eval_end, expected = case1_13_day_phantom()
    out = compute_smoothed_for_series(series, eval_start, eval_end)
    assert smoothed_days(out) == sorted(expected)
    # Every smoothed value should land near the ~$14 baseline, not the spikes.
    for d in expected:
        assert out[d] is not None
        assert 10.0 <= out[d] <= 18.0, f"{d} smoothed to {out[d]}, expected ~14"


def test_case2_30_day_move_not_smoothed():
    series, eval_start, eval_end, _ = case2_30_day_sustained_move()
    out = compute_smoothed_for_series(series, eval_start, eval_end)
    assert smoothed_days(out) == []


def test_case3_3_day_pump_all_smoothed():
    series, eval_start, eval_end, expected = case3_3_day_pump()
    out = compute_smoothed_for_series(series, eval_start, eval_end)
    assert smoothed_days(out) == sorted(expected)
    for d in expected:
        assert out[d] is not None
        assert 1.0 <= out[d] <= 6.0, f"{d} smoothed to {out[d]}, expected ~3"


def test_case4_step_up_not_smoothed():
    series, eval_start, eval_end, _ = case4_step_up_no_return()
    out = compute_smoothed_for_series(series, eval_start, eval_end)
    assert smoothed_days(out) == []


# --- plain-python runner ----------------------------------------------------

def main() -> int:
    cases = [
        ("case1: 13-day phantom -> all smoothed", case1_13_day_phantom),
        ("case2: 30-day move -> 0 smoothed", case2_30_day_sustained_move),
        ("case3: 3-day pump -> all smoothed", case3_3_day_pump),
        ("case4: step-up -> 0 smoothed", case4_step_up_no_return),
    ]
    results = [_run_case(name, builder) for name, builder in cases]
    passed = sum(results)
    print(f"\n{passed}/{len(results)} cases passed.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
