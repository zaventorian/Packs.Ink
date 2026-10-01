r"""check_pop_coverage.py - every card with PSA graded sales must have a PSA population row.

    python scripts/check_pop_coverage.py        # exit 1 when a NEW gap appears

Zaven's rule (2026-10-01): "if any card has graded sales but no pop report,
something is wrong". It was: the Gen Con 2022 promos (Promo Set 1 #1-7) had
~1,100 PSA sales and no population because their PSA heading sits under a slug
the pull skipped, and the D23 numbers (PSA "01", ours "1") never joined.

The join mirrors the site's `popCardKey` (set + name + number, folded the same
way), so a gap here is a gap on the card page. Keep the two in step: the set
aliases below are Index.html's POP_SET_ALIASES.

Read-only. Needs .env. KNOWN is the ruled-on list; anything else exits 1 and is
named with its sale count, which is what the weekly PSA review reports.
"""
import json, re, sys, unicodedata, urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALIASES = [("1-demo deck", "The First Chapter"), ("p1-promo", "Promo Set 1"),
           ("p2-promo", "Promo Set 2"), ("p3-promo", "Promo Set 3"), ("pd1-promo", "PD1"),
           ("c1-", "Lorcana Challenge Promo (C1)"), ("c2-", "Lorcana Challenge Promo (C2)"),
           ("d23-", "D23 Collection"), ("dis-magical places", "Magical Places Promos"),
           ("cc1-", "Curator's Collection: Heroines"),
           ("cc2-", "Curator's Collection: Beauty and the Beast"),
           ("q1 ", "Extras & Oddities"), ("q2 ", "Extras & Oddities")]
DISPLAY = {"Challenge Promo": "Lorcana Challenge Promo (C1)",
           "Lorcana Challenge Year 3": "Lorcana Challenge Promo (C2)",
           "EPCOT Festival of the Arts": "Magical Places Promos"}
C1_RENUMBER = {"25": "1", "41": "2", "42": "3", "43": "4"}
# Ruled on: (our set, name, number) -> why it has no PSA row. Add with a reason.
# Empty on purpose: Index.html's popRowsFor fallback (lead name + number, PSA's "A"
# suffix) joins everything that used to live here. A new entry is a real gap.
KNOWN = {
    ("Ursula's Return", "Piglet - Pooh Pirate Captain", "223"):
        "the Deep Trouble quest card; on the site it joins PSA's ITI #223 through popRowsFor's quest fallback",
}
MIN_SALES = 5   # below this a name collision or one stray sale is more likely than a real gap


def fold(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c)).translate({ord(c): None for c in "'‘’`´"})
    s = re.sub(r"^([^/]+)/\1(?= - )", r"\1", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def num(n):
    return re.sub(r"^0+(?=\d)", "", str(n or "").strip())


def pset(label):
    m = re.search(r"disney lorcana\s+en\s+(.+)$", str(label or "").strip(), re.I)
    if not m:
        return None
    rest = m.group(1).strip()
    for frag, ours in ALIASES:
        if rest.lower().startswith(frag):
            return ours
    d = rest.find("-")
    return rest[d + 1:].strip() if d > 0 else None


def env():
    e = dict(re.findall(r"^([A-Z_]+)=(.*)$", (HERE.parent / ".env").read_text(encoding="utf-8"), re.M))
    return e["SUPABASE_URL"].rstrip("/"), e["SUPABASE_SERVICE_KEY"]


def fetch(url, key, table, select, order, extra=""):
    out, off = [], 0
    while True:
        req = urllib.request.Request(
            f"{url}/rest/v1/{table}?select={select}&order={order}&limit=1000&offset={off}{extra}",
            headers={"apikey": key, "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            page = json.load(r)
        out += page
        if len(page) < 1000:
            return out
        off += 1000


def main():
    url, key = env()
    pop = set()
    for r in fetch(url, key, "graded_pop", "set_label,subject_name,card_number", "spec_id.asc"):
        if pset(r["set_label"]):
            st, no = fold(pset(r["set_label"])), num(r["card_number"])
            pop.add(f"{st}|{fold(r['subject_name'])}|{no}")
            pop.add(f"~{st}|{fold(r['subject_name'].split(' - ')[0])}|{no}")  # popLooseKey
    sets = {s["id"]: s["name"] for s in fetch(url, key, "sets", "id,name", "id.asc")}
    cards = {c["id"]: c for c in fetch(url, key, "cards", "id,name,version,collector_number,set_id", "id.asc")}
    sales = defaultdict(int)
    for r in fetch(url, key, "graded_sales_rollup", "card_id,sale_count", "card_id.asc,grade.asc,printing.asc",
                   "&grader=eq.PSA"):
        sales[r["card_id"]] += r["sale_count"] or 0

    missing, known = [], []
    for cid, n in sales.items():
        c = cards.get(cid)
        if not c or n < MIN_SALES:
            continue
        raw = sets.get(c["set_id"], "")
        sname = DISPLAY.get(raw, raw)
        cn = str(c["collector_number"] or "")
        if re.search(r"[a-z]{2}$", cn, re.I) and cn[:-2].isdigit():
            continue  # 25ja / 25zh: regional printings, not in PSA's English headings
        if raw == "Challenge Promo":
            cn = C1_RENUMBER.get(cn, cn)
        name = c["name"] + (f" - {c['version']}" if c["version"] else "")
        st, lead = fold(sname), fold(name.split(" - ")[0])
        # mirrors Index.html's popRowsFor: exact, then number + PSA's "A", then lead name + number
        if (f"{st}|{fold(name)}|{num(cn)}" in pop or f"{st}|{fold(name)}|{num(cn)}A" in pop
                or f"~{st}|{lead}|{num(cn)}" in pop):
            continue
        item = (sname, name, num(cn), n)
        (known if (sname, name, num(cn)) in KNOWN else missing).append(item)
    for sname, name, cn, n in sorted(known, key=lambda x: -x[3]):
        print(f"  known   {sname} #{cn} {name}: {n} sales - {KNOWN[(sname, name, cn)]}")
    for sname, name, cn, n in sorted(missing, key=lambda x: -x[3]):
        print(f"  MISSING {sname} #{cn} {name}: {n} PSA sales, no population row")
    print(f"{len(missing)} card(s) with PSA sales and no population row"
          f" ({len(known)} ruled on)")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
