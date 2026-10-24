-- 197_calendar_inkdark_dates.sql (2026-10-24): Into the Inkdark's prerelease weekend.
--
-- Feedback 2026-10-21 ("Wrong dates for Into the Ink Dark prerelease"). The site
-- only knew Inkdark by NAME, so the calendar drew a cadence ESTIMATE (LGS Fri
-- 2027-01-15, retail 01-22, labelled "est."). The dates are announced (Hyperia
-- City Special Lorecast): prereleases at game stores start Fri 2027-02-05, retail
-- 2027-02-12 (lorcanaplayer.com/set/into-the-inkdark; ICv2's preorder story).
-- SET_RELEASE_DATES in Index.html now carries the LGS and retail rows; this adds
-- the third row, the prerelease weekend, which lives in the table like
-- Hyperia City's (migration 141).
--
-- Fri-Sun comes from our own feed, not an assumption: lorcana_events holds 706
-- Into the Inkdark prerelease listings on those three days (Fri 148 / Sat 363 /
-- Sun 195), then a tail of 31-45 a day through the following Thursday.
--
-- id = uuid5(6b3e1d2a-9c44-4f1e-8a77-5ca1e0da7e01, 'set:Into the Inkdark:prerelease'),
-- the 141 convention. Idempotent.

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, source, confirmed, notes)
values
  ('ccb18df2-84d1-5ea2-9bca-8b90b64dc799', 'set', 'Into the Inkdark', 'Prerelease',
   date '2027-02-05', date '2027-02-07', 'manual', true,
   'Prerelease weekend at participating game stores, announced on the Hyperia City Special Lorecast (Set 15). Weekend shape from 706 Ravensburger Play listings (Fri 148 / Sat 363 / Sun 195). Retail release is February 12, 2027.')
on conflict (id) do update set
  title = excluded.title, subtitle = excluded.subtitle, starts_on = excluded.starts_on,
  ends_on = excluded.ends_on, notes = excluded.notes, updated_at = now();
