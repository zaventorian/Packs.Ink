-- Per-user saved Screener views.
--
-- Replaces the localStorage-only `packsink:screener:views` JSON blob with
-- a Supabase-backed table so views roam across devices. Signed-out users
-- still get the localStorage path as a fallback (no migration cost on
-- first visit — saves just don't persist until they sign in).
--
-- Schema choice: one row per (user, name). Payload is a jsonb snapshot of
-- the screener's UI state (preset, filters, sort, etc.) — opaque to the
-- DB. Keeping it opaque means future client-side fields don't need a
-- migration; the cost is no per-field querying, but views are an
-- inherently client-rendered concept so that's fine.
--
-- Idempotent.

create table if not exists public.screener_views (
  user_id     uuid    not null references auth.users(id) on delete cascade,
  name        text    not null check (length(trim(name)) > 0 and length(name) <= 80),
  payload     jsonb   not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, name)
);

create index if not exists screener_views_user_idx
  on public.screener_views (user_id, updated_at desc);

alter table public.screener_views enable row level security;

drop policy if exists "screener_views: select own" on public.screener_views;
drop policy if exists "screener_views: insert own" on public.screener_views;
drop policy if exists "screener_views: update own" on public.screener_views;
drop policy if exists "screener_views: delete own" on public.screener_views;

create policy "screener_views: select own"
  on public.screener_views for select
  using (auth.uid() = user_id);

create policy "screener_views: insert own"
  on public.screener_views for insert
  with check (auth.uid() = user_id);

create policy "screener_views: update own"
  on public.screener_views for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

create policy "screener_views: delete own"
  on public.screener_views for delete
  using (auth.uid() = user_id);

grant select, insert, update, delete on public.screener_views to authenticated;
grant select, insert, update, delete on public.screener_views to service_role;

drop trigger if exists screener_views_updated_at on public.screener_views;
create trigger screener_views_updated_at
  before update on public.screener_views
  for each row execute function public.set_updated_at();

notify pgrst, 'reload schema';
