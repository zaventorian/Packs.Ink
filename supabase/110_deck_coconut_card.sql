-- [Format Coconut] support: record which Coconut leader card a deck is built
-- around.
--
-- Core Constructed and Infinity are DERIVED formats — checkDeckLegality()
-- computes them from the cards alone (set pool, ink count, copy caps). Coconut
-- can't work that way: the format hinges on which Coconut card the builder
-- picked, and that choice is unrecoverable from the 60 cards. So it has to be
-- persisted per deck.
--
-- This column doubles as the format declaration: coconut_card IS NOT NULL
-- means the deck is a Coconut deck. A separate `format` column would be
-- redundant and could drift out of sync with the leader.
--
-- Values are stable slugs of the Coconut card ("nick-wilde-wily-fox"), matching
-- the COCONUT_CARDS const in Index.html. Deliberately slugs rather than the
-- beta collector numbers, which can shift as Ravensburger adds and removes
-- cards during the open beta.
--
-- The CHECK only validates slug SHAPE, not membership. Ravensburger is posting
-- new Coconut cards weekly during the beta; an enum or a value-list constraint
-- would need a migration every time one lands.

alter table public.decks
  add column if not exists coconut_card text;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'decks_coconut_card_slug_chk'
  ) then
    alter table public.decks
      add constraint decks_coconut_card_slug_chk
      check (coconut_card is null or coconut_card ~ '^[a-z0-9][a-z0-9-]{0,63}$');
  end if;
end $$;

-- Partial index — Coconut decks are a small slice of the table, and the only
-- queries that filter on this want "the Coconut ones".
create index if not exists decks_coconut_card_idx
  on public.decks (coconut_card)
  where coconut_card is not null;

-- Shared/unlisted deck viewers need the leader too, or a shared Coconut deck
-- renders as a malformed 1-of pile with no leader and a bogus format label.
-- PostgREST only surfaces columns named in RETURNS TABLE, and Postgres rejects
-- CREATE OR REPLACE when that clause changes (42P13), so drop first.
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
  share_token  text,
  coconut_card text
)
language sql
security definer
set search_path = public
as $$
  select id, user_id, name, description, youtube_url, inks, tags, visibility,
         updated_at, share_token, coconut_card
    from public.decks
   where id = p_deck_id
     and share_token = p_token
     and visibility <> 'private';
$$;

revoke all on function public.get_shared_deck(uuid, text)     from public;
grant  execute on function public.get_shared_deck(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
