-- Migration 192: an unlisted collection link opens only what it was made for.
--
-- Backward compatible; applies with the live client unchanged (it only
-- WIDENS the tokens the read functions accept, and adds an owner RPC).
-- Idempotent.
--
-- profiles.collection_share_token is one token for all three sections, so
-- the one "Copy unlisted link" in the share popover opens every section that
-- is unlisted - including one made unlisted AFTER the link went out. Someone
-- who sent their Cards link last month and unlists Graded today has just
-- shown Graded to everybody holding that link.
--
-- A link can now carry a SCOPED token: HMAC-SHA256 of the scope under the
-- base token ("raw", "sealed+graded", ... sections in raw, sealed, graded
-- order joined by '+'), first 16 bytes, URL-safe base64 - the same 22-char
-- shape as the base token. A section's read accepts the base token (links
-- already in the wild keep working) or the token of any scope that names
-- that section. Without the base token a scoped token cannot be turned into
-- another one, and regenerating the base token (or the all-private rotation
-- trigger) changes every scoped token with it.
--
-- get_my_collection_share_tokens() hands the owner the seven scoped tokens;
-- the share popover builds each link from the scope the owner picked.

create or replace function public._collection_scope_token(p_base text, p_scope text)
returns text
language sql
stable
set search_path = ''
as $$
  select case when coalesce(p_base, '') = '' or coalesce(p_scope, '') = '' then null
    else rtrim(translate(encode(substring(extensions.hmac(
           convert_to('packsink-collection-scope|' || p_scope, 'UTF8'),
           convert_to(p_base, 'UTF8'), 'sha256') from 1 for 16), 'base64'), '+/', '-_'), '=')
  end
$$;
revoke all on function public._collection_scope_token(text, text) from public, anon, authenticated;

create or replace function public._collection_token_ok(p_base text, p_token text, p_section text)
returns boolean
language sql
stable
set search_path = ''
as $$
  select coalesce(p_base, '') <> '' and coalesce(p_token, '') <> ''
     and (p_token = p_base
          or exists (select 1
                       from unnest(array['raw', 'sealed', 'graded', 'raw+sealed', 'raw+graded',
                                         'sealed+graded', 'raw+sealed+graded']) s
                      where p_section = any(string_to_array(s, '+'))
                        and public._collection_scope_token(p_base, s) = p_token))
$$;
revoke all on function public._collection_token_ok(text, text, text) from public, anon, authenticated;

-- The five readers: live bodies, with the token test swapped.
create or replace function public.get_collection_visibility(p_user_id uuid, p_token text)
returns table(user_id uuid, raw_visible boolean, sealed_visible boolean, graded_visible boolean, display_name text, avatar_url text)
language sql
security definer
set search_path to 'public'
as $$
  select
    p.user_id,
    (p.collection_raw_visibility    = 'public'
      or (p.collection_raw_visibility    = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'raw'))) as raw_visible,
    (p.collection_sealed_visibility = 'public'
      or (p.collection_sealed_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'sealed'))) as sealed_visible,
    (p.collection_graded_visibility = 'public'
      or (p.collection_graded_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'graded'))) as graded_visible,
    p.display_name,
    p.avatar_url
    from public.profiles p
   where p.user_id = p_user_id;
$$;

create or replace function public.get_shared_collection_raw(p_user_id uuid, p_token text)
returns table(user_id uuid, card_id text, printing text, condition text, quantity integer, updated_at timestamp with time zone)
language sql
security definer
set search_path to 'public'
as $$
  select ci.user_id, ci.card_id, ci.printing, ci.condition, ci.quantity, ci.updated_at
    from public.collection_items ci
    join public.profiles p on p.user_id = ci.user_id
   where ci.user_id = p_user_id
     and (
       p.collection_raw_visibility = 'public'
       or (p.collection_raw_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'raw'))
     );
$$;

create or replace function public.get_shared_collection_sealed(p_user_id uuid, p_token text)
returns table(user_id uuid, tcgplayer_product_id bigint, condition text, quantity integer, acquired_date date, updated_at timestamp with time zone)
language sql
security definer
set search_path to 'public'
as $$
  select sci.user_id, sci.tcgplayer_product_id, sci.condition, sci.quantity,
         sci.acquired_date, sci.updated_at
    from public.sealed_collection_items sci
    join public.profiles p on p.user_id = sci.user_id
   where sci.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       or (p.collection_sealed_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'sealed'))
     );
$$;

create or replace function public.get_shared_collection_graded(p_user_id uuid, p_token text)
returns table(user_id uuid, card_id text, printing text, grader text, grade text, quantity integer, acquired_date date, updated_at timestamp with time zone)
language sql
security definer
set search_path to 'public'
as $$
  select gci.user_id, gci.card_id, gci.printing, gci.grader, gci.grade, gci.quantity,
         gci.acquired_date, gci.updated_at
    from public.graded_collection_items gci
    join public.profiles p on p.user_id = gci.user_id
   where gci.user_id = p_user_id
     and (
       p.collection_graded_visibility = 'public'
       or (p.collection_graded_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'graded'))
     );
$$;

-- Pins & Counters boards ride the SEALED axis (139).
create or replace function public.get_shared_collectible_boards(p_user_id uuid, p_token text)
returns table(board text, layout jsonb, updated_at timestamp with time zone)
language sql
stable
security definer
set search_path to 'public'
as $$
  select b.board, b.layout, b.updated_at
    from public.collectible_boards b
    join public.profiles p on p.user_id = b.user_id
   where b.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       or (p.collection_sealed_visibility = 'unlisted' and public._collection_token_ok(p.collection_share_token, p_token, 'sealed'))
     );
$$;

revoke all on function public.get_collection_visibility(uuid, text) from public;
revoke all on function public.get_shared_collection_raw(uuid, text) from public;
revoke all on function public.get_shared_collection_sealed(uuid, text) from public;
revoke all on function public.get_shared_collection_graded(uuid, text) from public;
revoke all on function public.get_shared_collectible_boards(uuid, text) from public;
grant execute on function public.get_collection_visibility(uuid, text) to anon, authenticated;
grant execute on function public.get_shared_collection_raw(uuid, text) to anon, authenticated;
grant execute on function public.get_shared_collection_sealed(uuid, text) to anon, authenticated;
grant execute on function public.get_shared_collection_graded(uuid, text) to anon, authenticated;
grant execute on function public.get_shared_collectible_boards(uuid, text) to anon, authenticated;

-- Owner only: {"raw": ..., "sealed": ..., ..., "raw+sealed+graded": ...}.
create or replace function public.get_my_collection_share_tokens()
returns jsonb
language sql
stable
security definer
set search_path to 'public'
as $$
  select (select jsonb_object_agg(s, public._collection_scope_token(p.collection_share_token, s))
            from unnest(array['raw', 'sealed', 'graded', 'raw+sealed', 'raw+graded',
                              'sealed+graded', 'raw+sealed+graded']) s)
    from public.profiles p
   where p.user_id = (select auth.uid())
     and coalesce(p.collection_share_token, '') <> '';
$$;
revoke all on function public.get_my_collection_share_tokens() from public, anon;
grant execute on function public.get_my_collection_share_tokens() to authenticated;

notify pgrst, 'reload schema';
