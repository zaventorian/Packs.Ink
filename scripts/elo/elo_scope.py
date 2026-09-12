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
EXCLUDED_STORE_IDS = {
    2237,   # Good Games - Indianapolis (Indianapolis, IN) — ~165 mi
    28480,  # Storming Good Games (Greencastle, IN) — ~165 mi
}
