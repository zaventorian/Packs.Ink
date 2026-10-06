"""Replay real RPH tournaments against the Swiss simulator's intentional-draw rule.

    python scripts/swiss_replay.py fetch          # cache every event in swiss_replay_events.txt (~10 min, once)
    python scripts/swiss_replay.py check          # the rule, scored against what players actually did
    python scripts/swiss_replay.py fetch 886104   # add one event

Read-only against RPH's public endpoints (the same ones scripts/elo/ingest.py uses); writes
only to scripts/swiss_replay_cache/ (gitignored, ~10 MB). See docs/claude/swiss-simulator.md.

`check` replays the last two Swiss rounds of every cached event with a cut and asks, for every
real table: would the simulator's rule have had them draw, did they draw (0-0, or the 1-1 some
regions report an ID as), and did both make the cut. It scores two rules:

  coordinated  the rule swiss.html ships: tables best-first by the LOWER player's points; a table
               draws if, with it and every table above it drawing out the event, every one of those
               players still finishes inside the cut while each other table puts at most one
               player (its winner) above them. Ties count as threats.
  guarantee    the rule it replaced: draw only if fewer than CUT other players could reach your
               final total by ALL winning out, ignoring that they are paired against each other.

Measured 2026-10-06 over 546 events: coordinated 92% / 50% recall (final round / two left),
guarantee 63% / 7%.
"""
from __future__ import annotations

import collections
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "swiss_replay_cache"
EVENTS = HERE / "swiss_replay_events.txt"
TV = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{}/tv/"
HDR = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
PW, PD = 3, 1

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── fetch ────────────────────────────────────────────────────────────────────
def get(url, allow404=False):
    last = None
    for i in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=90) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404 and allow404:
                return None
            last = e
            if e.code < 500 and e.code != 429:
                break
        except Exception as e:  # network blips: retry
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def fetch_one(eid):
    f = CACHE / f"{eid}.json"
    if f.exists():
        return eid, "cached"
    tv = get(TV.format(eid), allow404=True)
    if not tv:
        return eid, "not found"
    out = {"id": eid, "name": tv.get("name"), "n": tv.get("starting_player_count"), "phases": []}
    for ph in tv.get("tournament_phases", []):
        P = {"type": ph.get("round_type"), "rank_req": ph.get("rank_required_to_enter_phase"), "rounds": []}
        for r in ph.get("rounds", []):
            ms, page = [], 1   # `next_page_number` is a page NUMBER, not a URL
            while True:
                d = get(TV.format(eid) + f"matches/?round_id={r['id']}&page_size=500&page={page}", allow404=True)
                if d is None:
                    break
                ms += d.get("results", [])
                page = d.get("next_page_number")
                if not page:
                    break
            P["rounds"].append({"num": r["round_number"], "m": [
                {"t": m.get("table_number"), "s": m.get("status"), "b": bool(m.get("match_is_bye")),
                 "ml": bool(m.get("match_is_loss")),
                 "p": [[p.get("tv_display_name"), p.get("games_won"), bool(p.get("is_winner"))]
                       for p in sorted(m.get("players", []), key=lambda p: p.get("player_order") or 0)]}
                for m in ms]})
        out["phases"].append(P)
    f.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    return eid, f'{out["n"]} players'


def read_ids(argv):
    if argv:
        return [int(x) for x in argv]
    return [int(x) for line in EVENTS.read_text().splitlines() if not line.startswith("#") for x in line.split()]


def cmd_fetch(argv):
    CACHE.mkdir(exist_ok=True)
    ids = read_ids(argv)
    with ThreadPoolExecutor(6) as ex:
        for eid, msg in ex.map(fetch_one, ids):
            print(eid, msg, flush=True)


