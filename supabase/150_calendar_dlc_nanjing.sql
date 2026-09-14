-- 150_calendar_dlc_nanjing.sql - the DLC the season seed missed (2026-09-14).
--
-- 141 seeded 17 Challenges for 2026-27. A published season schedule carries an
-- 18th: Nanjing, 21-22 Nov 2026, the season's only mainland-China Challenge -
-- which is why a season page maintained by English-speaking players misses it.
--
-- It lands confirmed = false. 139's SELECT policy (as 142 wrote it) shows an
-- unconfirmed row to a graded admin and to nobody else, so it is in the editor
-- to rule on and no visitor sees a date we cannot stand behind yet. Confirm it
-- in the /calendar admin editor; never flip confirmed from a script.
--
-- Numbered 150 because 149 was burned on a withdrawn migration that is still
-- fetchable from its closed PR ref - see CLAUDE.md's migration ledger.
--
-- Five dates that source disagrees with 141 on are deliberately NOT changed
-- here; the reasoning is in CLAUDE.md under the calendar section.
--
-- id = uuid5(6b3e1d2a-9c44-4f1e-8a77-5ca1e0da7e01, 'dlc:DLC Nanjing'), the same
-- scheme 141 uses, so re-running updates in place.

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, location, country, notes, confirmed)
values
  ('30a13cdc-682e-5c6c-abfa-3b6221d69116', 'dlc', 'DLC Nanjing',
   'Disney Lorcana Challenge', date '2026-11-21', date '2026-11-22',
   'Nanjing, China', 'CN',
   'Entered 2026-09-14 from a published 2026-27 season schedule; not on the community season page 141 was seeded from. UNCONFIRMED - check the official listing before publishing.',
   false)
on conflict (id) do update set
  -- Same asymmetry as 141: refresh what this file owns, never touch what a
  -- person added on top. confirmed is the important one - a re-run must not
  -- un-publish a row an admin has already ruled on.
  title      = excluded.title,
  subtitle   = excluded.subtitle,
  starts_on  = excluded.starts_on,
  ends_on    = excluded.ends_on,
  location   = excluded.location,
  country    = excluded.country,
  updated_at = now();

notify pgrst, 'reload schema';
