-- Re-classify Lorcana Challenge Promo C1 sale printings from the SAVED slab OCR
-- (graded_sales.slab_ocr, migration 80) — no re-OCR needed. The slab label prints
-- the tier: "PRIZE WALL EXCLUSIVE" / PARTICIPATION / SIDE EVENT = Non-Foil; TOP PRIZE
-- / SERIALIZED / CHALLENGE EVENT / CHAMP / WORLD CHAMP = Foil. (The original
-- classify_c1_printing.py run MISSED "prize wall" → ~100 Prize Wall sales landed in
-- Unknown; this fix recovered them, e.g. Cinderella Stouthearted PSA 10 Non-Foil
-- 11 -> 103.) Re-run after any reload that re-OCRs/re-loads C1.
update graded_sales set printing='Foil'
where card_id in (select id from cards where set_id='set_e0eb34fc0fbb446886f84c34381d4dce')
  and not excluded and slab_ocr ~* 'top\s*[0-9]*\s*prize|top\s*(4|8|16|32|64)\y|challenge\s*event|champ|seriali[sz]ed|world\s*champ';

update graded_sales set printing='Non-Foil'
where card_id in (select id from cards where set_id='set_e0eb34fc0fbb446886f84c34381d4dce')
  and not excluded and slab_ocr ~* 'prize\s*wall|participation|side\s*event'
  and slab_ocr !~* 'top\s*[0-9]*\s*prize|seriali[sz]ed|world\s*champ';

-- Title fallback where the slab OCR was empty/unreadable
update graded_sales set printing='Foil'
where card_id in (select id from cards where set_id='set_e0eb34fc0fbb446886f84c34381d4dce')
  and not excluded and printing is null
  and title ~* 'top\s*prize|seriali[sz]ed|world\s*champ' and title !~* 'prize\s*wall|non.?foil';
update graded_sales set printing='Non-Foil'
where card_id in (select id from cards where set_id='set_e0eb34fc0fbb446886f84c34381d4dce')
  and not excluded and printing is null
  and title ~* 'prize\s*wall|participation|non.?foil|side\s*event';

select public.refresh_graded_sales_rollup();
