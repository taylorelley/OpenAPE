"""Habit learning, separate from the latent.

A habit preference (one choice keeps the same trait configuration and adds or drops a
habit, or the habit part of any pairwise preference) moves a per-version habit bias,
never the latent, so "end with next steps" does not drag directness or warmth. The bias
is recomputed from all valid habit evidence of the scope, so revoking evidence simply
removes its contribution:

    bias[h] = clip(HABIT_STEP * sum(weight * signal_h), -HABIT_MAX, HABIT_MAX)

where signal_h is +1 when the preferred choice has the habit and the rejected one does
not, and -1 the other way round. Weights are the recency and influence weights automatic
learning uses, except that a person's request counts at least fully: one explicit
request reaches the cap, which selects a habit unless the decoder strongly disfavours it.
An agent's reflections alone move a habit at most REFLECTION_MAX. A new bias is promoted when it
moves some habit by at least HABIT_MIN_CHANGE and passes the bounds gate.
"""
import torch
from protocol.catalogue import HABIT_IDS
from engine.learning.trainer import pair

HABIT_STEP, HABIT_MAX, HABIT_MIN_CHANGE = 4.0, 4.0, 0.25
# An agent's own reflections can be steered by text it reads (prompt injection), so on
# their own they move a habit at most halfway; people's feedback has the full range.
REFLECTION_MAX = HABIT_MAX / 2

def signal(e):
    """{habit: +1 or -1} from one pairwise preference, or {} when habits do not differ."""
    p = pair(e)
    if p is None: return {}
    preferred, rejected = set(p[0][1]), set(p[1][1])
    return {h: 1 for h in preferred - rejected} | {h: -1 for h in rejected - preferred}

def bias_from(examples):
    """The habit bias the scope's valid evidence supports, and the evidence it used."""
    people, agents = torch.zeros(len(HABIT_IDS)), torch.zeros(len(HABIT_IDS)); used = []
    for e in examples:
        s = signal(e)
        if not s: continue
        used.append(e['feedback_id']); agent = e.get('source') == 'agent_reflection'
        # A person asking for a habit is taken at their word (weight at least 1).
        w = float(e.get('weight', 1.0)) if agent else max(1.0, float(e.get('weight', 1.0)))
        for h, sign in s.items(): (agents if agent else people)[HABIT_IDS.index(h)] += w * sign
    return (HABIT_STEP * people + (HABIT_STEP * agents).clamp(-REFLECTION_MAX, REFLECTION_MAX)).clamp(-HABIT_MAX, HABIT_MAX), used

def session_offset(examples):
    """This session's habit offset: a habit asked for (or against) in the session applies at
    once, fully, until the session ends; the durable bias above is what persists."""
    net, _ = bias_from([{**e, 'weight': 1.0} for e in examples])
    return torch.sign(net) * HABIT_MAX

def gate(old, new):
    """Bounds gate for a habit-bias candidate: finite, within the cap, and a real change."""
    change = (new - old).abs()
    checks = {'finite': bool(torch.isfinite(new).all()) and new.shape == old.shape, 'bounded': float(new.abs().max()) <= HABIT_MAX + 1e-6,
        'changed': float(change.max()) >= HABIT_MIN_CHANGE}
    moved = {h: round(float(new[i]), 3) for i, h in enumerate(HABIT_IDS) if float(change[i]) >= HABIT_MIN_CHANGE}
    return {'eligible': all(checks.values()), 'checks': checks, 'moved': moved, 'evidence': 'explicit consented habit preferences; bounded rule, not a fitted model'}
