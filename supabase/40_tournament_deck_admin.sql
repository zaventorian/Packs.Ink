-- 40_tournament_deck_admin.sql — full deck-level admin ops for tournaments.
--
-- Previously the admin UI could only edit a tournament's headline (name /
-- date / format / num_players) and per-row meta (place / player / deck name);
-- the only way to rewrite the deck list itself was delete + re-upload. This
-- migration closes that gap with three new SECURITY DEFINER RPCs:
--
--   1. admin_replace_tournament_deck_cards(result_id, inks, cards jsonb)
--      Wipes and re-inserts deck_cards for a tournament's deck. Updates the
--      stored ink array on the deck row.
--   2. admin_add_tournament_deck(tournament_id, place, rank, player, deck_name,
--      inks, cards jsonb) returns result_id
--      Adds a brand-new deck (with cards) to an existing tournament — same
--      shape as one row inside the bulk-upload payload, just standalone.
--   3. admin_delete_tournament_deck(result_id)
--      Removes one row from a tournament. Drops the underlying decks entry
--      (cascade-deletes deck_cards + tournament_decks via FKs).
--
-- All gated on is_tournament_admin(auth.uid()). Same shape conventions as
-- migration 37 — cards jsonb is an array of {card_id, quantity} objects.

create or replace function public.admin_replace_tournament_deck_cards(
  p_result_id uuid,
  p_inks      text[],
  p_cards     jsonb
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_did uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  set local statement_timeout = '1min';

  select deck_id into v_did
    from public.tournament_decks
   where id = p_result_id;
  if v_did is null then
    raise exception 'tournament deck not found for result %', p_result_id;
  end if;

  delete from public.deck_cards where deck_id = v_did;

  if jsonb_typeof(p_cards) = 'array' then
    insert into public.deck_cards (deck_id, card_id, printing, quantity)
    select v_did,
           e->>'card_id',
           'Normal',
           least(99, greatest(1, (e->>'quantity')::int))
      from jsonb_array_elements(p_cards) e
     where e->>'card_id' is not null;
  end if;

  update public.decks
     set inks       = p_inks,
         updated_at = now()
   where id = v_did;
end;
$$;
revoke all on function public.admin_replace_tournament_deck_cards(uuid, text[], jsonb) from public;
grant  execute on function public.admin_replace_tournament_deck_cards(uuid, text[], jsonb) to authenticated;

-- Add a single new deck to an existing tournament. Mirrors the per-row
-- portion of bulk_upload_tournament — creates ownerless public decks +
-- deck_cards + tournament_decks. Returns the new result_id.
create or replace function public.admin_add_tournament_deck(
  p_tid         uuid,
  p_place       text,
  p_place_rank  integer,
  p_player_name text,
  p_deck_name   text,
  p_inks        text[],
  p_cards       jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_did uuid;
  v_rid uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  set local statement_timeout = '1min';

  if not exists (select 1 from public.tournaments where id = p_tid) then
    raise exception 'tournament % not found', p_tid;
  end if;

  insert into public.decks (user_id, name, visibility, inks)
    values (
      null,
      coalesce(nullif(btrim(p_deck_name), ''), 'Untitled deck'),
      'public',
      p_inks
    )
    returning id into v_did;

  if jsonb_typeof(p_cards) = 'array' then
    insert into public.deck_cards (deck_id, card_id, printing, quantity)
    select v_did,
           e->>'card_id',
           'Normal',
           least(99, greatest(1, (e->>'quantity')::int))
      from jsonb_array_elements(p_cards) e
     where e->>'card_id' is not null;
  end if;

  insert into public.tournament_decks
    (tournament_id, deck_id, place, place_rank, player_name)
    values (
      p_tid, v_did,
      nullif(btrim(p_place), ''),
      p_place_rank,
      nullif(btrim(p_player_name), '')
    )
    returning id into v_rid;

  return v_rid;
end;
$$;
revoke all on function public.admin_add_tournament_deck(uuid, text, integer, text, text, text[], jsonb) from public;
grant  execute on function public.admin_add_tournament_deck(uuid, text, integer, text, text, text[], jsonb) to authenticated;

-- Drop one result row + its underlying deck. Deck FK cascades remove the
-- linked deck_cards + tournament_decks rows.
create or replace function public.admin_delete_tournament_deck(p_result_id uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_did uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  select deck_id into v_did
    from public.tournament_decks
   where id = p_result_id;
  if v_did is null then
    raise exception 'tournament deck not found for result %', p_result_id;
  end if;

  -- Deleting the deck row cascades to deck_cards + tournament_decks (FK).
  delete from public.decks where id = v_did;
end;
$$;
revoke all on function public.admin_delete_tournament_deck(uuid) from public;
grant  execute on function public.admin_delete_tournament_deck(uuid) to authenticated;

notify pgrst, 'reload schema';
