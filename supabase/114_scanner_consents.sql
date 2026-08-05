-- 114_scanner_consents.sql
-- Public beta of the camera scanner: record that a user was shown (and accepted)
-- the beta notice explaining that scan photos are uploaded, and carry their
-- per-account upload preference.
--
-- Two columns, two different jobs:
--   version         — which notice text they agreed to. Bumping SCAN_BETA_VERSION
--                     in Index.html re-prompts everyone, same pattern as the
--                     graded ToS (GRADED_TOS_VERSION).
--   uploads_enabled — the opt-out. Defaults true (the notice says uploads happen),
--                     but a user can turn it off and keep using the scanner; the
--                     client then skips uploadSample entirely.
--
-- Unlike graded_tos_acceptances this is one row per user, updated in place: we
-- need the CURRENT preference on every scan, not an append-only audit trail.
-- accepted_at still moves forward on each re-acceptance, which is the record that
-- matters if anyone ever asks "was this user shown the notice, and when".

create table if not exists public.scanner_consents (
  user_id         uuid primary key references auth.users(id) on delete cascade,
  version         text        not null,
  accepted_at     timestamptz not null default now(),
  uploads_enabled boolean     not null default true,
  updated_at      timestamptz not null default now()
);

alter table public.scanner_consents enable row level security;

-- Owner-only, all three verbs. No admin read branch: nothing here is needed for
-- curation, and a broad SELECT policy is exactly the RLS-broadening trap that bit
-- the collection tables in migration 90.
drop policy if exists scanner_consents_select on public.scanner_consents;
create policy scanner_consents_select on public.scanner_consents
  for select to authenticated
  using (user_id = (select auth.uid()));

drop policy if exists scanner_consents_insert on public.scanner_consents;
create policy scanner_consents_insert on public.scanner_consents
  for insert to authenticated
  with check (user_id = (select auth.uid()));

drop policy if exists scanner_consents_update on public.scanner_consents;
create policy scanner_consents_update on public.scanner_consents
  for update to authenticated
  using (user_id = (select auth.uid()))
  with check (user_id = (select auth.uid()));

grant select, insert, update on public.scanner_consents to authenticated;

create or replace function public.scanner_consents_touch()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists scanner_consents_touch_trg on public.scanner_consents;
create trigger scanner_consents_touch_trg
  before update on public.scanner_consents
  for each row execute function public.scanner_consents_touch();

notify pgrst, 'reload schema';
