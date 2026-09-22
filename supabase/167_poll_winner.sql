-- 167: a poll can be CLOSED with a declared winner, instead of just vanishing.
--
-- 161 gave a poll exactly two states: active (get_active_poll returns it) and
-- not (it disappears). So "end the poll and say who won" had no home — the only
-- way to end one was to make it invisible, which throws away the answer at the
-- moment the answer is the interesting part.
--
-- ⚠ Kept DATA-DRIVEN, because that is 161's whole design ("the next poll is an
-- INSERT, not a deploy"). Hardcoding this result in the client would mean the
-- next poll's winner needs a deploy, and the one after that, forever. Both the
-- winning option AND its picture live here.
--
-- ⚠ winner_image is a URL, NOT a card id, and that is deliberate. The obvious
-- choice is the winning card's id, but Hyperia City's cards are prestage rows
-- (crd_prestage_set14_*) that retire_prestaged DELETES and replaces the day
-- Lorcast publishes them — and it repoints deck/collection/scan references, not
-- polls, so a stored card id would silently break. The storage path is the
-- stable thing: import_official_set overwrites card-art/set14/242.jpg IN PLACE
-- with official art, so this URL keeps working and quietly gets better.
--
-- ⚠ Once a winner is declared the results become PUBLIC. 161 returns pct only
-- to someone who voted, which is right while a poll is live (it stops the
-- standings steering later votes) and wrong once it is closed: announcing a
-- winner and then hiding the split from the people who did not vote is a
-- worse answer than showing nothing.

alter table public.polls add column if not exists winner       smallint;
alter table public.polls add column if not exists winner_image text;

-- A winner must be a real option, and a URL must look like one.
alter table public.polls drop constraint if exists polls_winner_range;
alter table public.polls add constraint polls_winner_range
  check (winner is null or (winner >= 0 and winner < cardinality(options)));
alter table public.polls drop constraint if exists polls_winner_image_url;
alter table public.polls add constraint polls_winner_image_url
  check (winner_image is null or winner_image ~ '^https://');

-- RETURNS TABLE gains columns, so the function has to be dropped first.
drop function if exists public.get_active_poll();
create function public.get_active_poll()
returns table(poll_id text, question text, options text[], my_choice smallint,
              pct numeric[], winner smallint, winner_image text)
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
  winner := p.winner; winner_image := p.winner_image;
  -- Results to voters while it is live; to everyone once it is closed.
  if mine is not null or p.winner is not null then
    select count(*) into tot from public.poll_votes v where v.poll_id = p.id;
    if tot > 0 then
      select array_agg(round(100 * coalesce(c.n, 0) / tot, 1) order by i.i) into pct
        from generate_series(0, cardinality(p.options) - 1) as i(i)
        left join (select v.choice, count(*)::numeric n from public.poll_votes v
                    where v.poll_id = p.id group by v.choice) c on c.choice = i.i;
    end if;
  end if;
  return next;
end $$;

-- A closed poll takes no more votes. Without this the box would stop OFFERING
-- the buttons while the RPC still happily accepted a vote from anything that
-- called it directly.
drop function if exists public.vote_poll(text, int);
create function public.vote_poll(p_poll text, p_choice int)
returns void
language plpgsql volatile security definer
set search_path = public
as $$
declare n int; w smallint;
begin
  if (select auth.uid()) is null then raise exception 'sign in to vote' using errcode = '42501'; end if;
  select cardinality(pl.options), pl.winner into n, w
    from public.polls pl where pl.id = p_poll and pl.active;
  if n is null then raise exception 'poll not found'; end if;
  if w is not null then raise exception 'this poll has closed'; end if;
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

-- Close the Hyperia City poll. Option 3 is 'Cinderella' (162 added it), and the
-- answer is Hyperia City #242 Cinderella - Unintentional Icon: every recent set
-- numbers its two Iconics at the very top (Wilds Unknown 241-242, Attack of the
-- Vine! 244-245), so #242 is the SECOND Iconic, which is what the poll asked.
update public.polls
   set winner = 3,
       winner_image = 'https://umwqowkiatjjltologrd.supabase.co/storage/v1/object/public/card-art/set14/242.jpg'
 where id = 'hyperia-second-iconic'
   and options[4] = 'Cinderella';   -- 1-based in SQL; belt and braces on the index

notify pgrst, 'reload schema';
