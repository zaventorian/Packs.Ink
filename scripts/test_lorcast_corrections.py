"""test_lorcast_corrections.py: load_lorcast.py's CARD_CORRECTIONS, Lorcast's own
typos corrected against the printed card. Offline (no network, no .env).

    python scripts/test_lorcast_corrections.py

Both ways this fails are silent: a correction that stops applying leaves the
typo on the site, and a corrected NAME whose TCG_PID_OVERRIDES key still uses
the old spelling loses that card's TCGplayer link and price.
"""
import os
import re
import sys

os.environ.setdefault("SUPABASE_URL", "http://stub")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "stub")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import load_lorcast as L
import patch_pid_overrides as P

fails = 0


def ok(name, got, want):
    global fails
    if got == want:
        print("  ok   " + name)
    else:
        fails += 1
        print(f"  FAIL {name}\n        got  {got!r}\n        want {want!r}")


RUSSELL = "crd_fa5f0ceced414c31a886670d84e5a6c7"
MERLIN = "crd_ac48e83f0cec4636ae8d4db35632ba27"

# Lorcast's spelling is corrected on the way in.
row = L.transform_card({"id": RUSSELL, "name": "Russel", "version": "Finding Adventure"}, "s", "14")
ok("typo in name corrected", (row["name"], row["version"]), ("Russell", "Finding Adventure"))
row = L.transform_card({"id": MERLIN, "name": "Merlin's Shop and Smithy", "version": "Magical Markey"}, "s", "14")
ok("typo in version corrected", (row["name"], row["version"]), ("Merlin's Shop and Smithy", "Magical Market"))

# Once Lorcast fixes it, the entry stops applying and says so.
stale = []
row = L.transform_card({"id": RUSSELL, "name": "Russell", "version": "Finding Adventure"}, "s", "14", stale)
ok("a fixed typo is left alone", row["name"], "Russell")
ok("a fixed typo is reported", len(stale), 1)

# A value Lorcast changed to something else is never overwritten.
stale = []
row = L.transform_card({"id": RUSSELL, "name": "Russell Jr.", "version": "Finding Adventure"}, "s", "14", stale)
ok("an unexpected value is kept", row["name"], "Russell Jr.")
ok("an unexpected value is reported", len(stale), 1)

# Other cards pass through untouched.
row = L.transform_card({"id": "crd_other", "name": "Russel", "version": "Markey"}, "s", "14")
ok("only the keyed card is corrected", (row["name"], row["version"]), ("Russel", "Markey"))

# Every entry is well-formed.
for cid, fix in L.CARD_CORRECTIONS.items():
    for field, pair in fix.items():
        ok(f"{cid} {field} is a (wrong, right) pair",
           isinstance(pair, tuple) and len(pair) == 2 and pair[0] != pair[1] and all(isinstance(x, str) for x in pair),
           True)

# TCG_PID_OVERRIDES keys are "Name - Version|cn", built from the CORRECTED row,
# so none may still spell a corrected name or version the old way.
html = open(os.path.join(os.path.dirname(HERE), "Index.html"), encoding="utf8").read()
block = html[html.index("const TCG_PID_OVERRIDES"):]
block = block[:block.index("};")]
client_keys = re.findall(r'^\s*"([^"\n]+\|[^"\n]+)"\s*:', block, re.M)
ok("client override keys found", len(client_keys) > 10, True)
for where, keys in (("Index.html", client_keys), ("patch_pid_overrides.py", list(P.OVERRIDES))):
    for key in keys:
        product = key.rsplit("|", 1)[0]
        name, _, version = product.partition(" - ")
        for fix in L.CARD_CORRECTIONS.values():
            for field, (wrong, right) in fix.items():
                part = name if field == "name" else version
                if part == wrong:
                    ok(f"{where} key {key!r} uses the corrected {field}", part, right)

print(f"\n{'OK' if not fails else 'FAILED'}: lorcast corrections ({fails} failure(s))")
sys.exit(1 if fails else 0)
