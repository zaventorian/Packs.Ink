-- Profile display-name hardening + a one-line PostgREST reload as a habit
-- to copy into every future schema migration.

-- Length cap on display_name to prevent impersonation-by-padding (a user
-- setting a giant display name that visually pushes other UI off-screen)
-- and to keep DB rows bounded. Allow null so a fresh profile can be
-- created without a name and the frontend can prompt for one.
alter table public.profiles
  drop constraint if exists profiles_display_name_len;
alter table public.profiles
  add constraint profiles_display_name_len
  check (display_name is null or char_length(trim(display_name)) between 1 and 32);

-- Reload the PostgREST schema cache so the constraint takes effect on the
-- API immediately. Habit-forming reminder: append this to every future
-- migration that adds/renames/drops tables, columns, RPCs, or policies.
notify pgrst, 'reload schema';
