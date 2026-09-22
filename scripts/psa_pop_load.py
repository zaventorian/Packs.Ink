r"""psa_pop_load.py - load pulled PSA population files into graded_pop.

    node scripts\psa_pop_pull.mjs          # pull first (needs a signed-in Chrome)
    python scripts\psa_pop_load.py         # DRY RUN - reports, writes nothing
    python scripts\psa_pop_load.py --commit

Reads scripts/pop_output/psa_pop_<heading>_<date>.json and upserts one row per
PSA spec_id. Dry run by default, like every other writer here: a load is easy to
repeat and hard to notice going wrong.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not resolve PSA rows to our card_id. Rows go in exactly as PSA publishes
them and the client joins them to the catalog in memory, the same way the
Screener joins price_movers. A card_id column here would be a second copy of a
mapping that already exists, free to drift from it, and it would freeze today's
catalog gaps into the data -- the Illumineer's Quest decks are 40 cards PSA
catalogs and we do not, and the day we add them their pops should simply appear.

It also does not interpret Variety. PSA uses that one field for finish (Foil,
Errata), rarity (Enchanted, Epic, Iconic) and provenance (Top Prize, Prize Wall
Exclusive, League Promo) all at once, and deciding which of our printings each
means is a judgement the client makes with the catalog in front of it.

⚠ ONE ROW PER spec_id, NOT PER SET. PSA splits promo sets by year, so P1-Promo
is heading 245594 (2023) AND 263753 (2024). Keyed on the heading a loader would
overwrite one year's promos with another's; keyed on spec_id both survive.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "pop_output"
BATCH = 500

# PSA's own field names -> the keys we store in grades jsonb. Everything that
# looks like a grade is mapped generically so a new one needs no edit here:
#   GradeN0 -> auth | Grade9 -> "9" | Grade9Q -> "9Q" | Grade9_5 -> "9.5"
GRADE_RE = re.compile(r"^Grade(N0|\d+(?:_\d+)?)(Q)?$")
TOTALS = {"GradeTotal": "gradeTotal", "HalfGradeTotal": "halfTotal",
          "QualifiedGradeTotal": "qualifiedTotal"}


def grades_of(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k in TOTALS:
            if v:
                out[TOTALS[k]] = v
            continue
        m = GRADE_RE.match(k)
        if not m or not v:          # drop zeros — most of the ladder is zero
            continue
        num, qual = m.group(1), m.group(2)
        key = "auth" if num == "N0" else num.replace("_", ".")
        out[key + ("Q" if qual else "")] = v
    return out


def env():
    txt = (HERE.parent / ".env").read_text(encoding="utf-8")
    e = dict(re.findall(r"^([A-Z_]+)=(.*)$", txt, re.M))
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not e.get(k):
            sys.exit(f"{k} missing from .env")
    return e["SUPABASE_URL"].rstrip("/"), e["SUPABASE_SERVICE_KEY"]


def upsert(url, key, rows):
    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/rest/v1/graded_pop?on_conflict=spec_id", data=body, method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status
    except urllib.error.HTTPError as e:
        sys.exit(f"upsert failed {e.code}: {e.read().decode('utf-8', 'replace')[:400]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--commit", action="store_true", help="actually write (default is a dry run)")
    ap.add_argument("--glob", default="psa_pop_*.json")
    args = ap.parse_args()

    files = sorted(glob.glob(str(OUT_DIR / args.glob)))
    if not files:
        sys.exit(f"no pop files in {OUT_DIR} — run scripts/psa_pop_pull.mjs first")

    # Newest file wins per heading, so a re-pull on a later day supersedes.
    newest: dict[int, tuple[str, str]] = {}
    for f in files:
        m = re.search(r"psa_pop_(\d+)_(\d{4}-\d{2}-\d{2})\.json$", f)
        if not m:
            continue
        hid, day = int(m.group(1)), m.group(2)
        if hid not in newest or day > newest[hid][1]:
            newest[hid] = (f, day)

    rows, skipped, varieties = [], 0, Counter()
    for hid, (f, day) in sorted(newest.items()):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        st = d["set"]
        for r in d["rows"]:
            # PSA includes its own TOTAL POPULATION line in the data; it has no
            # card number and is not a card.
            if not r.get("CardNumber") or not r.get("SpecID"):
                skipped += 1
                continue
            varieties[r.get("Variety") or ""] += 1
            rows.append({
                "spec_id": int(r["SpecID"]),
                "heading_id": hid,
                "set_label": st["name"],
                "year_issued": st.get("year"),
                "subject_name": r["SubjectName"],
                "card_number": str(r["CardNumber"]).strip(),
                "variety": r.get("Variety") or "",
                "total": int(r.get("Total") or 0),
                "pop_10": int(r.get("Grade10") or 0),
                "pop_9": int(r.get("Grade9") or 0),
                "grades": grades_of(r),
                "pulled_at": d["pulled_at"],
            })

    # A duplicate spec_id across two headings would make the upsert reject the
    # batch (ON CONFLICT DO UPDATE cannot take the same key twice), and it would
    # mean PSA had reused an id — worth stopping for rather than silently keeping
    # whichever came last.
    dupes = [k for k, n in Counter(r["spec_id"] for r in rows).items() if n > 1]
    if dupes:
        sys.exit(f"{len(dupes)} duplicate spec_ids across files, e.g. {dupes[:5]}")

    print(f"{len(rows)} card rows from {len(newest)} PSA headings "
          f"({skipped} total-population lines skipped)")
    print(f"population: {sum(r['total'] for r in rows):,} graded, "
          f"{sum(r['pop_10'] for r in rows):,} of them PSA 10")
    print(f"varieties: {len(varieties)} distinct; commonest "
          f"{[v or '(none)' for v, _ in varieties.most_common(6)]}")

    if not args.commit:
        print("\nDRY RUN — nothing written. Re-run with --commit.")
        sample = rows[0]
        print("sample row:")
        print(json.dumps(sample, indent=2)[:600])
        return 0

    for i in range(0, len(rows), BATCH):
        upsert(*env(), rows[i:i + BATCH])
        print(f"  upserted {min(i + BATCH, len(rows))}/{len(rows)}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
