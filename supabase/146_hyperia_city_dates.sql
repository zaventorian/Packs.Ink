-- 146_hyperia_city_dates.sql
--
-- Hyperia City's LGS and wide-retail dates were published after migration 141
-- seeded its prerelease weekend, so 141's note on that row now says the opposite
-- of what the calendar shows two lines below it:
--
--     "Hyperia City's LGS and retail dates are not published yet."
--
-- The DATES themselves are not seeded here. They live in SET_RELEASE_DATES in
-- Index.html, where every other set's do, and calendarSetEntries derives the two
-- rows from them — putting them in this table as well would fork one fact into
-- two stores and let them disagree. This migration only corrects the sentence.
--
-- Source: lorcanaplayer.com/set/hyperia-city (read 2026-09-12) — LGS and
-- prerelease weekend Oct 16, wide retail Oct 23. NOT inferred from the cadence:
-- the gap has moved before (Archazia's Island ran two weeks LGS-to-retail where
-- every set since has run one).
--
-- Safe to run before or after the client ships, and safe to run twice. A
-- database where 141 never landed simply updates nothing.

update public.calendar_events
   set notes = 'Prerelease weekend, from the store events published so far. '
               || 'Shops may sell the set from Fri Oct 16; wide retail is Fri Oct 23.',
       updated_at = now()
 where id = '9ad9a21b-df19-51a0-b1db-975e918321af'
   and notes like '%not published%';

notify pgrst, 'reload schema';
