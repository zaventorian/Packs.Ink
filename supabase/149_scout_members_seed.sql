-- 149_scout_members_seed.sql -- grant the scouting feature to the team that
-- signed up for it in the #packs_ink Discord channel (2026-09-12).
--
-- These are 14 rows in scout_members, the email allowlist can_scout() reads.
-- Same thing the admin panel's "Who can scout" box writes, one paste instead of
-- fourteen. The note column carries each person's Discord display name so the
-- list stays legible.
--
-- WARNING: this is a SEED, not a reconciler. Re-running it RE-ADDS anyone an
-- admin has since removed in the panel, because a removed row is deleted and so
-- conflicts with nothing. Run it once. Remove people in the panel, not here.
-- The on-conflict clause is DO NOTHING so a re-run cannot clobber a note that
-- has been edited since.
--
-- Sign-in is Google OAuth only, so the match is against the Google account each
-- person signs in with. If someone reports the Scout tab missing, that is the
-- first thing to check -- the failure is silent by design (can_scout() returns
-- false and the tab simply is not rendered). Two shapes to watch:
--   * a non-gmail address here (comcast.net, yahoo.com) only matches if that
--     address is itself a Google account;
--   * Gmail ignores dots in the local part but the JWT does not -- a person who
--     signed up as codybraun1@ is not matched by cody.braun1@.
-- Either way the fix is one row, added from the panel.
--
-- Requires 143_scout_team.sql. Emails are lowercased by the table's own BEFORE
-- trigger; they are written lowercase here so the conflict target is obvious.

insert into public.scout_members (email, note) values
  ('paulaxelpaxel@gmail.com',     'Paul Axel'),
  ('rabbid.ygo@gmail.com',        'Rabbid. (Kyle S)'),
  ('cody.braun1@gmail.com',       'Cody B'),
  ('steven.j.you@gmail.com',      'Steven'),
  ('angel.jr@comcast.net',        'Angel'),
  ('drayton.hammond@gmail.com',   'Adam'),
  ('henrydavid84@gmail.com',      'Hank'),
  ('cristhianlopez09@yahoo.com',  'Mycity'),
  ('amp3878@gmail.com',           'Aaron P'),
  ('shawn.tang.7@gmail.com',      'I&L Shawn'),
  ('ferflores1225@gmail.com',     'CheekyNando'),
  ('soaringstarling@gmail.com',   'Eric'),
  ('rhauge01@gmail.com',          'Robert H'),
  ('ayyadpauljacobiii@gmail.com', 'Ayyad J')
on conflict (email) do nothing;

notify pgrst, 'reload schema';
