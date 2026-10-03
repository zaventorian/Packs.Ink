-- 176_into_the_inkdark_set.sql
-- A set row for Into the Inkdark (set 15), so TCGplayer group 24890 binds and
-- its sealed products stop loading with no set. Same shape as 166 (Hyperia
-- City), and code is NULL for the reason written there: a claimed code would
-- make load_lorcast skip the real set, and all its cards, the day Lorcast
-- publishes it. released_at is the group's publishedOn on TCGplayer; it is a
-- placeholder for sorting, NOT a published release date, and nothing copies
-- it into SET_RELEASE_DATES.
insert into public.sets (id, code, name, released_at, card_count, tcgplayer_group_id)
values ('set_into_the_inkdark', null, 'Into the Inkdark', '2027-02-05', null, 24890)
on conflict (id) do update
  set name               = excluded.name,
      released_at        = excluded.released_at,
      tcgplayer_group_id = excluded.tcgplayer_group_id;
notify pgrst, 'reload schema';
