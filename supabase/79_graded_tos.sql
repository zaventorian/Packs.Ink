-- Premium graded-data Terms of Use acceptance. A user on the graded_premium_viewers
-- allowlist must click through the ToS (no scrape / sell / redistribute / retain)
-- before the per-sale graded data unlocks. We keep an auditable per-user record of
-- which ToS version they accepted and when.

create table if not exists public.graded_tos_acceptances (
  user_id     uuid primary key references auth.users(id) on delete cascade,
  accepted_at timestamptz not null default now(),
  tos_version text not null
);

alter table public.graded_tos_acceptances enable row level security;
-- No policies: all access is via the SECURITY DEFINER RPCs below (auth.uid()-scoped),
-- mirroring graded_premium_viewers / can_view_graded_premium.

create or replace function public.accept_graded_tos(p_version text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  if auth.uid() is null then
    raise exception 'authentication required';
  end if;
  insert into public.graded_tos_acceptances(user_id, accepted_at, tos_version)
  values (auth.uid(), now(), p_version)
  on conflict (user_id) do update
    set accepted_at = now(), tos_version = excluded.tos_version;
end;
$$;

-- Returns the ToS version the current user has accepted, or null.
create or replace function public.graded_tos_status()
returns text
language sql
security definer
set search_path = public
as $$
  select tos_version from public.graded_tos_acceptances where user_id = auth.uid();
$$;

grant execute on function public.accept_graded_tos(text) to authenticated;
grant execute on function public.graded_tos_status() to authenticated;

notify pgrst, 'reload schema';
