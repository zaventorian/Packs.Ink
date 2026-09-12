-- 143_scout_team.sql — the scouting feature becomes a TEAM tool.
--
-- Three things, all of them about the same question: "who is in this room, what
-- are they playing, and what did they play last time?"
--
--   1. scout_members  — an EMAIL allowlist. Until now every scouting surface was
--      gated on can_view_store_report() (tournament admin OR elo_report_viewers,
--      keyed on user_id). A user_id can only be added AFTER someone has signed in
--      at least once and you've gone and looked it up, which makes onboarding a
--      teammate a two-step chore. An email can be added before they have ever
--      opened the site. can_view_store_report() is deliberately LEFT ALONE — the
--      store report keeps its own gate; this one covers the scout surfaces only.
--
--   2. scout_notes    — two open text fields (deck, notes) per PLAYER per EVENT,
--      shared across the whole team. One row per (event_id, player_key): a deck
--      is a fact about the table, not an opinion, so a second scout amending the
--      first is the behaviour we want. updated_by_name + updated_at are stored so
--      it stays attributable rather than anonymous.
--
--      ⚠ The event label (name / date / store) is DENORMALISED onto the note.
--      lorcana_events is an upcoming-events feed that PRUNES what has already
--      happened (see 121), and the archive does not reach back before it landed.
--      The whole point of a note is that you read it next month, so the log has
--      to survive its event row disappearing. Never "normalise" these away.
--
--   3. player_key     — how one person is recognised across events. RPH's user id
--      when the registration carried one, else the lowercased display name. The
--      id is the real key; the name fallback exists because a guest plays without
--      an account, and a nameless note is worse than a fuzzy one.
--
-- Scope: TRACKED STORES ONLY (elo_tracked_stores) — the same universe the Elo
-- board covers. Every read and write below checks it, so a scout member cannot
-- start logging notes on a shop in another state by pasting an event id.
--
-- Also here: elo_event_roster loses its FK to set_championships. That table only
-- holds Set Championships, but a tracked store's league nights are full of the
-- same people, and the calendar surfaces them. The roster tables are keyed on a
-- bare RPH event id either way.
--
-- Idempotent; safe to re-run.

-- ── 1. Membership ──────────────────────────────────────────────────────────
-- Either half identifies a person: email for someone who has never signed in,
-- user_id as the fallback when a provider does not put email in the JWT.
create table if not exists public.scout_members (
  id       uuid primary key default gen_random_uuid(),
  email    text unique,
  user_id  uuid unique,
  note     text,
  added_at timestamptz not null default now(),
  constraint scout_members_who check (email is not null or user_id is not null)
);
alter table public.scout_members enable row level security;  -- definer-only

-- Lowercase every email on the way in so the lookup below can be an equality
-- test rather than a scan.
create or replace function public.scout_members_lower_email()
returns trigger language plpgsql set search_path = public, extensions as $$
begin
  new.email := nullif(lower(btrim(new.email)), '');
  return new;
end;
$$;
drop trigger if exists scout_members_lower_email_trg on public.scout_members;
create trigger scout_members_lower_email_trg
  before insert or update on public.scout_members
  for each row execute function public.scout_members_lower_email();

-- The gate. Admins always pass. Everyone else is on the list by email (the
-- normal path) or by user_id (the escape hatch).
create or replace function public.can_scout()
returns boolean
language sql security definer set search_path = public, extensions stable
as $$
  select coalesce(public.is_tournament_admin((select auth.uid())), false)
      or exists (
           select 1 from public.scout_members m
            where (m.user_id is not null and m.user_id = (select auth.uid()))
               or (m.email  is not null
                   and m.email = lower(btrim(coalesce((select auth.jwt()) ->> 'email', ''))))
         );
$$;
revoke all on function public.can_scout() from public, anon;
grant execute on function public.can_scout() to authenticated;

