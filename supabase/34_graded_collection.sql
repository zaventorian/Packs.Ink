-- 34_graded_collection.sql — user-owned graded cards + custom tracking goals.
--
-- Why: the existing collection_items table is for raw (NM Low / Cold Foil)
-- copies. Graded cards are a different inventory dimension — a PSA 10
-- Steamboat Pilot is not the same as a NM Holofoil Steamboat Pilot, and
-- ownership needs to be tracked separately so portfolio math doesn't double
-- count.
--
-- Tables:
--   graded_collection_items  — what the user owns (graded copies)
--   graded_collection_goals  — custom set/rarity tracking targets
--
-- The Graded section of the Collection page reads both: owned items appear
-- with their owned-quantity, goal-driven cards appear as "tracking — not
-- yet owned" placeholders the user can check off.

create table if not exists public.graded_collection_items (
  user_id     uuid not null references auth.users(id) on delete cascade,
  card_id     text not null references public.cards(id) on delete cascade,
  grader      text not null,        -- 'psa' | 'cgc' | 'bgs' | 'sgc' | 'tag'
  grade       text not null,        -- '10' | '9.5' | '9' | ...
  quantity    integer not null default 1 check (quantity > 0 and quantity <= 99),
  inserted_at timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, card_id, grader, grade)
);

create index if not exists graded_collection_items_user_idx
  on public.graded_collection_items (user_id);

alter table public.graded_collection_items enable row level security;
drop policy if exists "graded_collection_items_owner_all"
  on public.graded_collection_items;
create policy "graded_collection_items_owner_all"
  on public.graded_collection_items
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- Set-tracking goals. Each goal is "track set X, but only the rarities I
-- pick" (e.g. Fabled / Epic + Enchanted + Iconic). The Graded section
-- surfaces every card matching the goal even when the user doesn't own
-- a graded copy yet, so it acts as a collection checklist.
create table if not exists public.graded_collection_goals (
  user_id      uuid not null references auth.users(id) on delete cascade,
  goal_id      uuid not null default gen_random_uuid(),
  set_id       text not null references public.sets(id) on delete cascade,
  rarities     text[] not null default '{}',  -- empty array = all rarities
  display_name text,                          -- optional user-given label
  inserted_at  timestamptz not null default now(),
  primary key (user_id, goal_id)
);

create index if not exists graded_collection_goals_user_idx
  on public.graded_collection_goals (user_id);

alter table public.graded_collection_goals enable row level security;
drop policy if exists "graded_collection_goals_owner_all"
  on public.graded_collection_goals;
create policy "graded_collection_goals_owner_all"
  on public.graded_collection_goals
  for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

grant select, insert, update, delete
  on public.graded_collection_items, public.graded_collection_goals
  to authenticated;

notify pgrst, 'reload schema';
