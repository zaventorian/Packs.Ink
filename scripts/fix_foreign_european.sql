-- One-time re-exclusion of European-language graded sales (German / French / Italian)
-- that the original foreign filter missed (it only caught CN/JP/KR). Mirrors the
-- updated terapeak_load.py is_foreign_lang() exactly, so a future reload stays correct.
--
-- Precision notes (verified against live data 2026-06-23):
--   • "IT"/"ITA" codes are NOT used — uppercase "IT" is almost always an English card
--     name ("It Means No Worries", "Wreck-It Ralph", "Let It Go").
--   • bare "DE" collides with "Cruella de Vil"; guarded with `!~* 'de\s+vil'`. Genuinely
--     German Cruella sales are still caught by the german/deutsch WORD.
--   • Verified: 763 rows excluded, 0 English false positives.
update graded_sales set excluded = true
where not excluded and (
       title ~ '\yGER\y'
    or title ~ '\yDEU\y'
    or title ~* '\y(german|germany|deutsch|deutsche)\y'
    or (title ~ '\yDE\y' and title !~* 'de\s+vil')
    or title ~ '\y(FR|FRA)\y'
    or title ~* '\y(french|francais|française|francaise)\y'
    or title ~* '\y(italian|italiano|italien|italienne)\y'
    or title ~ '[äöüÄÖÜß]'   -- German umlaut/eszett — never in an English Lorcana title
    or title ~* 'flutgestalten'  -- "Floodborn" (DE), no umlaut
);

select public.refresh_graded_sales_rollup();
