"""
apply_catalog_resolutions.py — turn a DECIDED catalog_watch.json ack into the
patch_pid_overrides.py entry it describes, and drop the ack.

The gap this closes is not detection — reconcile_catalog.py's
`promo_printing_hint` already classifies a `missing_single` finding as a
promo printing of a card we hold and prints a near-complete REPRINT_PROMOS
line, missing only the printed collector number and (when the name matches
more than one card) which base to clone. No feed carries either; a person has
to read the card. The gap is what happens AFTER that: today, filling in those
two blanks still means someone remembers to hand-edit patch_pid_overrides.py
AND remove the ack, in two files, correctly, without being reminded — and
when nobody does, the ack just sits "RESOLVED, not deferred" describing a fix
that was never typed in. That happened to the Rapunzel Set Championship pair
(705084/705085) for days before anyone noticed the entry didn't exist yet.

This script is the mechanical half ONLY. It never decides which card is the
base, what number is printed on it, or whether a card belongs in the catalog
at all — see catalog_watch.json's README for the `resolution` block a human
writes once they've read the card. Given that block, this script:

  1. appends the REPRINT_PROMOS line it describes into patch_pid_overrides.py,
     inside the dedicated AUTO-RESOLVED region at the end of that list;
  2. removes the ack, because the finding can't fire once the row exists —
     same precedent as every other "RESOLVED, not deferred" ack in this file.

It writes local FILES only, never the database. Someone still has to run
`python scripts/patch_pid_overrides.py` (against real Supabase credentials)
for the row to reach the live site — same as every other change staged this
way in this repo. --check reports whether there's anything to apply without
writing, for CI to decide whether to open a PR.

Only resolution kind "reprint_promo" is handled. A "reassign" (moving an
EXISTING row's set/collector_number — e.g. fixing a mis-filed promo) mutates
identity on a row real collections may already reference, and stays a manual
PR: this script only ever ADDS new synthetic clone rows, which is why it can
run without a second pair of eyes on each one before merge.

Usage:
    python scripts/apply_catalog_resolutions.py            # apply, write files
    python scripts/apply_catalog_resolutions.py --check     # exit 1 if there's
                                                             # anything to apply
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WATCH_PATH = HERE / "catalog_watch.json"
OVERRIDES_PATH = HERE / "patch_pid_overrides.py"

AUTO_MARKER = "# === AUTO-RESOLVED"
AUTO_LINE_RE = re.compile(r"# auto:(\d+)\s*$", re.MULTILINE)
RESOLVABLE_KINDS = {"reprint_promo"}
REQUIRED_FIELDS = ("base_pid", "set_id", "collector_number", "new_id", "promo_pid")


def load_watch() -> dict:
    # No default-argument shortcut here: a default is bound to WATCH_PATH at
    # module-load time, so a test pointing WATCH_PATH at a temp file would be
    # silently ignored. Read the module global at call time instead.
    return json.loads(WATCH_PATH.read_text())


def reprint_line(indent: str, res: dict) -> str:
    base_pid = int(res["base_pid"])
    set_id = str(res["set_id"])
    cn = str(res["collector_number"])
    new_id = str(res["new_id"])
    promo_pid = int(res["promo_pid"])
    return (f"{indent}({base_pid}, {set_id!r}, {cn!r}, {new_id!r}, {promo_pid}),"
            f"  # auto:{promo_pid}")


def collect_resolutions(watch: dict) -> list[tuple[str, dict]]:
    """[(ack_key, resolution), ...] for every ack carrying an appliable resolution."""
    out = []
    for key, ack in (watch.get("acks") or {}).items():
        res = ack.get("resolution")
        if not res:
            continue
        kind = res.get("kind")
        if kind not in RESOLVABLE_KINDS:
            continue  # reassign and anything else stay manual, deliberately
        missing = [f for f in REQUIRED_FIELDS if f not in res]
        if missing:
            raise SystemExit(f"{key}: resolution missing {missing}")
        out.append((key, res))
    return out


def already_in_file(src: str, promo_pid: int) -> bool:
    """True if this promo pid is anywhere in the file already — a prior run's
    auto line, or a hand-written REPRINT_PROMOS / OVERRIDES entry. Either way
    the row exists on disk and the ack describing it is stale, not pending."""
    return bool(re.search(rf"\b{promo_pid}\b", src))


def apply(check: bool = False) -> bool:
    """Returns True if anything changed (or, under --check, would change)."""
    watch = load_watch()
    resolutions = collect_resolutions(watch)
    if not resolutions:
        print("No resolved acks to apply.")
        return False

    src = OVERRIDES_PATH.read_text()
    if AUTO_MARKER not in src:
        raise SystemExit(
            f"{OVERRIDES_PATH.name}: AUTO-RESOLVED marker not found — has the "
            f"REPRINT_PROMOS block moved? Re-add the marker before its closing ']'."
        )
    marker_idx = src.index(AUTO_MARKER)
    close_idx = src.index("\n    ]", marker_idx)
    indent = "        "

    new_lines: list[str] = []
    resolved_keys: list[str] = []
    for key, res in resolutions:
        resolved_keys.append(key)
        if already_in_file(src, int(res["promo_pid"])):
            continue  # already written — this run only needs to drop the ack
        new_lines.append(reprint_line(indent, res))

    if new_lines:
        src = src[:close_idx] + "\n" + "\n".join(new_lines) + src[close_idx:]

    acks = watch.get("acks") or {}
    removed = [k for k in resolved_keys if k in acks]
    for k in removed:
        del acks[k]

    changed = bool(new_lines) or bool(removed)
    if not changed:
        print("Every resolved ack is already reflected on disk. Nothing to do.")
        return False

    if check:
        print(f"Would add {len(new_lines)} REPRINT_PROMOS line(s) and remove "
              f"{len(removed)} ack(s): {', '.join(removed)}")
        return True

    OVERRIDES_PATH.write_text(src)
    WATCH_PATH.write_text(json.dumps(watch, indent=2, ensure_ascii=False) + "\n")
    print(f"Added {len(new_lines)} REPRINT_PROMOS line(s), removed {len(removed)} ack(s).")
    if new_lines:
        print("Run `python scripts/patch_pid_overrides.py` (with real Supabase "
              "credentials) to push these to the live catalog.")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                     help="Exit 1 if there's anything to apply; write nothing.")
    args = ap.parse_args()
    did_or_would = apply(check=args.check)
    if args.check:
        sys.exit(1 if did_or_would else 0)
