"""Dump ONE Ravensburger Play event in full: metadata, final standings,
registrations (real names + final place) and every round's pairings/results.

    python scripts/elo/dump_event.py 886104
    python scripts/elo/dump_event.py https://tcg.ravensburgerplay.com/events/886104
    python scripts/elo/dump_event.py 886104 --json out.json --csv-dir out/

Read-only: hits the same public endpoints ingest.py uses, writes nothing to
any DB. To get an event INTO the Elo pipeline use ingest.py instead.
"""
import argparse, csv, json, re, sys, time, urllib.request, urllib.error
from pathlib import Path

TV = "https://api.cloudflare.ravensburgerplay.com/hydraproxy/api/v2/player/events/{eid}/tv/"
META = "https://api.ravensburgerplay.com/api/v2/events/{eid}/"
REG = "https://api.ravensburgerplay.com/api/v2/events/{eid}/registrations/?page_size=100"
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def http_get(url, retries=3, allow_404=False):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404 and allow_404:
                return None
            last = e
            if e.code < 500:
                break
            time.sleep(0.5 * (i + 1))
        except Exception as e:
            last = e
            time.sleep(0.5 * (i + 1))
    if allow_404:
        return None
    raise last


def paged(url):
    """Walk RPH's pagination, returning every result row.

    `next` / `next_page_number` are PAGE NUMBERS, not URLs — feeding `next`
    straight back to urlopen dies with "unknown url type: '2'".
    """
    out, seen = [], set()
    page = None
    while True:
        u = url if page is None else "{}&page={}".format(url, page)
        if u in seen:
            break
        seen.add(u)
        d = http_get(u)
        out.extend(d.get("results", []))
        nxt = d.get("next_page_number") or d.get("next")
        if not nxt or not str(nxt).isdigit():
            break
        page = int(nxt)
    return out


def fetch(event_id):
    tv = http_get(TV.format(eid=event_id))
    meta = http_get(META.format(eid=event_id), allow_404=True) or {}
    standings = paged(TV.format(eid=event_id) + "standings/?page_size=100")
    regs = paged(REG.format(eid=event_id))

    rounds = []
    for ph in tv.get("tournament_phases", []):
        for r in ph.get("rounds", []):
            rounds.append({
                "round_id": r["id"],
                "round_number": r["round_number"],
                "round_type": r.get("round_type"),
                "phase_type": ph.get("round_type"),
                "status": r.get("status"),
                "final_round": r.get("final_round_in_event"),
                "matches": [],
            })

    for rd in rounds:
        url = TV.format(eid=event_id) + "matches/?round_id={}&page_size=100".format(rd["round_id"])
        try:
            rd["matches"] = paged(url)
        except urllib.error.HTTPError as e:
            if e.code == 404:  # round exists on the bracket but never started
                rd["matches"] = []
            else:
                raise

    return {"event_id": event_id, "tv": tv, "meta": meta,
            "standings": standings, "registrations": regs, "rounds": rounds}


def _seat(m, order):
    for p in m.get("players", []):
        if (p.get("player_order") or 0) == order:
            return p
    ps = sorted(m.get("players", []), key=lambda p: p.get("player_order") or 0)
    return ps[order - 1] if len(ps) >= order else {}


def flat_matches(data):
    """One row per match, both seats resolved."""
    rows = []
    for rd in data["rounds"]:
        for m in rd["matches"]:
            p1, p2 = _seat(m, 1), _seat(m, 2)
            bye = bool(m.get("match_is_bye"))
            n1 = p1.get("tv_display_name")
            n2 = None if bye else p2.get("tv_display_name")
            if p1.get("is_winner"):
                winner = n1
            elif p2.get("is_winner"):
                winner = n2
            else:
                winner = "BYE" if bye else ("draw" if m.get("status") == "COMPLETE" else None)
            rows.append({
                "round": rd["round_number"], "phase": rd["phase_type"],
                "table": m.get("table_number"), "status": m.get("status"),
                "player1": n1, "player2": n2,
                "games_p1": p1.get("games_won"),
                "games_p2": None if bye else p2.get("games_won"),
                "winner": winner, "is_bye": bye,
            })
    rows.sort(key=lambda r: (r["round"], r["table"] if r["table"] is not None else 9999))
    return rows


