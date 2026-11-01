-- 198_calendar_hideout_ccq_singapore.sql (2026-10-24): Hideout CCQ, Singapore.
--
-- From Ravensburger's Organized Play slides (Challenge Championship Qualifier,
-- ASIA): HIDEOUT CCQ, Singapore, November 7-8 2026, Core Constructed, tickets
-- on sale now. The same slide set names three events the calendar already holds,
-- so they are left alone: League Castle CCQ Hong Kong (Dec 5-6, tickets from
-- Oct 24), Good Games Bern (Nov 22) and RNG Games CCQ (Dec 5-6, Renfrewshire).
-- Only this one was missing.
--
-- No Ravensburger Play listing for it is in our feed yet, and the slide's QR code
-- is not readable from here, so there is no `url`, no venue address and no map
-- point: the row says what the slide says and nothing more. Add the link when the
-- listing appears (the linker script will pick it up by date + words).
--
-- id = uuid5(6b3e1d2a-9c44-4f1e-8a77-5ca1e0da7e01, 'ccq:Hideout CCQ'), the 141
-- convention. Idempotent.

insert into public.calendar_events
  (id, kind, title, subtitle, starts_on, ends_on, location, country, source, confirmed, notes)
values
  ('9c8d873a-e2b9-5fc9-9d59-872ff7a3a06b', 'ccq', 'Hideout CCQ', 'Challenge Championship Qualifier',
   date '2026-11-07', date '2026-11-08', 'Hideout · Singapore', 'SG', 'manual', true,
   'Core Constructed. Tickets on sale. From Ravensburger''s Organized Play slide for the Asia Challenge Championship Qualifiers (Hideout CCQ, Singapore, November 7-8, 2026).')
on conflict (id) do update set
  title = excluded.title, subtitle = excluded.subtitle, starts_on = excluded.starts_on,
  ends_on = excluded.ends_on, location = excluded.location, country = excluded.country,
  notes = excluded.notes, updated_at = now();
