-- 195_calendar_lorecast_1008.sql (2026-10-08) — the 2026-10-08 Lorecast / Organized Play announcements.
--
-- Sources: the Lorecast's "Challenge Ticket Update" and "Challenge Update" slides
-- for North America, the playmat slides from the same stream, and Pastimes
-- Events' Discord announcement that went out the same day (posted by the user).
--
-- 1. DLC Tampa (Dec 18-20 2026): venue, format, the badge on-sale moment and
--    prices, and the organiser's landing page. The dates were already right.
--    Badges: 2026-10-19 12:00pm ET (the Discord timestamp 1792425600 is
--    16:00 UTC, i.e. 12:00 EDT, which matches the slide).
--
-- 2. DLC Las Vegas MOVED: Apr 30-May 2 2027 -> Apr 9-11 2027, because of a
--    conflict with the venue (organiser's statement). Venue is now named:
--    Las Vegas Convention Center, South Hall, Halls S3 and S4. Same weekend as
--    DLC Hong Kong, which is a different continent and is left alone.
--
-- 3. Two new playmats (Jack-Jack, Snow White) as kind='product'.
--    ⚠ The slides print "February 5, 2026", a misprint: the release is
--    February 5, 2027 (confirmed by Zaven 2026-10-08; also a Friday, the day
--    every Lorcana product lands). Rows are confirmed=true at 2027-02-05.
--
-- Idempotent: fixed ids, so a re-run re-applies the same values.

update public.calendar_events set
  location   = 'Tampa Convention Center · Tampa, FL',
  url        = 'https://www.pastimesevents.com/disneys-lorcana-challenge-series-tampa-2026/',
  source     = 'official-2026-27',
  notes      = 'Format: Core Constructed. Badges for the Main Event, Youth Division and Attendee go on sale October 19, 2026 at 12:00pm ET: Main Events $85, Attendee $35, Youth Division $50. Premium and VIP add-ons and side events (including CCQ) will be announced later. Main Event and Youth Division structure is on the organiser''s Tampa page (Pastimes Events).',
  updated_at = now()
where id = 'c64532d8-3150-5211-b23f-712774b61d5f';  -- DLC Tampa

update public.calendar_events set
  starts_on  = date '2027-04-09',
  ends_on    = date '2027-04-11',
  location   = 'Las Vegas Convention Center, South Hall (Halls S3-S4) · Las Vegas, NV',
  source     = 'official-2026-27',
  notes      = 'Moved from April 30 - May 2, 2027 to April 9-11, 2027 because of a conflict with the venue (announced on the October 8, 2026 Lorecast). Format: Core Constructed.',
  updated_at = now()
where id = 'c4816ff3-0a7e-53b8-aa92-9dff866e6251';  -- DLC Las Vegas

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, location, source, confirmed, notes)
values
  ('5b1e6d52-3b0f-5c1a-9a52-0c8f1b1d7a01', 'product', 'Jack-Jack Playmat', 'Playmat',
   date '2027-02-05', null, 'manual', true,
   'Announced on the October 8, 2026 Lorecast. The slide misprints the year as 2026; the release date is February 5, 2027.'),
  ('0d7f3a90-6a44-5e2b-8c13-7d2e9f5b3a02', 'product', 'Snow White Playmat', 'Playmat',
   date '2027-02-05', null, 'manual', true,
   'Announced on the October 8, 2026 Lorecast. The slide misprints the year as 2026; the release date is February 5, 2027.')
on conflict (id) do update set
  title = excluded.title, subtitle = excluded.subtitle, starts_on = excluded.starts_on,
  notes = excluded.notes, updated_at = now();

notify pgrst, 'reload schema';
