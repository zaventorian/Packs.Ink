-- fix_d23_attribution.sql — one-time correction (2026-06-23).
-- The matcher attached some D23-titled sales to the WRONG same-name card: the
-- 2022 D23 Expo Collector's Set is catalogued as Promo Set 1 #1-7, but sales
-- without a clear collector# fell through to other same-name promos (Robin Hood
-- #6 → #17 "Capable Fighter", Maleficent #5 → #22 "Uninvited", etc.), and a few
-- leaked to other sets entirely. terapeak_match.py is now fixed (D23_2022 bias),
-- so a future re-run is correct; this re-attributes the already-loaded rows.
--
-- Rule: a D23-titled sale belongs on Promo Set 1 #1-7 (2022) or D23 Collection
-- (2024). Mickey is in BOTH (PS1 #1 = 2022 Brave Little Tailor; D23C = 2024) so
-- it's disambiguated by title. Characters in neither D23 set (Minnie, Maui, …)
-- are NOT in our catalog → unmatched (card_id null). Canonical card_ids below
-- are the ones already holding the most correct D23 sales per character.

update graded_sales g set card_id = sub.new_id
from (
  select g2.item_id,
    case lower(split_part(c.name, ' - ', 1))
      when 'captain hook'           then 'crd_d41a4c80d657424e855e6e3f06caccb8' -- PS1 #7
      when 'cruella de vil'         then 'crd_09435d146f0844b3ac864e77a8ac746d' -- PS1 #4
      when 'elsa'                   then 'crd_d01b88e57beb41db97537585ad763334' -- PS1 #3
      when 'maleficent'             then 'crd_4962196e0306474a8191dc8624c1b7ef' -- PS1 #5
      when 'robin hood'             then 'crd_ca25b4581bec448ca5dc7f742615aea8' -- PS1 #6
      when 'stitch'                 then 'crd_f8c86fca55d8453da9c1c6a39a5164dd' -- PS1 #2
      when 'bruno madrigal'         then 'crd_8d986fbd95984691b7fe1a27a5e110bc' -- D23 Collection
      when 'cinderella'             then 'crd_8de3ae21bca6455bb44da9803af19ea8'
      when 'iago'                   then 'crd_a2a3f642e4704e159e4e65233aacc2fb'
      when 'mad hatter'             then 'crd_b01c656daf06443fb63d76d9df3ff108'
      when 'oswald'                 then 'crd_9093f79568f941ccaf0f4708a1b74133'
      when 'ursula'                 then 'crd_e18e96745a00405d8e927f8d4c75dc72'
      when 'vanellope von schweetz' then 'crd_b2e4820cbbda4610b54f3e9c00fa4576'
      when 'mickey mouse' then case
        when (g2.title ilike '%tailor%' or g2.title ilike '%2022%' or g2.title ilike '%expo%'
              or g2.title ilike '%/p1%' or g2.title ilike '% p1 %')
        then 'crd_a9407e39c2ee47869d7a634aa46a7f04'   -- PS1 #1 (2022)
        else 'crd_db6db54405ff449ba819ed521fae7df0' end -- D23 Collection (2024)
      else null
    end as new_id
  from graded_sales g2
  join cards c on c.id = g2.card_id
  join sets  s on s.id = c.set_id
  where g2.title ilike '%d23%'
    and not (s.name = 'Promo Set 1' and c.collector_number in ('1','2','3','4','5','6','7'))
    and s.name <> 'D23 Collection'
) sub
where g.item_id = sub.item_id and g.card_id is distinct from sub.new_id;

select public.refresh_graded_sales_rollup();
