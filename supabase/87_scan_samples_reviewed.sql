-- 87_scan_samples_reviewed.sql — review state for the scanner flywheel.
--
-- The "Scan Review" admin panel pages through saved scans and labels each
-- Right/Wrong. `reviewed` lets us (a) skip already-judged scans and (b) compute
-- an honest accuracy from SQL: of the reviewed rows, corrected=true were wrong.
-- Unreviewed rows are "not yet judged" (an auto-logged corrected=false add is
-- only a *presumed* positive until a human confirms it).

alter table public.scan_samples
  add column if not exists reviewed boolean not null default false,
  add column if not exists reviewed_at timestamptz;

create index if not exists scan_samples_reviewed_idx on public.scan_samples(reviewed);

-- owner (or graded admin) can update their own rows' label/review state.
drop policy if exists scan_samples_update on public.scan_samples;
create policy scan_samples_update on public.scan_samples
  for update to authenticated
  using (auth.uid() = user_id or public.is_graded_admin())
  with check (auth.uid() = user_id or public.is_graded_admin());

grant update on public.scan_samples to authenticated;

notify pgrst, 'reload schema';
