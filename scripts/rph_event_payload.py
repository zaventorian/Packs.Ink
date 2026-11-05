"""Build an admin_import_tournament payload for one RPH event with published lists.

    python scripts/rph_event_payload.py <rph_event_id> <out_dir>
    python scripts/upload_tournament.py <out_dir>/<id>.event.json [--commit]

Only for events whose settings.decklist_status is PUBLISHED: registrations then
carry a deck_id, and /deckbuilder/decks/<id>/ is public. Writes
<out_dir>/<id>.event.json (the payload) and <id>.meta.json (how it was built:
skipped rows, notes, top 8). Places: top cut from the elimination matches (1st,
2nd, Top 4, Top 8, ...); everyone else by final standings rank as an ordinal.
Player name = the event handle (registration best_identifier), as inkDecks and
the TV show it. Decks are cached in <out_dir>/decks/. Used 2026-11-04 for 36
events, 8,295 lists.
"""
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

API = "https://api.ravensburgerplay.com/api/v2"
# RPH display names the catalog spells differently (checked 2026-11-04). Add one
# only after matching the card itself (set, ink, rarity, classifications, text).
NAME_ALIASES = {
    "Nick Wilde - Determined Detective": "Nick Wilde - Sly Fox Sleuth",          # set 10 vanilla Steel common
    "Vaiana - Adventurer of Land and Sea": "Moana - Adventurer of Land and Sea",  # European name
}


def get(url):
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                return {"_error": e.code}
            time.sleep(2 + attempt * 4)
        except Exception:
            time.sleep(2 + attempt * 4)
    raise RuntimeError(f"failed: {url}")


def pages(path):
    out, p = [], 1
    while True:
        d = get(f"{API}/{path}{'&' if '?' in path else '?'}page_size=100&page={p}")
        out += d.get("results", [])
        if not d.get("next"):
            return out
        p += 1


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def local_date(iso, tz):
    t = dt.datetime.fromisoformat(iso)
    try:
        from zoneinfo import ZoneInfo
        return t.astimezone(ZoneInfo(tz)).date().isoformat(), True
    except Exception:
        return t.date().isoformat(), False


def main():
    eid, out = int(sys.argv[1]), Path(sys.argv[2])
    (out / "decks").mkdir(parents=True, exist_ok=True)
    e = get(f"{API}/events/{eid}/")
    phases = sorted(e.get("tournament_phases") or [], key=lambda p: p["order_in_phases"])
    elim_rounds = [r["id"] for p in phases if p["round_type"] == "RANKED_SINGLE_ELIMINATION"
                   for r in sorted(p.get("rounds") or [], key=lambda r: r["round_number"])]
    all_rounds = [r["id"] for p in phases for r in sorted(p.get("rounds") or [], key=lambda r: r["round_number"])]
    notes = []

    regs = pages(f"events/{eid}/registrations/")
    standings = pages(f"tournament-rounds/{all_rounds[-1]}/standings/paginated/") if all_rounds else []
    rank = {s["player"]["id"]: s["rank"] for s in standings}

    # Top cut: a loser in an elimination round with M players left finished "Top M".
    bucket, cut_size = {}, 0
    for i, rid in enumerate(elim_rounds):
        ms = pages(f"tournament-rounds/{rid}/matches/paginated/")
        players = {p for m in ms for p in (m.get("players") or [])}
        if i == 0:
            cut_size = len(players)
        last = i == len(elim_rounds) - 1
        real = [m for m in ms if len(m.get("players") or []) == 2 and not m.get("match_is_bye")]
        if last and len(real) != 1:
            notes.append(f"final round has {len(real)} matches")
        for m in real:
            w = m.get("winning_player")
            if w is None:
                notes.append(f"round {rid} match {m['id']} has no winner")
                continue
            loser = [p for p in m["players"] if p != w][0]
            bucket[loser] = "2nd" if last else f"Top {len(players)}"
            if last:
                bucket[w] = "1st"

    rows, skipped = [], []
    with_deck = [r for r in regs if r.get("deck_id")]

    def fetch(deck_id):
        f = out / "decks" / f"{deck_id}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
        d = get(f"{API}/deckbuilder/decks/{deck_id}/")
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return d

    with ThreadPoolExecutor(max_workers=4) as pool:
        decks = dict(zip([r["deck_id"] for r in with_deck], pool.map(fetch, [r["deck_id"] for r in with_deck])))

    for r in with_deck:
        uid = (r.get("user") or {}).get("id")
        d = decks[r["deck_id"]]
        if "_error" in d:
            skipped.append((r.get("best_identifier"), f"deck {d['_error']}"))
            continue
        lines, total = [], 0
        for s in d.get("sections") or []:
            if s.get("section_type") != "main":
                notes.append(f"section {s.get('section_type')} on {r.get('best_identifier')}")
                continue
            for c in s.get("cards") or []:
                name = c["card"]["display_name"]
                lines.append(f"{c['quantity']} {NAME_ALIASES.get(name, name)}")
                total += c["quantity"]
        if not lines:
            skipped.append((r.get("best_identifier"), "empty list"))
            continue
        fr = rank.get(uid) or r.get("final_place_in_standings")
        if uid in bucket:
            place = bucket[uid]
        elif fr:
            if cut_size and fr <= cut_size:
                notes.append(f"{r.get('best_identifier')} ranked {fr} inside the cut but no elimination loss")
            place = ordinal(fr)
        else:
            skipped.append((r.get("best_identifier"), "no final rank"))
            continue
        rows.append({"_rank": fr or 0, "_sort": {"1st": 1, "2nd": 2}.get(place) or int("".join(ch for ch in place if ch.isdigit())),
                     "_uid": uid, "_card_count": d.get("card_count"), "_total": total,
                     "place": place, "player_name": (r.get("best_identifier") or "").strip(),
                     "decklist": "\n".join(lines)})
    rows.sort(key=lambda x: (x["_sort"], x["_rank"]))

    fmt = ((e.get("gameplay_format") or {}).get("name") or "").lower()
    date, tz_ok = local_date(e["start_datetime"], e.get("timezone") or "UTC")
    event = {"name": e["name"].strip(), "event_date": date,
             "format": "infinity" if "infinity" in fmt else "core" if "core" in fmt else fmt,
             "num_players": e.get("starting_player_count"),
             "rows": [{k: v for k, v in x.items() if not k.startswith("_")} for x in rows]}
    meta = {"rph_id": eid, "rph_name": e["name"], "start": e["start_datetime"], "tz": e.get("timezone"), "tz_ok": tz_ok,
            "registrations": len(regs), "with_deck": len(with_deck), "rows": len(rows), "skipped": skipped,
            "cut_size": cut_size, "elim_rounds": len(elim_rounds), "standings_rows": len(standings),
            "card_count_mismatch": [(x["player_name"], x["_card_count"], x["_total"]) for x in rows if x["_card_count"] != x["_total"]],
            "notes": notes, "top8": [(x["place"], x["player_name"]) for x in rows[:8]]}
    (out / f"{eid}.event.json").write_text(json.dumps(event, ensure_ascii=False), encoding="utf-8")
    (out / f"{eid}.meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(eid, date, len(rows), "rows", "cut", cut_size, "skipped", len(skipped), "notes", len(notes), e["name"][:50], flush=True)


if __name__ == "__main__":
    main()
