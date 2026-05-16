-- Add youtube_url to the get_shared_deck RPC's RETURNS TABLE so shared-deck
-- viewers see the embedded video the creator attached.
--
-- The RPC was originally defined in 22_deck_share_tokens.sql before the
-- youtube_url column existed (added in 29_deck_youtube_url.sql). PostgREST
-- only surfaces columns named in the RETURNS TABLE clause, so the field
-- was silently stripped on the way to the client even though the underlying
-- decks row has it.
--
-- Postgres rejects CREATE OR REPLACE when RETURNS TABLE columns change
-- ("cannot change return type of existing function" / 42P13), so we drop
-- the old definition first. Drop is idempotent via IF EXISTS.

drop function if exists public.get_shared_deck(uuid, text);

create or replace function public.get_shared_deck(p_deck_id uuid, p_token text)
returns table(
  id           uuid,
  user_id      uuid,
  name         text,
  description  text,
  youtube_url  text,
  inks         text[],
  tags         text[],
  visibility   text,
  updated_at   timestamptz,
  share_token  text
)
language sql
security definer
set search_path = public
as $$
  select id, user_id, name, description, youtube_url, inks, tags, visibility, updated_at, share_token
    from public.decks
   where id = p_deck_id
     and share_token = p_token
     and visibility <> 'private';
$$;

revoke all on function public.get_shared_deck(uuid, text)     from public;
grant  execute on function public.get_shared_deck(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
