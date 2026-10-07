-- Migration 184: Tier List hardening (from the 2026-10-06 review of 180-182).
--
-- Independent of the client: the site works the same before and after it.
-- Applied 2026-10-06 through the connector, after a PGlite run of 180-182 +
-- this file with RLS on (26 checks; the cap, self-like, view and cleanup
-- checks fail without it). Live, it changed no rows: 2 lists, no copies,
-- no self-likes, no views yet.
--
-- 1. The 500-list cap no longer blocks EDITS. Saves are upserts, and a BEFORE
--    INSERT trigger runs before Postgres finds the conflicting row, so at 500
--    lists every save of an EXISTING list raised 'tier list limit reached'
--    too. The client only logged it, so edits were silently lost.
-- 2. forked_from names a parent only while the parent is public. An unlisted
--    list's slug is its whole secret, and a public copy of one carried that
--    slug to every reader (anon can read public rows straight from the
--    table). The guard now clears a non-public parent on every write, and
--    the existing rows are cleaned once. The client stopped writing one in
--    the same change (tierForkParent).
--    Known gap: a parent that is public when copied and later made unlisted
--    stays named by its copies until each copy is next saved.
-- 3. You cannot like your own list. tier_list_likeable() returned true for
--    the owner, so an owner could put their own list up "Most liked".
--    Existing self-likes are LEFT IN PLACE; to remove them, see the note at
--    the end.
-- 4. Views: one per list per viewer per day. bump_tier_list_view() was
--    executable by anon with no limit, so a loop could add a view (and a
--    table write) per request. A viewer is the signed-in user, or a hash of
--    the client IP (public._client_ip(), migration 133). Marks older than two
--    days are swept as it goes.
-- 5. tier_lists: take back the default privileges 182 already took back on
--    custom_tier_lists (TRUNCATE bypasses RLS; anon never needed writes).
--
-- Idempotent. Needs migration 133 (public._client_ip) and pgcrypto (digest).

-- ── 1 + 2. The guard ────────────────────────────────────────────────────────
-- Runs as the caller, so its parent lookup sees what the caller's RLS allows:
-- public rows and the caller's own. "Is the parent public" is exactly
-- answerable from there.
create or replace function public.custom_tier_lists_guard()
returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT'
     and not exists (select 1 from public.custom_tier_lists where slug = new.slug)
     and (select count(*) from public.custom_tier_lists where user_id = new.user_id) >= 500 then
    raise exception 'tier list limit reached' using errcode = 'P0001';
  end if;
  if new.forked_from is not null and not exists (
       select 1 from public.custom_tier_lists p
       where p.slug = new.forked_from and p.visibility = 'public') then
    new.forked_from := null;
  end if;
  if new.visibility = 'public' and new.published_at is null then
    new.published_at := now();
  end if;
  if new.updated_at > now() + interval '5 minutes' then
    new.updated_at := now();
  end if;
  return new;
end $$;

-- One-time clean of copies that already name a non-public (or deleted) parent.
-- Runs as the migration owner, so it sees every row.
update public.custom_tier_lists c
   set forked_from = null
 where c.forked_from is not null
   and not exists (select 1 from public.custom_tier_lists p
                   where p.slug = c.forked_from and p.visibility = 'public');

-- ── 3. No liking your own list ──────────────────────────────────────────────
create or replace function public.tier_list_likeable(p_slug text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.custom_tier_lists l
                 where l.slug = p_slug
                   and l.visibility <> 'private'
                   and l.user_id is distinct from (select auth.uid()));
$$;
revoke execute on function public.tier_list_likeable(text) from public;
grant execute on function public.tier_list_likeable(text) to authenticated, service_role;

-- ── 4. One view per list per viewer per day ─────────────────────────────────
create table if not exists public.custom_tier_list_view_marks (
  slug   text not null,
  viewer text not null,
  day    date not null default current_date,
  primary key (slug, viewer, day)
);
create index if not exists custom_tier_list_view_marks_day_idx
  on public.custom_tier_list_view_marks (day);
alter table public.custom_tier_list_view_marks enable row level security;
-- No policies and no grants: only the definer function below touches it.
revoke all on public.custom_tier_list_view_marks from anon, authenticated;
grant all on public.custom_tier_list_view_marks to service_role;

drop function if exists public.bump_tier_list_view(text);
create function public.bump_tier_list_view(p_slug text)
returns void language plpgsql volatile security definer
set search_path = public, extensions as $$
declare
  v_uid    uuid := (select auth.uid());
  v_viewer text;
  v_new    int;
begin
  if p_slug is null or p_slug !~ '^[A-Za-z0-9]{8,16}$' then
    return;
  end if;
  v_viewer := coalesce('u:' || v_uid::text,
    'ip:' || encode(digest('packsink-tierview|' || coalesce(nullif(public._client_ip(), ''), 'unknown'), 'sha256'), 'hex'));
  delete from public.custom_tier_list_view_marks where day < current_date - 1;
  insert into public.custom_tier_list_view_marks (slug, viewer)
  values (p_slug, v_viewer)
  on conflict do nothing;
  get diagnostics v_new = row_count;
  if v_new = 0 then
    return;
  end if;
  update public.custom_tier_lists
     set view_count = view_count + 1
   where slug = p_slug
     and visibility <> 'private'
     and user_id is distinct from v_uid;
end $$;
revoke execute on function public.bump_tier_list_view(text) from public;
grant execute on function public.bump_tier_list_view(text) to anon, authenticated, service_role;

-- ── 5. tier_lists default privileges ────────────────────────────────────────
revoke insert, update, delete, truncate, trigger, references on public.tier_lists from anon;
revoke truncate, trigger, references on public.tier_lists from authenticated;

notify pgrst, 'reload schema';

-- Removing existing self-likes (optional, user-visible: counts drop):
--   delete from public.custom_tier_list_likes k
--    using public.custom_tier_lists l
--    where l.slug = k.slug and l.user_id = k.user_id;
-- The like_count trigger lowers each list's count as the rows go.
