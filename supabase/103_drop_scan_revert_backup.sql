-- Drop the 2026-06-27 scanner-incident revert backup (35 rows, one user).
-- The revert it protected was verified the same week; the live
-- collection_items has long since moved on. Held for owner sign-off in the
-- 2026-06-27 audit; approved 2026-07-14 (pre-launch cleanup). A JSON dump of
-- the rows was saved locally before this ran (Desktop/
-- scan_revert_backup_20260627.json).
drop table if exists public._scan_revert_backup_20260627;

notify pgrst, 'reload schema';
