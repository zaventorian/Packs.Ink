-- 142_calendar_geo_and_read_fix.sql (2026-09-12)
--
-- Three things, one of them urgent.
--
-- 1. ⚠ THE READ POLICY WAS BROKEN FOR EVERY SIGNED-OUT VISITOR.
--    139 wrote `for select to anon, authenticated using (confirmed or (select
--    public.is_graded_admin()))`. But migration 134 did
--    `revoke all on function public.is_graded_admin() from public, anon`, so an
--    anonymous read does not return false — it RAISES 42501 "permission denied
--    for function is_graded_admin", and PostgREST turns that into a hard error.
--    The whole curated calendar was invisible to everybody who was not signed
--    in, which is almost everybody. Confirmed against the live database.
--
--    Every other policy in the repo that calls is_graded_admin() is scoped `to
--    authenticated` — 139's SELECT was the one that handed it to anon. The fix
--    is two policies rather than one: anon gets a branch that never touches the
--    function, and PostgreSQL ORs the admin branch in for authenticated users.
--    Do NOT "simplify" this back into a single policy with an OR.
--
-- 2. Coordinates + country, so the event detail can show a small map and the
--    calendar can filter by region. City-level for the curated rows: a DLC is
--    announced as "DLC Bangkok" months before a venue exists, and a city centre
--    is the honest resolution for "where in the world is this". Store events
--    carry the venue's own coordinates from lorcana_events instead.
--
-- 3. Neutral provenance text. The `notes` column is DISPLAYED in the event
--    modal, and it named where the listing was compiled from. Users want to
--    know whether a date is firm, not who typed it up.

alter table public.calendar_events add column if not exists latitude  double precision;
alter table public.calendar_events add column if not exists longitude double precision;
alter table public.calendar_events add column if not exists country   text
  check (country is null or char_length(country) between 2 and 3);

-- ── 1. the read fix ────────────────────────────────────────────────────────
drop policy if exists calendar_events_read on public.calendar_events;

-- anon NEVER evaluates is_graded_admin(): it cannot execute it (migration 134).
drop policy if exists calendar_events_read_public on public.calendar_events;
create policy calendar_events_read_public on public.calendar_events
  for select to anon, authenticated using (confirmed);

-- Policies for the same command OR together, so an admin also sees candidates.
drop policy if exists calendar_events_read_admin on public.calendar_events;
create policy calendar_events_read_admin on public.calendar_events
  for select to authenticated using ((select public.is_graded_admin()));

-- ── 2. geography ───────────────────────────────────────────────────────────
update public.calendar_events c set country = g.country,
       latitude = g.lat, longitude = g.lng, updated_at = now()
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

-- Known country but no venue yet; the linker fills coordinates if the shop
-- lists the event on Ravensburger Play.
update public.calendar_events c set country = g.country, updated_at = now()
  from (values
  ('7a551690-c01c-5163-aecc-e55a22fdea81'::uuid, 'US'),
  ('df2ba8fb-a281-5d99-a67b-d63ed1785e40'::uuid, 'US'),
  ('9510a60c-b011-5bd7-b85f-12f2e19a8a90'::uuid, 'US'),
  ('02db50b5-25ad-5f23-af7a-3a22cd370708'::uuid, 'US')
  ) as g(id, country)
 where c.id = g.id and c.country is null;

create index if not exists calendar_events_country_idx
  on public.calendar_events (country) where confirmed;

-- ── 3. provenance text users actually benefit from ─────────────────────────
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
