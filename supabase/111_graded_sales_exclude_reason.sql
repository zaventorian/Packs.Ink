-- graded_sales.exclude_reason — WHY a row was quarantined.
--
-- `excluded` (migration 76) is a bare boolean, so once a row is hidden there is no
-- way to tell a foreign-language listing from an autograph from a mis-priced
-- outlier, and no way to reverse one class of decision without reversing all of
-- them. The reattribution script's "never un-exclude a row" rule exists purely
-- because of that ambiguity.
--
-- Recording the reason makes exclusion auditable and selectively reversible: if an
-- outlier threshold turns out too aggressive we can re-evaluate exactly the
-- reason='outlier' rows and leave every hand-reviewed decision alone.
--
-- Values in use: 'outlier' (flag_graded_outliers.py), 'lot', 'foreign', 'auto',
-- 'troll', 'cn-conflict', 'nomatch', 'manual'. Left NULL for the ~8.3k rows
-- excluded before this column existed — those stay as-is.

alter table public.graded_sales
  add column if not exists exclude_reason text;

comment on column public.graded_sales.exclude_reason is
  'Why this sale is excluded. NULL for rows excluded before migration 111, or for included rows.';

-- Partial index: we only ever filter this among already-excluded rows.
create index if not exists graded_sales_exclude_reason_idx
  on public.graded_sales (exclude_reason)
  where excluded and exclude_reason is not null;

notify pgrst, 'reload schema';
