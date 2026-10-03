"""Guard: the graded matcher honours SUPPRESSED_CARD_IDS (Index.html).

A suppressed row is dropped from the matcher's catalog, or kept under the id
of the card that replaces it (SUPPRESSED_ALIASES). Both failures are silent:
a sale lands on a row the site never shows, or a title that used to match
stops matching. Offline; requests.get is stubbed.
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("SUPABASE_URL", "https://stub.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import terapeak_match as tm  # noqa: E402

fails = []
def check(cond, label):
    print(("PASS  " if cond else "FAIL  ") + label)
    if not cond:
        fails.append(label)

bad = tm._suppressed_ids()
check(len(bad) >= 1, f"SUPPRESSED_CARD_IDS parses ({len(bad)} ids)")
for k, v in tm.SUPPRESSED_ALIASES.items():
    check(k in bad, f"alias source {k} is in SUPPRESSED_CARD_IDS (otherwise the alias never fires)")
    check(v["id"] not in bad, f"alias target {v['id']} is not itself suppressed")

alias_src, alias = next(iter(tm.SUPPRESSED_ALIASES.items()))
dropped = next(iter(bad - set(tm.SUPPRESSED_ALIASES)), None)
rows = [
    {"id": "crd_keep", "set_id": "s", "name": "A", "version": "B", "collector_number": "1"},
    {"id": alias_src, "set_id": "s2", "name": "P", "version": "Q", "collector_number": "223", "tcgplayer_product_id": None},
]
if dropped:
    rows.append({"id": dropped, "set_id": "s3", "name": "D", "version": "E", "collector_number": "7"})

class Resp:
    def __init__(self, b): self.b = b
    def raise_for_status(self): pass
    def json(self): return self.b

real_get = tm.requests.get
tm.requests.get = lambda *a, **k: Resp(rows if k["params"]["offset"] == 0 else [])
try:
    cat = tm.fetch_catalog()
finally:
    tm.requests.get = real_get
ids = [c["id"] for c in cat]
check("crd_keep" in ids, "an ordinary row is kept")
check(alias_src not in ids, "the suppressed alias source never appears under its own id")
aliased = [c for c in cat if c["id"] == alias["id"]]
check(len(aliased) == 1 and aliased[0]["collector_number"] == "223" and aliased[0]["set_id"] == "s2",
      "the alias keeps the source row's set and number under the replacement id")
check(aliased and aliased[0]["tcgplayer_product_id"] == alias["pid"], "the alias carries the replacement's pid")
if dropped:
    check(dropped not in ids, f"a suppressed row with no alias ({dropped}) is dropped")

if fails:
    print(f"\n{len(fails)} failed")
    sys.exit(1)
print("\nall passed")
