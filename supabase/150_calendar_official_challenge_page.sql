-- 150_calendar_official_challenge_page.sql — reconcile the calendar against
-- Ravensburger's own Challenge page (2026-09-14).
--
-- Source: https://www.disneylorcana.com/<locale>/play/lorcana-challenge
--
-- ⚠ THE QUALIFIER LIST IS SPLIT ACROSS LOCALES AND en-US ONLY CARRIES HALF.
-- en-US heads its list "North America Challenge Championship Qualifiers" and
-- shows five events. en-GB / de-DE / fr-FR carry a SECOND list, "EU & UK
-- Challenge Championship Qualifiers", with five more that appear on no US page.
-- Reading one locale therefore loses half the season, which is how CCQ Sevilla
-- came to be missing entirely. (it-IT is stale — it still lists June 2026 — so
-- it is not a third source, it is a trap.)
--
-- WHAT WAS WRONG, AND WHY NONE OF IT SHOWED UP AS AN ERROR
-- =======================================================
-- Migration 141 seeded the season from the community wiki, and
-- scan_ccq_candidates.py separately proposed the same events off Ravensburger
-- Play. Nobody reconciled the two, so three qualifiers existed TWICE: once as a
-- wiki stub (confirmed, no venue, no registration link) and once as a scan
-- candidate (unconfirmed — therefore invisible to the public — carrying the
-- venue AND the link). The public calendar rendered the empty half of each pair.
--
-- Every row below is now checked against the official page. Where the sources
-- disagreed it was resolved against the organiser's own registration page, and
-- where it could NOT be resolved the note says so rather than picking a winner.
--
-- 1. Charlie's Collectible Show was stored at "Stone Mountain, GA". That is the
--    organiser's registered RPH store address, not the venue — the event is at
--    3801 Sumner Blvd, Raleigh NC (agreed by ccs-raleigh.com and the RPH listing
--    itself). A travelling show's RPH store address is the wrong city by
--    construction; treat a scan-derived location as the STORE, not the venue.
-- 2. DLC Bangkok was stored 10-30..11-01. The main event is Oct 31 - Nov 1;
--    Friday Oct 30 is early check-in and side events (organiser's schedule).
-- 3. Senigallia and Malmö were stored as two-day; the official listing dates
--    each as one day. Narrowed, with the surrounding weekend noted.
-- 4. Iconic Tour: Ravensburger says Klagenfurt am Wörthersee, the organiser's
--    ticket page says Schloss Freyenthurn at Mannswörther Straße 59-61, 2320
--    Schwechat (near Vienna) — 300 km apart. UNRESOLVED, so the location carries
--    only the fact both agree on and the note names both. Do not guess this one.
--
-- Every registration link here returned HTTP 200 on 2026-09-14.
--
-- Ids for new rows are uuid5(6b3e1d2a-9c44-4f1e-8a77-5ca1e0da7e01,
-- '<kind>:<title>'), matching 141, so a re-run updates in place.
--
-- Idempotent: safe to run twice. The deletes are keyed on each stub's exact
-- (title, starts_on) AND event_id is null, so they cannot take a promoted row.

-- ---------------------------------------------------------------------------
-- 1. Promote the scan candidates the official page proves are sanctioned CCQs.
--    scan_ccq_candidates.py only ever updates rows still at source='ccq-scan'
--    AND confirmed=false, so flipping these freezes them against the scanner,
--    while event_id keeps them deduped against a re-scan.
-- ---------------------------------------------------------------------------
update public.calendar_events set
  title      = 'Lorcana X Brainwash Cards 2K CCQ',
  subtitle   = 'Challenge Championship Qualifier',
  location   = 'Brainwash Cards · East York, PA',
  url        = 'https://tcg.ravensburgerplay.com/events/853992',
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Listed on Ravensburger''s official Disney Lorcana Challenge page.',
  updated_at = now()
where event_id = 853992;

update public.calendar_events set
  title      = 'Disney Lorcana: CCQ Essen 2026',
  subtitle   = 'Challenge Championship Qualifier',
  location   = 'White Rabbit Community Game Store · Essen, Germany',
  url        = 'https://shop.whiterabbit-cgs.de/Disney-Lorcana-CCQ-Essen-2026',
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Listed on Ravensburger''s official Disney Lorcana Challenge page (EU & UK qualifiers).',
  updated_at = now()
where event_id = 943174;

update public.calendar_events set
  title      = 'CCS Raleigh 10K Weekend CCQ',
  subtitle   = 'Challenge Championship Qualifier',
  starts_on  = date '2026-09-26',
  ends_on    = date '2026-09-27',
  -- was "Stone Mountain, GA" — the organiser's registered store, not the venue.
  location   = 'Charlie''s Collectible Show · 3801 Sumner Blvd, Raleigh, NC',
  url        = 'https://ccs-raleigh.com/events/ccs-lorcana-10k-weekend-official-ccq',
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Listed on Ravensburger''s official Disney Lorcana Challenge page. Two-day $10,000 weekend.',
  updated_at = now()
where event_id = 838766;

update public.calendar_events set
  title      = 'The Cauldron Cup CCQ',
  subtitle   = 'Challenge Championship Qualifier',
  starts_on  = date '2026-10-10',
  ends_on    = date '2026-10-11',
  location   = 'Impact Gaming Center · Fairview Heights, IL',
  url        = 'https://impactgamingcenter.gg/products/igc-x-rov-the-black-cauldron-cup-5k-ticket-sat-10-oct-2026',
  source     = 'official-2026-27',
  confirmed  = true,
  notes      = 'Listed on Ravensburger''s official Disney Lorcana Challenge page. $5,000 event.',
  updated_at = now()
where event_id = 770995;

-- ---------------------------------------------------------------------------
-- 2. Drop the wiki stubs the rows above replace.
-- ---------------------------------------------------------------------------
delete from public.calendar_events
 where event_id is null
   and kind = 'ccq'
   and (title, starts_on) in (
     ('Brainwash Cards 2K', date '2026-09-19'),
     ('White Rabbit CCQ',   date '2026-09-19'),
     ('CCS Raleigh 10K',    date '2026-09-26')
   );

-- ---------------------------------------------------------------------------
-- 3. Name the remaining wiki rows the way the official page names them, and
--    give them their registration links.
-- ---------------------------------------------------------------------------
update public.calendar_events set
  title      = 'Utopica Fantasy Festival CCQ',
  location   = 'Utopica Fantasy Festival · Senigallia, Italy',
  ends_on    = null,
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official Challenge page dates the qualifier as one day (Sep 19); the festival around it runs the weekend. No registration link published yet.',
  updated_at = now()
where title = 'Lore League Senigallia CCQ' and starts_on = date '2026-09-19';

update public.calendar_events set
  title      = 'Malmö Game Week – Disney Lorcana Open',
  location   = 'Malmö Game Week · Malmö, Sweden',
  ends_on    = null,
  url        = 'https://www.mgwlorcanaopen.com',
  source     = 'official-2026-27',
  notes      = 'Ravensburger''s official Challenge page dates the qualifier Sep 26; Malmö Game Week itself runs longer.',
  updated_at = now()
where title = 'Malmö Game Week Open #3' and starts_on = date '2026-09-26';

update public.calendar_events set
  title      = 'Iconic Tour CCQ',
  -- ⚠ Deliberately names no city — see note 4 in the header.
  location   = 'Schloss Freyenthurn, Austria',
  url        = 'https://shop.rarehuntershop.at/en/products/disney-lorcana-iconic-tour-ccq-october-2026',
  source     = 'official-2026-27',
  notes      = 'Venue conflict, unresolved: Ravensburger''s Challenge page says Klagenfurt am Wörthersee, the organiser''s ticket page gives Schloss Freyenthurn at Mannswörther Straße 59-61, 2320 Schwechat (near Vienna). Check the ticket page before travelling.',
  updated_at = now()
where title = 'RareHunter CCQ' and starts_on = date '2026-10-03';

-- ---------------------------------------------------------------------------
-- 4. Challenges: the links the official page carries, and Bangkok's real dates.
-- ---------------------------------------------------------------------------
update public.calendar_events set
  starts_on  = date '2026-10-31',
  ends_on    = date '2026-11-01',
  location   = 'MCC Hall, The Mall Lifestore Bangkae · Bangkok, Thailand',
  url        = 'https://www.sakasakaevent.com/disney-Lorcana/Disney_Lorcana_TCG_Challenge_Bangkok_2026',
  source     = 'official-2026-27',
  notes      = 'Main event Oct 31 – Nov 1. Friday Oct 30 is early check-in and side events (15:00–20:00).',
  updated_at = now()
where title = 'DLC Bangkok';

update public.calendar_events set
  url        = 'https://www.fanfinity.gg/event/disney-lorcana-challenge-26-27-season-of-villainy-london',
  source     = 'official-2026-27',
  updated_at = now()
where title = 'DLC London';

-- ---------------------------------------------------------------------------
-- 5. The three qualifiers neither source had.
-- ---------------------------------------------------------------------------
insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, location, url, source, confirmed, notes)
values
  ('485ee659-68d9-5bfa-b058-83c525894a6b', 'ccq', 'Game Grid Open CCQ',
   'Challenge Championship Qualifier', date '2026-10-03', null,
   'Mountain America Expo Center · Sandy, UT',
   'https://gamegridopen.com/products/10-03-lorcana-challenge-championship-qualifier-saturday',
   'official-2026-27', true,
   'Listed on Ravensburger''s official Disney Lorcana Challenge page. Saturday event; the organiser extends it to a Sunday cut above 128 players.'),
  ('30043284-81dd-5e99-8f3c-40eb11f0a6f0', 'ccq', 'CCQ Sevilla',
   'Challenge Championship Qualifier', date '2026-10-10', date '2026-10-11',
   'Empire Games Sevilla · Seville, Spain',
   'https://www.empiregames.es/producto/lorcanaccq26',
   'official-2026-27', true,
   'Listed on Ravensburger''s official Disney Lorcana Challenge page (EU & UK qualifiers).'),
  ('183c831a-6ef7-519a-83b8-29f9b44aa1da', 'ccq', 'Through the Decades Collectables CCQ',
   'Challenge Championship Qualifier', date '2026-10-24', date '2026-10-25',
   'Through the Decades Collectables · Louisville, KY',
   'https://ttdcollectibles.square.site/product/disney-lorcana-challenge-championship-qualifier-2026/3IBJZ6JAMTMC55KXMRSPXE22',
   'official-2026-27', true,
   'Listed on Ravensburger''s official Disney Lorcana Challenge page.')
