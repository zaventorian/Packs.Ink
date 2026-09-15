-- 153_social_feed.sql - the home page community feed (2026-09-15).
--
-- Two tables. social_sources is the ALLOWLIST a person curates: one row per
-- creator we are willing to surface. social_posts is one row per item, fed by
-- scripts/ingest_social_feed.py (YouTube RSS, free, no API key) and by an admin
-- pasting an X post URL.
--
-- Why YouTube is the engine and X is curated-only: X retired its Basic and Pro
-- tiers, so every read is metered at $0.005, and its free oEmbed endpoint
-- carries no engagement data at all - it can hydrate a URL you already hold but
-- can never tell you what is popular. YouTube's RSS needs no key, no quota and
-- no registration. See scripts/SOCIAL_FEED_RESEARCH.md for the full costing.
--
-- WARNING  NEVER STORE X's oEmbed `html` FIELD. It is an HTML blob containing
-- text written by strangers, and `innerHTML` appears zero times in Index.html
-- today - a discipline the whole app has held. Store the parsed plain text in
-- `body` so nobody can later "just render what X gave us". CSP will not save
-- you there: script-src already carries 'unsafe-inline' for the app's own
-- inline scripts.
--
-- WARNING  `confirmed` DEFAULTS FALSE, the scan_ccq_candidates.py contract. The
-- one case where automation may set it true is a source whose `auto_confirm` is
-- on - a human vetted that account, so the delegation is narrow and lives in
-- DATA rather than in a script's discretion. Card communities are thick with
-- counterfeit sellers; a tile on the home page reads as an endorsement.

create table if not exists public.social_sources (
  id            uuid primary key default gen_random_uuid(),
  platform      text not null check (platform in ('youtube','x','bluesky','twitch')),
  -- YouTube: the UC... channel id. X: the handle without the @.
  source_key    text not null check (char_length(source_key) between 1 and 120),
  name          text not null check (char_length(name) between 1 and 120),
  -- Off without deleting, so a creator can be paused without losing their row
  -- (and without the ingest re-adding them on the next sweep).
  enabled       boolean not null default true,
  -- The trust flag. See the WARNING above: this is what lets the ingest, or a
  -- curation routine, publish without a human ruling on each item.
  auto_confirm  boolean not null default false,
  note          text check (note is null or char_length(note) <= 500),
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (platform, source_key)
);

create table if not exists public.social_posts (
  id            uuid primary key default gen_random_uuid(),
  platform      text not null check (platform in ('youtube','x','bluesky','twitch')),
  -- The platform's own id for the item (YouTube video id, X post id). Unique
  -- with platform, so the hourly ingest is idempotent.
  source_id     text not null check (char_length(source_id) between 1 and 120),
  source_ref    uuid references public.social_sources(id) on delete set null,
  url           text not null check (char_length(url) <= 500),
  author_name   text check (author_name is null or char_length(author_name) <= 120),
  author_url    text check (author_url is null or char_length(author_url) <= 500),
  title         text check (title is null or char_length(title) <= 300),
  -- Post text / video description snippet. PLAIN TEXT ONLY - see the warning.
  body          text check (body is null or char_length(body) <= 2000),
  -- OUR line about why this is here. The whole point of the tile: a feed that
  -- only mirrors posts is a commodity, and the reader already has the app open.
  note          text check (note is null or char_length(note) <= 300),
  -- Optional link into the catalog, which is the thing no other feed can draw.
  card_id       text check (card_id is null or char_length(card_id) <= 120),
  set_name      text check (set_name is null or char_length(set_name) <= 120),
  thumb_url     text check (thumb_url is null or char_length(thumb_url) <= 500),
  posted_at     timestamptz not null,
  confirmed     boolean not null default false,
  -- The reaper's bookkeeping. A row is never deleted on the reaper's say-so:
  -- marking it dead keeps the id so a re-ingest cannot resurrect it.
  dead          boolean not null default false,
  hydrated_at   timestamptz,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (platform, source_id)
);

-- The feed's only query: newest confirmed live rows.
create index if not exists social_posts_feed_idx
  on public.social_posts (posted_at desc)
  where confirmed and not dead;

alter table public.social_sources enable row level security;
alter table public.social_posts  enable row level security;

-- WARNING  TWO SELECT POLICIES, NOT ONE WITH AN OR. Migration 134 did
-- `revoke all on function public.is_graded_admin() from public, anon`, so an
-- anonymous read of a policy that calls it does not get false - it RAISES 42501
-- and PostgREST turns that into a hard error. That is exactly how the curated
-- calendar was invisible to every signed-out visitor until migration 142.
-- Policies for the same command OR together, so an admin still sees candidates.
-- Do NOT "simplify" these back into one policy.
drop policy if exists social_posts_read_public on public.social_posts;
create policy social_posts_read_public on public.social_posts
  for select to anon, authenticated using (confirmed and not dead);

drop policy if exists social_posts_read_admin on public.social_posts;
create policy social_posts_read_admin on public.social_posts
  for select to authenticated using ((select public.is_graded_admin()));

drop policy if exists social_posts_admin_insert on public.social_posts;
create policy social_posts_admin_insert on public.social_posts
  for insert to authenticated with check ((select public.is_graded_admin()));

drop policy if exists social_posts_admin_update on public.social_posts;
create policy social_posts_admin_update on public.social_posts
  for update to authenticated
  using ((select public.is_graded_admin()))
  with check ((select public.is_graded_admin()));

drop policy if exists social_posts_admin_delete on public.social_posts;
create policy social_posts_admin_delete on public.social_posts
  for delete to authenticated using ((select public.is_graded_admin()));

-- The source list is admin-only in both directions. It is an editorial
-- decision record, not public data, and nothing client-side reads it.
drop policy if exists social_sources_admin_all on public.social_sources;
create policy social_sources_admin_all on public.social_sources
  for all to authenticated
  using ((select public.is_graded_admin()))
  with check ((select public.is_graded_admin()));

-- A new table grants nothing implicitly (the migration-126 lesson): without
-- these, every read is a flat 403 before RLS is ever consulted.
grant select on public.social_posts to anon, authenticated;
grant insert, update, delete on public.social_posts to authenticated;
grant select, insert, update, delete on public.social_posts to service_role;

grant select, insert, update, delete on public.social_sources to authenticated;
grant select, insert, update, delete on public.social_sources to service_role;

-- No seed. Which creators to carry is a human editorial judgement, not a
-- lookup, and an empty feed renders as nothing rather than as something wrong.

NOTIFY pgrst, 'reload schema';
