-- One-time exclusion of autographed / artist-signed / sketch graded sales. An artist
-- signature or 1/1 sketch sells far above a plain graded copy, so they distort a card's
-- price history. Mirrors terapeak_load.py is_autograph() so a future reload stays correct.
--
-- Precision note (verified against live data 2026-06-23): bare "1/1" is NOT matched —
-- it collides with "Pop 1/1" (a normal card that's merely the only one PSA-graded; all
-- 20 such rows survive). Verified: 1,358 rows excluded, 0 Pop-1/1 false positives.
update graded_sales set excluded = true
where not excluded and (
       title ~* '\y(auto|autograph|signed|signature|jsa|sketch|witnessed|inscribed)\y'
    or title ~* 'psa/?dna'
    or title ~* 'hand.?drawn'
);

select public.refresh_graded_sales_rollup();
