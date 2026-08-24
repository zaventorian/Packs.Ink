-- 125_deck_versions.sql — deck version history + an opt-in share toggle.
--
-- A version is one EDITING SESSION, not one keystroke. The editor already
-- captures `editSnapshot` when you enter edit mode (it powers "Undo changes");
-- hitting Done writes that pre-edit state here as the next version, but only
-- if something actually changed. So v1 is "how the deck looked before the first
-- time you edited it", and the live deck is always the newest state. Snapshot
-- per card-tap would produce hundreds of rows nobody could read as history.
--
-- Cards are stored as a jsonb array of {card_id, printing, quantity} using the
-- SAME obfuscation as deck_cards — card_id encrypted with the deterministic
-- codec, quantity left as a plain int. A version snapshot is a decklist; it
-- would be strange for the archive to be readable when the live table is not.
-- Tournament decks (user_id null) never reach this table: nothing edits them.
--
-- Applied: NOT YET (staged for Zaven).

create table if not exists public.deck_versions (
  deck_id      uuid        not null references public.decks(id) on delete cascade,
  version      int         not null,
  name         text,
  coconut_card text,
  cards        jsonb       not null default '[]'::jsonb,
  created_at   timestamptz not null default now(),
  primary key (deck_id, version)
);

-- Every read path filters by deck_id and orders by version.
create index if not exists deck_versions_deck_idx
  on public.deck_versions (deck_id, version desc);

alter table public.deck_versions enable row level security;

-- Owner-only direct access. Non-owners come through the RPC below, which adds
-- the token + share_versions checks — same shape as get_shared_deck_cards.
drop policy if exists deck_versions_owner_select on public.deck_versions;
create policy deck_versions_owner_select on public.deck_versions
  for select using (
    exists (select 1 from public.decks d
             where d.id = deck_versions.deck_id
               and d.user_id = (select auth.uid()))
  );

drop policy if exists deck_versions_owner_delete on public.deck_versions;
create policy deck_versions_owner_delete on public.deck_versions
  for delete using (
    exists (select 1 from public.decks d
             where d.id = deck_versions.deck_id
               and d.user_id = (select auth.uid()))
  );

-- No INSERT/UPDATE policy on purpose: writes go through save_deck_version so
-- the version number and the retention cap can't be raced or bypassed.

-- ── the share toggle ─────────────────────────────────────────────────────
-- Default FALSE. Sharing a deck is already a decision; sharing every draft it
-- passed through is a second, bigger one, and it should never happen because
-- someone forgot a checkbox existed.
alter table public.decks
  add column if not exists share_versions boolean not null default false;

-- ── write path ───────────────────────────────────────────────────────────
-- SECURITY DEFINER so it can assign max(version)+1 and prune under one lock.
-- Ownership is re-checked here rather than trusted from the client.
create or replace function public.save_deck_version(
  p_deck_id      uuid,
  p_name         text,
  p_coconut_card text,
  p_cards        jsonb
)
returns int
language plpgsql
security definer
set search_path = public
as $$
declare
  v_owner uuid;
  v_next  int;
  v_keep  constant int := 30;
begin
  select user_id into v_owner from public.decks where id = p_deck_id;
  if v_owner is null or v_owner <> (select auth.uid()) then
    raise exception 'not your deck';
  end if;

  select coalesce(max(version), 0) + 1 into v_next
    from public.deck_versions where deck_id = p_deck_id;

  insert into public.deck_versions (deck_id, version, name, coconut_card, cards)
  values (p_deck_id, v_next, p_name, p_coconut_card, coalesce(p_cards, '[]'::jsonb));

  -- Keep the most recent v_keep. A 60-card snapshot is ~2KB, so the cap is
  -- about readability rather than storage: a history nobody can scan is the
  -- same as no history. Version NUMBERS are never reused, so "v4" always
  -- means the same snapshot even after v1 is pruned away.
  delete from public.deck_versions
   where deck_id = p_deck_id
     and version <= v_next - v_keep;

  return v_next;
end;
$$;

revoke all on function public.save_deck_version(uuid, text, text, jsonb) from public;
grant  execute on function public.save_deck_version(uuid, text, text, jsonb) to authenticated;

-- ── shared read path ─────────────────────────────────────────────────────
-- Three gates, all required: the deck isn't private, the token matches, and
-- the owner opted this deck's history in. Dropping share_versions from the
-- WHERE would silently expose every draft of every shared deck.
create or replace function public.get_shared_deck_versions(p_deck_id uuid, p_token text)
returns table(
  version      int,
  name         text,
  coconut_card text,
  cards        jsonb,
  created_at   timestamptz
)
language sql
security definer
set search_path = public
as $$
  select v.version, v.name, v.coconut_card, v.cards, v.created_at
    from public.deck_versions v
    join public.decks d on d.id = v.deck_id
   where v.deck_id = p_deck_id
     and d.share_token = p_token
     and d.visibility <> 'private'
     and d.share_versions
   order by v.version desc;
$$;

revoke all on function public.get_shared_deck_versions(uuid, text) from public;
grant  execute on function public.get_shared_deck_versions(uuid, text) to anon, authenticated;

-- get_shared_deck must report the flag so a viewer's client knows whether to
-- offer the History button at all. RETURNS TABLE can't be altered in place.
drop function if exists public.get_shared_deck(uuid, text);

create or replace function public.get_shared_deck(p_deck_id uuid, p_token text)
returns table(
  id             uuid,
  user_id        uuid,
  name           text,
  description    text,
  youtube_url    text,
  inks           text[],
  tags           text[],
  visibility     text,
  updated_at     timestamptz,
  share_token    text,
  coconut_card   text,
  share_versions boolean
)
language sql
security definer
set search_path = public
as $$
  select id, user_id, name, description, youtube_url, inks, tags, visibility,
         updated_at, share_token, coconut_card, share_versions
    from public.decks
   where id = p_deck_id
     and share_token = p_token
     and visibility <> 'private';
$$;

revoke all on function public.get_shared_deck(uuid, text)     from public;
grant  execute on function public.get_shared_deck(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
