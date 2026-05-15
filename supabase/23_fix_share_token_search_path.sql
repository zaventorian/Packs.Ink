-- Fixup for 22_deck_share_tokens.sql: gen_random_bytes() lives in the
-- pgcrypto extension, which Supabase installs into the `extensions`
-- schema (NOT on the default search_path). The original gen_share_token()
-- failed with "function gen_random_bytes(integer) does not exist" because
-- SECURITY DEFINER functions only see schemas in their pinned search_path.
--
-- Fix: pin search_path to include `extensions`, and ensure pgcrypto is
-- enabled. Safe to re-run.

create extension if not exists pgcrypto with schema extensions;

create or replace function public.gen_share_token()
returns text
language sql
volatile
-- Include the extensions schema so gen_random_bytes() resolves from
-- pgcrypto regardless of where Supabase installed it.
set search_path = public, extensions, pg_catalog
as $$
  -- 16 random bytes -> 22-char URL-safe base64 (no '+', '/', or padding).
  select replace(replace(replace(encode(gen_random_bytes(16), 'base64'), '+', '-'), '/', '_'), '=', '');
$$;

-- The downstream RPC inherits this search_path through its own
-- SET clause, but re-pin to be safe.
create or replace function public.regenerate_deck_share_token(p_deck_id uuid)
returns text
language plpgsql
security definer
set search_path = public, extensions, pg_catalog
as $$
declare
  v_new text;
begin
  v_new := public.gen_share_token();
  update public.decks
     set share_token = v_new
   where id = p_deck_id
     and user_id = auth.uid();
  if not found then
    raise exception 'deck not found or not owned by caller';
  end if;
  return v_new;
end;
$$;

-- Backfill any rows that previously got an empty token because the
-- earlier failed function returned NULL into the not-null column.
-- (If 22 actually completed, this is a no-op.)
update public.decks
   set share_token = public.gen_share_token()
 where share_token is null or share_token = '';

notify pgrst, 'reload schema';
