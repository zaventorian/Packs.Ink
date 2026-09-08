"""Draws whose intent RPH does not record and no rule can reach.

The last resort, and deliberately a small list. Every automatic signal is an
inference over position and score; when a draw carries neither — a 1-1 in an
early round, at ordinary standings — the data simply does not contain the
answer, and someone who was in the room has to supply it.

⚠ This is a CODE list because a hand-edit of the DB does not survive.
`flag_intentional_draws.py` reconciles in both directions on every run
(`drop = already - want`), so a manually set `is_intentional_draw` is cleared
by the next weekly refresh, silently and with nothing red. An entry here is
re-applied every run instead.

Keyed on `(event_id, round_number, table_number)` — all three straight from
RPH, so the key survives a rebuild of the local SQLite. `match_id` would NOT:
it is a bare autoincrement rowid, so a rebuilt DB renumbers it and every
override would quietly point at a different match.

The draw report prints exactly this key. `e605246 R2 t0` is `(605246, 2, 0)`.

A key that matches no draw is an ERROR, not a shrug: an override that stopped
applying is a decision that silently reverted, which is the same failure shape
as the board freezing at set rotation.
"""

# (event_id, round_number, table_number): why, and who says so
FORCE_ID = {
    (605246, 2, 0): "I&L⟡Zaven vs I&L⟡jacobayy, 2026-06-13 Wilds Unknown SC at "
                    "Screaming Monkey Comics — agreed at the table. R2 at 3 points "
                    "each and entered 1-1, so no rule can see it. Zaven, 2026-09-08.",
}

# The other direction: a draw the rule calls intentional that was really played
# out. Empty today; kept so a false positive has somewhere to go that isn't
# retuning the rule for everyone.
FORCE_REAL = {}
