"""Events that count for Elo but whose STORE we do not track.

Scope is derived from the events we have ingested — and TWICE OVER, by two
scripts reading two different mirrors of the same history:

  * discover_store_scs.tracked_store_ids() reads the local SQLite and decides
    whose Set Championships future discovery ingests.
  * sync_elo_tracked_stores reads Supabase `elo_events` and decides whose SCs
    reach the site's "Upcoming SCs" tab — and, through elo_tracked_stores, the
    store-history backfill behind the Stores tab's events/tickets/fans.

A single hand-added guest event would enrol its store in BOTH, which is the
opposite of what "just this one" means. This list is the one place that says
otherwise, so keep it the only definition and have both sides import it.

The event still counts in full: matches, ratings, the player's rating. Only the
STORE is out of scope. That is what separates this from EXCLUDED_STORE_IDS in
discover_store_scs.py, which drops a store's events entirely.
"""

ONE_OFF_EVENT_IDS = {
    796836,  # Zaven 2026-09-08: count this event, never the store
}
