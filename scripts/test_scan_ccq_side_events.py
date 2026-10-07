"""Side events at a CCQ are never proposed as CCQs (Zaven, 2026-10-03).

Offline: runs scan_ccq_candidates.to_row on hand-made listings.
    python scripts/test_scan_ccq_side_events.py
"""
import os, sys

os.environ.setdefault("SUPABASE_URL", "https://example.invalid")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
sys.path.insert(0, os.path.dirname(__file__))
import scan_ccq_candidates as s  # noqa: E402


def ev(name, cap=64):
    return {"event_id": 1, "name": name, "start_datetime": "2099-11-14T15:00:00+00:00",
            "timezone": "Europe/Madrid", "store_name": "Shop", "city": "X", "country": "ES",
            "latitude": 1.0, "longitude": 2.0, "capacity": cap, "url": "https://example.invalid"}


SIDE = [
    "Big Sunday Core Constructed (RHS-CCQ-SIDE)",
    "Chaos Sealed (RHS-CCQ-SIDE)",
    "CCQ - PARALELO 1 [10/10/26]",
    "CCQ Side Event: Sealed",
    "CCQ parallel tournament",
    "CCQ side-event: Draft",
    "CCQ (Side)",
]
REAL = [
    "Lorcana Viernes CCQ",
    "CCQ La Sagrera",
    "Super Duper CCQper",
    "The Collector Store - $5000 Challenge Championship Qualifier",
    "Legendz League German Championship Qualifier",
    # A store whose NAME ends in "side" (substring tests used to drop these).
    "Lorcana CCQ (Westside)",
    "Seaside Games - CCQ",
    "CCQ at Bayside-Comics",
]

fails = 0
for name in SIDE:
    if s.to_row(ev(name)) is not None:
        print("FAIL: side event proposed:", name); fails += 1
for name in REAL:
    if s.to_row(ev(name)) is None:
        print("FAIL: real qualifier dropped:", name); fails += 1
print(f"{len(SIDE) + len(REAL) - fails}/{len(SIDE) + len(REAL)} ok")
sys.exit(1 if fails else 0)
