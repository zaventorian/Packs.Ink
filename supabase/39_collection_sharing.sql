-- Collection sharing — public / unlisted / private per section.
--
-- Mirrors the deck-share model in 22_deck_share_tokens.sql, with two
-- differences:
--   1. Three independent visibility flags on profiles (raw / sealed / graded)
--      so users can expose just one section without the others.
--   2. ONE share_token per profile. The user shares "my collection" as a
--      single URL; the viewer renders whichever sections are unlisted/public.
--
-- RLS broadening: existing owner-only SELECT policies on the three collection
-- tables get an OR clause for public sections. Unlisted reads go through
-- SECURITY DEFINER RPCs that gate on token match.
--
-- Token rotation: when ALL THREE sections flip to private (collection becomes
-- fully unshareable), the token rotates and any in-the-wild URL dies. Going
-- back out to unlisted/public uses the new token. Owners can also manually
-- rotate via regenerate_collection_share_token().
--
-- Idempotent on re-run.

-- ── profiles: visibility + token ─────────────────────────────────────────
alter table public.profiles
  add column if not exists collection_raw_visibility    text not null default 'private',
  add column if not exists collection_sealed_visibility text not null default 'private',
  add column if not exists collection_graded_visibility text not null default 'private',
  add column if not exists collection_share_token       text;

-- CHECK constraints (idempotent: drop-then-add)
alter table public.profiles
  drop constraint if exists profiles_collection_raw_visibility_check;
alter table public.profiles
  add  constraint profiles_collection_raw_visibility_check
       check (collection_raw_visibility in ('private','unlisted','public'));

alter table public.profiles
  drop constraint if exists profiles_collection_sealed_visibility_check;
alter table public.profiles
  add  constraint profiles_collection_sealed_visibility_check
       check (collection_sealed_visibility in ('private','unlisted','public'));

alter table public.profiles
  drop constraint if exists profiles_collection_graded_visibility_check;
alter table public.profiles
  add  constraint profiles_collection_graded_visibility_check
       check (collection_graded_visibility in ('private','unlisted','public'));

-- Per-row token backfill (same caveat as 22_*: a NOT NULL DEFAULT fn() runs
-- once and assigns the SAME token to every existing row).
update public.profiles
   set collection_share_token = public.gen_share_token()
 where collection_share_token is null or collection_share_token = '';

alter table public.profiles
  alter column collection_share_token set default public.gen_share_token(),
  alter column collection_share_token set not null;

create index if not exists profiles_collection_share_token_idx
  on public.profiles (collection_share_token);

-- ── RLS broadening on the three collection tables ───────────────────────
-- Owner stays unrestricted (insert/update/delete policies untouched).
-- Add SELECT visibility for public sections.

drop policy if exists "collection_items: select own"           on public.collection_items;
drop policy if exists "collection_items: select own or public" on public.collection_items;
create policy "collection_items: select own or public"
  on public.collection_items for select
  using (
    auth.uid() = user_id
    OR exists (
      select 1 from public.profiles p
       where p.user_id = collection_items.user_id
         and p.collection_raw_visibility = 'public'
    )
  );

drop policy if exists "sealed_collection_items: select own"           on public.sealed_collection_items;
drop policy if exists "sealed_collection_items: select own or public" on public.sealed_collection_items;
create policy "sealed_collection_items: select own or public"
  on public.sealed_collection_items for select
  using (
    auth.uid() = user_id
    OR exists (
      select 1 from public.profiles p
       where p.user_id = sealed_collection_items.user_id
         and p.collection_sealed_visibility = 'public'
    )
  );

drop policy if exists "graded_collection_items_owner_all"           on public.graded_collection_items;
drop policy if exists "graded_collection_items: select own or public" on public.graded_collection_items;
drop policy if exists "graded_collection_items: insert own"          on public.graded_collection_items;
drop policy if exists "graded_collection_items: update own"          on public.graded_collection_items;
drop policy if exists "graded_collection_items: delete own"          on public.graded_collection_items;

create policy "graded_collection_items: select own or public"
  on public.graded_collection_items for select
  using (
    auth.uid() = user_id
    OR exists (
      select 1 from public.profiles p
       where p.user_id = graded_collection_items.user_id
         and p.collection_graded_visibility = 'public'
    )
  );
create policy "graded_collection_items: insert own"
  on public.graded_collection_items for insert
  with check (auth.uid() = user_id);
create policy "graded_collection_items: update own"
  on public.graded_collection_items for update
  using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "graded_collection_items: delete own"
  on public.graded_collection_items for delete
  using (auth.uid() = user_id);

-- ── token-rotation trigger ──────────────────────────────────────────────
-- Rotate the collection token only when ALL three sections become private
-- in this update (and at least one of them just changed). Single-section
-- toggles don't rotate, because the link may still be needed for the
-- remaining unlisted section.
create or replace function public.rotate_collection_token_on_all_private()
returns trigger
language plpgsql
as $$
begin
  if NEW.collection_raw_visibility    = 'private'
     and NEW.collection_sealed_visibility = 'private'
     and NEW.collection_graded_visibility = 'private'
     and (
       OLD.collection_raw_visibility    is distinct from NEW.collection_raw_visibility
       OR OLD.collection_sealed_visibility is distinct from NEW.collection_sealed_visibility
       OR OLD.collection_graded_visibility is distinct from NEW.collection_graded_visibility
     ) then
    NEW.collection_share_token := public.gen_share_token();
  end if;
  return NEW;
