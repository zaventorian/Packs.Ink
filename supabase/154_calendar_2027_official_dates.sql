-- 154_calendar_2027_official_dates.sql — reconcile the 2027 half of the season
-- against Ravensburger's own "2027" timeline graphic (2026-09-17), the same
-- source migration 150 already checked the Fall 2026 half against.
--
-- Source: the Disney Lorcana Challenge page's own 2027 calendar infographic
-- (two images, Jan-May and Jun-Oct), posted by the user 2026-09-17.
--
-- WHAT CHANGED
-- ============
-- Migration 141 seeded these four from the Lorcana Fandom wiki as SINGLE-DAY
-- events (the wiki's table has no end-date column). The official graphic draws
-- each as a date RANGE. Every other 2027 row already matched the graphic
-- exactly (Milwaukee, Singapore, Melbourne, Turin, Hong Kong, Las Vegas, Lyon,
-- Utrecht, Taipei, Portland, Toronto, Düsseldorf) — these four are the only
-- discrepancies:
--   Tokyo CCQ      Jan 11        -> Jan 9-11   (3-day, not 1)
--   DLC Tokyo      Mar 27        -> Mar 27-28  (2-day, not 1)
--   Sydney CCQ     Apr 3         -> Apr 3-4    (2-day, not 1)
--   Auckland CCQ   Jul 31        -> Jul 31-Aug 1 (2-day, crosses the month)
--
-- NOT included: "Oceania Championship 2027" (Sep/Oct 2027), new on this
-- graphic and not seeded anywhere. No exact date is given — only the quarter
-- — and `starts_on` is NOT NULL, so a row here would mean inventing a day.
-- Per migration 139's own rule ("a confident wrong date is worse than an
-- empty row"), it stays OUT of the table until Ravensburger names one; add it
-- by hand with `python scripts/reconcile_catalog.py`-style discipline once
-- confirmed=true is warranted, i.e. once there's a real date to put in
-- starts_on. Tracked as an ack note in scripts/calendar_watch.json in the same
-- commit as this migration.
--
-- Idempotent: keyed on each row's fixed id from migration 141, so re-running
-- just re-applies the same dates.

update public.calendar_events set
  starts_on  = date '2027-01-09',
  ends_on    = date '2027-01-11',
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official 2027 Challenge-page timeline graphic dates this Jan 9-11 (was seeded as a single day, Jan 11, from the community wiki).',
  updated_at = now()
where id = '4ad6a054-e680-529d-8062-05d262c0298a';  -- Tokyo CCQ

update public.calendar_events set
  ends_on    = date '2027-03-28',
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official 2027 Challenge-page timeline graphic dates this Mar 27-28 (was seeded as a single day, Mar 27, from the community wiki).',
  updated_at = now()
where id = 'bae3075e-6043-5091-b1cc-c961744ce94f';  -- DLC Tokyo

update public.calendar_events set
  ends_on    = date '2027-04-04',
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official 2027 Challenge-page timeline graphic dates this Apr 3-4 (was seeded as a single day, Apr 3, from the community wiki).',
  updated_at = now()
where id = '56442320-a4b0-58bb-b593-06ca6fa01796';  -- Sydney CCQ

update public.calendar_events set
  ends_on    = date '2027-08-01',
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official 2027 Challenge-page timeline graphic dates this Jul 31-Aug 1 (was seeded as a single day, Jul 31, from the community wiki).',
  updated_at = now()
where id = 'fdcca0bd-3121-5b44-bbf7-4188acc43354';  -- Auckland CCQ

notify pgrst, 'reload schema';
