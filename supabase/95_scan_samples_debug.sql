-- 95_scan_samples_debug.sql
-- QA tooling: store the scanner's full reasoning alongside each saved scan
-- sample — top guess, the ranked candidate list with colour scores, the OCR
-- lines, the collector-number read, the conf/source, and the live-vs-snap
-- divergence. Lets a one-tap "Snap (QA)" capture be reviewed later (photo +
-- guess + thought process) WITHOUT any manual right/wrong labeling.
--
-- Additive + nullable; the client writes it schema-tolerantly (retries the
-- insert without `debug` if this migration hasn't been applied yet).
alter table public.scan_samples add column if not exists debug jsonb;

notify pgrst, 'reload schema';
