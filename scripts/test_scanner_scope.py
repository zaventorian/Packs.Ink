"""
Guard: the SHIPPED scanner index only holds cards the site renders.

    python scripts/test_scanner_scope.py

Offline. Reads scanner/text.json + scanner/index.json as committed and the
suppressed list straight out of Index.html (scripts/scanner/scanner_scope.py).

Why it matters: the review row resolves a scan through the scanner's OWN index,
not the catalog, so an out-of-scope card is offered as the answer and saved as a
card the site never shows. The first rebuild that met Lorcast's Format Coconut
rows took 20 clean reads off real released cards, because a leader's name and
version match the card it is drawn from.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE / "scanner"))
import scanner_scope  # noqa: E402

fails = 0


def check(cond: bool, msg: str) -> None:
    global fails
    print(("  ok    " if cond else "  FAIL  ") + msg)
    if not cond:
        fails += 1


text = json.loads((REPO / "scanner" / "text.json").read_text(encoding="utf-8"))
index = json.loads((REPO / "scanner" / "index.json").read_text(encoding="utf-8"))["cards"]
text_ids = {c["id"] for c in text}

suppressed = scanner_scope.suppressed_card_ids()
check(len(suppressed) >= 1, f"SUPPRESSED_CARD_IDS parses out of Index.html ({len(suppressed)} ids)")

bad_code = [c["id"] for c in text if (c.get("s") or "").upper() in scanner_scope.EXCLUDED_SET_CODES]
check(not bad_code, f"text.json carries no excluded-set card ({len(bad_code)} found)")
check(not (suppressed & text_ids), f"text.json carries no suppressed id ({len(suppressed & text_ids)} found)")
check(not (suppressed & {c['id'] for c in index}), "index.json carries no suppressed id")
# index.json has no set code of its own, so it is held to text.json's scope instead:
# every card it can answer must be one the text index (already checked above) also holds.
stray = [c["id"] for c in index if c["id"] not in text_ids]
check(not stray, f"every index.json card is in text.json ({len(stray)} strays)")

# `d` is emitted only for a set that was unreleased at build time, so it must look
# like a date; a malformed one would compare wrong against the browser's today.
bad_d = [c["id"] for c in text if "d" in c and not (isinstance(c["d"], str) and len(c["d"]) == 10 and c["d"][4] == "-")]
check(not bad_d, f"every release date `d` is YYYY-MM-DD ({len(bad_d)} bad)")

# The parser has to fail loudly, not return an empty set, when the const is renamed.
tmp = Path(__file__).with_suffix(".tmp.html")
try:
    tmp.write_text("const SOMETHING_ELSE = new Set([]);", encoding="utf-8")
    try:
        scanner_scope.suppressed_card_ids(tmp)
        check(False, "a missing SUPPRESSED_CARD_IDS raises")
    except SystemExit:
        check(True, "a missing SUPPRESSED_CARD_IDS raises")
finally:
    tmp.unlink(missing_ok=True)

print("\nall passed" if not fails else f"\n{fails} failed")
sys.exit(1 if fails else 0)
