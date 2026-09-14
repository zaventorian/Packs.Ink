-- 151_calendar_custom_events.sql - events you add yourself (2026-09-14).
--
-- Not every Lorcana night is on Ravensburger Play: a pod, a shop that only
-- posts to Discord, your group's monthly draft. Those ride
-- calendar_subscriptions as a FIFTH kind rather than a table of their own --
-- per-user, already RLS'd owner-only, already localStorage-first -- so nothing
-- new has to be granted and a signed-out visitor keeps working.
--
-- The subscription's `meta` IS the event:
--   {title, subtitle, starts_on, ends_on, location, url, notes}
-- Every other kind here points at a row somewhere (a curated uuid, an RPH
-- event id, a set name). This one has no feed behind it, so the stored label is
-- the only record that it exists at all.
--
-- Until this runs, adding an event works PER DEVICE: the CHECK rejects the
-- insert, the remote write fails silently and localStorage keeps it. Same
-- degradation 144 had before it landed. Safe to ship the client first.
--
-- The old constraint is dropped BY LOOKUP, not by name: a column CHECK gets an
-- auto-generated name, and guessing wrong would leave it in place, rejecting
-- every custom event while this migration reported success. 144's own body.

do $$
declare c text;
begin
  for c in
    select con.conname
      from pg_constraint con
      join pg_class rel on rel.oid = con.conrelid
      join pg_namespace ns on ns.oid = rel.relnamespace
     where ns.nspname = 'public'
       and rel.relname = 'calendar_subscriptions'
       and con.contype = 'c'
       and pg_get_constraintdef(con.oid) ilike '%kind%'
  loop
    execute format('alter table public.calendar_subscriptions drop constraint %I', c);
  end loop;
end $$;

alter table public.calendar_subscriptions
  add constraint calendar_subscriptions_kind_check
  check (kind in ('event','series','store','hide','custom'));

notify pgrst, 'reload schema';
