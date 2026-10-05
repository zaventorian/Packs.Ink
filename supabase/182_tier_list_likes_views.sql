-- Migration 182: tier list likes + views, and room for up to 10 tiers.
--
-- * Up to 10 tiers: a list's tier COUNT travels in its labels ("_"-joined,
--   up to 12 characters each), so 10 renamed tiers need ~130 characters.
--   Both labels checks widen to 160.
-- * Likes: custom_tier_list_likes, one row per (list, person). like_count on
--   the list is kept by a trigger, so Community can sort by it cheaply.
--   You can like any list you can open (public or unlisted), not a private one.
-- * Views: view_count, bumped by bump_tier_list_view(slug) when someone who
--   is not the owner opens a public or unlisted list. The client asks at most
--   once per list per browser session.
-- * The two counters cannot be written by the owner: authenticated gets
--   INSERT/UPDATE on the editable columns only.
-- * get_custom_tier_list / list_public_tier_lists return like_count,
--   view_count and liked_by_me; list_public_tier_lists gains p_sort
--   ('new' | 'liked').
--
-- Idempotent.

alter table public.tier_lists drop constraint if exists tier_lists_labels_len;
alter table public.tier_lists add constraint tier_lists_labels_len check (char_length(labels) <= 160);
alter table public.custom_tier_lists drop constraint if exists custom_tier_lists_labels_len;
alter table public.custom_tier_lists add constraint custom_tier_lists_labels_len check (char_length(labels) <= 160);

alter table public.custom_tier_lists add column if not exists like_count int not null default 0;
alter table public.custom_tier_lists add column if not exists view_count int not null default 0;

create index if not exists custom_tier_lists_liked_idx
  on public.custom_tier_lists (like_count desc, updated_at desc) where visibility = 'public';

-- This project's default privileges hand anon/authenticated everything on a
-- new table (TRUNCATE included). Take back what nobody should have.
revoke insert, update, delete, truncate, trigger, references on public.custom_tier_lists from anon;
revoke truncate, trigger, references on public.custom_tier_lists from authenticated;

-- Column-level writes: everything a list's owner edits, never the counters.
revoke insert, update on public.custom_tier_lists from authenticated;
grant insert (slug, user_id, title, labels, code, card_count, ranked_count, visibility, forked_from,
              created_at, updated_at)
  on public.custom_tier_lists to authenticated;
grant update (slug, user_id, title, labels, code, card_count, ranked_count, visibility, forked_from,
              updated_at)
  on public.custom_tier_lists to authenticated;

create table if not exists public.custom_tier_list_likes (
  slug       text        not null references public.custom_tier_lists(slug) on delete cascade,
  user_id    uuid        not null references auth.users(id) on delete cascade,
  created_at timestamptz not null default now(),
  primary key (slug, user_id)
);
create index if not exists custom_tier_list_likes_user_idx on public.custom_tier_list_likes (user_id);

alter table public.custom_tier_list_likes enable row level security;

drop policy if exists "custom_tier_list_likes: select own" on public.custom_tier_list_likes;
drop policy if exists "custom_tier_list_likes: insert own" on public.custom_tier_list_likes;
drop policy if exists "custom_tier_list_likes: delete own" on public.custom_tier_list_likes;

create policy "custom_tier_list_likes: select own"
  on public.custom_tier_list_likes for select to authenticated
  using ((select auth.uid()) = user_id);

-- Only a list you could open: public or unlisted (or your own). A DEFINER
-- check, because the caller's own RLS hides unlisted lists from a select.
create or replace function public.tier_list_likeable(p_slug text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.custom_tier_lists l
                 where l.slug = p_slug
                   and (l.visibility <> 'private' or l.user_id = (select auth.uid())));
$$;
revoke execute on function public.tier_list_likeable(text) from public;
grant execute on function public.tier_list_likeable(text) to authenticated, service_role;

create policy "custom_tier_list_likes: insert own"
  on public.custom_tier_list_likes for insert to authenticated
  with check ((select auth.uid()) = user_id and public.tier_list_likeable(slug));

create policy "custom_tier_list_likes: delete own"
  on public.custom_tier_list_likes for delete to authenticated
  using ((select auth.uid()) = user_id);

