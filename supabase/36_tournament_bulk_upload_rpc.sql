-- 36_tournament_bulk_upload_rpc.sql — single-round-trip tournament upload.
--
-- Replaces the client-side loop that did 4 sequential round-trips per deck
-- (tournament, decks, deck_cards, tournament_decks) with one transactional
-- RPC. When Supabase is slow, latency stops compounding — a 60s-baseline
-- tournament upload that took 5+ minutes now takes ~60s.
--
-- Atomic: if any row fails, nothing persists. Admin-gated: only callers
-- in public.tournament_admins can execute it.
--
-- Input shape:
--   p_name       text          — tournament name (required)
--   p_event_date date          — optional
--   p_format     text          — 'core' | 'infinity' | null
--   p_rows       jsonb         — array of objects:
--     {
--       place: "1st" | "Top 8" | ...,
--       place_rank: 1 | 8 | ...,
--       player_name: text,
--       deck_name: text,
--       entries: [{ card_id: text, quantity: int }, ...]
--     }
--
-- Returns the new tournament_id.

create or replace function public.bulk_upload_tournament(
  p_name       text,
  p_event_date date,
  p_format     text,
  p_rows       jsonb
)
returns uuid
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  v_uid    uuid := auth.uid();
  v_tid    uuid;
  v_row    jsonb;
  v_did    uuid;
  v_entry  jsonb;
begin
  if v_uid is null then
    raise exception 'not authenticated';
  end if;
  if not public.is_tournament_admin(v_uid) then
    raise exception 'caller is not a tournament admin';
  end if;
  if p_name is null or btrim(p_name) = '' then
    raise exception 'tournament name is required';
  end if;

  set local statement_timeout = '2min';

  insert into public.tournaments (name, event_date, format, uploaded_by)
    values (btrim(p_name), p_event_date, p_format, v_uid)
    returning id into v_tid;

  for v_row in select * from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb))
  loop
    insert into public.decks (user_id, name, visibility)
      values (
        v_uid,
        coalesce(
          nullif(btrim(v_row->>'deck_name'), ''),
          nullif(btrim(v_row->>'player_name'), '') || '''s deck',
          'Untitled deck'
        ),
        'public'
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
        v_tid,
        v_did,
        nullif(btrim(v_row->>'place'), ''),
        nullif(v_row->>'place_rank', '')::int,
        nullif(btrim(v_row->>'player_name'), '')
      );
  end loop;

  return v_tid;
end;
$$;

revoke all on function public.bulk_upload_tournament(text, date, text, jsonb) from public;
grant execute on function public.bulk_upload_tournament(text, date, text, jsonb) to authenticated;

notify pgrst, 'reload schema';
