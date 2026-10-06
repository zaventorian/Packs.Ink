"""test_watch_sources.py — guards the source watch's diff, ack and match layers.

    python scripts/test_watch_sources.py

No network and no database: it imports the real functions out of watch_sources,
swaps each source's `extract` for a stub, and checks the findings. Then it
validates the committed source_watch.json.

WHY THIS EXISTS
===============
Every way this watcher can break is SILENT — the run is green either way:

  * a source whose URL moved reads zero items, and an empty list diffs clean
    against any baseline, so it reports "nothing new" forever. That is the same
    failure that froze the Elo board at a set rotation and left 212 events with
    no roster. `source_empty` is the guard; this test is what proves the guard
    fires.
  * an ack that matches too much, or an `until` that does not actually expire,
    turns "revisit later" into "never".
  * the pin/counter token matcher decides whether "you don't have this pin" is
    trustworthy. Too loose and a genuinely new pin matches something and is
    never reported; too tight and it cries wolf about 41 pins we already own
    until somebody switches the whole check off. Both directions are pinned
    here, because both look identical in production: quiet.
  * and a baseline re-seeded over an unexplained loss removes the items from the
    file, so they can never be reported again.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import watch_sources as W  # noqa: E402

failed = 0


def check(name: str, got, want) -> None:
    global failed
    ok = got == want
    if not ok:
        failed += 1
    print(f"{'ok  ' if ok else 'FAIL'} {name}")
    if not ok:
        print(f"       got  {got!r}")
        print(f"       want {want!r}")


def sweep(source_id, extract, baseline, acks=None, compare="keep"):
    """Run collect() over exactly one source with a stubbed extract."""
    src = next(s for s in W.SOURCES if s["id"] == source_id)
    saved_extract, saved_compare = src["extract"], src["compare"]
    src["extract"] = extract
    if compare != "keep":
        src["compare"] = compare
    try:
        state = {"baselines": {source_id: baseline} if baseline is not None else {},
                 "acks": acks or {}}
        return W.collect(state, only={source_id})
    finally:
        src["extract"], src["compare"] = saved_extract, saved_compare


def kinds(findings):
    return sorted({f["kind"] for f in findings})


print("== a source that reads nothing is an ERROR, not 'nothing new' ==")
# THE load-bearing case. A moved URL, a redesign, a bot wall and a broken regex
# all look like this, and all of them diff clean against any baseline.
f = sweep("lp-pins", lambda: {}, {"count": 41, "items": ["ursula-deceiver-pin"]}, compare=None)
check("empty read is reported", kinds(f), ["source_empty"])
check("...and says so in the name", "returned no items" in f[0]["name"], True)
check("...and does NOT also claim items went missing", "shrank" in kinds(f), False)

print("\n== a source that raises is reported, not swallowed ==")


def boom():
    raise OSError("getaddrinfo failed")


f = sweep("lp-pins", boom, {"count": 41, "items": ["ursula-deceiver-pin"]}, compare=None)
check("fetch failure is reported", kinds(f), ["source_error"])
check("...and names the exception", "getaddrinfo failed" in f[0]["name"], True)

print("\n== fetch retries a server FAILURE, never a REFUSAL ==")
# Both directions are silent in production: without the retry a one-off 500
# turns the run red for nothing (it did, 2026-10-06); with a retry on 403 the
# watcher hammers the rate-sensitive host it is supposed to leave alone.
import io  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_open(script):
    """urlopen stand-in that raises/returns each scripted step in turn."""
    calls = []

    def opener(req, timeout=None):
        step = script[len(calls)]
        calls.append(step)
        if isinstance(step, BaseException):
            raise step
        return _Resp(step.encode())
    return opener, calls


def _http(code):
    return urllib.error.HTTPError("https://x.test/", code, "x", {}, None)


def _fetch_with(script):
    opener, calls = _fake_open(script)
    saved_open, saved_sleep = urllib.request.urlopen, W.time.sleep
    urllib.request.urlopen, W.time.sleep = opener, (lambda s: None)
    try:
        try:
            return W.fetch("https://x.test/"), len(calls)
        except Exception as e:  # noqa: BLE001
            return type(e).__name__ + ":" + str(getattr(e, "code", "")), len(calls)
    finally:
        urllib.request.urlopen, W.time.sleep = saved_open, saved_sleep


check("a 500 then a page reads the page", _fetch_with([_http(500), "ok"]), ("ok", 2))
check("two 503s then a page reads the page",
      _fetch_with([_http(503), _http(503), "ok"]), ("ok", 3))
check("three 500s give up and raise", _fetch_with([_http(500)] * 3), ("HTTPError:500", 3))
check("a dropped connection is retried",
      _fetch_with([ConnectionResetError("reset"), "ok"]), ("ok", 2))
check("a DNS failure is retried",
      _fetch_with([urllib.error.URLError("getaddrinfo failed"), "ok"]), ("ok", 2))
check("a 403 is NOT retried", _fetch_with([_http(403), "ok"]), ("HTTPError:403", 1))
check("a 429 is NOT retried", _fetch_with([_http(429), "ok"]), ("HTTPError:429", 1))
check("a 404 is NOT retried", _fetch_with([_http(404), "ok"]), ("HTTPError:404", 1))
check("one timeout is retried", _fetch_with([TimeoutError("t"), "ok"]), ("ok", 2))
check("a second timeout gives up (the gallery waits 180s a try)",
      _fetch_with([TimeoutError("t"), TimeoutError("t"), "ok"]), ("TimeoutError:", 2))
check("a connect timeout counts as a timeout",
      _fetch_with([urllib.error.URLError(TimeoutError("t")), TimeoutError("t"), "ok"]),
      ("TimeoutError:", 2))
check("a timeout after a 500 still gets its one retry",
      _fetch_with([_http(500), TimeoutError("t"), "ok"]), ("ok", 3))

print("\n== an un-baselined source asks to be baselined, once ==")
f = sweep("lp-pins", lambda: {"a-pin": "a-pin"}, None, compare=None)
check("exactly one finding", len(f), 1)
check("...telling you to run --baseline", "--baseline" in f[0]["hint"], True)
check("...not 1 finding per item", f[0]["key"], "lp-pins:unbaselined")

print("\n== a new item is reported, and only the new one ==")
base = {"count": 2, "items": ["old-one-pin", "old-two-pin"]}
f = sweep("lp-pins", lambda: {k: k for k in ["old-one-pin", "old-two-pin", "brand-new-pin"]},
          base, compare=None)
check("one finding", len(f), 1)
check("...the new slug", f[0]["name"], "brand-new-pin")
check("...keyed by source and slug", f[0]["key"], "lp-pins:brand-new-pin")
check("...and it carries the how-to", "LORCANA_PINS" in f[0]["hint"], True)

print("\n== an item disappearing is NOT reported as new, but a big loss is ==")
f = sweep("lp-pins", lambda: {"old-one-pin": "old-one-pin"}, base, compare=None)
check("a single loss is quiet", "new_item" in kinds(f), False)
check("...but halving the list is reported", "shrank" in kinds(f), True)
big = {"count": 100, "items": [f"p{i}-pin" for i in range(100)]}
f = sweep("lp-pins", lambda: {f"p{i}-pin": "" for i in range(80)}, big, compare=None)
check("a 20% loss is within tolerance", kinds(f), [])
f = sweep("lp-pins", lambda: {f"p{i}-pin": "" for i in range(74)}, big, compare=None)
check("a 26% loss is not", kinds(f), ["shrank"])

print("\n== counts mode: a new bucket and a moved bucket ==")
gal = {"counts": {"EN 01": 216, "EN 13": 245}}
f = sweep("official-gallery", lambda: {"EN 01": 216, "EN 13": 245}, gal)
check("unchanged counts are quiet", kinds(f), [])
f = sweep("official-gallery", lambda: {"EN 01": 216, "EN 13": 245, "EN 14": 7}, gal)
check("a new set bucket is reported", len(f), 1)
check("...named as new", "EN 14 is new" in f[0]["name"], True)
check("...and tells you to prestage it", "import_official_set.py" in f[0]["hint"], True)
f = sweep("official-gallery", lambda: {"EN 01": 216, "EN 13": 251}, gal)
check("a grown bucket is reported with both numbers", f[0]["name"], "EN 13: 245 → 251 cards")
# ⚠ The key carries the NEW count so a second, further move re-alerts instead of
# being covered by the ack written for the first one.
check("...and the key carries the new count", f[0]["key"], "official-gallery:EN 13:251")

print("\n== acks ==")
today = "2026-09-14"
st = {"acks": {"k": {"why": "checked, it's a reprint", "acked": "2026-09-01"}}}
check("an ack with a why silences its key", W.ack_reason(st, "k", today),
      "checked, it's a reprint")
check("...and nothing else", W.ack_reason(st, "other", today), None)
st = {"acks": {"k": {"why": "wait for the photo", "until": "2026-12-01"}}}
check("an ack with a future until still holds", W.ack_reason(st, "k", today) is not None, True)
st = {"acks": {"k": {"why": "wait for the photo", "until": "2026-09-14"}}}
check("an until that has ARRIVED expires the ack", W.ack_reason(st, "k", today), None)
st = {"acks": {"k": {"why": "x", "until": "2026-09-01"}}}
check("...and a past one too", W.ack_reason(st, "k", today), None)

# An acked finding must still be COLLECTED (so it counts as "known") — the
# report subtracts them. If collect() dropped them the counter would read zero
# and a silenced problem would be indistinguishable from no problem at all.
f = sweep("lp-pins", lambda: {k: k for k in ["old-one-pin", "old-two-pin", "brand-new-pin"]},
          base, acks={"lp-pins:brand-new-pin": {"why": "not a Lorcana pin"}}, compare=None)
check("an acked finding is still collected", len(f), 1)
check("...and the report can tell it is acked",
      W.ack_reason({"acks": {"lp-pins:brand-new-pin": {"why": "not a Lorcana pin"}}},
                   f[0]["key"], today) is not None, True)

print("\n== the pin/counter matcher, both directions ==")
held = [(1, "Mickey Mouse - Brave Little Tailor", "D23 Expo 2022"),
        (19, "Azurite Sea Logo", "Lorcana League - Azurite Sea"),
        (23, "Amber Ink Symbol", "Lorcana League - Fabled"),
        (29, "A Whole New World", "World Championships 2026"),
        (34, "Elsa - Ice Maker", "Lorcana League - Winterspell")]
for slug, want in [("mickey-mouse-brave-little-tailor-pin", True),
                   ("azurite-sea-lorcana-league-logo-pin", True),
                   ("amber-ink-symbol-pin", True),
                   ("a-whole-new-world-world-championships-pin", True),
                   ("elsa-ice-maker-lorcana-league-pin", True)]:
    score, _ = W.best_match(slug, held)
    check(f"held: {slug}", score >= W.MATCH_MIN, want)
# ⚠ The other half. A threshold loose enough to match everything reports nothing,
# which is the same as having no check — and it looks identical in production.
for slug in ["elsa-snow-queen-lorcana-league-pin", "hyperia-city-lorcana-league-pin",
             "stitch-rock-star-pin", "cosmic-quest-ink-symbol-pin",
             "goofy-super-goof-challenge-pin"]:
    score, _ = W.best_match(slug, held)
    check(f"NOT held: {slug}", score < W.MATCH_MIN, True)

# Word order must not matter: the site says purple-maleficent-logo-pin, we say
# "Maleficent Logo (Purple)". Six league logo pins hung on this.
score, _ = W.best_match("purple-maleficent-logo-pin",
                        [(2, "Maleficent Logo (Purple)", "D23 Expo 2022")])
check("word order does not matter", score >= W.MATCH_MIN, True)
# And the `source` field is part of the haystack: a league pin's slug names the
# set, which lives in `source`, not in `name`.
score_name_only, _ = W.best_match("ariel-whoseit-collector-lorcana-league-pin",
                                  [(3, "Ariel - Whoseit Collector", "")])
score_with_src, _ = W.best_match("ariel-whoseit-collector-lorcana-league-pin",
                                 [(3, "Ariel - Whoseit Collector", "Lorcana League - Ursula's Return")])
check("source field does not hurt a name match", score_with_src >= score_name_only, True)

print("\n== every source is declared completely ==")
seen = set()
for s in W.SOURCES:
    sid = s["id"]
    check(f"{sid}: id is unique", sid in seen, False)
    seen.add(sid)
    check(f"{sid}: mode is items or counts", s["mode"] in ("items", "counts"), True)
    check(f"{sid}: has a site", bool(s.get("site")), True)
    check(f"{sid}: has a what", bool(s.get("what")), True)
    # `how` is printed INSIDE the alert. A source with no steps produces a
    # finding nobody can act on, which is how a watcher stops being read.
    check(f"{sid}: has actionable steps", len(s.get("how") or "") > 40, True)
    check(f"{sid}: extract is callable", callable(s["extract"]), True)
    check(f"{sid}: counts mode has no comparer", not (s["mode"] == "counts" and s["compare"]), True)
for kind in W.KIND_ORDER:
    check(f"KIND_ORDER {kind} has a label", kind in W.KIND_LABEL, True)
check("every label is ordered", sorted(W.KIND_LABEL) == sorted(W.KIND_ORDER), True)

print("\n== the committed state file ==")
state = W.load_state()
check("it exists and parses", isinstance(state.get("baselines"), dict), True)
check("it carries its own readme", "_readme" in json.load(open(W.STATE_PATH, encoding="utf-8")), True)
for s in W.SOURCES:
    b = state["baselines"].get(s["id"])
    check(f"{s['id']} is baselined", b is not None, True)
    if not b:
        continue
    if s["mode"] == "items":
        check(f"{s['id']} baseline has items", len(b.get("items") or []) > 0, True)
        check(f"{s['id']} count matches its items", b.get("count"), len(b.get("items") or []))
    else:
        check(f"{s['id']} baseline has counts", len(b.get("counts") or {}) > 0, True)
    check(f"{s['id']} records when it was checked", bool(b.get("checked")), True)
for key, entry in (state.get("acks") or {}).items():
    check(f"ack {key} states a reason", bool((entry or {}).get("why")), True)
    if entry.get("until"):
        from datetime import date as _d
        try:
            _d.fromisoformat(entry["until"])
            ok = True
        except ValueError:
            ok = False
        check(f"ack {key} until is a date", ok, True)

# The gallery baseline is also a fact worth asserting: EN buckets are contiguous
# from 1. A gap means the extraction regex dropped a set, which would read as
# "that set is new" the next time it matched.
gal = (state["baselines"].get("official-gallery") or {}).get("counts") or {}
nums = sorted(int(k.split()[1]) for k in gal)
check("gallery buckets are contiguous from EN 1", nums, list(range(1, len(nums) + 1)))
check("gallery buckets all hold real cards", all(v > 100 for v in gal.values()), True)

# duels.ink: a count of clean renders and a count of placeholders. Both keys are
# always present, so a month with neither reads as two zeros (not an empty
# source, which would be reported as a dead URL), and a response with no cards
# at all is an error rather than a clean diff.
import json as _json  # noqa: E402

_pages = {
    "0": {"cards": [{"imageSource": "reveal"}, {"imageSource": "generated"}, {"imageSource": None}],
          "meta": {"hasMore": True}},
    "200": {"cards": [{"imageSource": "reveal"}], "meta": {"hasMore": False}},
}
_real_fetch = W.fetch
try:
    W.fetch = lambda url, timeout=60: _json.dumps(_pages[url.rsplit("=", 1)[1]])
    check("duels: reveal renders and placeholders are counted across pages",
          W.extract_duels_renders(), {"reveal renders": 2, "placeholders": 1})
    W.fetch = lambda url, timeout=60: _json.dumps(
        {"cards": [{"imageSource": None}], "meta": {"hasMore": False}})
    check("duels: a quiet month is two zeros, not an empty source",
          W.extract_duels_renders(), {"reveal renders": 0, "placeholders": 0})
    W.fetch = lambda url, timeout=60: _json.dumps({"cards": [], "meta": {}})
    try:
        W.extract_duels_renders()
        check("duels: a response with no cards raises", "returned", "raised")
    except ValueError:
        check("duels: a response with no cards raises", "raised", "raised")
finally:
    W.fetch = _real_fetch
_dz = {"counts": {"reveal renders": 0, "placeholders": 0}}
check("duels: two zeros against a zero baseline is quiet",
      sweep("duels-renders", lambda: {"reveal renders": 0, "placeholders": 0}, _dz), [])
f = sweep("duels-renders", lambda: {"reveal renders": 3, "placeholders": 0}, _dz)
check("duels: a new render is reported", [x["kind"] for x in f], ["count_moved"])

print(f"\n{failed} FAILED" if failed else "\nall passed")
raise SystemExit(1 if failed else 0)