revoke all on public.custom_tier_list_likes from anon, authenticated;
grant select, insert, delete on public.custom_tier_list_likes to authenticated;
grant select, insert, update, delete on public.custom_tier_list_likes to service_role;

create or replace function public.custom_tier_list_likes_count()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  if tg_op = 'INSERT' then
    update public.custom_tier_lists set like_count = like_count + 1 where slug = new.slug;
  elsif tg_op = 'DELETE' then
    update public.custom_tier_lists set like_count = greatest(like_count - 1, 0) where slug = old.slug;
  end if;
  return null;
end $$;

drop trigger if exists custom_tier_list_likes_count on public.custom_tier_list_likes;
create trigger custom_tier_list_likes_count
  after insert or delete on public.custom_tier_list_likes
  for each row execute function public.custom_tier_list_likes_count();

create or replace function public.bump_tier_list_view(p_slug text)
returns void language sql volatile security definer set search_path = public as $$
  update public.custom_tier_lists
     set view_count = view_count + 1
   where slug = p_slug
     and visibility <> 'private'
     and user_id is distinct from (select auth.uid());
$$;

drop function if exists public.get_custom_tier_list(text);
create function public.get_custom_tier_list(p_slug text)
returns table (
  slug text, user_id uuid, title text, labels text, code text,
  card_count int, ranked_count int, visibility text, forked_from text,
  created_at timestamptz, updated_at timestamptz, published_at timestamptz,
  display_name text, avatar_url text,
  like_count int, view_count int, liked_by_me boolean
)
language sql stable security definer set search_path = public as $$
  select l.slug, l.user_id, l.title, l.labels, l.code,
         l.card_count, l.ranked_count, l.visibility, l.forked_from,
         l.created_at, l.updated_at, l.published_at,
         p.display_name, p.avatar_url,
         l.like_count, l.view_count,
         exists (select 1 from public.custom_tier_list_likes k
                 where k.slug = l.slug and k.user_id = (select auth.uid()))
  from public.custom_tier_lists l
  left join public.profiles p on p.user_id = l.user_id
  where l.slug = p_slug
    and (l.visibility <> 'private' or l.user_id = (select auth.uid()));
$$;

drop function if exists public.list_public_tier_lists(text, uuid, int, timestamptz);
drop function if exists public.list_public_tier_lists(text, uuid, int, timestamptz, text);
create function public.list_public_tier_lists(
  p_scope text default 'all', p_user uuid default null,
  p_limit int default 60, p_before timestamptz default null, p_sort text default 'new')
returns table (
  slug text, user_id uuid, title text, labels text, code text,
  card_count int, ranked_count int, forked_from text,
  created_at timestamptz, updated_at timestamptz, published_at timestamptz,
  display_name text, avatar_url text,
  like_count int, view_count int, liked_by_me boolean
)
language sql stable security definer set search_path = public as $$
  select l.slug, l.user_id, l.title, l.labels, l.code,
         l.card_count, l.ranked_count, l.forked_from,
         l.created_at, l.updated_at, l.published_at,
         p.display_name, p.avatar_url,
         l.like_count, l.view_count,
         exists (select 1 from public.custom_tier_list_likes k
                 where k.slug = l.slug and k.user_id = (select auth.uid()))
  from public.custom_tier_lists l
  left join public.profiles p on p.user_id = l.user_id
  where l.visibility = 'public'
    and (p_user is null or l.user_id = p_user)
    and (p_before is null or l.updated_at < p_before)
    and (coalesce(p_scope, 'all') <> 'following'
         or l.user_id in (select f.followed_id from public.user_follows f
                          where f.follower_id = (select auth.uid())))
  order by case when p_sort = 'liked' then l.like_count end desc nulls last,
           l.updated_at desc
  limit least(greatest(coalesce(p_limit, 60), 1), 100);
$$;

revoke execute on function public.get_custom_tier_list(text) from public;
revoke execute on function public.list_public_tier_lists(text, uuid, int, timestamptz, text) from public;
revoke execute on function public.bump_tier_list_view(text) from public;
grant execute on function public.get_custom_tier_list(text) to anon, authenticated, service_role;
grant execute on function public.list_public_tier_lists(text, uuid, int, timestamptz, text) to anon, authenticated, service_role;
grant execute on function public.bump_tier_list_view(text) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
