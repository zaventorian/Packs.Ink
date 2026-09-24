-- 169_calendar_chattanooga_london_youth.sql (2026-09-24)
--
-- Two updates from Ravensburger's Organized Play announcement graphics.
--
-- 1. CCQ Comic Con Chattanooga is an official North America Challenge
--    Championship Qualifier: Chattanooga, TN, November 7-8 2026, Core
--    Constructed, tickets on sale. It was already in the table as an
--    UNCONFIRMED scan candidate (one day, no geo), so it was invisible to the
--    public. Confirmed, widened to two days, geocoded. The scan's location was
--    the organiser's RPH store (Game On Chattanooga); the event runs at Comic
--    Con Chattanooga, and a travelling show's store address is not its venue,
--    so the location names the show rather than guessing a hall. The RPH link
--    and event_id are kept. Setting source away from 'ccq-scan' freezes the row
--    against scan_ccq_candidates.py.
--
-- 2. DLC London (Nov 13-15): the Youth Division policy, into the notes the
--    event modal displays.
--
-- Safe to re-run.

update public.calendar_events set
  title      = 'Comic Con Chattanooga CCQ',
  subtitle   = 'Challenge Championship Qualifier',
  starts_on  = date '2026-11-07',
  ends_on    = date '2026-11-08',
  location   = 'Comic Con Chattanooga · Chattanooga, TN',
  country    = 'US',
  latitude   = 35.0456,
  longitude  = -85.3097,
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Official North America Challenge Championship Qualifier, announced by Ravensburger Organized Play. Format: Core Constructed. Tickets on sale now.',
  updated_at = now()
where id = 'cacd67a8-1540-498f-9d8e-27d90133cfd7';

update public.calendar_events set
  notes      = 'Youth Division: all Youth Division tickets include one free badge for a guardian/parent. Youth players and guardians may play the Friday Main Event together; if either qualifies for Day 2 and the youth player is in a Youth Division event, they must choose which event to play. Standard policy: all players 17 or under must be accompanied by an adult guardian/parent at all times inside the venue. Full policies on the DLC London ticket page.',
  updated_at = now()
where id = 'de8a8438-43e7-521b-a37f-bffe590f9268';

notify pgrst, 'reload schema';
