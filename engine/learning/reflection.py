"""Agent reflections: map a bounded trait adjustment to an approved catalogue row.

The agent never supplies text or a control index. The engine moves the served row
one level per adjusted trait and picks the nearest approved row that is valid in
the decision's context, so a reflection is just another pairwise preference.
"""
from engine.neural.policy import CATALOGUE, mask

LEVEL = {'low': 0, 'moderate': 1, 'high': 2}

def adjusted_control(served, adjustments, context):
    base = CATALOGUE[served]; allowed = mask(context); best = None
    for i, row in enumerate(CATALOGUE):
        if i == served or not allowed[i]: continue
        moves = {t: LEVEL[row[t]] - LEVEL[base[t]] for t in row}
        if not all(moves[t] * (1 if way == 'more' else -1) >= 1 for t, way in adjustments.items()): continue
        cost = sum(abs(v) for t, v in moves.items() if t not in adjustments) + sum(abs(moves[t]) - 1 for t in adjustments)
        if best is None or (cost, i) < best: best = (cost, i)
    return None if best is None else best[1]
