-- Split the Genie "Two Swords" and Peter Pan "Text Error" graded sales out from the
-- normal Enchanted print they share a card_id with. These are CUSTOM_VARIANTS (error
-- prints Lorcast doesn't index) — rather than insert separate card rows + fight the
-- client-side clone, we reuse the printing-split infra: tag the variant sales with a
-- printing value and flag the base Enchanted card split_printing=true so the rollup
-- (and the card-detail toggle / screener) separate them. Re-run after any reload.
--   Genie - On the Job, Enchanted #209 (First Chapter) = crd_ae7e91462bfc4861bbf97e99ed53a1c1
--   Peter Pan - Pirate's Bane, Enchanted #215 (Inklands) = crd_b5e74b533270492982dff9472aee8664
-- (mirror crd ids in Index.html SPLIT_PRINTING_CARD_IDS).

update graded_sales set card_id='crd_ae7e91462bfc4861bbf97e99ed53a1c1', printing='Two Swords'
where not excluded and title ~* 'genie' and title ~* 'two\s*sword|double\s*sword'
  and (card_id='crd_ae7e91462bfc4861bbf97e99ed53a1c1' or card_id is null);
update graded_sales set printing='Normal'
where not excluded and card_id='crd_ae7e91462bfc4861bbf97e99ed53a1c1' and coalesce(printing,'') <> 'Two Swords';

update graded_sales set card_id='crd_b5e74b533270492982dff9472aee8664', printing='Text Error'
where not excluded and title ~* 'peter pan' and title ~* 'text\s*error|misprint'
  and (card_id='crd_b5e74b533270492982dff9472aee8664' or card_id is null);
update graded_sales set printing='Normal'
where not excluded and card_id='crd_b5e74b533270492982dff9472aee8664' and coalesce(printing,'') <> 'Text Error';

update cards set split_printing=true
where id in ('crd_ae7e91462bfc4861bbf97e99ed53a1c1','crd_b5e74b533270492982dff9472aee8664');

select public.refresh_graded_sales_rollup();
