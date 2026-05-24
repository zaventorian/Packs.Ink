-- Allow Graded tracking goals to target an Extras & Oddities sub-bucket
-- instead of a real set.
--
-- Why: "Extras & Oddities" is a client-side synthetic bucket that pulls
-- cards from many actual sets (Wilds Unknown starter foils, Deep Trouble,
-- Palace Heist, etc.) and labels each card with a variant_label. Tracking
-- goals previously required a real set_id, which excluded Extras entirely.
-- This migration adds an extras_bucket column so a goal can target e.g.
-- "all Deep Trouble cards" without needing a real set_id.
--
-- One of set_id or extras_bucket must be set; both is fine in theory but
-- the UI picks one or the other.

alter table public.graded_collection_goals
  add column if not exists extras_bucket text;

alter table public.graded_collection_goals
  alter column set_id drop not null;

alter table public.graded_collection_goals
  drop constraint if exists graded_collection_goals_target_check;

alter table public.graded_collection_goals
  add constraint graded_collection_goals_target_check
  check (set_id is not null or extras_bucket is not null);

notify pgrst, 'reload schema';
