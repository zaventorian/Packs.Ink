-- Regional-exclusive recovery. The foreign-language filter (correctly) excludes
-- Chinese/Japanese sales as a separate market — BUT a few cards are CHINA/JAPAN
-- EXCLUSIVES we DO want (their sales are inherently CN/JP-titled). The title matcher
-- also conflated the two (Chinese "Chinajoy" sales landed on the Japanese card_id).
--
-- Today the only zh/ja-suffixed exclusives in `cards` are Mickey Mouse - True Friend
-- Promo Set 1 #25zh (Chinese) and #25ja (Japanese). Route by title language + un-exclude.
--   #25zh (Chinese)  = crd_e12a06c8188f4b1ba084b7c6b14b466d
--   #25ja (Japanese) = crd_a204f84909b6469c95cf671500547b35
-- Re-run after any terapeak_load.py reload (the title matcher re-creates the mixup).
-- TODO(matcher): teach terapeak_match.py the zh/ja split + skip foreign-exclusion for
-- a sale whose matched card is a regional exclusive, so a reload stays correct.

update graded_sales set card_id='crd_e12a06c8188f4b1ba084b7c6b14b466d', excluded=false
where title ~* 'true friend' and title ~* 'chin|chinajoy|\yzh\y|mandarin';

update graded_sales set card_id='crd_a204f84909b6469c95cf671500547b35', excluded=false
where title ~* 'true friend' and title ~* 'japan|jpn|tokyo|\yja\y'
  and title !~* 'chin|chinajoy|\yzh\y|mandarin';

-- Belt-and-suspenders: a sale correctly matched to ANY regional-exclusive card should
-- be visible (the foreignness IS the card). Exclusive cards are flagged by a zh/ja
-- collector-number suffix (Mickey True Friend #25zh/#25ja) OR a _zh/_ja card_id suffix
-- (Snow White - Unexpected Houseguest #41 = crd_promo1_41_snowwhite_uhg_ja).
update graded_sales g set excluded=false
from cards c where c.id=g.card_id and (c.collector_number ~ '(zh|ja)$' or c.id ~ '_(ja|zh)$') and g.excluded;

select public.refresh_graded_sales_rollup();
