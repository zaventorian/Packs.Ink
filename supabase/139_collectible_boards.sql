-- Migration 139: collectible boards — where a collector's pins and lore
-- counters sit on their board (Collection » Pins & Counters).
--
-- OWNERSHIP is not stored here. A pin or counter you own is still a row in
-- sealed_collection_items (synthetic pids 950000000+n / 960000000+n, see
-- LORCANA_PINS in Index.html), exactly as before this migration, so the owned
-- marks, the collection-sharing axis and the offline mirror all keep working
-- unchanged. This table holds only the ARRANGEMENT: one jsonb document per
-- (user, board), because a board is edited and saved as a whole — dragging one
-- pin rewrites one small document instead of a row per pin.
--
-- Layout shape (validated and repaired client-side by normalizeCollectibleBoard;
-- the server only bounds its size):
--   pins     {"v":1, "bg":"cork", "scale":1, "items":{"<n>":{"x":0.42,"y":0.31,"r":-8,"z":4}}}
--   counters {"v":1, "bg":"felt",             "items":{"<n>":{"c":3,"r":1}}}
-- x/y are fractions of the board so an arrangement looks the same on a phone
-- and a monitor; counters snap to a honeycomb, so they store a cell, not a point.
--
-- Sharing follows the SEALED visibility axis, because the owned marks the board
-- draws already live behind it: whoever can see your sealed collection can see
-- how you arranged its pins, and nobody else can.
--
-- Safe to ship the client first: before this lands, boards save to the device
-- (localStorage) and the tab says so.
--
-- Idempotent.

create table if not exists public.collectible_boards (
  user_id    uuid        not null references auth.users(id) on delete cascade,
  board      text        not null check (board in ('pins', 'counters')),
  layout     jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now(),
  primary key (user_id, board),
  -- 62 collectibles at ~40 bytes a placement is ~2.5 KB. The cap is generous
  -- headroom for a growing catalog, not a limit anyone should meet — it exists
  -- so the table can't be used as free storage.
  constraint collectible_boards_layout_size check (octet_length(layout::text) < 32768),
  constraint collectible_boards_layout_object check (jsonb_typeof(layout) = 'object')
);

-- ── RLS ─────────────────────────────────────────────────────────────────
-- Owner-only. auth.uid() wrapped in (select …) per migration 91.
alter table public.collectible_boards enable row level security;

drop policy if exists "collectible_boards: select own" on public.collectible_boards;
drop policy if exists "collectible_boards: insert own" on public.collectible_boards;
drop policy if exists "collectible_boards: update own" on public.collectible_boards;
drop policy if exists "collectible_boards: delete own" on public.collectible_boards;

create policy "collectible_boards: select own"
  on public.collectible_boards for select
  using ((select auth.uid()) = user_id);

create policy "collectible_boards: insert own"
  on public.collectible_boards for insert
  with check ((select auth.uid()) = user_id);

create policy "collectible_boards: update own"
  on public.collectible_boards for update
  using ((select auth.uid()) = user_id)
  with check ((select auth.uid()) = user_id);

create policy "collectible_boards: delete own"
  on public.collectible_boards for delete
  using ((select auth.uid()) = user_id);

-- ⚠ A new relation grants NOTHING implicitly (the migration 125 → 126 lesson).
-- Keep the grants in the same file as the table.
grant select, insert, update, delete on public.collectible_boards to authenticated;
grant select, insert, update, delete on public.collectible_boards to service_role;

drop trigger if exists collectible_boards_updated_at on public.collectible_boards;
create trigger collectible_boards_updated_at
  before update on public.collectible_boards
  for each row execute function public.set_updated_at();

-- ── Shared read ─────────────────────────────────────────────────────────
-- A viewer of someone's collection (?collection=<uuid>[&token=]) sees their
-- boards under the same rule as get_shared_collection_sealed (migration 134):
-- sealed visibility public, or unlisted with the matching share token.
drop function if exists public.get_shared_collectible_boards(uuid, text);
create function public.get_shared_collectible_boards(p_user_id uuid, p_token text)
returns table(board text, layout jsonb, updated_at timestamptz)
language sql
stable
security definer
set search_path to 'public'
as $function$
  select b.board, b.layout, b.updated_at
    from public.collectible_boards b
    join public.profiles p on p.user_id = b.user_id
   where b.user_id = p_user_id
     and (
       p.collection_sealed_visibility = 'public'
       or (p.collection_sealed_visibility = 'unlisted' and p.collection_share_token = p_token)
     );
$function$;
revoke all on function public.get_shared_collectible_boards(uuid, text) from public;
grant execute on function public.get_shared_collectible_boards(uuid, text) to anon, authenticated;

notify pgrst, 'reload schema';