-- ── 2. Player identity ─────────────────────────────────────────────────────
create or replace function public.scout_player_key(p_rph_user_id bigint, p_identifier text)
returns text language sql immutable set search_path = public, extensions
as $$
  select case
    when p_rph_user_id is not null then 'rph:' || p_rph_user_id::text
    else 'name:' || lower(btrim(coalesce(p_identifier, '')))
  end;
$$;
revoke all on function public.scout_player_key(bigint, text) from public, anon;
grant execute on function public.scout_player_key(bigint, text) to authenticated;

-- ── 3. The notes ───────────────────────────────────────────────────────────
create table if not exists public.scout_notes (
  id              uuid primary key default gen_random_uuid(),
  event_id        bigint not null,
  player_key      text   not null,
  player_name     text   not null,
  rph_user_id     bigint,
  deck            text,
  notes           text,
  -- denormalised on purpose — see the header.
  event_name      text,
  event_date      timestamptz,
  event_tz        text,     -- the event's own timezone: a 7pm Friday in Elgin is
                            -- Friday for whoever was in the room, and the log has
                            -- to say the day they were actually there.
  store_name      text,
  created_by      uuid not null,
  created_at      timestamptz not null default now(),
  updated_by      uuid not null,
  updated_by_name text,
  updated_at      timestamptz not null default now(),
  constraint scout_notes_one_per_player unique (event_id, player_key)
);
alter table public.scout_notes enable row level security;  -- definer-only
create index if not exists scout_notes_player_idx on public.scout_notes (player_key, event_date desc nulls last);
create index if not exists scout_notes_event_idx  on public.scout_notes (event_id);

grant select, insert, update, delete on public.scout_notes   to service_role;
grant select, insert, update, delete on public.scout_members to service_role;

-- ── 4. Roster tables: any tracked-store event, not just Set Championships ───
-- The FK pinned rosters to set_championships. League nights at the same stores
-- are the same people; the calendar already shows them.
alter table public.elo_event_roster drop constraint if exists elo_event_roster_event_id_fkey;

-- ── 5. Event resolution ────────────────────────────────────────────────────
-- One event id, wherever it currently lives: the upcoming feed, the SC table, or
-- the archive. `tracked` is the scope test every caller below leans on.
create or replace function public.scout_event_meta(p_event_id bigint)
returns table (
  event_id bigint, name text, store_id bigint, store_name text,
  start_datetime timestamptz, timezone text, city text, state text,
  capacity int, kind text, set_name text, tracked boolean
)
language sql security definer set search_path = public, extensions stable
as $$
  with src as (
    select e.event_id, e.name, e.store_id, e.store_name, e.start_datetime, e.timezone,
           e.city, e.state, e.capacity, e.kind, e.set_name, 1 as pref
      from public.lorcana_events e where e.event_id = p_event_id
    union all
    select h.event_id, h.name, h.store_id, h.store_name, h.start_datetime, h.timezone,
           h.city, h.state, h.capacity, h.kind, h.set_name, 2
      from public.lorcana_events_history h where h.event_id = p_event_id
    union all
    select s.event_id, s.name, s.store_id, s.store_name, s.start_datetime, s.timezone,
           s.city, s.state, s.capacity, 'sc', s.set_name, 3
      from public.set_championships s where s.event_id = p_event_id
  )
  select s.event_id, s.name, s.store_id, s.store_name, s.start_datetime, s.timezone,
         s.city, s.state, s.capacity, s.kind, s.set_name,
         exists (select 1 from public.elo_tracked_stores t where t.store_id = s.store_id)
    from src s order by s.pref limit 1;
$$;
revoke all on function public.scout_event_meta(bigint) from public, anon;
grant execute on function public.scout_event_meta(bigint) to authenticated;
-- ⚠ service_role too: the refresh-elo-rosters edge function resolves a single
-- event through this with its SERVICE key, and service_role does NOT inherit the
-- `authenticated` grant. Without this the per-event roster refresh fails with
-- "permission denied for function scout_event_meta" — the same class of trap as
-- the matview grants in migration 45. Every other function here is called only
-- from a user session, which is why this is the only extra grant.
grant execute on function public.scout_event_meta(bigint) to service_role;

