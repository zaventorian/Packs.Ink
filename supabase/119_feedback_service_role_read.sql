-- Zaven uses the footer feedback widget as a to-do channel for the coding
-- agent, so the queue has to be readable from a script — not only from the
-- in-app admin inbox, which needs an interactive browser session.
--
-- Migration 106 left `feedback` with RLS on and no policies, routing every
-- client path through SECURITY DEFINER functions. That posture is about anon
-- and authenticated; it was never meant to fence out service_role, which
-- already reads every other table via the ETL key. Postgres itself names the
-- fix in its error hint: GRANT SELECT ON public.feedback TO service_role.
--
-- SELECT + UPDATE only. No DELETE: dropping a user's feedback should stay a
-- deliberate act through delete_feedback(), not something a script can do by
-- accident. Matches how migration 74 grants service_role on
-- graded_sale_reports, the sibling triage queue.
grant select, update on public.feedback to service_role;

notify pgrst, 'reload schema';
