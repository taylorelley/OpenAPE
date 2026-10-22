"""Natural maturation: slow, bounded drift of approved state with no feedback.

Maturation is not reward. It never reads task outcomes, engagement or text. It is a
fixed, documented prior driven only by accumulated experience (ended sessions that
received an active decision), and it follows a square-root curve:

    m(t) = sqrt(min(t / T, 1))

so a persona changes often and noticeably early on, then ever more rarely and by
ever smaller amounts. Development is complete at t >= T, but plasticity never reaches
zero: growth g(t) = m(t) + ADULT_RATE * max(0, t - T) / T keeps a slow adult slope.
Each step may move the latent by at most (g - g_last) * BUDGET[scope], so
developmental drift is bounded by the budget and adult drift accrues slowly. The
horizon T is the configurable maturation rate.

t is effective experience (engine.learning.development): novel sessions count more
than repeated ones and life events raise it for a while. Steps fall on whole units of
it, so a backlog is replayed as the same sequence of steps.
"""
import math
import torch
from engine.neural.policy import features, level_mask
from engine.neural.profiles import reference_contexts, trait_targets, habit_targets, context_table, context_habits, distribution_loss
from engine.learning.trainer import state_norm_limit

# (relationship horizon, core horizon) in ended sessions.
RATES = {'fast': (10, 30), 'normal': (30, 100), 'slow': (100, 300)}
BUDGET = {'relationship': 1.0, 'core': 0.6}
MIN_STEP = 0.05  # smallest growth increase worth a new version
ADULT_RATE = 0.15  # adult growth per further horizon of experience
FAMILIARITY_MIX = 0.3
HABIT_BETA, HABIT_TEMPERATURE = 0.5, 0.9
REFERENCE_HOST = {'provider_family': 'other', 'adapter_id': 'maturation'}

def horizons(rate):
    """Normalise a rate preset or explicit horizons to the stored form."""
    if rate is None or isinstance(rate, str):
        name = rate if rate in RATES else 'normal'
        relationship, core = RATES[name]
        return {'rate': name, 'relationship': relationship, 'core': core}
    return {'rate': 'custom', 'relationship': int(rate['relationship_horizon']), 'core': int(rate['core_horizon'])}

def public_rate(stored):
    if stored['rate'] in RATES: return stored['rate']
    return {'relationship_horizon': stored['relationship'], 'core_horizon': stored['core']}

def maturity(t, horizon):
    return math.sqrt(min(max(t, 0) / horizon, 1.0))

def growth(t, horizon):
    return maturity(t, horizon) + ADULT_RATE * max(0.0, t - horizon) / horizon

def due(t, horizon, last_g, last_t=0):
    """Growth level of the next step on the curve, or None if none is due.

    Steps walk the curve in order: if several sessions ended while the worker was
    busy, this returns the first threshold crossed, not the current growth, so a
    backlog is replayed as the same sequence of shrinking steps instead of one jump."""
    step = due_step(t, horizon, last_g, last_t)
    return step and step[1]

def due_step(t, horizon, last_g, last_t=0):
    """(experience at which the next step falls, its growth), or None."""
    for s in range(int(last_t) + 1, int(t + 1e-9) + 1):
        g = growth(s, horizon)
        if g - last_g >= MIN_STEP - 1e-9 or (g >= 1.0 and last_g < 1.0 - 1e-9): return s, g
    return None

def step_budget(scope, g, last_g):
    return max(0.0, g - last_g) * BUDGET[scope]

def familiarity_profile(m):
    """Growing familiarity with one user: warmer, less formal, a little briefer."""
    return {'warmth': (3, 1.0 * m), 'formality': (1, 0.8 * m), 'verbosity': (1, 0.4 * m)}

def fit_toward(decoder, core, rel, scope, rows, budget, steps=100):
    """Fit one latent (decoder frozen) toward weighted per-trait level and habit targets,
    then project onto the step budget and the absolute state-norm bound. rows:
    (context, host, (trait target (7, 5), habit target (H,)), weight)."""
    if decoder.model is None: raise ValueError('trained decoder required')
    original = (core if scope == 'core' else rel).clone()
    feats = torch.stack([features(c, h) for c, h, *_ in rows]); lm = torch.stack([level_mask(c) for c, *_ in rows])
    tt = torch.stack([t[0] for *_, t, _ in rows]); ht = torch.stack([t[1] for *_, t, _ in rows])
    weights = torch.tensor([w for *_, w in rows]); weights = weights / weights.sum()
    x = original.clone().requires_grad_(True)
    optimizer = torch.optim.Adam([x], lr=0.05)
    for _ in range(steps):
        optimizer.zero_grad()
        t, h = decoder.batch(x, rel, feats, lm) if scope == 'core' else decoder.batch(core, x, feats, lm)
        loss = (weights * distribution_loss(t, h, tt, ht)).sum()
        loss.backward(); optimizer.step()
        with torch.no_grad():
            delta = x - original
            x.copy_(original + delta * min(1.0, budget * 0.98 / (float(delta.norm()) + 1e-8)))
            x.mul_(min(1.0, state_norm_limit(decoder, scope) / (float(x.norm()) + 1e-8)))
    return x.detach()

def current(decoder, core, rel, context, host):
    t, h = decoder.heads(core, rel, context, host)
    return t.exp(), torch.sigmoid(h)

def familiarize(decoder, core, rel, profile, m, budget, accommodation=None, weights=None):
    """Relationship step: nudge toward the archetype plus familiarity at maturity m and
    accommodation to the user, mixed with the current policy so learned feedback is
    preserved. Optional per-trait weights apply development's sensitive periods."""
    rows = []; scale = (lambda p: {t: (v, w * weights.get(t, 1.0)) for t, (v, w) in p.items()}) if weights else (lambda p: p)
    profiles = [profile, scale(familiarity_profile(m))] + ([scale(accommodation)] if accommodation else [])
    with torch.no_grad():
        for context in reference_contexts():
            ct, ch = current(decoder, core, rel, context, REFERENCE_HOST)
            target = ((1 - FAMILIARITY_MIX) * ct + FAMILIARITY_MIX * trait_targets(context, *profiles), (1 - FAMILIARITY_MIX) * ch + FAMILIARITY_MIX * habit_targets(context, *profiles))
            rows.append((context, REFERENCE_HOST, target, 1.0))
    return fit_toward(decoder, core, rel, 'relationship', rows, budget)

def habituate(decoder, core, experienced, budget, weights=None):
    """Core step: lean into the norms of the contexts this persona actually works in
    (weighted by salience) and settle slightly; reference contexts anchor the rest.
    Optional per-trait weights apply development's sensitive periods."""
    rel = torch.zeros(32); rows = []
    with torch.no_grad():
        for context, host, count in experienced:
            t, h = decoder.heads(core, rel, context, host)
            target = (torch.softmax(((t + HABIT_BETA * context_table(context, weights)) / HABIT_TEMPERATURE).masked_fill(~level_mask(context), float('-inf')), 1),
                torch.sigmoid(h + HABIT_BETA * context_habits(context)))
            rows.append((context, host, target, float(count)))
        anchor = sum(c for *_, c in experienced) * 0.25 / len(reference_contexts())
        for context in reference_contexts():
            rows.append((context, REFERENCE_HOST, current(decoder, core, rel, context, REFERENCE_HOST), anchor))
    return fit_toward(decoder, core, rel, 'core', rows, budget)
