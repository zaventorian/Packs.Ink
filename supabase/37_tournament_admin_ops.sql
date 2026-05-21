-- 37_tournament_admin_ops.sql — tournament admin ops + ownerless decks.
--
-- Changes:
--   1. decks.user_id is now NULLABLE — tournament-uploaded decks have no
--      owner. This stops them from showing up in the uploader's "My Decks",
--      Following feed, etc. (those queries all filter by user_id).
--   2. tournaments.num_players column — total field size of the event,
--      surfaced on the tile + detail view.
--   3. bulk_upload_tournament gains p_num_players; writes user_id=null.
--   4. admin_delete_tournament(uuid) — wipes a tournament + its decks.
--   5. admin_update_tournament_meta(uuid, name, date, format, num_players)
--      — edits headline fields without rewriting decks.
--   6. admin_update_tournament_deck(uuid, place, place_rank, player_name,
--      deck_name) — edit one result row in place.
--   7. tournament_results_v rebuilt to include num_players.
--
-- All RPCs SECURITY DEFINER, gated on is_tournament_admin(auth.uid()).

alter table public.decks
  alter column user_id drop not null;

alter table public.tournaments
  add column if not exists num_players integer;

-- Rebuild the view so num_players is visible to the client without an
-- extra join.
drop view if exists public.tournament_results_v;
create view public.tournament_results_v
  with (security_invoker = on)
as
select td.id            as result_id,
       td.tournament_id,
       t.name           as tournament_name,
       t.event_date     as event_date,
       t.format         as tournament_format,
       t.num_players    as num_players,
       td.place,
       td.place_rank,
       td.player_name,
       td.inserted_at   as result_inserted_at,
       d.id             as deck_id,
       d.name           as deck_name,
       d.user_id        as deck_owner_id,
       d.visibility     as deck_visibility,
       d.inks           as deck_inks,
       d.share_token    as deck_share_token,
       d.updated_at     as deck_updated_at
  from public.tournament_decks td
  join public.tournaments t on t.id = td.tournament_id
  left join public.decks d on d.id = td.deck_id;

grant select on public.tournament_results_v to anon, authenticated;

-- Drop the previous bulk_upload signature so we can change the parameter list.
drop function if exists public.bulk_upload_tournament(text, date, text, jsonb);

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
        coalesce(nullif(btrim(v_row->>'deck_name'), ''), 'Untitled deck'),
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

-- Hard-delete a tournament and every deck linked to it. tournament_decks
-- rows cascade via the deck_id FK; the tournament row itself is removed last.
create or replace function public.admin_delete_tournament(p_tid uuid)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare v_uid uuid := auth.uid();
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;

  delete from public.decks
   where id in (
     select deck_id from public.tournament_decks
      where tournament_id = p_tid
        and deck_id is not null
   );
  delete from public.tournaments where id = p_tid;
end;
$$;
revoke all on function public.admin_delete_tournament(uuid) from public;
grant execute on function public.admin_delete_tournament(uuid) to authenticated;

-- Edit tournament headline fields without touching decks.
create or replace function public.admin_update_tournament_meta(
  p_tid uuid,
  p_name text,
  p_event_date date,
  p_format text,
  p_num_players integer
)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare v_uid uuid := auth.uid();
begin
  if v_uid is null or not public.is_tournament_admin(v_uid) then
    raise exception 'not authorized';
  end if;
  update public.tournaments
     set name        = coalesce(nullif(btrim(p_name), ''), name),
         event_date  = p_event_date,
         format      = p_format,
         num_players = p_num_players
   where id = p_tid;
end;
$$;
revoke all on function public.admin_update_tournament_meta(uuid, text, date, text, integer) from public;
grant execute on function public.admin_update_tournament_meta(uuid, text, date, text, integer) to authenticated;

-- Edit one result row's display fields (place, player name, deck name).
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
  if v_dkid is not null and p_deck_name is not null and btrim(p_deck_name) <> '' then
    update public.decks set name = btrim(p_deck_name) where id = v_dkid;
  end if;
end;
$$;
revoke all on function public.admin_update_tournament_deck(uuid, text, integer, text, text) from public;
grant execute on function public.admin_update_tournament_deck(uuid, text, integer, text, text) to authenticated;

notify pgrst, 'reload schema';