-- ── 6. The one read the scout panel makes ──────────────────────────────────
-- Event header + field strength + every signed-up player, each carrying their
-- note FOR THIS EVENT and how many notes the team already holds on them. That
-- last count is what turns a roster into a scouting sheet: it is the "you have
-- seen this person before" flag, and it costs one extra aggregate.
create or replace function public.get_scout_event(p_event_id bigint)
returns jsonb
language plpgsql security definer set search_path = public, extensions stable
as $$
declare
  v_meta    record;
  v_event   jsonb;
  v_field   jsonb;
  v_players jsonb;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;

  select * into v_meta from public.scout_event_meta(p_event_id);
  if v_meta.event_id is null then
    return jsonb_build_object('scoutable', false, 'reason', 'unknown_event',
                              'event', jsonb_build_object('event_id', p_event_id));
  end if;
  if not v_meta.tracked then
    return jsonb_build_object('scoutable', false, 'reason', 'untracked_store',
      'event', jsonb_build_object('event_id', v_meta.event_id, 'name', v_meta.name,
                                  'store_name', v_meta.store_name));
  end if;

  with mem as (
    select m.best_identifier, m.account_name, m.rph_user_id,
           public.scout_player_key(m.rph_user_id, m.best_identifier) as player_key
      from public.elo_event_roster_members m
     where m.event_id = p_event_id
  ),
  resolved as (
    select mb.*, lb.player_id, lb.current_rating, lb.rank, lb.wins, lb.losses,
           (lb.player_id is not null) as matched
      from mem mb
      left join public.elo_players p
             on p.platform = 'rph' and lower(p.display_name) = lower(mb.best_identifier)
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
  ),
  hist as (
    select n.player_key, count(*) as n_notes
      from public.scout_notes n
     where n.player_key in (select player_key from mem) and n.event_id <> p_event_id
     group by n.player_key
  )
  select
    coalesce(jsonb_agg(jsonb_build_object(
      'best_identifier', r.best_identifier,
      'account_name',    r.account_name,
      'rph_user_id',     r.rph_user_id,
      'player_key',      r.player_key,
      'player_id',       r.player_id,
      'current_rating',  r.current_rating,
      'rank',            r.rank,
      'wins',            r.wins,
      'losses',          r.losses,
      'matched',         r.matched,
      'deck',            sn.deck,
      'notes',           sn.notes,
      'note_by',         sn.updated_by_name,
      'note_at',         sn.updated_at,
      'prior_notes',     coalesce(h.n_notes, 0)
    ) order by r.current_rating desc nulls last, r.best_identifier asc), '[]'::jsonb),
    jsonb_build_object(
      'n_signed_up', count(*),
      'n_rated',     count(*) filter (where r.matched),
      'n_unrated',   count(*) filter (where not r.matched),
      'n_logged',    count(*) filter (where sn.id is not null),
      'avg_elo',     round(avg(r.current_rating) filter (where r.matched)::numeric, 0),
      'top_elo',     round(max(r.current_rating) filter (where r.matched)::numeric, 0)
    )
  into v_players, v_field
  from resolved r
  left join public.scout_notes sn
         on sn.event_id = p_event_id and sn.player_key = r.player_key
  left join hist h on h.player_key = r.player_key;

  -- Roster header carries the scrape metadata; it is absent until the first
  -- refresh, which is exactly the state the panel's "never pulled" copy covers.
  select jsonb_build_object(
    'event_id',       v_meta.event_id,
    'name',           v_meta.name,
    'store_name',     v_meta.store_name,
    'store_id',       v_meta.store_id,
    'city',           v_meta.city,
    'state',          v_meta.state,
    'set_name',       v_meta.set_name,
    'kind',           v_meta.kind,
    'capacity',       coalesce(r.capacity, v_meta.capacity),
    'start_datetime', v_meta.start_datetime,
    'timezone',       v_meta.timezone,
    'scraped_at',     r.scraped_at,
    'registered_count', r.registered_count
  ) into v_event
  from (select p_event_id as eid) base
  left join public.elo_event_roster r on r.event_id = base.eid;

  return jsonb_build_object(
    'scoutable', true,
    'event',   coalesce(v_event, jsonb_build_object('event_id', p_event_id)),
    'field',   coalesce(v_field, jsonb_build_object('n_signed_up', 0, 'n_rated', 0,
                 'n_unrated', 0, 'n_logged', 0, 'avg_elo', null, 'top_elo', null)),
    'players', coalesce(v_players, '[]'::jsonb)
  );
