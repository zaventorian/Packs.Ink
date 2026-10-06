-- Migration 191: an admin check only answers for the caller.
--
-- Server-only; applies with the live client unchanged. Idempotent.
--
-- is_tournament_admin(uuid) and is_elo_admin(uuid) are the only role checks
-- that take a user id (can_scout, can_view_store_report, is_graded_admin,
-- is_scanner_tester and is_inkbox_user all read auth.uid() themselves). Both
-- are executable by every signed-in user (RLS policies call them as the
-- querying role), and user ids are public (?user=<uuid> creator pages,
-- shared collection links), so any account could ask "is <user> a
-- tournament / Elo admin" for anyone.
--
-- Every caller passes the caller's own id: 12 RLS policies as
-- (select auth.uid()), the admin RPCs and can_scout / can_view_store_report /
-- scout_member_* as auth.uid(), and the client as user.id. So the check now
-- answers false for any OTHER id when the request comes from anon or
-- authenticated. The API role is read from the `role` setting, which
-- PostgREST sets with SET LOCAL ROLE and which a SECURITY DEFINER call does
-- not change (checked live 2026-10-06: 'anon' inside a definer function).
-- service_role, the SQL editor and other server code can still ask about
-- anyone.

create or replace function public.is_tournament_admin(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select p_user is not null
     and (p_user = (select auth.uid())
          or coalesce(current_setting('role', true), 'none') not in ('anon', 'authenticated'))
     and exists (select 1 from public.tournament_admins where user_id = p_user)
$$;
revoke all on function public.is_tournament_admin(uuid) from public, anon;
grant execute on function public.is_tournament_admin(uuid) to authenticated, service_role;

create or replace function public.is_elo_admin(p_user uuid)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select p_user is not null
     and (p_user = (select auth.uid())
          or coalesce(current_setting('role', true), 'none') not in ('anon', 'authenticated'))
     and exists (select 1 from public.elo_admins where user_id = p_user)
$$;
revoke all on function public.is_elo_admin(uuid) from public, anon;
grant execute on function public.is_elo_admin(uuid) to authenticated, service_role;

notify pgrst, 'reload schema';