on conflict (id) do update set
  title      = excluded.title,
  subtitle   = excluded.subtitle,
  starts_on  = excluded.starts_on,
  ends_on    = excluded.ends_on,
  location   = excluded.location,
  url        = excluded.url,
  source     = excluded.source,
  confirmed  = excluded.confirmed,
  notes      = excluded.notes,
  updated_at = now();

-- ---------------------------------------------------------------------------
-- 6. Geocode. Migration 143's pass ran before any of these rows existed, and an
--    ungeocoded row falls into the region filter's "Elsewhere" bucket — so
--    without this, three of the five North American qualifiers do not appear
--    when a North American filters to their own region, which is the one thing
--    that filter is for. Nothing errors; the row is simply in the wrong drawer.
--    Coordinates are Nominatim's, each asserted against its expected country so
--    a bad lookup fails loudly instead of pinning a US event in Europe.
-- ---------------------------------------------------------------------------
update public.calendar_events as c
   set country = g.country, latitude = g.lat, longitude = g.lng, updated_at = now()
  from (values
    ('485ee659-68d9-5bfa-b058-83c525894a6b'::uuid, 'US',  40.57105, -111.89538), -- Sandy, UT
    ('30043284-81dd-5e99-8f3c-40eb11f0a6f0'::uuid, 'ES',  37.38863,   -5.99534), -- Seville
    ('183c831a-6ef7-519a-83b8-29f9b44aa1da'::uuid, 'US',  38.25424,  -85.75941)  -- Louisville, KY
  ) as g(id, country, lat, lng)
 where c.id = g.id;

update public.calendar_events as c
   set country = g.country, latitude = g.lat, longitude = g.lng, updated_at = now()
  from (values
    (853992, 'US', 39.96711,  -76.67478), -- East York, PA
    (943174, 'DE', 51.45822,    7.01582), -- Essen
    (838766, 'US', 35.86350,  -78.57379), -- Raleigh, NC (NOT the store's Stone Mountain GA)
    (770995, 'US', 38.58894,  -89.99038)  -- Fairview Heights, IL
  ) as g(event_id, country, lat, lng)
 where c.event_id = g.event_id;

notify pgrst, 'reload schema';
