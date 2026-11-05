-- 204: bulk_upload_tournament keeps the real copies of the two cards a deck may
-- hold more than 4 of.
--
-- It clamped every quantity to 4 (134), while the app's SPECIAL_DECK_LIMITS
-- (Index.html) allows Dalmatian Puppy - Tail Wagger 99 and Microbots any number
-- (99 in the UI). Whole RPH fields carry real decks built on that: two DLC Manila
-- lists are 60 Dalmatian Puppy, which the clamp would have stored as a 4-card
-- deck. Every other card stays capped at 4, as before. The modal already caps
-- per card in parseDeckText, so this only stops the server undoing that.
--
-- Body copied verbatim from the live function (134, via 116); the only edit is
-- the quantity cap in the deck_cards insert. admin_add_tournament_deck and
-- admin_replace_tournament_deck_cards still clamp to 4.
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
set statement_timeout = '2min'
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
             least(case when exists (select 1 from public.cards c
                                      where c.id = e->>'card_id'
                                        and c.name || coalesce(' - ' || nullif(c.version, ''), '')
                                            in ('Dalmatian Puppy - Tail Wagger', 'Microbots'))
                        then 99 else 4 end,
                   greatest(1, (e->>'quantity')::int))
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
