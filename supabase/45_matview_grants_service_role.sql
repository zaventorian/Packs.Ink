-- Re-grant SELECT on every price matview to all roles that need it.
--
-- Why: the hourly matview self-heal job started failing with HTTP 403 on
-- `card_prices_latest` reads via the service key. service_role doesn't
-- inherit table/view grants implicitly; an old recreation of the matview
-- (or a manual revoke) dropped the grant. Same gotcha CLAUDE.md flagged
-- against migration 26 / price_movers.
--
-- This migration re-grants SELECT to anon, authenticated, AND service_role
-- on every price matview so neither the client (anon) nor any server-side
-- maintenance script (service_role) can be broken by a future recreation.
--
-- Idempotent: grants are no-ops when already in place.

grant select on public.card_prices_latest   to anon, authenticated, service_role;
grant select on public.price_movers         to anon, authenticated, service_role;
grant select on public.rarity_avg_daily     to anon, authenticated, service_role;
grant select on public.sealed_prices_latest to anon, authenticated, service_role;
grant select on public.graded_prices_latest to anon, authenticated, service_role;

-- prices_daily isn't a matview but the self-heal also reads it. Service
-- role usually has it via being the table's effective owner, but make it
-- explicit so we never debug this same 403 again.
grant select on public.prices_daily to service_role;

notify pgrst, 'reload schema';
