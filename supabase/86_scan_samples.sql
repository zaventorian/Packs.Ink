-- 86_scan_samples.sql — data flywheel for the card scanner.
--
-- Every time the user confirms a scanned card (adds it / corrects to an
-- alternate) we log a labelled (rectified photo -> confirmed card_id) example.
-- Over time this becomes a REAL-photo dataset that can train a matcher which
-- doesn't suffer the digital-art domain gap (the current colour/text matchers
-- compare against clean Lorcast art). `corrected = true` rows (user picked an
-- alternate over the scanner's top guess) are hard negatives — the most
-- valuable training signal.
--
-- The scanner is admin-gated for now, so in practice these are the owner's own
-- card photos; RLS keeps each user's samples private, with graded admins able
-- to read all for training export.

create table if not exists public.scan_samples (
  id                bigint generated always as identity primary key,
  user_id           uuid references auth.users(id) on delete set null,
  card_id           text not null,                 -- CONFIRMED card (what was added)
  predicted_card_id text,                           -- scanner's top-1 guess
  corrected         boolean not null default false, -- user overrode top-1 = hard negative
  printing          text,
  image_path        text,                           -- scan-samples/<uid>/<uuid>.jpg
  created_at        timestamptz not null default now()
);
create index if not exists scan_samples_card_idx on public.scan_samples(card_id);
create index if not exists scan_samples_corrected_idx on public.scan_samples(corrected) where corrected;

alter table public.scan_samples enable row level security;

drop policy if exists scan_samples_insert on public.scan_samples;
create policy scan_samples_insert on public.scan_samples
  for insert to authenticated with check (auth.uid() = user_id);

drop policy if exists scan_samples_select on public.scan_samples;
create policy scan_samples_select on public.scan_samples
  for select to authenticated
  using (auth.uid() = user_id or public.is_graded_admin());

grant select, insert on public.scan_samples to authenticated;

-- private bucket for the rectified card crops (downscaled ~400px, tiny)
insert into storage.buckets (id, name, public)
  values ('scan-samples', 'scan-samples', false)
  on conflict (id) do nothing;

drop policy if exists scan_samples_obj_insert on storage.objects;
create policy scan_samples_obj_insert on storage.objects
  for insert to authenticated
  with check (bucket_id = 'scan-samples' and (storage.foldername(name))[1] = auth.uid()::text);

drop policy if exists scan_samples_obj_select on storage.objects;
create policy scan_samples_obj_select on storage.objects
  for select to authenticated
  using (bucket_id = 'scan-samples'
         and ((storage.foldername(name))[1] = auth.uid()::text or public.is_graded_admin()));

notify pgrst, 'reload schema';
