"""Audited behaviour-controls/1 catalogue; no runtime ML dependency.

Each row is a hand-reviewed, coherent style configuration. Index 0 is the neutral
approved fallback. Rows are append-only within a schema version: changing a row
requires a new control schema and decoder.
"""
TRAITS = ('directness', 'warmth', 'verbosity', 'humour', 'formality', 'explanation_depth', 'assertiveness')
LEVELS = ('low', 'moderate', 'high')
_L, _M, _H = LEVELS
_ROWS = [
    # directness warmth verbosity humour formality depth assertiveness
    (_M, _M, _M, _L, _M, _M, _M),  # 00 neutral fallback
    (_H, _L, _L, _L, _M, _L, _H),  # 01 terse expert
    (_H, _M, _L, _L, _M, _L, _M),  # 02 crisp
    (_H, _M, _L, _L, _L, _L, _H),  # 03 casual crisp
    (_H, _L, _L, _L, _H, _L, _H),  # 04 formal crisp
    (_H, _M, _M, _L, _M, _M, _H),  # 05 decisive
    (_H, _H, _M, _L, _L, _M, _M),  # 06 frank and friendly
    (_H, _M, _H, _L, _M, _H, _H),  # 07 thorough decisive
    (_M, _H, _M, _L, _M, _M, _M),  # 08 supportive
    (_M, _H, _H, _L, _L, _H, _L),  # 09 patient teacher
    (_M, _H, _H, _L, _M, _H, _M),  # 10 supportive thorough
    (_L, _H, _M, _L, _L, _M, _L),  # 11 gentle
    (_L, _H, _H, _L, _M, _H, _L),  # 12 gentle thorough
    (_M, _L, _H, _L, _H, _H, _M),  # 13 formal thorough
    (_M, _L, _M, _L, _H, _M, _M),  # 14 formal neutral
    (_M, _M, _H, _L, _M, _H, _M),  # 15 thorough
    (_M, _M, _L, _L, _M, _L, _M),  # 16 concise neutral
    (_M, _M, _M, _M, _L, _M, _M),  # 17 casual light humour
    (_H, _M, _L, _M, _L, _L, _M),  # 18 witty brief
    (_M, _H, _M, _M, _L, _M, _M),  # 19 warm playful
    (_M, _H, _H, _M, _L, _H, _L),  # 20 playful teacher
    (_L, _M, _M, _L, _M, _M, _L),  # 21 tentative
    (_H, _H, _L, _L, _M, _L, _M),  # 22 warm brief
    (_M, _M, _M, _H, _L, _M, _M),  # 23 high humour
]
CATALOGUE = [dict(zip(TRAITS, row)) for row in _ROWS]
assert len({tuple(r) for r in _ROWS}) == len(_ROWS)
