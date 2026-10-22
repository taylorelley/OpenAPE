"""Natural maturation: slow, bounded drift of approved state with no feedback.

Maturation is not reward. It never reads task outcomes, engagement or text. It is a
fixed, documented prior driven only by accumulated experience (ended sessions that
received an active decision), and it follows a square-root curve:

    m(t) = sqrt(min(t / T, 1))

so a persona changes often and noticeably early on, then ever more rarely and by
ever smaller amounts, and is settled once t >= T. Each step may move the latent by at
most (m - m_last) * BUDGET[scope], so total maturation drift is bounded by the
budget. The horizon T is the configurable maturation rate.
"""
import math
import torch
from engine.neural.policy import CATALOGUE, SESSION_DIM, features, mask
from engine.neural.profiles import reference_contexts, target_distribution, context_score
from engine.learning.trainer import state_norm_limit

# (relationship horizon, core horizon) in ended sessions.
RATES = {'fast': (10, 30), 'normal': (30, 100), 'slow': (100, 300)}
BUDGET = {'relationship': 1.0, 'core': 0.6}
MIN_STEP = 0.05  # smallest maturity increase worth a new version
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

def due(t, horizon, last_m):
    """Maturity level of the next step on the curve, or None if none is due.

    Steps walk the curve in order: if several sessions ended while the worker was
    busy, this returns the first threshold crossed, not the current maturity, so a
    backlog is replayed as the same sequence of shrinking steps instead of one jump."""
    step = due_step(t, horizon, last_m)
    return step and step[1]

def due_step(t, horizon, last_m):
    """(experience at which the next step falls, its maturity), or None."""
    for s in range(1, t + 1):
        m = maturity(s, horizon)
        if m - last_m >= MIN_STEP - 1e-9 or (m >= 1.0 and last_m < 1.0 - 1e-9): return s, m
    return None

def step_budget(scope, m, last_m):
    return max(0.0, m - last_m) * BUDGET[scope]

def familiarity_profile(m):
    """Growing familiarity with one user: warmer, less formal, a little briefer."""
    return {'warmth': (2, 1.0 * m), 'formality': (0, 0.8 * m), 'verbosity': (0, 0.4 * m)}

def fit_toward(decoder, core, rel, scope, rows, budget, steps=100):
    """Fit one latent (decoder frozen) toward weighted target distributions, then
    project onto the step budget and the absolute state-norm bound."""
    if decoder.model is None: raise ValueError('trained decoder required')
    original = (core if scope == 'core' else rel).clone()
    feats = torch.stack([features(c, h) for c, h, *_ in rows]); masks = torch.stack([mask(c) for c, *_ in rows])
    targets = torch.stack([t for *_, t, _ in rows]); weights = torch.tensor([w for *_, w in rows]); weights = weights / weights.sum()
    other = (rel if scope == 'core' else core).expand(len(rows), -1); session = torch.zeros(len(rows), SESSION_DIM)
    x = original.clone().requires_grad_(True)
    optimizer = torch.optim.Adam([x], lr=0.05)
    for _ in range(steps):
        optimizer.zero_grad()
        own = x.expand(len(rows), -1)
        latents = (own, other) if scope == 'core' else (other, own)
        logp = torch.log_softmax(decoder.model(torch.cat((*latents, session, feats), 1)).masked_fill(~masks, -1e9), 1)
        loss = -(weights * (targets * logp.masked_fill(targets == 0, 0)).sum(1)).sum()
        loss.backward(); optimizer.step()
        with torch.no_grad():
            delta = x - original
            x.copy_(original + delta * min(1.0, budget * 0.98 / (float(delta.norm()) + 1e-8)))
            x.mul_(min(1.0, state_norm_limit(decoder, scope) / (float(x.norm()) + 1e-8)))
    return x.detach()

def familiarize(decoder, core, rel, profile, m, budget):
    """Relationship step: nudge toward the archetype plus familiarity at maturity m,
    mixed with the current policy so learned feedback is preserved."""
    rows = []
    with torch.no_grad():
        for context in reference_contexts():
            current = torch.softmax(decoder.logits(core, rel, context, REFERENCE_HOST), 0)
            target = (1 - FAMILIARITY_MIX) * current + FAMILIARITY_MIX * target_distribution(context, profile, familiarity_profile(m))
            rows.append((context, REFERENCE_HOST, target, 1.0))
    return fit_toward(decoder, core, rel, 'relationship', rows, budget)

def habituate(decoder, core, experienced, budget):
    """Core step: lean into the norms of the contexts this persona actually works in
    (weighted by frequency) and settle slightly; reference contexts anchor the rest."""
    rel = torch.zeros(32); rows = []
    norms = lambda context: torch.tensor([context_score(c, context) for c in CATALOGUE])
    with torch.no_grad():
        for context, host, count in experienced:
            logp = torch.log_softmax(decoder.logits(core, rel, context, host), 0)
            target = torch.softmax(((logp + HABIT_BETA * norms(context)) / HABIT_TEMPERATURE).masked_fill(~mask(context), float('-inf')), 0)
            rows.append((context, host, target, float(count)))
        anchor = sum(c for *_, c in experienced) * 0.25 / len(reference_contexts())
        for context in reference_contexts():
            rows.append((context, REFERENCE_HOST, torch.softmax(decoder.logits(core, rel, context, REFERENCE_HOST), 0), anchor))
    return fit_toward(decoder, core, rel, 'core', rows, budget)
