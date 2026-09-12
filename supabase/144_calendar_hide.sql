-- 144_calendar_hide.sql (2026-09-12)
--
-- Lets one event be hidden from your calendar without giving up the filter that
-- brought it in: "show me European CCQs, except that one".
--
-- It rides calendar_subscriptions as a fourth kind rather than a new table --
-- it is the same thing (a per-user opinion about one event, keyed the same way)
-- pointing the other direction, and one table still answers "what is on my
-- calendar" in one round trip.
--
-- The `ref` is the entry's own id, which is stable for all three shapes the
-- calendar renders: a curated row's uuid, "ev:<rph event id>" for a store
-- event, and "set:<Set Name>:<phase>" for a release derived from the catalog.
--
-- Until this runs, hiding still works but only on the device you did it on:
-- the client keeps its own copy in localStorage and the remote write fails the
-- CHECK silently, which is the same degradation as every other pre-migration
-- state here.
--
-- The constraint is dropped by LOOKUP rather than by name. A column CHECK gets
-- an auto-generated name, and guessing it wrong would leave the old constraint
-- in place -- rejecting every 'hide' row while the migration reported success.

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
  check (kind in ('event','series','store','hide'));

notify pgrst, 'reload schema';
