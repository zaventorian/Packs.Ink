-- 205: admin_import_tournament works with more than one tournament admin.
--
-- 202 picked the uploader with `select user_id into strict ... from
-- tournament_admins`, which raises too_many_rows the day a second admin is
-- granted, so every `upload_tournament.py --commit` would fail. It now takes the
-- earliest-granted admin and still refuses when there is none. Same signature,
-- so the grants, SECURITY DEFINER and settings carry over.
--
-- Body as in 202 apart from that lookup.
--
-- Correction to 204's header: admin_add_tournament_deck and
-- admin_replace_tournament_deck_cards do NOT clamp to 4. They have capped at 99
-- since 40 (live, checked 2026-11-05).
create or replace function public.admin_import_tournament(p_event jsonb, p_commit boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public
set statement_timeout = '5min'
as $$
declare
  v_name     text := btrim(coalesce(p_event->>'name', ''));
  v_date     date := nullif(btrim(p_event->>'event_date'), '')::date;
  v_format   text := lower(nullif(btrim(p_event->>'format'), ''));
  v_players  int  := nullif(btrim(p_event->>'num_players'), '')::int;
  v_admin    uuid;
  v_dup      uuid;
  v_problems text[] := '{}';
  v_rows     jsonb := '[]';
  v_report   jsonb := '[]';
  v_all      jsonb;
  v_tid      uuid;
  r          jsonb;
  res        jsonb;
  v_place    text;
  v_key      text;
  v_rank     int;
  i          int := 0;
begin
  if v_name = '' then raise exception 'name is required'; end if;
  if v_date is null then v_problems := v_problems || 'event_date is missing'; end if;
  if v_format is null or v_format not in ('core', 'infinity') then
    v_problems := v_problems || ('format must be core or infinity, got ' || coalesce(v_format, 'nothing'));
  end if;

  select id into v_dup from public.tournaments
   where lower(btrim(name)) = lower(v_name) and event_date is not distinct from v_date limit 1;
  if v_dup is not null then
    v_problems := v_problems || ('already uploaded as tournament ' || v_dup);
  end if;

  v_all := public.import_resolve_decklists(array(
    select e->>'decklist' from jsonb_array_elements(coalesce(p_event->'rows', '[]'::jsonb)) with ordinality as t(e, ord)
     order by ord));

  for r in select e from jsonb_array_elements(coalesce(p_event->'rows', '[]'::jsonb)) with ordinality as t(e, ord) order by ord loop
    i := i + 1;
    res := v_all -> (i - 1);
    v_place := nullif(btrim(r->>'place'), '');
    -- parsePlaceRank in Index.html: 1st/2nd/3rd, "Top 8", "T16", "5th".
    v_key := regexp_replace(lower(coalesce(v_place, '')), '[^a-z0-9]', '', 'g');
    v_rank := case v_key when '1st' then 1 when '1' then 1 when '2nd' then 2 when '2' then 2
                         when '3rd' then 3 when '3' then 3
                         else (regexp_match(v_key, '^(?:top|t)?(\d{1,4})(?:th|st|nd|rd)?$'))[1]::int end;
    if v_rank is null then
      v_problems := v_problems || format('row %s: unreadable place %L', i, v_place);
    end if;
    if jsonb_array_length(res->'unmatched') > 0 then
      v_problems := v_problems || format('row %s: unmatched %s', i, res->'unmatched');
    end if;
    if (res->>'total')::int = 0 then
      v_problems := v_problems || format('row %s: empty decklist', i);
    end if;
    v_rows := v_rows || jsonb_build_object(
      'place', v_place, 'place_rank', v_rank,
      'player_name', nullif(btrim(r->>'player_name'), ''),
      'deck_name', nullif(btrim(r->>'deck_name'), ''),
      'entries', res->'entries', 'inks', res->'inks');
    v_report := v_report || jsonb_build_object(
      'row', i, 'place', v_place, 'player', r->>'player_name',
      'total', res->'total', 'lines', res->'lines', 'cards', jsonb_array_length(res->'entries'),
      'inks', res->'inks', 'unmatched', res->'unmatched', 'over_cap', res->'over_cap');
  end loop;
  if i = 0 then v_problems := v_problems || 'no rows'::text; end if;

  if p_commit then
    if cardinality(v_problems) > 0 then
      raise exception 'not uploaded: %', array_to_string(v_problems, '; ');
    end if;
    -- The earliest-granted admin, so a second admin doesn't break the import
    -- (`into strict` raised too_many_rows on more than one row).
    select user_id into v_admin from public.tournament_admins order by granted_at, user_id limit 1;
    if v_admin is null then raise exception 'no tournament admin to upload as'; end if;
    -- bulk_upload_tournament checks auth.uid(), which reads this setting. Local to
    -- the transaction, and cleared again straight after.
    perform set_config('request.jwt.claim.sub', v_admin::text, true);
    v_tid := public.bulk_upload_tournament(v_name, v_date, v_format, v_players, v_rows);
    perform set_config('request.jwt.claim.sub', '', true);
  end if;

  return jsonb_build_object(
    'committed', v_tid is not null, 'tournament_id', v_tid,
    'name', v_name, 'event_date', v_date, 'format', v_format, 'num_players', v_players,
    'problems', to_jsonb(v_problems), 'rows', v_report);
end;
$$;

revoke all on function public.admin_import_tournament(jsonb, boolean) from public, anon, authenticated;
grant execute on function public.admin_import_tournament(jsonb, boolean) to service_role;
