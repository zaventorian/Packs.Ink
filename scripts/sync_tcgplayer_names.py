"""
sync_tcgplayer_names.py — keep public.tcgplayer_names (migration 169) in step
with TCGplayer's own spelling of every Lorcana single.

    python scripts/sync_tcgplayer_names.py            # dry run: counts + samples
    python scripts/sync_tcgplayer_names.py --commit

Why: "Buy bulk on TCGplayer" (mass entry) matches on TCGplayer's exact product
name. Where it differs from ours the card either fails ("Chief Bogo- Commanding
Officer") or, worse, silently resolves to the base printing because TCGplayer
suffixes chase versions ("... (Enchanted)"). The client sends the name stored
here, looked up by product id, and falls back to our own name otherwise.

Stores a row for every TCGCSV single (a product with a card Number) whose name
differs from the `cards` row carrying that product id — plus every single no
`cards` row carries (CONNECTING_FOILS companions like "X (Foil)", whose rows the
client builds under the base card). Rows that no longer differ are deleted.
Idempotent; cheap (one products call per group).
"""
from __future__ import annotations

import argparse
import sys

import requests

from supabase_client import Supabase
from tcgcsv_common import LORCANA_CATEGORY_ID, TCGCSV_BASE


def tcgcsv(path: str) -> list[dict]:
    r = requests.get(f"{TCGCSV_BASE}/{LORCANA_CATEGORY_ID}{path}", timeout=60,
                     headers={"User-Agent": "packs.ink name sync"})
    r.raise_for_status()
    return r.json().get("results") or []


def is_single(p: dict) -> bool:
    return any((e.get("name") or "").lower() == "number" and (e.get("value") or "").strip()
               for e in (p.get("extendedData") or []))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    tcg: dict[int, str] = {}
    for g in tcgcsv("/groups"):
        for p in tcgcsv(f"/{g['groupId']}/products"):
            if is_single(p) and p.get("name"):
                tcg[int(p["productId"])] = p["name"].strip()
    if len(tcg) < 2000:
        # A partial TCGCSV answer would delete good rows below. Refuse.
        print(f"only {len(tcg)} singles from TCGCSV — refusing to sync", file=sys.stderr)
        return 1

    sb = Supabase()
    ours: dict[int, str] = {}
    for c in sb.select("cards", "id,name,version,tcgplayer_product_id",
                       filters={"tcgplayer_product_id": "not.is.null"}, order="id.asc"):
        ours[int(c["tcgplayer_product_id"])] = c["name"] + (" - " + c["version"] if c.get("version") else "")

    want = {pid: name for pid, name in tcg.items() if ours.get(pid) != name}
    try:
        have = {int(r["product_id"]): r["name"] for r in sb.select("tcgplayer_names", "product_id,name", order="product_id.asc")}
    except RuntimeError as e:
        if "PGRST205" not in str(e):
            raise
        if args.commit:
            print("tcgplayer_names does not exist yet — apply supabase/169_tcgplayer_names.sql first", file=sys.stderr)
            return 1
        have = {}
    upserts = [{"product_id": pid, "name": name} for pid, name in want.items() if have.get(pid) != name]
    stale = [pid for pid in have if pid not in want]

    differ = sum(1 for pid in want if pid in ours)
    print(f"TCGCSV singles {len(tcg)} · card pids {len(ours)} · differing from ours {differ} · "
          f"not a cards row {len(want) - differ} · to write {len(upserts)} · stale {len(stale)}")
    for r in upserts[:8]:
        print(f"  {r['product_id']}: {ours.get(r['product_id'], '(no cards row)')!r} -> {r['name']!r}")
    if not args.commit:
        print("dry run — pass --commit to write")
        return 0
    if upserts:
        sb.upsert("tcgplayer_names", upserts, on_conflict="product_id", batch=500)
    for i in range(0, len(stale), 200):
        sb.delete("tcgplayer_names", {"product_id": "in.(" + ",".join(map(str, stale[i:i + 200])) + ")"})
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
