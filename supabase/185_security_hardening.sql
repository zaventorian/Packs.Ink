-- Migration 185: security hardening from the 2026-10-06 database review.
--
-- Applied 2026-10-06 through the connector. Independent of the client.
--
-- 1. bump_tier_list_view (184) wrote its per-viewer mark BEFORE checking the
--    list exists, so a loop over random slugs added a row per request for
--    anon (swept after two days, but unbounded meanwhile). It now returns
--    first for a slug that isn't an openable list.
-- 2. scout_event_meta(bigint) was executable by every signed-in user and
--    answers "did the team add this event, who, when" plus a note's stored
--    label for events that have aged out of every public feed. Its callers
--    are four SECURITY DEFINER functions (they run as the owner) and the
--    refresh-elo-rosters edge function's SERVICE client, so no caller needs
--    the grant.
-- 3. scan-samples: 2 MB per object let one account park ~6 GB a day under
--    the 3000-object cap. Real objects (3,546 checked): max 506 KB, p99 451
--    KB; the client sends JPEG q0.85 at <= 1000px. 1 MB keeps 2x headroom;
--    a rare oversized sample is a lost training photo (uploadSample
--    swallows it), never a lost save.
-- 4. anon / authenticated held TRUNCATE, REFERENCES, TRIGGER and MAINTAIN on
--    81 public relations, and postgres's default privileges hand them out on
--    every new table. PostgREST cannot issue any of them today, but TRUNCATE
--    bypasses RLS, so this closes the door before anything could open it.
--    (Tables created by supabase_admin keep that role's own defaults; they
--    are not ours to alter.)
--
-- Idempotent.

-- 1 ───────────────────────────────────────────────────────────────────────────
create or replace function public.bump_tier_list_view(p_slug text)
returns void language plpgsql volatile security definer
set search_path = public, extensions as $$
declare
  v_uid    uuid := (select auth.uid());
  v_viewer text;
  v_new    int;
begin
  if p_slug is null or p_slug !~ '^[A-Za-z0-9]{8,16}$' then
    return;
  end if;
  if not exists (select 1 from public.custom_tier_lists
                 where slug = p_slug and visibility <> 'private'
                   and user_id is distinct from v_uid) then
    return;
  end if;
  v_viewer := coalesce('u:' || v_uid::text,
    'ip:' || encode(digest('packsink-tierview|' || coalesce(nullif(public._client_ip(), ''), 'unknown'), 'sha256'), 'hex'));
  delete from public.custom_tier_list_view_marks where day < current_date - 1;
  insert into public.custom_tier_list_view_marks (slug, viewer)
  values (p_slug, v_viewer)
  on conflict do nothing;
  get diagnostics v_new = row_count;
  if v_new = 0 then
    return;
  end if;
  update public.custom_tier_lists
     set view_count = view_count + 1
   where slug = p_slug;
end $$;
revoke execute on function public.bump_tier_list_view(text) from public;
grant execute on function public.bump_tier_list_view(text) to anon, authenticated, service_role;

-- 2 ───────────────────────────────────────────────────────────────────────────
revoke execute on function public.scout_event_meta(bigint) from public, anon, authenticated;
grant execute on function public.scout_event_meta(bigint) to service_role;

-- 3 ───────────────────────────────────────────────────────────────────────────
update storage.buckets set file_size_limit = 1048576 where id = 'scan-samples';

-- 4 ───────────────────────────────────────────────────────────────────────────
revoke truncate, references, trigger, maintain on all tables in schema public from anon, authenticated;
alter default privileges for role postgres in schema public
  revoke truncate, references, trigger, maintain on tables from anon, authenticated;

notify pgrst, 'reload schema';
