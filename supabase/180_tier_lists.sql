-- Migration 180: tier lists saved to the account (Analytics > Tier List, /tierlist).
--
-- One row per (user, set). The list is stored in the SAME shape the share link
-- carries it, so the two can never disagree:
--   code   = the ?tl= string: one base-36 character per card (its collector-number
--            offset from the set's first chase card), tiers separated by "."
--   title  = the ?tn= title, '' for the default
--   labels = the ?tt= renamed tier labels, '' for S/A/B/C/D
-- Collector numbers rather than card ids because prestaged sets swap their
-- stand-in ids for Lorcast's; a numbered list survives that day.
--
-- Safe to ship the client first: before this lands the page keeps lists on the
-- device (localStorage) exactly as it always did, and stops asking.
--
-- Idempotent.

create table if not exists public.tier_lists (
  user_id    uuid        not null references auth.users(id) on delete cascade,
  set_name   text        not null,
  code       text        not null default '',
  title      text        not null default '',
  labels     text        not null default '',
  updated_at timestamptz not null default now(),
  primary key (user_id, set_name),
  constraint tier_lists_set_len check (char_length(set_name) between 1 and 80),
  constraint tier_lists_code_len check (char_length(code) <= 200),
  constraint tier_lists_title_len check (char_length(title) <= 60),
  constraint tier_lists_labels_len check (char_length(labels) <= 80)
);

-- Owner-only. auth.uid() wrapped in (select ...) per migration 91.
alter table public.tier_lists enable row level security;

drop policy if exists "tier_lists: select own" on public.tier_lists;
drop policy if exists "tier_lists: insert own" on public.tier_lists;
drop policy if exists "tier_lists: update own" on public.tier_lists;
drop policy if exists "tier_lists: delete own" on public.tier_lists;

create policy "tier_lists: select own"
  on public.tier_lists for select to authenticated
  using ((select auth.uid()) = user_id);

create policy "tier_lists: insert own"
  on public.tier_lists for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "tier_lists: update own"
  on public.tier_lists for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "tier_lists: delete own"
  on public.tier_lists for delete to authenticated
  using ((select auth.uid()) = user_id);

-- A new relation grants NOTHING implicitly (the migration 125 -> 126 lesson).
grant select, insert, update, delete on public.tier_lists to authenticated;
grant select, insert, update, delete on public.tier_lists to service_role;

notify pgrst, 'reload schema';
