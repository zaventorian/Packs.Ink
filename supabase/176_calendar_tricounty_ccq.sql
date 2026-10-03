-- 176_calendar_tricounty_ccq.sql (2026-10-01)
--
-- Tri-County Collectibles CCQ is an official North America Challenge
-- Championship Qualifier (Ravensburger Organized Play graphic): Fenton, MI,
-- November 28-29 2026, Core Constructed, tickets on sale. It was already in the
-- table as an UNCONFIRMED scan candidate (one day, no geo). Confirmed, widened
-- to two days, geocoded. The RPH link and event_id are kept. Setting source
-- away from 'ccq-scan' freezes the row against scan_ccq_candidates.py.
--
-- Safe to re-run.

update public.calendar_events set
  title      = 'Tri-County Collectibles CCQ',
  subtitle   = 'Challenge Championship Qualifier',
  starts_on  = date '2026-11-28',
  ends_on    = date '2026-11-29',
  location   = 'Tri-County Collectibles · Fenton, MI',
  country    = 'US',
  latitude   = 42.7978,
  longitude  = -83.7049,
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Official North America Challenge Championship Qualifier, announced by Ravensburger Organized Play. Format: Core Constructed. Tickets on sale now.',
  updated_at = now()
where id = '8febb51f-c8ff-48f2-a097-39cf1387b10f';

notify pgrst, 'reload schema';
