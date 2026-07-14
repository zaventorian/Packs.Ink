-- 100_retire_prestaged_service_role_grants.sql
--
-- scripts/retire_prestaged.py (the daily Lorcast-metadata ETL's last step)
-- re-points user references off a superseded pre-stage stand-in card and onto
-- the real Lorcast card, then deletes the stand-in. It runs as service_role.
-- Three of the tables it re-points were never granted the write access
-- service_role needs, so the re-point 403'd (Forbidden) and the daily job
-- exited non-zero EVERY night — the stand-in was kept safely, but it spammed
-- "Run failed: ETL" while prices/data stayed fresh. Same missing-grant class
-- of bug as migration 45 (service_role does NOT inherit grants implicitly).
--
-- Observed 2026-07-13 (ETL #407): re-point of crd_prestage_set13_238 ->
-- crd_9da69a8f... hit `403 ... /rest/v1/graded_collection_items`.
--
--   graded_collection_items — had NO service_role grant. repoint() does
--                             select + update + delete (the merge path).
--   grading_submissions     — had NO service_role grant. plain_repoint()
--                             does select + update.
--   scan_samples            — had SELECT only (migration 88); plain_repoint()
--                             UPDATEs card_id / predicted_card_id.
--
-- Mirrors the full-CRUD service_role grants that collection_items (mig 03) and
-- deck_cards (mig 13) — the analogous re-point targets — already carry.
-- service_role bypasses RLS; these are plain table grants.

grant select, insert, update, delete on public.graded_collection_items to service_role;
grant select, insert, update, delete on public.grading_submissions      to service_role;
grant update                          on public.scan_samples             to service_role;

notify pgrst, 'reload schema';
