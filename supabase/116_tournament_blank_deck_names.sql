-- 116_tournament_blank_deck_names.sql — let a tournament deck have no name.
--
-- Until now a blank "Deck name" field could never survive a save:
--
--   * The CLIENT replaced blank with a generated string before it ever hit an
--     RPC — inks.join("/") ("Amber/Emerald"), else "<Player>'s deck", else
--     "Untitled deck". That generated value was then persisted verbatim, which
--     is why reopening the edit modal showed it pre-filled.
--   * admin_update_tournament_deck additionally REFUSED to write a blank name
--     (`btrim(p_deck_name) <> ''`), so even a client that sent one got a no-op
--     and the old name stayed.
--
-- Both halves are fixed: the client now sends NULL (see Index.html), and these
-- three RPCs store NULL instead of inventing a placeholder.
--
-- Behaviour change worth knowing: admin_update_tournament_deck now ALWAYS
-- writes p_deck_name. Passing NULL used to mean "leave the name alone"; it now
-- means "clear the name". Both call sites always send the field explicitly, so
-- nothing in the app relied on the old skip-on-null semantics.
--
-- Note: decks.name is encrypted at rest for USER decks (see the "e1:" prefix
-- in Index.html). Tournament decks are ownerless and stored plaintext, which is
-- what makes the companion cleanup migration's pattern matching possible.

-- Tournament decks are allowed to be nameless. User-deck creation and rename
-- both reject blank input client-side, so this only widens what tournament
-- uploads can store.
alter table public.decks
  alter column name drop not null;

-- Body copied from migration 37 (the newest to touch it — 36's four-arg
-- signature was dropped there) with the deck-name coalesce removed.
create or replace function public.bulk_upload_tournament(
  p_name        text,
  p_event_date  date,
  p_format      text,
  p_num_players integer,
  p_rows        jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_uid   uuid := auth.uid();
  v_tid   uuid;
  v_row   jsonb;
  v_did   uuid;
begin
  if v_uid is null then raise exception 'not authenticated'; end if;
  if not public.is_tournament_admin(v_uid) then
    raise exception 'caller is not a tournament admin';
  end if;
  if p_name is null or btrim(p_name) = '' then
    raise exception 'tournament name is required';
  end if;

  set local statement_timeout = '2min';

  insert into public.tournaments (name, event_date, format, num_players, uploaded_by)
    values (btrim(p_name), p_event_date, p_format, p_num_players, v_uid)
    returning id into v_tid;

  for v_row in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb))
  loop
    insert into public.decks (user_id, name, visibility, inks)
      values (
        null,
        nullif(btrim(v_row->>'deck_name'), ''),
        'public',
        case when jsonb_typeof(v_row->'inks') = 'array'
             then (select array_agg(value) from jsonb_array_elements_text(v_row->'inks'))
             else null end
      )
      returning id into v_did;

    if jsonb_typeof(v_row->'entries') = 'array' then
      insert into public.deck_cards (deck_id, card_id, printing, quantity)
      select v_did,
             e->>'card_id',
             'Normal',
             least(4, greatest(1, (e->>'quantity')::int))
        from jsonb_array_elements(v_row->'entries') e
       where e->>'card_id' is not null;
    end if;

    insert into public.tournament_decks
      (tournament_id, deck_id, place, place_rank, player_name)
      values (
        v_tid, v_did,
        nullif(btrim(v_row->>'place'), ''),
        nullif(v_row->>'place_rank', '')::int,
        nullif(btrim(v_row->>'player_name'), '')
      );
  end loop;

  return v_tid;
end;
$$;

revoke all on function public.bulk_upload_tournament(text, date, text, integer, jsonb) from public;
grant execute on function public.bulk_upload_tournament(text, date, text, integer, jsonb) to authenticated;

-- Body copied from migration 40 with the deck-name coalesce removed.
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
      nullif(btrim(p_deck_name), ''),
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

-- Body copied from migration 37. The `p_deck_name is not null and btrim(...)
-- <> ''` guard is gone — a blank or NULL name now clears the stored name
-- instead of silently keeping the old one.
create or replace function public.admin_update_tournament_deck(
  p_result_id uuid,
  p_place text,
  p_place_rank integer,
  p_player_name text,
  p_deck_name text
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_uid    uuid := auth.uid();
  v_dkid   uuid;
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;
  update public.tournament_decks
     set place       = nullif(btrim(p_place), ''),
         place_rank  = p_place_rank,
         player_name = nullif(btrim(p_player_name), '')
   where id = p_result_id
   returning deck_id into v_dkid;
  if v_dkid is not null then
    update public.decks
       set name = nullif(btrim(p_deck_name), '')
     where id = v_dkid;
  end if;
end;
$$;
revoke all on function public.admin_update_tournament_deck(uuid, text, integer, text, text) from public;
grant execute on function public.admin_update_tournament_deck(uuid, text, integer, text, text) to authenticated;

notify pgrst, 'reload schema';
