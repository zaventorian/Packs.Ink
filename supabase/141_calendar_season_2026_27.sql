-- 141_calendar_season_2026_27.sql — the Season of Villainy (2026-09-12).
--
-- Seeds the 2026-2027 competitive season into the curated calendar: 14 Challenge
-- Championship Qualifiers, 17 Disney Lorcana Challenges, and the next set's
-- prerelease weekend.
--
-- SOURCE, AND HOW FAR TO TRUST IT
-- ===============================
-- The competitive half comes from the Lorcana FANDOM WIKI's 2026-2027
-- Competitive Season page, which is the only public list of the whole season:
-- Ravensburger announces DLCs piecemeal, and most of these CCQs are large
-- independent events that never appear on Ravensburger Play at all (checked —
-- White Rabbit, CCS Raleigh, Senigallia, Osaka and RareHunter all return nothing
-- from lorcana_events).
--
-- It is fan-maintained, so it is a starting point, not an authority. Three of its
-- entries WERE cross-checked against our own RPH feed and all three matched to
-- the day — D23 2026 CCQ (Aug 15), Woodzshack (Aug 22) and Brainwash Cards 2K
-- (Sep 19) — which is what made the rest worth seeding.
--
-- ⚠ Every competitive row carries source='wiki-2026-27' and a note saying so.
-- That is the handle for replacing a date once the real one is published:
-- scripts/link_calendar_events.py attaches the official URL and RPH event id
-- wherever a listing turns up, and an admin can correct any row in the editor on
-- /calendar. Do not treat a wiki date as settled just because it is in a table.
--
-- ⚠ The wiki's DLC table has its Players and "Sets Legal" columns transposed
-- (DLC Bangkok's player count reads "Fabled-Hyperia City"). NAME and DATE are the
-- only fields taken from it, for exactly that reason.
--
-- THE PRERELEASE ROW IS NOT FROM THE WIKI — it is derived from our own
-- lorcana_events feed. Hyperia City's LGS and retail dates are published nowhere
-- yet and are deliberately absent: an invented release date is the one thing this
-- calendar must never show.
--
-- IDs are uuid5(6b3e1d2a-9c44-4f1e-8a77-5ca1e0da7e01, '<kind>:<title>'), so
-- re-running this updates rows in place instead of duplicating them, and
-- regenerating the file reproduces the same ids byte for byte.

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, location, notes)
values
  ('45cd1bb3-175e-5d11-b705-aeb0e524377a', 'ccq', 'D23 2026 CCQ', 'Challenge Championship Qualifier', date '2026-08-15', null, 'Elk Grove Village, IL', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('7a551690-c01c-5163-aecc-e55a22fdea81', 'ccq', 'Woodzshack TCG CCQ', 'Challenge Championship Qualifier', date '2026-08-22', date '2026-08-23', null, 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('9510a60c-b011-5bd7-b85f-12f2e19a8a90', 'ccq', 'White Rabbit CCQ', 'Challenge Championship Qualifier', date '2026-09-19', null, null, 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('df2ba8fb-a281-5d99-a67b-d63ed1785e40', 'ccq', 'Brainwash Cards 2K', 'Challenge Championship Qualifier', date '2026-09-19', null, null, 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('d96d5987-f131-5dd2-bcb7-2ee66a900a84', 'ccq', 'Lore League Senigallia CCQ', 'Challenge Championship Qualifier', date '2026-09-19', date '2026-09-20', 'Senigallia, Italy', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('f47e92a4-f535-5bf8-9972-401131ca56fc', 'ccq', 'CCS Raleigh 10K', 'Challenge Championship Qualifier', date '2026-09-26', date '2026-09-27', 'Raleigh, NC', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('56f31685-4975-53ce-ad18-a59b12d9a598', 'ccq', 'Malmö Game Week Open #3', 'Challenge Championship Qualifier', date '2026-09-26', date '2026-09-27', 'Malmö, Sweden', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('02db50b5-25ad-5f23-af7a-3a22cd370708', 'ccq', 'RareHunter CCQ', 'Challenge Championship Qualifier', date '2026-10-03', date '2026-10-04', null, 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('49977d6a-8aa9-5320-8928-70416128f7dd', 'ccq', 'Osaka CCQ', 'Challenge Championship Qualifier', date '2026-10-31', date '2026-11-01', 'Osaka, Japan', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('21877bdb-59d0-5548-821a-7e2ddd0ea45e', 'ccq', 'Brisbane CCQ', 'Challenge Championship Qualifier', date '2026-11-14', null, 'Brisbane, Australia', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('4ad6a054-e680-529d-8062-05d262c0298a', 'ccq', 'Tokyo CCQ', 'Challenge Championship Qualifier', date '2027-01-11', null, 'Tokyo, Japan', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('cf2cabe2-e223-5874-afcd-0ec1c005bffb', 'ccq', 'Melbourne CCQ', 'Challenge Championship Qualifier', date '2027-02-26', null, 'Melbourne, Australia', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('56442320-a4b0-58bb-b593-06ca6fa01796', 'ccq', 'Sydney CCQ', 'Challenge Championship Qualifier', date '2027-04-03', null, 'Sydney, Australia', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('fdcca0bd-3121-5b44-bbf7-4188acc43354', 'ccq', 'Auckland CCQ', 'Challenge Championship Qualifier', date '2027-07-31', null, 'Auckland, New Zealand', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('3af2a074-ed71-5d65-9479-5b6a2a61d02b', 'dlc', 'DLC Kobe', 'Disney Lorcana Challenge', date '2026-09-06', null, 'Kobe, Japan', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('38207557-e489-5de6-b1ed-06338afa026f', 'dlc', 'DLC Bangkok', 'Disney Lorcana Challenge', date '2026-10-30', date '2026-11-01', 'Bangkok, Thailand', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('de8a8438-43e7-521b-a37f-bffe590f9268', 'dlc', 'DLC London', 'Disney Lorcana Challenge', date '2026-11-13', date '2026-11-15', 'London, United Kingdom', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('c64532d8-3150-5211-b23f-712774b61d5f', 'dlc', 'DLC Tampa', 'Disney Lorcana Challenge', date '2026-12-18', date '2026-12-20', 'Tampa, FL', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('050304e3-e868-57a6-a385-c75415cb7d50', 'dlc', 'DLC Milwaukee', 'Disney Lorcana Challenge', date '2027-02-19', date '2027-02-21', 'Milwaukee, WI', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('e4c27703-447b-5f0a-a6ed-9b9cfea8bcf7', 'dlc', 'DLC Melbourne', 'Disney Lorcana Challenge', date '2027-02-26', date '2027-02-28', 'Melbourne, Australia', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('77e222c6-27a6-53b1-b5c3-832dbaaba63f', 'dlc', 'DLC Singapore', 'Disney Lorcana Challenge', date '2027-02-26', date '2027-02-28', 'Singapore', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('06c9ce3c-81fa-5efe-89f9-35f132955d4c', 'dlc', 'DLC Turin', 'Disney Lorcana Challenge', date '2027-03-05', date '2027-03-07', 'Turin, Italy', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('bae3075e-6043-5091-b1cc-c961744ce94f', 'dlc', 'DLC Tokyo', 'Disney Lorcana Challenge', date '2027-03-27', null, 'Tokyo, Japan', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('34e5b224-7e5d-59d3-9d63-cc47930d7783', 'dlc', 'DLC Hong Kong', 'Disney Lorcana Challenge', date '2027-04-09', date '2027-04-11', 'Hong Kong', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('c4816ff3-0a7e-53b8-aa92-9dff866e6251', 'dlc', 'DLC Las Vegas', 'Disney Lorcana Challenge', date '2027-04-30', date '2027-05-02', 'Las Vegas, NV', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('ea05d007-526b-594c-9261-fc01a562d521', 'dlc', 'DLC Lyon', 'Disney Lorcana Challenge', date '2027-05-07', date '2027-05-09', 'Lyon, France', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('f15fe3fc-c9e7-5f84-bb79-4d4266d77580', 'dlc', 'DLC Utrecht', 'Disney Lorcana Challenge', date '2027-05-28', date '2027-05-30', 'Utrecht, Netherlands', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('51d4627f-81f2-5642-9197-557aec14ca1a', 'dlc', 'DLC Taipei', 'Disney Lorcana Challenge', date '2027-06-11', date '2027-06-13', 'Taipei, Taiwan', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('d75332f1-4885-5171-915a-eb4afe0db36a', 'dlc', 'DLC Portland', 'Disney Lorcana Challenge', date '2027-06-18', date '2027-06-20', 'Portland, OR', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('51c9d651-e0db-5b1a-aafa-38b59bc31a18', 'dlc', 'DLC Toronto', 'Disney Lorcana Challenge', date '2027-07-16', date '2027-07-18', 'Toronto, Canada', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('29c10f42-26d5-5a38-95e7-187ca0647f05', 'dlc', 'DLC Düsseldorf', 'Disney Lorcana Challenge', date '2027-07-23', date '2027-07-25', 'Düsseldorf, Germany', 'Seeded 2026-09-12 from the Lorcana Fandom wiki''s 2026-2027 Competitive Season page. Fan-maintained — confirm against the official listing before relying on it.'),
  ('9ad9a21b-df19-51a0-b1db-975e918321af', 'set', 'Hyperia City', 'Prerelease', date '2026-10-16', date '2026-10-18', null, 'Prerelease weekend derived from 1,628 Ravensburger Play listings (Fri 349 / Sat 588 / Sun 368). Hyperia City''s LGS and retail dates are not published yet.')
on conflict (id) do update set
  -- A re-run refreshes what the source owns. It deliberately does NOT touch
  -- `url`, `event_id` or `confirmed`: those are what a person or the linker
  -- script added on top, and a re-seed must never undo a human's work.
  title      = excluded.title,
  subtitle   = excluded.subtitle,
  starts_on  = excluded.starts_on,
  ends_on    = excluded.ends_on,
  location   = coalesce(excluded.location, public.calendar_events.location),
  notes      = excluded.notes,
  updated_at = now();

update public.calendar_events set source = 'wiki-2026-27'
 where kind in ('ccq','dlc') and source = 'manual'
   and notes like 'Seeded 2026-09-12 from the Lorcana Fandom wiki%';

notify pgrst, 'reload schema';
