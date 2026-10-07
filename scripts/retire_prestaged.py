"""
retire_prestaged.py — drop pre-staged card rows once Lorcast publishes the real
card, so the site switches from our local art + TCGCSV data to Lorcast's.

A pre-staged row (id `crd_prestage_*`, written by prestage_set_cards.py) is a
stand-in for a revealed card Lorcast hadn't indexed yet. Once load_lorcast
inserts the genuine row for that (set_id, collector_number) — a NON-prestage id —
the stand-in is a duplicate and must go, or the catalog shows two tiles for the
same card.

Two supersession keys, both exact:
  1. (set_id, collector_number) — the normal case: Lorcast lands the card in
     the same set we prestaged it into.
  2. shared tcgplayer_product_id — promo prestage rows (set_<slug>_promos, e.g.
     the AotV prerelease-box promos) get their Lorcast twin in Lorcast's OWN
     promo set (PD1), so key 1 never matches. Both twins carry the same pid via
     patch_pid_overrides' name|cn OVERRIDES, and a pid IS product identity.
     This is what retired the six crd_prestage_avp_* rows on 2026-08-12.
Name/version-based matching is deliberately NOT a key: the same name+version+cn
exists as genuinely different products across sets (Maleficent - Monstrous
Dragon is cn 5 in both Promo Set 1 and Promo Set 3, different pids).

Only `crd_prestage_*` ids are ever retired. The hand-minted `crd_custom_*` /
`crd_avp_*` / `crd_cc1_*` rows from patch_pid_overrides are excluded on
purpose: that script re-upserts them every run, so auto-deleting one here would
churn (delete nightly, re-mint next patch run) — and Piglet - Pooh Pirate
Captain (crd_custom_544487) shares (set, cn 223) with Yen Sid in Ursula's
Return, so key 1 would even mis-fire. When Lorcast starts indexing one of
those, do what supabase/107 did for P3 #52-55: move the pid into OVERRIDES,
delete the mint entry, and clean the row by hand.

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
import base64
import hashlib
import hmac
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(__file__))
from supabase_client import Supabase

# Tables that reference cards.id via card_id, with the OTHER columns that (with
# card_id) identify a unique row — used to merge quantities on re-point.
REF_TABLES = [
    ("collection_items", ["user_id", "printing"]),
    ("graded_collection_items", ["user_id", "printing", "grader", "grade"]),
]

# Tables that reference cards.id without a quantity to merge (surrogate PKs) —
# a plain UPDATE re-point is enough. graded_sales matters most: its FK to
# cards would otherwise block the stand-in delete and fail the daily job.
PLAIN_REF_COLS = [
    ("grading_submissions", "card_id"),
    ("scan_samples", "card_id"),
    ("scan_samples", "predicted_card_id"),
    ("graded_sales", "card_id"),
]


# deck_cards.card_id is stored ENCRYPTED ("e1:...", the codec in Index.html), so an
# `eq.<plaintext id>` filter never matches a deck row. Re-pointing decks by plaintext
# did nothing, the stand-in was deleted, and every deck holding one showed "(unknown)"
# (Hyperia City, 2026-10-02). Decks therefore go through this codec.
DECK_KEY = base64.urlsafe_b64decode("TFS-sPPVpi6lHP4MDDD1_VMS5csp0eggEnIIgqcCVYo" + "=")


def _b64u(b):
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def deck_dec(tok):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if not isinstance(tok, str) or not tok.startswith("e1:"):
        return tok
    raw = base64.urlsafe_b64decode(tok[3:] + "=" * (-len(tok[3:]) % 4))
    return AESGCM(DECK_KEY).decrypt(raw[:12], raw[12:], None).decode()


def deck_enc(plain):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = hmac.new(DECK_KEY, ("iv:" + plain).encode(), hashlib.sha256).digest()[:12]
    return "e1:" + _b64u(iv + AESGCM(DECK_KEY).encrypt(iv, plain.encode(), None))


def repoint_decks(sb, mapping, commit):
    """mapping: {old_card_id: new_card_id}. Re-point deck_cards rows (matched by their
    DECRYPTED card_id), merging quantity into an existing target row. Returns
    {old_id: count}. Raises on any error so the caller keeps the stand-in."""
    # Ordered on the whole primary key: Range pages over a tie (deck_id alone,
    # ~40 rows a deck) can return some rows twice and others never, and a row
    # never read is never re-pointed - the stand-in is then deleted under it.
    rows = sb.select("deck_cards", columns="deck_id,card_id,printing,quantity",
                     order="deck_id.asc,card_id.asc,printing.asc")
    have = {(r["deck_id"], r["card_id"], r["printing"]): r for r in rows}
    moved = {}
    for r in rows:
        old = deck_dec(r["card_id"])
        if old not in mapping:
            continue
        moved[old] = moved.get(old, 0) + 1
        if not commit:
            continue
        new_enc = deck_enc(mapping[old])
        tgt = have.get((r["deck_id"], new_enc, r["printing"]))
        key = {"deck_id": r["deck_id"], "printing": r["printing"]}
        if tgt:
            sb.update("deck_cards", match={**key, "card_id": new_enc},
                      patch={"quantity": min(99, (tgt.get("quantity") or 0) + (r.get("quantity") or 0))})
            sb.delete("deck_cards", {"deck_id": f"eq.{r['deck_id']}", "printing": f"eq.{r['printing']}",
                                     "card_id": f"eq.{r['card_id']}"})
        else:
            sb.update("deck_cards", match={**key, "card_id": r["card_id"]}, patch={"card_id": new_enc})
    return moved


def repoint_versions(sb, mapping, commit):
    """Same re-point inside deck_versions.cards (jsonb array of encrypted card_ids)."""
    n = 0
    for v in sb.select("deck_versions", columns="deck_id,version,cards",
                       order="deck_id.asc,version.asc"):
        out, changed = [], False
        for c in v.get("cards") or []:
            old = deck_dec(c.get("card_id"))
            if old in mapping:
                c = {**c, "card_id": deck_enc(mapping[old])}
                changed = True
            out.append(c)
        if changed:
            n += 1
            if commit:
                sb.update("deck_versions", match={"deck_id": v["deck_id"], "version": v["version"]},
                          patch={"cards": out})
    return n


def report_orphans(sb, card_ids):
    """Nightly tripwire: deck rows whose (decrypted) card_id has no cards row."""
    orphans = {}
    for r in sb.select("deck_cards", columns="deck_id,card_id",
                       order="deck_id.asc,card_id.asc,printing.asc"):
        cid = deck_dec(r["card_id"])
        if cid not in card_ids:
            orphans.setdefault(cid, set()).add(r["deck_id"])
    if orphans:
        top = ", ".join(f"{k} ({len(v)})" for k, v in sorted(orphans.items())[:8])
        msg = f"{len(orphans)} deck card id(s) have no cards row: {top}"
        print(msg)
        print(f"::warning title=orphaned deck cards::{msg}")
    else:
        print("No orphaned deck cards.")


def _norm_cn(cn):
    cn = str(cn or "").split("/", 1)[0].strip()
    if not cn:
        return None
    return str(int(cn)) if cn.isdigit() else cn


def repoint(sb, table, keycols, old_id, new_id, commit):
    """Move rows in `table` from card_id=old_id to card_id=new_id, merging
    quantity when a row for (keycols..., new_id) already exists. Returns count.
    Raises on any Supabase error — the caller must NOT delete the stand-in when
    a re-point fails, or the referencing rows are silently orphaned."""
    olds = sb.select(table, columns=",".join(keycols + ["card_id", "quantity"]),
                     filters={"card_id": f"eq.{old_id}"},
                     order=",".join(f"{c}.asc" for c in keycols + ["card_id"]))
    n = 0
    for o in olds:
        n += 1
        if not commit:
            continue
        tgt_filter = {k: f"eq.{o[k]}" for k in keycols}
        tgt_filter["card_id"] = f"eq.{new_id}"
        ex = sb.select(table, columns="card_id,quantity", filters=tgt_filter)
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


def plain_repoint(sb, table, col, old_id, new_id, commit):
    """Re-point a no-quantity reference column. Returns affected count."""
    rows = sb.select(table, columns=col, filters={col: f"eq.{old_id}"})
    if rows and commit:
        sb.update(table, match={col: old_id}, patch={col: new_id})
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", action="store_true")
    args = ap.parse_args()

    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
    sb = Supabase()

    rows = sb.select("cards", columns="id,set_id,collector_number,tcgplayer_product_id")
    real_by_key = {}
    real_by_pid = {}
    prestage = []
    for r in rows:
        key = (r.get("set_id"), _norm_cn(r.get("collector_number")))
        if str(r.get("id", "")).startswith("crd_prestage_"):
            prestage.append((r["id"], key, r.get("tcgplayer_product_id")))
        else:
            real_by_key[key] = r["id"]
            if r.get("tcgplayer_product_id") is not None:
                real_by_pid[r["tcgplayer_product_id"]] = r["id"]

    try:
        report_orphans(sb, {r["id"] for r in rows})
    except Exception as e:
        print(f"orphan check skipped: {repr(e)[:120]}")

    superseded = []
    for pid, key, tpid in prestage:
        real = real_by_key.get(key) or (real_by_pid.get(tpid) if tpid is not None else None)
        if real:
            superseded.append((pid, real))
    print(f"{len(prestage)} prestage row(s); {len(superseded)} superseded by a real Lorcast card.")
    if not superseded:
        print("Nothing to retire.")
        return

    # Re-point every reference off the stand-in and onto the real card first.
    # A stand-in whose re-point failed is excluded from the delete pass — better
    # a duplicate tile for one more day than orphaned deck/collection rows.
    failed = set()
    try:
        deck_moved = repoint_decks(sb, dict(superseded), args.commit)
        repoint_versions(sb, dict(superseded), args.commit)
    except Exception as e:
        # Without the deck re-point, deleting ANY stand-in orphans deck rows.
        print(f"deck re-point FAILED ({repr(e)[:120]}) — keeping every stand-in")
        print(f"::warning title=retire_prestaged deck re-point::{repr(e)[:200]}")
        return
    for pid, real_id in superseded:
        moved = deck_moved.get(pid, 0)
        try:
            for table, keycols in REF_TABLES:
                moved += repoint(sb, table, keycols, pid, real_id, args.commit)
            for table, col in PLAIN_REF_COLS:
                moved += plain_repoint(sb, table, col, pid, real_id, args.commit)
        except Exception as e:
            failed.add(pid)
            print(f"  retire {pid} -> {real_id}: re-point FAILED ({repr(e)[:100]}) — keeping stand-in")
            continue
        print(f"  retire {pid} -> {real_id}" + (f"  ({moved} refs re-pointed)" if moved else ""))

    if not args.commit:
        print("\nDry run — nothing changed. Re-run with --commit.")
        return

    # Delete the stand-ins in chunks (keep the in.() filter a sane length).
    ids = [pid for pid, _ in superseded if pid not in failed]
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        sb.delete("cards", {"id": f"in.({','.join(chunk)})"})
    print(f"\nDeleted {len(ids)} prestage row(s).")
    try:
        sb.rpc("refresh_card_prices_latest")
        print("Refreshed card_prices_latest.")
    except Exception as e:
        print(f"matview refresh failed: {e}")
    if failed:
        # Keeping a stand-in is the safe, self-healing outcome — the card just
        # shows a duplicate tile until a later run re-points it — NOT a pipeline
        # failure. Surface it as a non-fatal GitHub warning so the daily
        # metadata job stops emailing "Run failed" every night for a condition
        # that retries on its own (matches the ETL's "only real failures notify"
        # model). A persistent re-point 403 is usually a missing service_role
        # grant on a referenced table (see migration 100).
        msg = (f"{len(failed)} stand-in(s) kept after re-point failures "
               f"(will retry next run): {', '.join(sorted(failed))}")
        print(f"Done with warnings: {msg}")
        print(f"::warning title=retire_prestaged re-point::{msg}")
        return
    print("Done.")


if __name__ == "__main__":
    main()