end;
$$;
revoke all on function public.get_scout_event(bigint) from public, anon;
grant execute on function public.get_scout_event(bigint) to authenticated;

-- ── 7. Write one note ──────────────────────────────────────────────────────
-- Both fields empty DELETES the row rather than storing a pair of blanks: an
-- empty note would still count toward "you have seen this player before", which
-- is the one thing the count must not lie about.
create or replace function public.save_scout_note(
  p_event_id    bigint,
  p_player_name text,
  p_rph_user_id bigint  default null,
  p_deck        text    default null,
  p_notes       text    default null
)
returns jsonb
language plpgsql security definer set search_path = public, extensions volatile
as $$
declare
  v_meta   record;
  v_key    text;
  v_deck   text := nullif(btrim(coalesce(p_deck, '')), '');
  v_note   text := nullif(btrim(coalesce(p_notes, '')), '');
  v_name   text;
  v_author text;
  v_row    public.scout_notes;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;
  if nullif(btrim(coalesce(p_player_name, '')), '') is null and p_rph_user_id is null then
    raise exception 'a player is required';
  end if;

  select * into v_meta from public.scout_event_meta(p_event_id);
  if v_meta.event_id is null or not v_meta.tracked then
    raise exception 'event % is not one we scout', p_event_id;
  end if;

  -- Caps: these are hand-typed team notes, not a document store.
  if length(coalesce(v_deck, '')) > 400  then raise exception 'deck is too long (400 max)';  end if;
  if length(coalesce(v_note, '')) > 4000 then raise exception 'notes are too long (4000 max)'; end if;

  v_key  := public.scout_player_key(p_rph_user_id, p_player_name);
  v_name := coalesce(nullif(btrim(p_player_name), ''), v_key);

  if v_deck is null and v_note is null then
    delete from public.scout_notes where event_id = p_event_id and player_key = v_key;
    return null;
  end if;

  -- Display name of whoever is writing, for attribution in the UI.
  select nullif(btrim(pr.display_name), '')
    into v_author from public.profiles pr where pr.user_id = (select auth.uid());
  v_author := coalesce(v_author, 'A teammate');

  insert into public.scout_notes as n (
    event_id, player_key, player_name, rph_user_id, deck, notes,
    event_name, event_date, event_tz, store_name,
    created_by, updated_by, updated_by_name)
  values (
    p_event_id, v_key, v_name, p_rph_user_id, v_deck, v_note,
    v_meta.name, v_meta.start_datetime, v_meta.timezone, v_meta.store_name,
    (select auth.uid()), (select auth.uid()), v_author)
  on conflict (event_id, player_key) do update
     set deck            = excluded.deck,
         notes           = excluded.notes,
         player_name     = excluded.player_name,
         rph_user_id     = coalesce(excluded.rph_user_id, n.rph_user_id),
         event_name      = excluded.event_name,
         event_date      = excluded.event_date,
         event_tz        = excluded.event_tz,
         store_name      = excluded.store_name,
         updated_by      = excluded.updated_by,
         updated_by_name = excluded.updated_by_name,
         updated_at      = now()
  returning * into v_row;

  return jsonb_build_object(
    'player_key', v_row.player_key, 'deck', v_row.deck, 'notes', v_row.notes,
    'note_by', v_row.updated_by_name, 'note_at', v_row.updated_at);
