-- 161: home-page poll. One active poll at a time, one vote per account, final.
-- Results are returned only to someone who has voted, and only as percentages
-- (never counts). A new poll is an INSERT here, not a deploy: set the old
-- row's active = false and insert the next one.

create table if not exists public.polls (
  id         text primary key check (id ~ '^[a-z0-9-]{1,64}$'),
  question   text not null,
  options    text[] not null check (cardinality(options) between 2 and 8),
  active     boolean not null default true,
  created_at timestamptz not null default now()
);

create table if not exists public.poll_votes (
  poll_id    text not null references public.polls(id) on delete cascade,
  user_id    uuid not null references auth.users(id) on delete cascade,
  choice     smallint not null check (choice >= 0),
  created_at timestamptz not null default now(),
  primary key (poll_id, user_id)
);
create index if not exists poll_votes_user_idx on public.poll_votes(user_id);

-- RLS on, no policies: only the two definer functions below can reach these.
alter table public.polls enable row level security;
alter table public.poll_votes enable row level security;
revoke all on public.polls, public.poll_votes from anon, authenticated;
grant select on public.polls, public.poll_votes to service_role;

drop function if exists public.get_active_poll();
create function public.get_active_poll()
returns table(poll_id text, question text, options text[], my_choice smallint, pct numeric[])
language plpgsql stable security definer
set search_path = public
as $$
#variable_conflict use_column
declare
  p    public.polls%rowtype;
  mine smallint;
  tot  numeric;
begin
  select * into p from public.polls pl where pl.active order by pl.created_at desc limit 1;
  if not found then return; end if;
  if (select auth.uid()) is not null then
    select v.choice into mine from public.poll_votes v
     where v.poll_id = p.id and v.user_id = (select auth.uid());
  end if;
  poll_id := p.id; question := p.question; options := p.options; my_choice := mine;
  if mine is not null then
    select count(*) into tot from public.poll_votes v where v.poll_id = p.id;
    select array_agg(round(100 * coalesce(c.n, 0) / tot, 1) order by i.i) into pct
      from generate_series(0, cardinality(p.options) - 1) as i(i)
      left join (select v.choice, count(*)::numeric n from public.poll_votes v
                  where v.poll_id = p.id group by v.choice) c on c.choice = i.i;
  end if;
  return next;
end $$;

drop function if exists public.vote_poll(text, int);
create function public.vote_poll(p_poll text, p_choice int)
returns void
language plpgsql volatile security definer
set search_path = public
as $$
declare n int;
begin
  if (select auth.uid()) is null then raise exception 'sign in to vote' using errcode = '42501'; end if;
  select cardinality(pl.options) into n from public.polls pl where pl.id = p_poll and pl.active;
  if n is null then raise exception 'poll not found'; end if;
  if p_choice is null or p_choice < 0 or p_choice >= n then raise exception 'bad choice'; end if;
  -- Votes are final: a second vote is ignored, never an update.
  insert into public.poll_votes(poll_id, user_id, choice)
  values (p_poll, (select auth.uid()), p_choice)
  on conflict (poll_id, user_id) do nothing;
end $$;

revoke execute on function public.get_active_poll() from public;
revoke execute on function public.vote_poll(text, int) from public;
grant execute on function public.get_active_poll() to anon, authenticated;
grant execute on function public.vote_poll(text, int) to authenticated;

insert into public.polls(id, question, options)
values ('hyperia-second-iconic',
        'What will be the second Iconic in Hyperia City?',
        array['Oswald the Lucky Rabbit','Minnie','Snow White','Other'])
on conflict (id) do nothing;

notify pgrst, 'reload schema';
