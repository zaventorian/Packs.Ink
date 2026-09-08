-- Intentional draws on elo_matches.
--
-- An ID is a scheduling decision, not evidence about who is better, so it must
-- not move a rating. elo.py already holds both ratings flat for a flagged match
-- while still writing score = 0.5 — every W/L/D count and mw_pct in the views
-- here is derived from elo_ratings.score, so the draw stays in the record and
-- only the rating stops moving. This column is what lets the SITE say which
-- draws those were, rather than showing a D that silently behaved differently.
--
-- Written by scripts/elo/flag_intentional_draws.py and carried up by
-- scripts/export_elo_to_supabase.py, which probes for this column and exports
-- without it until this migration is applied.

alter table public.elo_matches
  add column if not exists is_intentional_draw boolean not null default false;

comment on column public.elo_matches.is_intentional_draw is
  'Draw agreed rather than played. Scored 0.5 in elo_ratings like any draw, but '
  'the rating is held flat, so it counts in the record and not in the rating.';

-- The site asks "which of this player's draws were agreed", never "find every
-- ID across the whole table", so the index is only worth its keep on the true
-- rows — which are a small minority of matches.
create index if not exists elo_matches_intentional_draw_idx
  on public.elo_matches (event_id)
  where is_intentional_draw;

notify pgrst, 'reload schema';