end;
$$;

drop trigger if exists profiles_rotate_collection_token on public.profiles;
create trigger profiles_rotate_collection_token
  before update on public.profiles
  for each row execute function public.rotate_collection_token_on_all_private();

-- ── token-gated read RPCs (one per section) ─────────────────────────────
-- Each returns rows only if the matching section is public, or if it's
-- unlisted AND the token matches. Private sections return empty
-- regardless of token (defense-in-depth).

create or replace function public.get_shared_collection_raw(p_user_id uuid, p_token text)
returns table(
  user_id    uuid,
  card_id    text,
  printing   text,
  condition  text,
  quantity   int,
  notes      text,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
as $$
  select ci.user_id, ci.card_id, ci.printing, ci.condition, ci.quantity, ci.notes, ci.updated_at
    from public.collection_items ci
    join public.profiles p on p.user_id = ci.user_id
   where ci.user_id = p_user_id
     and (
       p.collection_raw_visibility = 'public'
       OR (p.collection_raw_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;

create or replace function public.get_shared_collection_sealed(p_user_id uuid, p_token text)
returns table(
  user_id              uuid,
  tcgplayer_product_id bigint,
  condition            text,
  quantity             int,
  notes                text,
  updated_at           timestamptz
)
language sql
security definer
set search_path = public
as $$
  select sci.user_id, sci.tcgplayer_product_id, sci.condition, sci.quantity, sci.notes, sci.updated_at
    from public.sealed_collection_items sci
    join public.profiles p on p.user_id = sci.user_id
   where sci.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       OR (p.collection_sealed_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;

create or replace function public.get_shared_collection_graded(p_user_id uuid, p_token text)
returns table(
  user_id    uuid,
  card_id    text,
  grader     text,
  grade      text,
  quantity   integer,
  updated_at timestamptz
)
language sql
security definer
set search_path = public
as $$
  select gci.user_id, gci.card_id, gci.grader, gci.grade, gci.quantity, gci.updated_at
    from public.graded_collection_items gci
    join public.profiles p on p.user_id = gci.user_id
   where gci.user_id = p_user_id
     and (
       p.collection_graded_visibility = 'public'
       OR (p.collection_graded_visibility = 'unlisted' AND p.collection_share_token = p_token)
     );
$$;

-- Visibility summary — the viewer calls this first to know which sections
-- to render and which to hide. Includes display_name + avatar_url so the
-- viewer can render the owner's banner in one round-trip.
create or replace function public.get_collection_visibility(p_user_id uuid, p_token text)
returns table(
  user_id        uuid,
  raw_visible    boolean,
  sealed_visible boolean,
  graded_visible boolean,
  display_name   text,
  avatar_url     text
)
language sql
security definer
set search_path = public
as $$
  select
    p.user_id,
    (p.collection_raw_visibility    = 'public'
      OR (p.collection_raw_visibility    = 'unlisted' AND p.collection_share_token = p_token)) as raw_visible,
    (p.collection_sealed_visibility = 'public'
      OR (p.collection_sealed_visibility = 'unlisted' AND p.collection_share_token = p_token)) as sealed_visible,
    (p.collection_graded_visibility = 'public'
      OR (p.collection_graded_visibility = 'unlisted' AND p.collection_share_token = p_token)) as graded_visible,
    p.display_name,
    p.avatar_url
    from public.profiles p
   where p.user_id = p_user_id;
$$;

revoke all on function public.get_shared_collection_raw(uuid, text)    from public;
revoke all on function public.get_shared_collection_sealed(uuid, text) from public;
revoke all on function public.get_shared_collection_graded(uuid, text) from public;
revoke all on function public.get_collection_visibility(uuid, text)    from public;
grant  execute on function public.get_shared_collection_raw(uuid, text)    to anon, authenticated;
grant  execute on function public.get_shared_collection_sealed(uuid, text) to anon, authenticated;
grant  execute on function public.get_shared_collection_graded(uuid, text) to anon, authenticated;
grant  execute on function public.get_collection_visibility(uuid, text)    to anon, authenticated;

-- Owner-only rotate (revoke an in-the-wild URL without flipping all sections
-- to private). Returns the new token.
create or replace function public.regenerate_collection_share_token()
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_new text;
begin
  v_new := public.gen_share_token();
  update public.profiles
     set collection_share_token = v_new
   where user_id = auth.uid();
  if not found then
    raise exception 'profile not found for caller';
  end if;
  return v_new;
end;
$$;

revoke all on function public.regenerate_collection_share_token() from public;
grant  execute on function public.regenerate_collection_share_token() to authenticated;

notify pgrst, 'reload schema';
