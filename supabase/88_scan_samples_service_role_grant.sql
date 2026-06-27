-- 88_scan_samples_service_role_grant.sql
-- service_role does NOT inherit table grants implicitly (same gotcha as the price
-- matviews in migration 45). The flywheel downloader (pull_scan_samples.py) reads
-- scan_samples with the service key, so grant it SELECT. RLS is bypassed by
-- service_role; this is just the table-level privilege.

grant select on public.scan_samples to service_role;

notify pgrst, 'reload schema';