def report(data):
    tv, meta = data["tv"], data["meta"]
    L = []
    a = L.append
    a(str(tv.get("name")))
    a("  event id     {}   https://tcg.ravensburgerplay.com/events/{}".format(
        data["event_id"], data["event_id"]))
    a("  status       {}   format {}".format(tv.get("lifecycle_status"), tv.get("event_format")))
    a("  starts       {}".format(meta.get("start_datetime")))
    a("  players      {} started / {} registered / {} registration rows".format(
        tv.get("starting_player_count"), tv.get("registered_user_count"), len(data["registrations"])))
    a("  phases       " + ", ".join(
        "{} x{}".format(ph.get("round_type"), len(ph.get("rounds", [])))
        for ph in tv.get("tournament_phases", [])))

    ms = flat_matches(data)
    played = [m for m in ms if not m["is_bye"]]
    a("  matches      {} ({} played, {} byes)".format(len(ms), len(played), len(ms) - len(played)))

    # Join standings -> registrations on PLACE, not on name. A player's
    # `tv_display_name` in standings is frequently NOT their registration
    # `special_user_identifier` ("MoleStar" registered as "Dillon"), so a
    # name join silently blanks most of the field.
    by_place = {}
    for r in data["registrations"]:
        pl = r.get("final_place_in_standings")
        if pl is not None:
            by_place[pl] = r

    a("")
    a("FINAL STANDINGS (top 16)")
    a("  {:>3}  {:<24} {:<22} {:<9} {:>4}  {:>6} {:>6}".format(
        "#", "player", "real name", "rec", "pts", "OMW%", "GW%"))
    for s in data["standings"][:16]:
        nm = s.get("tv_display_name") or ""
        reg = by_place.get(s.get("rank"))
        real = ""
        if reg and not reg.get("is_guest"):
            real = (reg.get("user") or {}).get("best_identifier") or ""
        rec = "{}-{}-{}".format(s.get("matches_won"), s.get("matches_lost"), s.get("matches_drawn"))
        a("  {:>3}  {:<24} {:<22} {:<9} {:>4}  {:>5.1f}% {:>5.1f}%".format(
            s.get("rank"), nm[:24], real[:22], rec, s.get("total_match_points"),
            (s.get("opponent_match_win_percentage") or 0) * 100,
            (s.get("game_win_percentage") or 0) * 100))

    a("")
    a("ROUNDS")
    for rd in data["rounds"]:
        n = len(rd["matches"])
        byes = sum(1 for m in rd["matches"] if m.get("match_is_bye"))
        a("  R{:<3} {:<28} {:<10} {:>3} matches{}".format(
            rd["round_number"], str(rd["phase_type"]), str(rd["status"]), n,
            " ({} bye)".format(byes) if byes else ""))
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("event", help="event id or tcg.ravensburgerplay.com/events/<id> URL")
    ap.add_argument("--json", help="write the full raw payload here")
    ap.add_argument("--csv-dir", help="write standings.csv / matches.csv / players.csv here")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    m = re.search(r"(\d{3,})", args.event)
    if not m:
        sys.exit("could not read an event id out of {!r}".format(args.event))
    eid = int(m.group(1))

    data = fetch(eid)
    if not args.quiet:
        print(report(data))

    if args.json:
        p = Path(args.json)
        if p.parent and not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=1), encoding="utf-8")
        print("\nwrote {}".format(args.json))

    if args.csv_dir:
        d = Path(args.csv_dir)
        d.mkdir(parents=True, exist_ok=True)

        rows = flat_matches(data)
        with open(d / "matches.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["round"])
            w.writeheader()
            w.writerows(rows)

        scols = ["rank", "tv_display_name", "matches_won", "matches_lost", "matches_drawn",
                 "total_match_points", "match_win_percentage", "opponent_match_win_percentage",
                 "game_win_percentage", "opponent_game_win_percentage"]
        with open(d / "standings.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=scols, extrasaction="ignore")
            w.writeheader()
            w.writerows(data["standings"])

        with open(d / "players.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["handle", "real_name", "is_guest", "final_place",
                        "matches_won", "matches_lost", "matches_drawn", "points", "status"])
            for r in data["registrations"]:
                w.writerow([
                    r.get("special_user_identifier") or r.get("best_identifier"),
                    "" if r.get("is_guest") else ((r.get("user") or {}).get("best_identifier") or ""),
                    r.get("is_guest"), r.get("final_place_in_standings"),
                    r.get("matches_won"), r.get("matches_lost"), r.get("matches_drawn"),
                    r.get("total_match_points"), r.get("registration_status")])
        print("wrote {}, {}, {}".format(d / "matches.csv", d / "standings.csv", d / "players.csv"))


if __name__ == "__main__":
    main()
