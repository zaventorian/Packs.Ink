-- One-time data fix (2026-06-24): graded copies of the split-printing variant
-- cards (Genie "Two Swords", Peter Pan "Text Error") were saved under the raw
-- catalog CLONE card_id (`<base>::variant::<slug>`), which has NO graded market
-- of its own — its sales live on the BASE card_id under a distinct `printing`.
-- So those owned slabs showed the base's Normal price and couldn't be told apart
-- from the plain version in the collection.
--
-- Remap each clone-keyed slot onto (base card_id, variant printing) where the
-- graded_sales / graded_sales_rollup data actually lives. Idempotent.
-- The client no longer creates these (canonicalGradedSlot in Index.html remaps
-- any ::variant:: pick to base + variant printing at the write layer), so this
-- is purely retroactive cleanup.

-- Genie - On the Job (Ench #209): clone -> base + 'Two Swords'
insert into graded_collection_items
  (user_id, card_id, printing, grader, grade, quantity, amount_paid, acquired_date, custom_value, updated_at)
select user_id, 'crd_ae7e91462bfc4861bbf97e99ed53a1c1', 'Two Swords', grader, grade,
       max(quantity), max(amount_paid), min(acquired_date), max(custom_value), now()
from graded_collection_items
where card_id = 'crd_ae7e91462bfc4861bbf97e99ed53a1c1::variant::two-swords-variant'
group by user_id, grader, grade
on conflict (user_id, card_id, printing, grader, grade) do update
  set quantity = greatest(graded_collection_items.quantity, excluded.quantity), updated_at = now();
delete from graded_collection_items
where card_id = 'crd_ae7e91462bfc4861bbf97e99ed53a1c1::variant::two-swords-variant';

-- Peter Pan - Pirate's Bane (Ench #215): clone -> base + 'Text Error'
insert into graded_collection_items
  (user_id, card_id, printing, grader, grade, quantity, amount_paid, acquired_date, custom_value, updated_at)
select user_id, 'crd_b5e74b533270492982dff9472aee8664', 'Text Error', grader, grade,
       max(quantity), max(amount_paid), min(acquired_date), max(custom_value), now()
from graded_collection_items
where card_id = 'crd_b5e74b533270492982dff9472aee8664::variant::text-error'
group by user_id, grader, grade
on conflict (user_id, card_id, printing, grader, grade) do update
  set quantity = greatest(graded_collection_items.quantity, excluded.quantity), updated_at = now();
delete from graded_collection_items
where card_id = 'crd_b5e74b533270492982dff9472aee8664::variant::text-error';
