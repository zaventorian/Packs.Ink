-- One-time exclusion of multi-card LOT / SET / SEQUENTIAL graded listings that
-- slipped past terapeak_clean.py's LOT_RE and got attributed to a single card,
-- distorting its price history (e.g. a $24,000 "Sequential Pair" and a $15,272
-- two-card "Sequential" both landed on a single Mickey card; a $1,550
-- "Cinderella PSA 10 + PSA 10 Ursula" landed on one of them).
--
-- Mirrors the new terapeak_clean.py lot detection so a future reload stays
-- correct. Idempotent; re-run after any terapeak_load reload.
--
-- Precision (verified against live data 2026-06-24, 95 rows flagged, all genuine
-- multi-card lots; 0 single-card false positives):
--   * "sequential"  — a PSA/CGC sequential-cert SET/PAIR is always multi-card.
--   * pair|duo|trio  — NOT "quad" (that's a BGS subgrade term, e.g. "BGS 9.5 Quad").
--   * "N-card set"   — hyphen form ("32-Card Set"); the "set" is required so a
--                      single card like "#88/204-card-Psa 10" is NOT caught.
--   * Nx / xN copy multiplier ("7x", "x4", "3X") — but the title must NOT mention
--                      "sword", to spare the Genie "2X Sword" / "Double Sword Error"
--                      variant (a single tracked card that sells for $400-$2,295).
--   * two graded tokens joined by a connector ("PSA 10 + PSA 10", "X & Y", "and")
--                      — two different cards in one listing. The "+" is
--                      space-flanked so it does NOT fire on a grade like "BGS 9.5+".
--
-- Deliberately NOT excluded: bare "set" / "collector's set" / "expo set" — those
-- are the PRODUCT-ORIGIN name of valuable SINGLE cards (Elsa - Snow Queen #3/P1
-- "D23 Expo Collector's Set" trades $6,000-$12,000). Blanket-"set" would destroy
-- the price history of the priciest cards in the game. Verified: of 376
-- "collector's set / expo set" rows, only 6 (the genuine lots above) are caught.
update graded_sales gs set excluded = true
where not excluded and (
       gs.title ~* '\msequential\M'
    or gs.title ~* '\m(pair|duo|trio)\M'
    or gs.title ~* '\d+[\s-]*card[\s-]*set'
    or (gs.title ~* '\m([2-9]\s?x|x\s?[2-9])\M' and gs.title !~* 'sword')
    or (
         gs.title ~* '(&|\sand\s|\splus\s| \+ )'
         and (select count(*) from regexp_matches(
                gs.title,
                '(PSA|CGC|BGS|SGC|TAG|BECKETT)\s*\.?\s*(10|9\.5|9|8\.5|8|7\.5|7)',
                'gi')) >= 2
       )
);

select public.refresh_graded_sales_rollup();
