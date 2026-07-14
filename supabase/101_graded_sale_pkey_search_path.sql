-- graded_sale_pkey is a pure IMMUTABLE SQL helper (no table access), but the
-- Supabase linter flags any function without a pinned search_path
-- (0011_function_search_path_mutable — the last remaining WARN of that kind).
-- Pinning is harmless for a pure function and silences the advisor.
alter function public.graded_sale_pkey(p_printing text, p_split boolean, p_foilsplit boolean)
  set search_path = public;

notify pgrst, 'reload schema';
