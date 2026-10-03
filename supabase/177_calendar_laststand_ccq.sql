-- 177_calendar_laststand_ccq.sql (2026-10-02)
--
-- Once Upon a CCQ at Last Stand Collectibles is an official North America
-- Challenge Championship Qualifier (Ravensburger Organized Play graphic):
-- Yakima, WA, November 21 2026, Core Constructed, tickets on sale. It was an
-- UNCONFIRMED scan candidate with no geo. Confirmed and geocoded; RPH link and
-- event_id kept. Setting source away from 'ccq-scan' freezes the row against
-- scan_ccq_candidates.py.
--
-- Safe to re-run.

update public.calendar_events set
  title      = 'Once Upon a CCQ at Last Stand Collectibles',
  subtitle   = 'Challenge Championship Qualifier',
  starts_on  = date '2026-11-21',
  ends_on    = null,
  location   = 'Last Stand Collectibles · Yakima, WA',
  country    = 'US',
  latitude   = 46.6021,
  longitude  = -120.5059,
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Official North America Challenge Championship Qualifier, announced by Ravensburger Organized Play. Format: Core Constructed. Tickets on sale now.',
  updated_at = now()
where id = '959cd027-1839-4d84-87d2-abe744ec346e';

notify pgrst, 'reload schema';
