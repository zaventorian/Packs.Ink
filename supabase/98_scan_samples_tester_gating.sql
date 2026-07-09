-- 98_scan_samples_tester_gating.sql — enforce the scanner-tester gate at the DB.
--
-- The scanner UI is gated on is_scanner_tester()/is_graded_admin(), but the
-- scan_samples table + storage bucket policies only required "any signed-in
-- user" — anyone with a Google account could upload unlimited files (no size
-- or MIME caps) and insert arbitrary rows, poisoning the training flywheel.
-- Require tester-or-admin on every write path and cap the bucket to what the
-- client actually uploads (~400px JPEG crops; 2 MB is generous headroom).

drop policy if exists scan_samples_insert on public.scan_samples;
create policy scan_samples_insert on public.scan_samples
  for insert to authenticated
  with check ((select auth.uid()) = user_id
              and ((select public.is_scanner_tester()) or (select public.is_graded_admin())));

drop policy if exists scan_samples_update on public.scan_samples;
create policy scan_samples_update on public.scan_samples
  for update to authenticated
  using ((select public.is_graded_admin())
         or ((select auth.uid()) = user_id and (select public.is_scanner_tester())))
  with check ((select public.is_graded_admin())
              or ((select auth.uid()) = user_id and (select public.is_scanner_tester())));

drop policy if exists scan_samples_obj_insert on storage.objects;
create policy scan_samples_obj_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'scan-samples'
              and (storage.foldername(name))[1] = (select auth.uid())::text
              and ((select public.is_scanner_tester()) or (select public.is_graded_admin())));

update storage.buckets
   set file_size_limit = 2097152,
       allowed_mime_types = array['image/jpeg']
 where id = 'scan-samples';

notify pgrst, 'reload schema';
