-- 97_graded_rollup_refresh_hardening.sql — lock down the graded-rollup refresh RPCs.
--
-- (1) refresh_graded_sales_rollup(): migration 73 granted service_role but never
--     revoked the default PUBLIC EXECUTE that CREATE FUNCTION hands out, so any
--     anon visitor could trigger a 5-minute-timeout matview refresh in a loop.
--     Only the ETL scripts (service key) call it.
revoke execute on function public.refresh_graded_sales_rollup() from public, anon, authenticated;

-- (2) admin_refresh_graded_rollup(): the concurrent->full fallback used a
--     function-level `exception when others`, which also caught the
--     'not authorized' raise — the admin gate was a no-op and any caller got a
--     full refresh anyway. Nest the fallback so the gate stands.
create or replace function public.admin_refresh_graded_rollup()
returns void language plpgsql security definer set search_path = public, extensions
set statement_timeout = '5min'
as $$
begin
  if not public.is_graded_admin() then raise exception 'not authorized'; end if;
  begin
    refresh materialized view concurrently public.graded_sales_rollup;
  exception when others then
    refresh materialized view public.graded_sales_rollup;
  end;
end;
$$;
revoke execute on function public.admin_refresh_graded_rollup() from public, anon;
grant execute on function public.admin_refresh_graded_rollup() to authenticated;

-- (3) Drop the dead 4-arg admin_update_graded_sale overload. The client always
--     sends all 5 named args; keeping both overloads makes any 4-key PostgREST
--     call ambiguous (300).
drop function if exists public.admin_update_graded_sale(text, text, text, text);

notify pgrst, 'reload schema';
