-- 177_admin_exec_sql.sql
-- A SQL route that works from every session: scripts/sql.py calls this with
-- the service key, which local sessions hold in scripts/.env and cloud
-- sessions get injected by the agent proxy. The Supabase connector stays the
-- first choice; this is what a session uses when the connector is missing or
-- refuses a statement.
--
-- SERVICE ROLE ONLY, checked twice: EXECUTE is granted to service_role alone,
-- and the body refuses any other role. The service key already bypasses RLS
-- on every table, so this widens what that key can do from data to DDL and
-- nothing else. Never grant it to anon or authenticated.
--
-- p_rows = true wraps the statement as a query and returns its rows as JSON.
-- p_rows = false runs it (several statements are fine) and returns {"ok":true}.
-- It runs inside a function, so no BEGIN/COMMIT, VACUUM or CREATE INDEX
-- CONCURRENTLY. Remove with: drop function public.admin_exec_sql(text, boolean);
create or replace function public.admin_exec_sql(p_sql text, p_rows boolean default false)
returns jsonb
language plpgsql
security definer
set search_path = public, extensions
set statement_timeout = '5min'
as $$
declare
  r jsonb;
begin
  if coalesce(auth.role(), '') <> 'service_role' then
    raise exception 'admin_exec_sql is service-role only' using errcode = '42501';
  end if;
  if p_rows then
    execute 'select coalesce(jsonb_agg(t), ''[]''::jsonb) from (' || p_sql || ') t' into r;
    return r;
  end if;
  execute p_sql;
  return jsonb_build_object('ok', true);
end;
$$;

revoke all on function public.admin_exec_sql(text, boolean) from public, anon, authenticated;
grant execute on function public.admin_exec_sql(text, boolean) to service_role;
notify pgrst, 'reload schema';
