-- Expose aggregate "how many users favorited this deck" counts publicly
-- without leaking the underlying who-favorited-what rows.
--
-- deck_favorites RLS restricts SELECT to the row owner ("read own"), which
-- is what we want for privacy — but it also means a naive aggregate query
-- from a non-owner sees zero. We use a SECURITY DEFINER function to
-- bypass RLS in a controlled way: the function only returns counts, never
-- user_ids. Safe to grant to anon + authenticated.

create or replace function public.deck_favorite_counts(deck_ids uuid[])
returns table(deck_id uuid, favorite_count bigint)
language sql
security definer
set search_path = public
as $$
  select deck_id, count(*)::bigint as favorite_count
  from public.deck_favorites
  where deck_id = any(deck_ids)
  group by deck_id;
$$;

revoke all on function public.deck_favorite_counts(uuid[]) from public;
grant  execute on function public.deck_favorite_counts(uuid[]) to anon, authenticated;