end;
$$;
revoke all on function public.save_scout_note(bigint, text, bigint, text, text) from public, anon;
grant execute on function public.save_scout_note(bigint, text, bigint, text, text) to authenticated;

-- ── 8. One player's whole log ──────────────────────────────────────────────
-- Newest first. Reads only the note rows, so it answers even for an event that
-- has since been pruned out of the feed.
create or replace function public.get_scout_player(p_player_key text)
returns jsonb
language plpgsql security definer set search_path = public, extensions stable
as $$
declare v_rows jsonb;
begin
  if not public.can_scout() then
    raise exception 'not authorized';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
           'event_id',   n.event_id,
           'event_name', n.event_name,
           'event_date', n.event_date,
           'event_tz',   n.event_tz,
           'store_name', n.store_name,
           'player_name', n.player_name,
           'deck',       n.deck,
           'notes',      n.notes,
           'note_by',    n.updated_by_name,
           'note_at',    n.updated_at
         ) order by n.event_date desc nulls last, n.updated_at desc), '[]'::jsonb)
    into v_rows
    from public.scout_notes n
   where n.player_key = p_player_key;
  return coalesce(v_rows, '[]'::jsonb);
end;
$$;
revoke all on function public.get_scout_player(text) from public, anon;
grant execute on function public.get_scout_player(text) to authenticated;

-- ── 9. The Scout tab's slate, widened ──────────────────────────────────────
-- 89's version INNER JOINed elo_event_roster, so an event whose roster had never
-- been pulled did not appear at all — and the panel's Refresh button is the only
-- way to pull one. You could not reach the control that would have made the
-- event visible. LEFT JOIN, and the scout gate alongside the report gate.
-- Body is 89's, unchanged apart from those two lines.
create or replace function public.get_roster_scout(p_exclude_org boolean default false)
returns jsonb
language plpgsql stable security definer
set search_path to 'public', 'extensions'
as $$
declare
  v_org_names constant text[] := array['I&L⟡Zaven', 'I&L⟡jacobayy'];
  v_result jsonb;
begin
  if not (public.can_view_store_report() or public.can_scout()) then
    raise exception 'not authorized';
  end if;

  with ev as (
    select sc.event_id, sc.name, sc.store_name, sc.city, sc.state,
           sc.start_datetime, sc.set_name, sc.timezone,
           coalesce(r.capacity, sc.capacity)                  as capacity,
           coalesce(r.registered_count, sc.registered_user_count) as registered_count,
           r.scraped_at
      from public.set_championships sc
      join public.elo_tracked_stores t on t.store_id = sc.store_id
      left join public.elo_event_roster r on r.event_id = sc.event_id
     where sc.start_datetime >= now()
  ),
  mem as (
    select m.event_id, m.best_identifier, m.account_name,
           lb.player_id, lb.current_rating, lb.rank, lb.wins, lb.losses,
           (lb.player_id is not null) as matched,
           lb.display_name as canonical_name
      from public.elo_event_roster_members m
      join ev on ev.event_id = m.event_id
      left join public.elo_players p
             on p.platform = 'rph' and lower(p.display_name) = lower(m.best_identifier)
      left join public.elo_leaderboard_v lb
             on lb.player_id = coalesce(p.merged_into_id, p.player_id)
     where not (p_exclude_org and coalesce(lb.display_name = any(v_org_names), false))
  ),
  per_event as (
    select e.event_id, e.start_datetime,
      jsonb_build_object(
        'event_id',        e.event_id,
        'name',            e.name,
        'store_name',      e.store_name,
        'city',            e.city,
        'state',           e.state,
        'set_name',        e.set_name,
        'start_datetime',  e.start_datetime,
        'timezone',        e.timezone,
        'capacity',        e.capacity,
        'registered_count',e.registered_count,
        'scraped_at',      e.scraped_at,
        'field', jsonb_build_object(
          'n_signed_up', count(mm.best_identifier),
          'n_rated',     count(*) filter (where mm.matched),
          'avg_elo',     round(avg(mm.current_rating) filter (where mm.matched)::numeric, 0),
          'top_elo',     round(max(mm.current_rating) filter (where mm.matched)::numeric, 0)
        ),
        'players', coalesce(jsonb_agg(
          jsonb_build_object(
            'best_identifier', mm.best_identifier,
            'account_name',    mm.account_name,
            'player_id',       mm.player_id,
            'current_rating',  mm.current_rating,
            'rank',            mm.rank,
            'wins',            mm.wins,
            'losses',          mm.losses,
            'matched',         mm.matched
          )
          order by mm.current_rating desc nulls last, mm.best_identifier asc
        ) filter (where mm.best_identifier is not null), '[]'::jsonb)
      ) as ev_json
    from ev e
    left join mem mm on mm.event_id = e.event_id
    group by e.event_id, e.name, e.store_name, e.city, e.state, e.set_name,
             e.start_datetime, e.timezone, e.capacity, e.registered_count, e.scraped_at
  )
  select coalesce(jsonb_agg(ev_json order by start_datetime asc), '[]'::jsonb)
    into v_result
    from per_event;

  return coalesce(v_result, '[]'::jsonb);
