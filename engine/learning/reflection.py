"""Agent reflections: map bounded trait and habit moves to an approved choice.

The agent never supplies text, levels or habit sets. The engine moves the served
configuration one level per adjusted trait (to the nearest approved configuration
allowed in the decision's context) and adds or drops the named habits, so a
reflection is just another pairwise preference.
"""
import torch
from engine.neural.policy import APPROVED_LEVELS, TRAITS, HABIT_IDS, mask, habits_allowed

def adjusted_choice(served, adjustments, context, habit_moves=None):
    """served: (action, habits). Returns the preferred (action, habits), or None if no
    approved move goes that way in this context."""
    action, habits = served
    if adjustments:
        delta = APPROVED_LEVELS - APPROVED_LEVELS[action]
        sign = torch.zeros(len(TRAITS))
        for t, way in adjustments.items(): sign[TRAITS.index(t)] = 1 if way == 'more' else -1
        moved = sign != 0
        ok = mask(context) & ((delta * sign)[:, moved] >= 1).all(1)
        ok[action] = False
        if not ok.any(): return None
        cost = (delta.abs() * ~moved).sum(1) + ((delta.abs() - 1) * moved).sum(1)
        cost = torch.where(ok, cost.float(), torch.tensor(float('inf')))
        action = int(torch.argmin(cost))  # lowest cost, then lowest index
    chosen = set(habits)
    for h, way in (habit_moves or {}).items():
        if way == 'more_often': chosen.add(h)
        else: chosen.discard(h)
    habits = tuple(sorted(chosen, key=HABIT_IDS.index))
    # Habits that no longer fit the moved configuration are dropped unless the agent asked for them.
    asked = {h for h, way in (habit_moves or {}).items() if way == 'more_often'}
    habits = tuple(h for h in habits if h in asked or habits_allowed([h], action, context))
    if not habits_allowed(list(habits), action, context): return None
    return None if (action, habits) == served else (action, habits)
