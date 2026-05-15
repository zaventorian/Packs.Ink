-- Decks: a user's saved Lorcana decklist.
-- A deck has a header (name, optional ink colors / description / tags) and
-- one deck_cards row per (card, printing). Lorcana rules cap a deck at 60
-- cards across at most 2 inks, with ≤4 copies of any single card — those
-- are enforced UI-side; the table doesn't constrain them so half-built
-- drafts can be saved.

create table if not exists public.decks (
  id          uuid    primary key default gen_random_uuid(),
  user_id     uuid    not null references auth.users(id) on delete cascade,
  name        text    not null,
  description text,
  -- Ink identity (e.g. ['Amber','Steel']). Optional — derive from cards if null.
  inks        text[],
  -- Free-form tags (e.g. "Infinity", "Core Constructed"). Optional.
  tags        text[],
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists decks_user_idx on public.decks (user_id, updated_at desc);

-- deck_cards: one row per (deck, card, printing). printing is stored so the
-- user can express "I want the foil copy" preferences; in v1 the deck
-- builder treats Normal as the default and ignores printing for legality.
create table if not exists public.deck_cards (
  deck_id     uuid    not null references public.decks(id) on delete cascade,
  card_id     text    not null,
  printing    text    not null default 'Normal',
  quantity    int     not null default 1 check (quantity > 0 and quantity <= 4),
  primary key (deck_id, card_id, printing)
);

create index if not exists deck_cards_deck_idx on public.deck_cards (deck_id);

-- RLS: each user reads / writes only their own decks and deck_cards.
alter table public.decks       enable row level security;
alter table public.deck_cards  enable row level security;

drop policy if exists "decks: select own"  on public.decks;
drop policy if exists "decks: insert own"  on public.decks;
drop policy if exists "decks: update own"  on public.decks;
drop policy if exists "decks: delete own"  on public.decks;
create policy "decks: select own" on public.decks for select using  (auth.uid() = user_id);
create policy "decks: insert own" on public.decks for insert with check (auth.uid() = user_id);
create policy "decks: update own" on public.decks for update using  (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "decks: delete own" on public.decks for delete using  (auth.uid() = user_id);

-- deck_cards policies join through decks to inherit ownership.
drop policy if exists "deck_cards: select own" on public.deck_cards;
drop policy if exists "deck_cards: insert own" on public.deck_cards;
drop policy if exists "deck_cards: update own" on public.deck_cards;
drop policy if exists "deck_cards: delete own" on public.deck_cards;
create policy "deck_cards: select own" on public.deck_cards for select
  using (exists (select 1 from public.decks d where d.id = deck_id and d.user_id = auth.uid()));
create policy "deck_cards: insert own" on public.deck_cards for insert
  with check (exists (select 1 from public.decks d where d.id = deck_id and d.user_id = auth.uid()));
create policy "deck_cards: update own" on public.deck_cards for update
  using (exists (select 1 from public.decks d where d.id = deck_id and d.user_id = auth.uid()))
  with check (exists (select 1 from public.decks d where d.id = deck_id and d.user_id = auth.uid()));
create policy "deck_cards: delete own" on public.deck_cards for delete
  using (exists (select 1 from public.decks d where d.id = deck_id and d.user_id = auth.uid()));

grant select, insert, update, delete on public.decks       to authenticated;
grant select, insert, update, delete on public.deck_cards  to authenticated;
grant select, insert, update, delete on public.decks       to service_role;
grant select, insert, update, delete on public.deck_cards  to service_role;

-- updated_at trigger on decks (mirrors collection_items pattern).
drop trigger if exists decks_updated_at on public.decks;
create trigger decks_updated_at
  before update on public.decks
  for each row execute function public.set_updated_at();