end;
$$;
revoke all on function public.get_roster_scout(boolean) from public, anon;
grant execute on function public.get_roster_scout(boolean) to authenticated;

-- get_event_roster (68) is deliberately LEFT ALONE — it is the plain roster a
-- store-report viewer sees, and scouts have get_scout_event instead.

-- ── 10. Managing the team (admin only) ─────────────────────────────────────
-- Self-serve so adding a teammate is a text field, not a SQL paste.
create or replace function public.scout_members_list()
returns jsonb
language plpgsql security definer set search_path = public, extensions stable
as $$
declare v jsonb;
begin
  if not coalesce(public.is_tournament_admin((select auth.uid())), false) then
    raise exception 'not authorized';
  end if;
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', m.id, 'email', m.email, 'user_id', m.user_id,
           'note', m.note, 'added_at', m.added_at) order by m.added_at), '[]'::jsonb)
    into v from public.scout_members m;
  return coalesce(v, '[]'::jsonb);
end;
$$;

create or replace function public.scout_member_add(p_email text, p_note text default null)
returns jsonb
language plpgsql security definer set search_path = public, extensions volatile
as $$
declare v_email text := nullif(lower(btrim(coalesce(p_email, ''))), ''); v_id uuid;
begin
  if not coalesce(public.is_tournament_admin((select auth.uid())), false) then
    raise exception 'not authorized';
  end if;
  if v_email is null or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then
    raise exception 'that does not look like an email address';
  end if;
  -- Aliased so the DO UPDATE can name the existing row: a schema-qualified
  -- three-part reference to the insert target is not the portable spelling.
  insert into public.scout_members as sm (email, note)
       values (v_email, nullif(btrim(p_note), ''))
    on conflict (email) do update set note = coalesce(excluded.note, sm.note)
    returning sm.id into v_id;
  return jsonb_build_object('id', v_id, 'email', v_email);
end;
$$;

create or replace function public.scout_member_remove(p_email text)
returns boolean
language plpgsql security definer set search_path = public, extensions volatile
as $$
begin
  if not coalesce(public.is_tournament_admin((select auth.uid())), false) then
    raise exception 'not authorized';
  end if;
  delete from public.scout_members where email = lower(btrim(coalesce(p_email, '')));
  return found;
end;
$$;

revoke all on function public.scout_members_list()             from public, anon;
revoke all on function public.scout_member_add(text, text)     from public, anon;
revoke all on function public.scout_member_remove(text)        from public, anon;
grant execute on function public.scout_members_list()          to authenticated;
grant execute on function public.scout_member_add(text, text)  to authenticated;
grant execute on function public.scout_member_remove(text)     to authenticated;

notify pgrst, 'reload schema';
