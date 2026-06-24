-- 84_grading_submissions.sql — the "sent for grading" pipeline.
--
-- Why: collectors track in-flight grading in spreadsheets ("waiting to
-- submit" / "sent to PSA"). Until a slab comes back it has no grade, so it
-- can't live in graded_collection_items (whose PK requires grader+grade).
-- This is a separate, lightweight queue. When the grade lands, the client
-- inserts the real graded_collection_items row and deletes the submission
-- ("graduate"). Pending rows also check off raw set completion (with an
-- "at grader" asterisk) since the user physically owns the card.
--
-- card_id has NO foreign key to cards (same reasoning as migration 47):
-- synthetic Extras/variant card_ids must be sendable to grading too.

create table if not exists public.grading_submissions (
  id              uuid not null default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  card_id         text not null,
  printing        text not null default 'Normal',  -- 'Normal' | 'Cold Foil' | 'Holofoil' | ...
  intended_grader text,                             -- 'psa' | 'cgc' | 'bgs' | 'sgc' | 'tag' | null
  status          text not null default 'to_submit'
                    check (status in ('to_submit', 'at_grader')),
  quantity        integer not null default 1 check (quantity > 0 and quantity <= 99),
  submitted_on    date,                             -- when it was shipped to the grader
  note            text,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  primary key (id)
);

create index if not exists grading_submissions_user_idx
  on public.grading_submissions (user_id);

alter table public.grading_submissions enable row level security;
drop policy if exists "grading_submissions_owner_all"
  on public.grading_submissions;
create policy "grading_submissions_owner_all"
  on public.grading_submissions
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

grant select, insert, update, delete
  on public.grading_submissions
  to authenticated;

notify pgrst, 'reload schema';
