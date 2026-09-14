"""Who this board counts — the two hand-written rulings, in one importable place.

Scope is derived from the events we have ingested, and TWICE OVER, by two
scripts reading two different mirrors of the same history:

  * discover_store_scs.tracked_store_ids() reads the local SQLite and decides
    whose Set Championships future discovery ingests.
  * sync_elo_tracked_stores reads Supabase `elo_events` and decides whose SCs
    reach the site's "Upcoming SCs" tab — and, through elo_tracked_stores, the
    Scout tab, whether a scouting sheet can be opened at all, the roster scrape
    and the store-history backfill behind the Stores tab.

Anything that overrides those derivations has to reach BOTH sides or it only
half-applies, and the half that is missing fails silently — the derivation runs
green and simply disagrees with the decision. So both rulings live here and both
scripts import them. Adding a third list somewhere else is the bug.

ONE_OFF_EVENT_IDS — the event counts, the STORE does not.
    Matches, ratings and the player's rating all count in full; the shop just
    doesn't become one we track. A single hand-added guest event would otherwise
    enrol its store in both derivations, which is the opposite of "just this one".

EXCLUDED_STORE_IDS — the STORE is out of scope entirely, past and future.
    A geographic ruling: these are central-Indiana shops, not Chicagoland. Their
    existing events are flagged is_ignored=1, so the leaderboard, standings and
    summary already drop them, and tracked_store_ids derives only from
    non-ignored events — but that inference is not the record. This set is, and
    it is what stops store-driven discovery re-adding new events for them on a
    future set.

    ⚠ An exclusion must also REMOVE the store from elo_tracked_stores, not merely
    stop re-adding it. sync_elo_tracked_stores upserts and has no delete of its
    own, so a store that qualified once stays tracked forever: Good Games -
    Indianapolis was excluded here and still sat on the Scout tab months later,
    because nothing in the pipeline could ever take a row back out (reported
    2026-09-12). sync_elo_tracked_stores.prune_excluded() is that delete.
"""

ONE_OFF_EVENT_IDS = {
    796836,  # Zaven 2026-09-08: count this event, never the store
}

# RPH store_ids that are OUT OF SCOPE for this (Chicagoland) board and must never
# be ingested, tracked, scouted or reported on — past, present, or future — even
# though they ran Lorcana SCs.
#
# ⚠ Distances here are DRIVING miles and times, not straight-line. That matters
# more than it sounds: you cannot drive across Lake Michigan, so every Michigan
# store reads far closer than it is. The Griffin's Rest in Muskegon is 117 miles
# from Chicago on a map and a 3 h 43 m drive — a bigger trip than Green Bay. An
# earlier pass at this ruling used straight-line distance and "found" a clean
# empty band at 130–160 mi to cut on; that band was an artefact of the lake
# stacking Michigan stores at similar map distances. By road the distribution is
# a smooth gradient whose largest gap anywhere is 14 miles, so the threshold
# below is a judgement about how far someone drives for a Set Championship, not
# a line the data draws by itself. Measure with a router, never with haversine.
#
# The rule (Zaven, 2026-09-13): Michigan is out entirely, and so is anything over
# a 3 h 30 m drive. 13 stores, 57 events, 1,434 matches — 10.7% of the board.
EXCLUDED_STORE_IDS = {
    # Central Indiana — the original ruling, 2026-09-12.
    2237,   # Good Games - Indianapolis (Indianapolis, IN) — ~165 mi
    28480,  # Storming Good Games (Greencastle, IN) — ~165 mi

    # Michigan, all of it — across the lake, so the drive is far worse than the
    # map suggests (2 h 47 m to 3 h 43 m).
    1550,   # Fanfare (Kalamazoo, MI) — 143 mi, 2 h 47 m
    3663,   # Odyssey Games (Kalamazoo, MI) — 145 mi, 2 h 50 m
    1646,   # Fortress Of Solitude (Plainwell, MI) — 156 mi, 3 h 01 m
    4495,   # Sydekick Toys (Grand Haven, MI) — 171 mi, 3 h 25 m
    2519,   # House Rules Board Game Lounge (Grand Rapids, MI) — 176 mi, 3 h 25 m
    1325,   # Draw 7 Games (Muskegon, MI) — 178 mi, 3 h 37 m
    4809,   # The Griffin's Rest (Muskegon, MI) — 186 mi, 3 h 43 m

    # Over a 3 h 30 m drive. The Fox Valley / Green Bay corridor plus Springfield.
    5392,   # WorldClassCards (Appleton, WI) — 193 mi, 3 h 48 m
    814,    # Chimera Hobby Shop Appleton (Appleton, WI) — 193 mi, 3 h 48 m
    2178,   # Gnome Games Green Bay East (Green Bay, WI) — 199 mi, 3 h 56 m
    5011,   # Titan Games - Springfield (Springfield, IL) — 204 mi, 3 h 59 m
    5364,   # Windfall Games LLC (De Pere, WI) — 204 mi, 4 h 02 m
    5393,   # WorldClassCards-Green Bay (Green Bay, WI) — 203 mi, 4 h 04 m
}

# ⚠ Several of the store_ids above were stored in our own DB as "World Class
# Cards" — Fanfare, Chimera, Gnome Games and Windfall among them. That was never
# their name: the hand-curated season spreadsheets passed a store name to
# ingest.py, which only looks one up when the caller supplies none, so one
# organiser's label stuck to six unrelated venues for a year. Only 5392 and 5393
# are actually WorldClassCards. Identify a store by its store_id, never by the
# name in `events.store`.
