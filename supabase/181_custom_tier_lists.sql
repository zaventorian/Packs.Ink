-- Migration 181: custom tier lists (Tier List > My lists / Community).
--
-- A custom list is a tier list over cards the person picked (every Legendary
-- in a set, one ink, every Mickey Mouse, their favourite frogs). One row per
-- list, keyed by a short random slug the CLIENT mints, so a list made signed
-- out keeps the same id once it is carried up to the account, and its short
-- link (packs.ink/tierlist?tid=<slug>) never changes.
--
-- The list is stored in the SAME shape its long link carries (?tc= / ?tn= /
-- ?tt=): printed set code + collector number per card, never card_id, because
-- prestaged sets swap their stand-in ids for Lorcast's on the day they are
-- indexed.
--
-- Visibility: private (only you), unlisted (anyone with the link, the
-- default), public (Community tab + your followers' home feed). Unlisted rows
-- are read only through get_custom_tier_list(slug), so they cannot be listed.
--
-- Safe to ship the client first: before this lands, custom lists stay on the
-- device and links are the long ?tc= form.
--
-- Idempotent.

create table if not exists public.custom_tier_lists (
  slug         text        primary key,
  user_id      uuid        not null references auth.users(id) on delete cascade,
  title        text        not null default '',
  labels       text        not null default '',
  code         text        not null default '',
  card_count   int         not null default 0,
  ranked_count int         not null default 0,
  visibility   text        not null default 'unlisted',
  forked_from  text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  published_at timestamptz,
  constraint custom_tier_lists_slug_fmt  check (slug ~ '^[A-Za-z0-9]{8,16}$'),
  constraint custom_tier_lists_vis       check (visibility in ('private', 'unlisted', 'public')),
  constraint custom_tier_lists_title_len check (char_length(title) <= 60),
  constraint custom_tier_lists_labels_len check (char_length(labels) <= 80),
  constraint custom_tier_lists_code_len  check (char_length(code) <= 6000),
  constraint custom_tier_lists_counts    check (card_count between 0 and 400
                                                and ranked_count between 0 and card_count),
  constraint custom_tier_lists_fork_fmt  check (forked_from is null or forked_from ~ '^[A-Za-z0-9]{8,16}$')
);

create index if not exists custom_tier_lists_user_idx
  on public.custom_tier_lists (user_id, updated_at desc);
create index if not exists custom_tier_lists_public_idx
  on public.custom_tier_lists (updated_at desc) where visibility = 'public';

-- Stamp the first publish, keep a client clock from writing the future, and
-- cap lists per person (a list is ~1-6 KB; 500 is far past any real use).
create or replace function public.custom_tier_lists_guard()
returns trigger language plpgsql set search_path = public as $$
begin
  if tg_op = 'INSERT' and (select count(*) from public.custom_tier_lists where user_id = new.user_id) >= 500 then
    raise exception 'tier list limit reached' using errcode = 'P0001';
  end if;
  if new.visibility = 'public' and new.published_at is null then
    new.published_at := now();
  end if;
  if new.updated_at > now() + interval '5 minutes' then
    new.updated_at := now();
  end if;
  return new;
end $$;

drop trigger if exists custom_tier_lists_guard on public.custom_tier_lists;
create trigger custom_tier_lists_guard
  before insert or update on public.custom_tier_lists
  for each row execute function public.custom_tier_lists_guard();

alter table public.custom_tier_lists enable row level security;

drop policy if exists "custom_tier_lists: select public or own" on public.custom_tier_lists;
drop policy if exists "custom_tier_lists: insert own" on public.custom_tier_lists;
drop policy if exists "custom_tier_lists: update own" on public.custom_tier_lists;
drop policy if exists "custom_tier_lists: delete own" on public.custom_tier_lists;

-- auth.uid() wrapped in (select ...) per migration 91. Anonymous readers get
-- null from auth.uid(), so they see public rows only.
create policy "custom_tier_lists: select public or own"
  on public.custom_tier_lists for select to anon, authenticated
  using (visibility = 'public' or (select auth.uid()) = user_id);

create policy "custom_tier_lists: insert own"
  on public.custom_tier_lists for insert to authenticated
  with check ((select auth.uid()) = user_id);

create policy "custom_tier_lists: update own"
  on public.custom_tier_lists for update to authenticated
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "custom_tier_lists: delete own"
  on public.custom_tier_lists for delete to authenticated
  using ((select auth.uid()) = user_id);

-- A new relation grants NOTHING implicitly (the migration 125 -> 126 lesson).
grant select on public.custom_tier_lists to anon;
grant select, insert, update, delete on public.custom_tier_lists to authenticated;
grant select, insert, update, delete on public.custom_tier_lists to service_role;

-- One list by its slug: public, unlisted, or your own. Carries the author's
-- display name so a shared link can say whose list it is. STABLE so the link
-- preview worker can call it with a GET.
drop function if exists public.get_custom_tier_list(text);
create function public.get_custom_tier_list(p_slug text)
returns table (
  slug text, user_id uuid, title text, labels text, code text,
  card_count int, ranked_count int, visibility text, forked_from text,
  created_at timestamptz, updated_at timestamptz, published_at timestamptz,
  display_name text, avatar_url text
)
language sql stable security definer set search_path = public as $$
  select l.slug, l.user_id, l.title, l.labels, l.code,
         l.card_count, l.ranked_count, l.visibility, l.forked_from,
         l.created_at, l.updated_at, l.published_at,
         p.display_name, p.avatar_url
  from public.custom_tier_lists l
  left join public.profiles p on p.user_id = l.user_id
  where l.slug = p_slug
    and (l.visibility <> 'private' or l.user_id = (select auth.uid()));
$$;

-- The Community tab: public lists, newest activity first. p_scope = 'all' or
-- 'following' (lists by people the caller follows); p_user narrows to one
-- creator.
drop function if exists public.list_public_tier_lists(text, uuid, int, timestamptz);
create function public.list_public_tier_lists(
  p_scope text default 'all', p_user uuid default null,
  p_limit int default 60, p_before timestamptz default null)
returns table (
  slug text, user_id uuid, title text, labels text, code text,
  card_count int, ranked_count int, forked_from text,
  created_at timestamptz, updated_at timestamptz, published_at timestamptz,
  display_name text, avatar_url text
)
language sql stable security definer set search_path = public as $$
  select l.slug, l.user_id, l.title, l.labels, l.code,
         l.card_count, l.ranked_count, l.forked_from,
         l.created_at, l.updated_at, l.published_at,
         p.display_name, p.avatar_url
  from public.custom_tier_lists l
  left join public.profiles p on p.user_id = l.user_id
  where l.visibility = 'public'
    and (p_user is null or l.user_id = p_user)
    and (p_before is null or l.updated_at < p_before)
    and (coalesce(p_scope, 'all') <> 'following'
         or l.user_id in (select f.followed_id from public.user_follows f
                          where f.follower_id = (select auth.uid())))
  order by l.updated_at desc
  limit least(greatest(coalesce(p_limit, 60), 1), 100);
$$;

revoke execute on function public.get_custom_tier_list(text) from public;
revoke execute on function public.list_public_tier_lists(text, uuid, int, timestamptz) from public;
grant execute on function public.get_custom_tier_list(text) to anon, authenticated, service_role;
grant execute on function public.list_public_tier_lists(text, uuid, int, timestamptz) to anon, authenticated, service_role;

notify pgrst, 'reload schema';
