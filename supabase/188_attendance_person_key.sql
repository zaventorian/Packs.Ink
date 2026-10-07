-- Migration 188: attendance person keys nobody can look a name up in.
--
-- Additive; applies with the live client unchanged. Migration 189 (STAGED)
-- is the half that takes the names away from anon, once the client that
-- reads person_key / played is deployed.
--
-- rph_event_attendance (122) is anon-readable in full: tournament name,
-- RPH account id, the account's "First L." name, standing and record for
-- every person at every event we scraped. The Store Status tab needs none
-- of that identity - only "how many distinct people" per store and set -
-- and the open table lets anyone ask "did <name> play at <event>" with one
-- filter. RPH publishes the same rosters, so this is low risk, but we do
-- not need to be a second, easier index of them.
--
--   person_key  HMAC-SHA256 of the client's old person key ('u:<id>', or
--               'n:<trimmed lowercased name>' for a guest) under a random
--               32-byte secret in private.server_secrets. Same person ->
--               same key, so distinct-people counts are unchanged; without
--               the secret a name or id cannot be turned into a key, which
--               is what an unsalted hash would have allowed.
--   played      the client's RPH_PLAYED_FILTER as a stored generated
--               column (a standing, or any recorded match), so the client
--               no longer needs the standings and records to filter on.
--
-- The trigger fills person_key on every insert/update, so the attendance
-- scrape (service key) needs no change. Idempotent.

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create table if not exists private.server_secrets (
  name       text primary key,
  secret     bytea not null default extensions.gen_random_bytes(32),
  created_at timestamptz not null default now()
);
alter table private.server_secrets enable row level security;
revoke all on private.server_secrets from public, anon, authenticated, service_role;
insert into private.server_secrets (name) values ('rph_person_key') on conflict do nothing;

-- Invoker on purpose: only ever runs inside the definer trigger below (and
-- this migration), and nobody else may execute it - with the secret it
-- would turn a name back into a key.
create or replace function private.rph_person_key(p_user_id bigint, p_ident text)
returns text
language sql
stable
set search_path = ''
as $$
  select encode(substring(extensions.hmac(
           convert_to(case when p_user_id is not null then 'u:' || p_user_id::text
                           else 'n:' || lower(regexp_replace(coalesce(p_ident, ''), '^\s+|\s+$', '', 'g'))
                      end, 'UTF8'),
           s.secret, 'sha256') from 1 for 16), 'hex')
    from private.server_secrets s
   where s.name = 'rph_person_key'
$$;
revoke all on function private.rph_person_key(bigint, text) from public, anon, authenticated, service_role;

alter table public.rph_event_attendance add column if not exists person_key text;
alter table public.rph_event_attendance add column if not exists played boolean
  generated always as (
    coalesce(final_place_in_standings >= 0, false)
    or coalesce(matches_won > 0, false)
    or coalesce(matches_lost > 0, false)
    or coalesce(matches_drawn > 0, false)
  ) stored;

create or replace function private.rph_attendance_person_key_trg()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.person_key := private.rph_person_key(new.rph_user_id, new.best_identifier);
  return new;
end;
$$;
revoke all on function private.rph_attendance_person_key_trg() from public, anon, authenticated, service_role;

drop trigger if exists rph_attendance_person_key on public.rph_event_attendance;
create trigger rph_attendance_person_key
  before insert or update on public.rph_event_attendance
  for each row execute function private.rph_attendance_person_key_trg();

update public.rph_event_attendance
   set person_key = private.rph_person_key(rph_user_id, best_identifier)
 where person_key is distinct from private.rph_person_key(rph_user_id, best_identifier);

-- A null key would count every such row as ONE person, silently. Better the
-- scrape fails loudly than the tab under-counts.
alter table public.rph_event_attendance alter column person_key set not null;

create index if not exists rph_event_attendance_event_person_idx
  on public.rph_event_attendance (event_id, person_key);

notify pgrst, 'reload schema';
