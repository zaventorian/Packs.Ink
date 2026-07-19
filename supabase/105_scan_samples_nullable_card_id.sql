-- 105_scan_samples_nullable_card_id.sql — let flywheel rows land without a card.
--
-- scan_samples.card_id was NOT NULL (mig 86), but two writers legitimately have
-- no card: (a) the qa-session summary row (kind=qa-session, whole-session trace
-- — card_id:null by design) and (b) QA snaps where identify() found NO match —
-- detection/OCR's worst failures, exactly the photos the tuning flywheel needs.
-- Both inserts have silently 23502'd since 2026-07-15 (fire-and-forget error
-- swallowed): zero qa-session rows exist and every no-match snap lost its row
-- (orphaned storage image). NULL card_id = "no confirmed card yet"; the tester
-- review flow (labelSample) can fill it in later.

alter table public.scan_samples alter column card_id drop not null;

notify pgrst, 'reload schema';
