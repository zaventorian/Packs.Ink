"""
retire_prestaged.py — drop pre-staged card rows once Lorcast publishes the real
card, so the site switches from our local art + TCGCSV data to Lorcast's.

A pre-staged row (id `crd_prestage_*`, written by prestage_set_cards.py) is a
stand-in for a revealed card Lorcast hadn't indexed yet. Once load_lorcast
inserts the genuine row for that (set_id, collector_number) — a NON-prestage id —
the stand-in is a duplicate and must go, or the catalog shows two tiles for the
same card.

BEFORE deleting a stand-in, any user data that references its card_id (deck
cards, collection items, graded items) is RE-POINTED to the real Lorcast card_id
for the same (set, collector number). Without this, a user who added a pre-staged
card to a deck/collection gets an orphaned "(unknown)" row the moment the card is
retired (the deck_cards.card_id points at a now-deleted row). Merges quantities
when the target row already exists.

Wired into the daily metadata job AFTER load_lorcast / patch_pid_overrides /
link_preorder_pids, so the hand-off is automatic. Idempotent.

Usage:
    python scripts/retire_prestaged.py            # dry run
    python scripts/retire_prestaged.py --commit
"""
from __future__ import annotations

import argparse
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

# Tables that reference cards.id via card_id, with the OTHER columns that (with
# card_id) identify a unique row — used to merge quantities on re-point.
REF_TABLES = [
    ("deck_cards", ["deck_id"]),
    ("collection_items", ["user_id", "printing"]),
    ("graded_collection_items", ["user_id", "printing", "grader", "grade"]),
]


def _norm_cn(cn):
    cn = str(cn or "").split("/", 1)[0].strip()
    if not cn:
        return None
    return str(int(cn)) if cn.isdigit() else cn


def repoint(sb, table, keycols, old_id, new_id, commit):
    """Move rows in `table` from card_id=old_id to card_id=new_id, merging
    quantity when a row for (keycols..., new_id) already exists. Returns count."""
    try:
        olds = sb.select(table, columns=",".join(keycols + ["card_id", "quantity"]),
                         filters={"card_id": f"eq.{old_id}"})
    except Exception as e:
        print(f"    {table}: skipped ({repr(e)[:60]})")
        return 0
    n = 0
    for o in olds:
        n += 1
        if not commit:
            continue
        tgt_filter = {k: f"eq.{o[k]}" for k in keycols}
        tgt_filter["card_id"] = f"eq.{new_id}"
        try:
            ex = sb.select(table, columns="card_id,quantity", filters=tgt_filter)
        except Exception:
            ex = []
        if ex:  # target already there → sum quantities, drop the old row
            newq = (ex[0].get("quantity") or 0) + (o.get("quantity") or 0)
            m = {k: o[k] for k in keycols}; m["card_id"] = new_id
            sb.update(table, match=m, patch={"quantity": newq})
            dfil = {k: f"eq.{o[k]}" for k in keycols}; dfil["card_id"] = f"eq.{old_id}"
            sb.delete(table, dfil)
        else:
            m = {k: o[k] for k in keycols}; m["card_id"] = old_id
            sb.update(table, match=m, patch={"card_id": new_id})
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    rows = sb.select("cards", columns="id,set_id,collector_number")
    real_by_key = {}
    prestage = []
    for r in rows:
        key = (r.get("set_id"), _norm_cn(r.get("collector_number")))
        if str(r.get("id", "")).startswith("crd_prestage_"):
            prestage.append((r["id"], key))
        else:
            real_by_key[key] = r["id"]

    superseded = [(pid, real_by_key[key]) for pid, key in prestage if key in real_by_key]
    print(f"{len(prestage)} prestage row(s); {len(superseded)} superseded by a real Lorcast card.")
    if not superseded:
        print("Nothing to retire.")
        return

    # Re-point every reference off the stand-in and onto the real card first.
    for pid, real_id in superseded:
        moved = 0
        for table, keycols in REF_TABLES:
            moved += repoint(sb, table, keycols, pid, real_id, args.commit)
        print(f"  retire {pid} -> {real_id}" + (f"  ({moved} refs re-pointed)" if moved else ""))

    if not args.commit:
        print("\nDry run — nothing changed. Re-run with --commit.")
        return

    # Delete the stand-ins in chunks (keep the in.() filter a sane length).
    ids = [pid for pid, _ in superseded]
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        sb.delete("cards", {"id": f"in.({','.join(chunk)})"})
    print(f"\nDeleted {len(ids)} prestage row(s).")
    try:
        sb.rpc("refresh_card_prices_latest")
        print("Refreshed card_prices_latest.")
    except Exception as e:
        print(f"matview refresh failed: {e}")
    print("Done.")


if __name__ == "__main__":
    main()
