"""Does RPH publish anything that separates an agreed draw from a played one?

    python scripts/elo/probe_rph_draw_fields.py --event 881262 [--round 5]

Read-only, network only — touches no database. `ingest.py` reads a handful of
keys out of the match payload (is_winner, games_won, match_is_bye,
table_number), and a field it does NOT read could settle intent directly
instead of by inference. This dumps the COMPLETE payload so that question gets
an evidence-based answer rather than an assumption.

It prints, for the chosen round: every key seen on a match and on a player, one
full draw record, one full decisive record, and the keys whose values differ
between the two groups. A key that is constant within draws and different in
decisive matches is the thing we are looking for.
"""
import argparse, json, sys, urllib.error, urllib.request
from collections import defaultdict

API = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def is_draw(m):
    ps = m.get("players", [])
    return (not m.get("match_is_bye")) and len(ps) >= 2 \
        and not any(p.get("is_winner") for p in ps)


def summarize(label, records, keys):
    """Per key, the distinct values across a group — a key that is constant in
    one group and differs in the other is a candidate signal."""
    out = {}
    for k in keys:
        vals = {json.dumps(r.get(k), default=str) for r in records}
        out[k] = sorted(vals)[:4]
    print(f"\n  {label} (n={len(records)})")
    for k, vals in sorted(out.items()):
        print(f"    {k:<28} {', '.join(vals)[:110]}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--round", type=int, default=None, help="round_number (default: all)")
    args = ap.parse_args()

    tv = get(API.format(eid=args.event) + "/tv/")
    rounds = []
    for ph in tv.get("tournament_phases", []):
        for r in ph.get("rounds", []):
            rounds.append((r["id"], r["round_number"], ph.get("round_type"), r.get("status")))
    print(f"event {args.event}: {len(rounds)} rounds")
    print("ROUND-LEVEL KEYS: " + ", ".join(sorted(
        {k for ph in tv.get("tournament_phases", []) for r in ph.get("rounds", []) for k in r})))
    print("PHASE-LEVEL KEYS: " + ", ".join(sorted(
        {k for ph in tv.get("tournament_phases", []) for k in ph})))

    draws, decisive, mkeys, pkeys = [], [], set(), set()
    for rid, rnum, rtype, rstatus in rounds:
        if args.round is not None and rnum != args.round:
            continue
        try:
            d = get(API.format(eid=args.event) + f"/tv/matches/?round_id={rid}")
        except urllib.error.HTTPError as e:
            print(f"  R{rnum}: HTTP {e.code}"); continue
        ms = d.get("results", [])
        print(f"  R{rnum} (id={rid}, {rtype}, {rstatus}): {len(ms)} matches")
        for m in ms:
            mkeys.update(m)
            for p in m.get("players", []):
                pkeys.update(p)
            if m.get("match_is_bye"):
                continue
            (draws if is_draw(m) else decisive).append(m)

    print(f"\nMATCH KEYS ingest.py does NOT read: " + ", ".join(sorted(
        mkeys - {"players", "match_is_bye", "table_number"})))
    print(f"PLAYER KEYS ingest.py does NOT read: " + ", ".join(sorted(
        pkeys - {"tv_display_name", "player_order", "is_winner", "games_won"})))

    if not draws:
        print("\nno draws in scope"); return

    summarize("DRAWS — match level", draws, mkeys)
    summarize("DECISIVE — match level", decisive, mkeys)
    dps = [p for m in draws for p in m.get("players", [])]
    cps = [p for m in decisive for p in m.get("players", [])]
    summarize("DRAWS — player level", dps, pkeys)
    summarize("DECISIVE — player level", cps, pkeys)

    print("\nONE FULL DRAW RECORD")
    print(json.dumps(draws[0], indent=2, default=str)[:2500])
    if decisive:
        print("\nONE FULL DECISIVE RECORD")
        print(json.dumps(decisive[0], indent=2, default=str)[:2500])


if __name__ == "__main__":
    main()
