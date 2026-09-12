-- 140_calendar_subscriptions.sql — the personal layer of the calendar (2026-09-12).
--
-- Three things a signed-in person can put on their own calendar:
--   event  — one curated row (calendar_events.id)
--   series — one repeating store event, keyed by the series_key that
--            get_nearby_lorcana_events already groups on (store + kind + format
--            + local weekday + local start time). This is what the ✚ button in
--            the "Upcoming near me" box writes, and it supersedes the
--            localStorage `packsink:scPinned` list for signed-in users.
--   store  — EVERY Lorcana event at that store, now and in future. Following a
--            store is the ask that made this a table rather than a bigger pin
--            list: "add everything from this shop, and any number of shops".
--
-- ⚠ Signed-out still works, and must keep working. The client holds the same
-- three sets in localStorage and mirrors them up on sign-in (the screener_views
-- pattern), so nothing here is a gate on using the feature — it is what makes a
-- laptop's six followed stores show up on the phone.
--
-- `ref` is text for all three kinds because they are different ID shapes (a
-- uuid, an opaque series_key, a bigint store id) and a single (kind, ref) PK is
-- what lets one small table answer "what is on my calendar" in one round trip.
-- There is deliberately NO foreign key to calendar_events: a curated row an
-- admin deletes should drop off the calendar, not fail the delete or cascade
-- into somebody's subscriptions silently — the client just renders what still
-- resolves.

create table if not exists public.calendar_subscriptions (
  user_id    uuid not null references auth.users(id) on delete cascade,
  kind       text not null check (kind in ('event','series','store')),
  ref        text not null check (char_length(ref) between 1 and 200),
  -- Denormalised display name ("Pastimes Events"), so the calendar can list a
  -- follow before — or without — resolving it against lorcana_events. A series
  -- whose events have all been played resolves to nothing; without this it
  -- would render as a blank row you cannot identify in order to unfollow it.
  label      text check (label is null or char_length(label) <= 200),
  meta       jsonb,
  created_at timestamptz not null default now(),
  primary key (user_id, kind, ref)
);

create index if not exists calendar_subscriptions_user_idx
  on public.calendar_subscriptions (user_id, kind);

-- Following a store means "every event at store X in this date window", which is
-- the one query this feature is built on and the one index lorcana_events (113)
-- does not have — it indexes start_datetime, geo, kind and last_seen_at, all
-- shaped for the ZIP-radius box. Cheap, and it belongs with the feature that
-- introduced the access pattern.
create index if not exists lorcana_events_store_start_idx
  on public.lorcana_events (store_id, start_datetime);

alter table public.calendar_subscriptions enable row level security;

-- Owner-only on every verb. No admin branch and no share-token branch: what a
-- person follows is not interesting to anyone else, and the collection-privacy
-- lesson (migration 90) is that an OR here is how private rows leak.
drop policy if exists calendar_subscriptions_own_select on public.calendar_subscriptions;
create policy calendar_subscriptions_own_select on public.calendar_subscriptions
  for select to authenticated using (user_id = (select auth.uid()));

drop policy if exists calendar_subscriptions_own_insert on public.calendar_subscriptions;
create policy calendar_subscriptions_own_insert on public.calendar_subscriptions
  for insert to authenticated with check (user_id = (select auth.uid()));

drop policy if exists calendar_subscriptions_own_update on public.calendar_subscriptions;
create policy calendar_subscriptions_own_update on public.calendar_subscriptions
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

drop policy if exists calendar_subscriptions_own_delete on public.calendar_subscriptions;
create policy calendar_subscriptions_own_delete on public.calendar_subscriptions
  for delete to authenticated using (user_id = (select auth.uid()));

-- A new table grants nothing implicitly (the migration-126 lesson).
grant select, insert, update, delete on public.calendar_subscriptions to authenticated;
grant select, insert, update, delete on public.calendar_subscriptions to service_role;

notify pgrst, 'reload schema';
