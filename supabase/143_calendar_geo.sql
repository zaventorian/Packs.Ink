-- 143_calendar_geo.sql (2026-09-12)
--
-- The half of 142 that did not run. 142's policy fix IS applied (an anonymous
-- read of calendar_events returns rows), but its columns never arrived:
-- selecting `country` still gives 42703. This is the remainder, on its own, in
-- plain ASCII with a short header -- if 142 died on a partial paste or on an
-- encoding hiccup in its comment block, this sidesteps both.
--
-- Adds latitude/longitude/country (the region filter and the event map need
-- them), fills city-level coordinates for the curated events, and replaces the
-- provenance text, which is DISPLAYED in the event modal and currently names
-- where the listing was compiled from.
--
-- Safe to re-run: every statement is idempotent.

alter table public.calendar_events add column if not exists latitude double precision;
alter table public.calendar_events add column if not exists longitude double precision;
alter table public.calendar_events add column if not exists country text;

update public.calendar_events c
   set country = g.country, latitude = g.lat, longitude = g.lng, updated_at = now()
  from (values
    ('7afbb8d1-51f9-5a5a-bca9-6d6636a9fc42'::uuid, 'US', 33.8366, -117.9143),
    ('27870d16-a0e4-553a-a593-cd1396d08af3'::uuid, 'FR', 48.8722, 2.7758),
    ('45cd1bb3-175e-5d11-b705-aeb0e524377a'::uuid, 'US', 42.0039, -87.9706),
    ('d96d5987-f131-5dd2-bcb7-2ee66a900a84'::uuid, 'IT', 43.7148, 13.2211),
    ('f47e92a4-f535-5bf8-9972-401131ca56fc'::uuid, 'US', 35.7796, -78.6382),
    ('56f31685-4975-53ce-ad18-a59b12d9a598'::uuid, 'SE', 55.605, 13.0038),
    ('49977d6a-8aa9-5320-8928-70416128f7dd'::uuid, 'JP', 34.6937, 135.5023),
    ('21877bdb-59d0-5548-821a-7e2ddd0ea45e'::uuid, 'AU', -27.4698, 153.0251),
    ('4ad6a054-e680-529d-8062-05d262c0298a'::uuid, 'JP', 35.6762, 139.6503),
    ('cf2cabe2-e223-5874-afcd-0ec1c005bffb'::uuid, 'AU', -37.8136, 144.9631),
    ('56442320-a4b0-58bb-b593-06ca6fa01796'::uuid, 'AU', -33.8688, 151.2093),
    ('fdcca0bd-3121-5b44-bbf7-4188acc43354'::uuid, 'NZ', -36.8485, 174.7633),
    ('3af2a074-ed71-5d65-9479-5b6a2a61d02b'::uuid, 'JP', 34.6901, 135.1955),
    ('38207557-e489-5de6-b1ed-06338afa026f'::uuid, 'TH', 13.7563, 100.5018),
    ('de8a8438-43e7-521b-a37f-bffe590f9268'::uuid, 'GB', 51.5074, -0.1278),
    ('c64532d8-3150-5211-b23f-712774b61d5f'::uuid, 'US', 27.9506, -82.4572),
    ('050304e3-e868-57a6-a385-c75415cb7d50'::uuid, 'US', 43.0389, -87.9065),
    ('e4c27703-447b-5f0a-a6ed-9b9cfea8bcf7'::uuid, 'AU', -37.8136, 144.9631),
    ('77e222c6-27a6-53b1-b5c3-832dbaaba63f'::uuid, 'SG', 1.3521, 103.8198),
    ('06c9ce3c-81fa-5efe-89f9-35f132955d4c'::uuid, 'IT', 45.0703, 7.6869),
    ('bae3075e-6043-5091-b1cc-c961744ce94f'::uuid, 'JP', 35.6762, 139.6503),
    ('34e5b224-7e5d-59d3-9d63-cc47930d7783'::uuid, 'HK', 22.3193, 114.1694),
    ('c4816ff3-0a7e-53b8-aa92-9dff866e6251'::uuid, 'US', 36.1699, -115.1398),
    ('ea05d007-526b-594c-9261-fc01a562d521'::uuid, 'FR', 45.764, 4.8357),
    ('f15fe3fc-c9e7-5f84-bb79-4d4266d77580'::uuid, 'NL', 52.0907, 5.1214),
    ('51d4627f-81f2-5642-9197-557aec14ca1a'::uuid, 'TW', 25.033, 121.5654),
    ('d75332f1-4885-5171-915a-eb4afe0db36a'::uuid, 'US', 45.5152, -122.6784),
    ('51c9d651-e0db-5b1a-aafa-38b59bc31a18'::uuid, 'CA', 43.6532, -79.3832),
    ('29c10f42-26d5-5a38-95e7-187ca0647f05'::uuid, 'DE', 51.2277, 6.7735)
  ) as g(id, country, lat, lng)
 where c.id = g.id;

update public.calendar_events c
   set country = g.country, updated_at = now()
  from (values
    ('7a551690-c01c-5163-aecc-e55a22fdea81'::uuid, 'US'),
    ('df2ba8fb-a281-5d99-a67b-d63ed1785e40'::uuid, 'US'),
    ('9510a60c-b011-5bd7-b85f-12f2e19a8a90'::uuid, 'US'),
    ('02db50b5-25ad-5f23-af7a-3a22cd370708'::uuid, 'US')
  ) as g(id, country)
 where c.id = g.id and c.country is null;

create index if not exists calendar_events_country_idx
  on public.calendar_events (country) where confirmed;

update public.calendar_events
   set notes = 'Announced for the 2026-27 competitive season. Confirm entry, format and timings with the organiser before travelling.',
       source = 'season-2026-27',
       updated_at = now()
 where source = 'wiki-2026-27';

update public.calendar_events
   set notes = 'Prerelease weekend, from the store events published so far. The wide release date has not been announced.',
       updated_at = now()
 where kind = 'set' and subtitle = 'Prerelease' and notes like '%Ravensburger Play listings%';

notify pgrst, 'reload schema';
