-- 162: add Cinderella to the Hyperia City Iconic poll, before "Other".
-- A vote is stored as an option INDEX, so inserting before "Other" moves
-- Other from 3 to 4: existing votes for it are shifted in the same
-- transaction. Guarded, so re-running is a no-op.

begin;

update public.poll_votes v
   set choice = 4
  from public.polls p
 where p.id = 'hyperia-second-iconic'
   and v.poll_id = p.id
   and v.choice = 3
   and not ('Cinderella' = any(p.options));

update public.polls
   set options = array['Oswald the Lucky Rabbit','Minnie','Snow White','Cinderella','Other']
 where id = 'hyperia-second-iconic'
   and not ('Cinderella' = any(options));

commit;