# ── rebuild one event's Swiss rounds ─────────────────────────────────────────
def rebuild(d):
    """Swiss rounds as [(a, b, result, games_a, games_b)] with players as ids.

    Display names are the only key RPH gives, and guests share first names, so
    a name held by k players in one round is split into k identities: each
    occurrence goes to whichever same-named player's points best match their
    opponent's (Swiss pairs within point groups)."""
    ident, pts = {}, collections.defaultdict(int)
    rounds, phase_of = [], []
    for pi, ph in enumerate(d["phases"]):
        if ph["type"] != "SWISS":
            continue
        for r in ph["rounds"]:
            ms = r["m"]
            occ = collections.Counter(p[0] for m in ms for p in m["p"])
            for nm, k in occ.items():
                ids = ident.setdefault(nm, [])
                while len(ids) < k:
                    ids.append((nm, len(ids)))
            slot, dup = {}, collections.defaultdict(list)
            for mi, m in enumerate(ms):
                for si, p in enumerate(m["p"]):
                    if len(ident[p[0]]) == 1:
                        slot[(mi, si)] = ident[p[0]][0]
                    else:
                        dup[p[0]].append((mi, si))
            for nm, occs in dup.items():
                free = list(ident[nm])
                for mi, si in occs:
                    m = ms[mi]
                    opp = m["p"][1 - si][0] if len(m["p"]) == 2 else None
                    op = pts[ident[opp][0]] if opp and len(ident[opp]) == 1 else None
                    pick = min(free, key=lambda x: abs(pts[x] - op) if op is not None else 0)
                    free.remove(pick)
                    slot[(mi, si)] = pick
            pairs = []
            for mi, m in enumerate(ms):
                ps = m["p"]
                if m["s"] != "COMPLETE" or not ps:
                    continue
                a = slot[(mi, 0)]
                if m["b"]:
                    pairs.append((a, None, "W", 2, 0))
                elif len(ps) == 1:
                    pairs.append((a, None, "W" if ps[0][2] else "L", 0, 0))
                else:
                    b = slot[(mi, 1)]
                    res = "W" if ps[0][2] else "L" if ps[1][2] else "LL" if m["ml"] else "D"
                    pairs.append((a, b, res, ps[0][1] or 0, ps[1][1] or 0))
            for a, b, res, *_ in pairs:
                if res == "W": pts[a] += PW
                elif res == "L" and b is not None: pts[b] += PW
                elif res == "D": pts[a] += PD; pts[b] += PD
            # A round that is (nearly) all 0-0 is a voided/restarted round, not 100 IDs.
            played = [p for p in pairs if p[1] is not None]
            z = sum(1 for p in played if p[2] == "D" and p[3] == 0 and p[4] == 0)
            if len(played) >= 4 and z >= 0.9 * len(played):
                for a, b, *_ in played:
                    pts[a] -= PD; pts[b] -= PD
                continue
            rounds.append(pairs); phase_of.append(pi)
    cut = None
    for ph in d["phases"]:
        if ph["type"] == "RANKED_SINGLE_ELIMINATION" and ph["rounds"] and ph["rounds"][0]["m"]:
            cut = set()
            for m in ph["rounds"][0]["m"]:
                for p in m["p"]:
                    ids = ident.get(p[0], [])
                    if ids:
                        cut.add(max(ids, key=lambda x: pts[x]))
            break
    return rounds, cut


def states(rounds):
    st = collections.defaultdict(int)
    out = []
    for pairs in rounds:
        out.append(dict(st))
        for a, b, res, *_ in pairs:
            if res == "W": st[a] += PW
            elif res == "L" and b is not None: st[b] += PW
            elif res == "D": st[a] += PD; st[b] += PD
    return out


# ── the two rules ────────────────────────────────────────────────────────────
def coordinated(tables, byes, rem, C):
    """Index set of tables the shipped rule has draw (cut only; tiers aren't on RPH)."""
    F, DD = rem * PW, PD * (rem + 1)
    order = sorted(range(len(tables)), key=lambda k: -min(tables[k]))
    D = set()
    for k in order:
        D.add(k)
        ok = True
        for t in D:
            for me in tables[t]:
                fin = me + DD
                ahead = -1   # me
                for j, (pa, pb) in enumerate(tables):
                    if j in D:
                        ahead += (pa + DD >= fin) + (pb + DD >= fin)
                    else:
                        ahead += max((pa + PW + F >= fin) + (pb + F >= fin), (pa + F >= fin) + (pb + PW + F >= fin))
                ahead += sum(1 for p in byes if p + PW + F >= fin)
                if ahead >= C:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            D.discard(k)
            break
    return D


def guarantee(active, pa, pb, rem, C):
    def safe(me, op):
        fin = me + PD * (rem + 1)
        T = fin - (rem + 1) * PW
        n = sum(1 for p in active if p >= T) - (me >= T)
        if op >= T and op < fin - PD - rem * PW:
            n -= 1
        return n < C
    return safe(pa, pb) and safe(pb, pa)


def cmd_check(argv):
    st = collections.Counter()
    events = 0
    for f in sorted(CACHE.glob("*.json")):
        rounds, cut = rebuild(json.loads(f.read_text(encoding="utf-8")))
        if not cut or len(rounds) < 2:
            continue
        events += 1
        R, C = len(rounds), len(cut)
        S = states(rounds)
        for i in (R - 2, R - 1):
            pre, rem = S[i], R - (i + 1)
            tabs, meta, byes, active = [], [], [], []
            for a, b, res, ga, gb in rounds[i]:
                active.append(pre.get(a, 0))
                if b is None:
                    if res == "W": byes.append(pre.get(a, 0))
                    continue
                active.append(pre.get(b, 0))
                tabs.append((pre.get(a, 0), pre.get(b, 0)))
                meta.append((res == "D" and (ga, gb) in ((0, 0), (1, 1)), a in cut and b in cut))
            D = coordinated(tabs, byes, rem, C)
            for k, (drew, both) in enumerate(meta):
                for rule, says in (("coordinated", k in D), ("guarantee", guarantee(active, *tabs[k], rem, C))):
                    st[(rule, R - i, says, drew, both)] += 1
    print(f"{events} events with a cut\n")
    for left, label in ((1, "final round"), (2, "two rounds left")):
        print(label)
        good = st[("coordinated", left, True, True, True)] + st[("coordinated", left, False, True, True)]
        for rule in ("coordinated", "guarantee"):
            hit = st[(rule, left, True, True, True)]
            taken = hit + st[(rule, left, True, True, False)]
            print(f"  {rule:12} calls {hit:4} of the {good} draws that got both players in ({hit / good:.0%});"
                  f" of its calls players took, {hit / taken if taken else 0:.0%} got both in")
        print()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    {"fetch": cmd_fetch, "check": cmd_check}[cmd](sys.argv[2:])
