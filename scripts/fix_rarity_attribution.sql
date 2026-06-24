-- fix_rarity_attribution.sql — one-time correction (2026-06-23).
-- The matcher wasn't rarity-aware, so Enchanted/Iconic/Epic sales were attaching
-- to the BASE card (e.g. Enchanted "Hades - Infernal Schemer" sales landed on the
-- Fabled Legendary #151 instead of the Fabled Enchanted #237). terapeak_match.py
-- is now rarity-aware (title_rarity + a rarity gate in best_match); this fixes the
-- already-loaded rows for the SAFE cases: a chase-rarity title where exactly one
-- same-(name, version, set) card of that rarity exists (so reprints stay in their
-- own set, just corrected to the right rarity). 2,375 rows.
--
-- NOT handled here (need the rarity-aware matcher re-run, or set disambiguation):
--   • chase-title sales whose correct card is in a DIFFERENT set than matched
--   • plain-title sales that landed on a chase card (base ↔ chase, ~2,079)
--   • normal vs foil splitting (esp. Lorcana Challenge Promos)
--   • reprint set disambiguation (TFC vs Fabled, etc.)

update graded_sales g set card_id = (
  select t.id from cards t
  where t.name = cur.name
    and coalesce(t.version,'') = coalesce(cur.version,'')
    and t.set_id = cur.set_id
    and t.rarity = (case when g.title ~* '\yenchanted\y' then 'Enchanted'
                         when g.title ~* '\yiconic\y'    then 'Iconic'
                         when g.title ~* '\yepic\y'      then 'Epic' end)
  limit 1)
from cards cur
where g.card_id = cur.id and not g.excluded
  and ( (g.title ~* '\yenchanted\y' and cur.rarity <> 'Enchanted')
     or (g.title ~* '\yiconic\y'    and cur.rarity <> 'Iconic')
     or (g.title ~* '\yepic\y'      and cur.rarity <> 'Epic') )
  and (select count(*) from cards t
       where t.name = cur.name and coalesce(t.version,'') = coalesce(cur.version,'')
         and t.set_id = cur.set_id
         and t.rarity = (case when g.title ~* '\yenchanted\y' then 'Enchanted'
                              when g.title ~* '\yiconic\y'    then 'Iconic'
                              when g.title ~* '\yepic\y'      then 'Epic' end)) = 1;

select public.refresh_graded_sales_rollup();
