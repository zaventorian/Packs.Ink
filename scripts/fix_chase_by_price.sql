-- fix_chase_by_price.sql — Option B: price-aware base→chase re-attribution.
-- When a graded sale matched a BASE-rarity card (Common…Legendary) that has a
-- single chase twin (same name+version, Enchanted/Iconic/Epic) AND the sale
-- price is implausibly high for a base card (>= $800 — the 99th percentile of
-- clean base-card PSA/CGC 10 sales is ~$800), the title almost certainly omitted
-- the rarity word/collector# and the sale is really the chase. Move it.
--
-- Safe by construction: only fires above the base-card price ceiling, only when
-- exactly ONE chase twin exists (no ambiguity). ~89 sales / 19 cards at first run
-- (Buzz Lightyear Jungle Ranger, Merida Formidable Archer, Mickey Brave Little
-- Prince, Minnie Sweetheart Princess, Elsa Snow Queen, Ariel Ethereal Voice, …).
--
-- Re-run after any terapeak_load.py reload (the title-only matcher re-creates the
-- base attribution; this pass corrects it). Idempotent.

with basecards as (
  select c.id base_id,
    (select t.id from cards t
       where t.name=c.name and coalesce(t.version,'')=coalesce(c.version,'')
         and t.rarity in ('Enchanted','Iconic','Epic') limit 1) chase_id,
    (select count(*) from cards t
       where t.name=c.name and coalesce(t.version,'')=coalesce(c.version,'')
         and t.rarity in ('Enchanted','Iconic','Epic')) chase_n
  from cards c where c.rarity in ('Common','Uncommon','Rare','Super Rare','Legendary')
)
update graded_sales g
set card_id = b.chase_id
from basecards b
where g.card_id = b.base_id and not g.excluded
  and g.sale_price >= 800 and b.chase_n = 1 and b.chase_id is not null;

select public.refresh_graded_sales_rollup();
