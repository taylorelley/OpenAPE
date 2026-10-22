"""Declared style profiles: synthetic decoder supervision and explicit seed initialization.

A profile maps traits to (target level 0-4, weight) and may carry habit preferences as
'habit:<id>' -> (1 to prefer it, 0 to avoid it; weight). Profiles are an
authoring/supervision device only; they are never stored as persona state and do not
assign meaning to latent coordinates.

Targets are factorised: each trait gets a distribution over its five levels and each
habit a probability, from documented context rules plus the profiles.
"""
import itertools
import torch
import torch.nn.functional as F
from engine.neural.policy import (TRAITS, LEVELS, NEUTRAL, HABIT_IDS, VOCAB, CORE_DIM, REL_DIM, SESSION_DIM, N_HABITS,
    features, level_mask, habit_mask, joint, mask, select_habits)

HABIT_BASE, HABIT_SCALE = -2.0, 2.0
SEEDS = {
    'concise': {'verbosity': (1, 1.6), 'explanation_depth': (1, 0.6)},
    'detailed': {'verbosity': (3, 1.6), 'explanation_depth': (3, 1.0)},
    'warm': {'warmth': (3, 1.6)},
    'reserved': {'warmth': (1, 1.4)},
    'formal': {'formality': (3, 1.6)},
    'casual': {'formality': (1, 1.4)},
    'direct': {'directness': (3, 1.6), 'assertiveness': (3, 0.6)},
    'gentle': {'directness': (1, 1.4), 'assertiveness': (1, 0.8)},
    'playful': {'humour': (2, 1.6)},
    'serious': {'humour': (0, 1.2)},
}
# Named starting personas. Each is a fixed, documented combination of seeds plus signature
# habits; the chosen archetype is the anchor that natural maturation builds on.
ARCHETYPES = {
    'balanced': (),
    'mentor': ('warm', 'detailed', 'gentle'),
    'pragmatic_engineer': ('concise', 'direct', 'casual'),
    'concierge': ('warm', 'formal'),
    'collaborator': ('warm', 'casual', 'playful'),
    'analyst': ('detailed', 'formal', 'reserved', 'serious'),
    'critic': ('direct', 'detailed', 'reserved'),
}
ARCHETYPE_HABITS = {
    'balanced': (),
    'mentor': ('concrete_examples', 'next_step', 'acknowledge_progress'),
    'pragmatic_engineer': ('risks_first', 'precise_terms', 'next_step'),
    'concierge': ('acknowledge_constraints', 'next_step', 'structured'),
    'collaborator': ('light_aside', 'tradeoffs', 'next_step'),
    'analyst': ('structured', 'tradeoffs', 'flag_uncertainty'),
    'critic': ('risks_first', 'tradeoffs', 'precise_terms'),
}
HABIT_WEIGHT = 1.5
CONFLICTS = [{'concise', 'detailed'}, {'warm', 'reserved'}, {'formal', 'casual'}, {'direct', 'gentle'}, {'playful', 'serious'}]

def seed_profile(seeds, archetype=None):
    seeds = set(seeds)
    for pair in CONFLICTS:
        if pair <= seeds: raise ValueError('conflicting seed preferences: ' + '+'.join(sorted(pair)))
    profile = {}
    for s in sorted(seeds):
        for trait, (target, weight) in SEEDS[s].items(): profile[trait] = (target, weight)
    for h in ARCHETYPE_HABITS.get(archetype, ()): profile['habit:' + h] = (1, HABIT_WEIGHT)
    return profile

def _pull(table, trait, target, w):
    table[TRAITS.index(trait)] -= w * 0.5 * (torch.arange(LEVELS, dtype=torch.float) - target).abs()

# Synthetic, documented context rules (CC0). Not human evidence. Each rule pulls a trait
# toward a level with a weight, and/or nudges habit logits.
def _rules(ctx):
    task, tags, out = ctx.get('task_type'), ctx.get('tags', []), []
    pull = lambda trait, target, w: out.append(('trait', trait, target, w))
    habit = lambda h, w: out.append(('habit', h, None, w))
    if task == 'code_review': pull('directness', 3, 0.8); habit('risks_first', 1.0)
    if task == 'support': pull('warmth', 3, 1.0); habit('acknowledge_constraints', 0.8)
    if task == 'creative': pull('humour', 2, 0.6)
    if task == 'research': pull('explanation_depth', 3, 0.6); habit('flag_uncertainty', 0.6)
    if task == 'coding': pull('verbosity', 1.5, 0.4)
    if task == 'debugging': pull('directness', 3, 0.6); pull('explanation_depth', 2, 0.4); habit('next_step', 0.6)
    if task == 'planning': pull('verbosity', 3, 0.6); pull('explanation_depth', 3, 0.4); habit('structured', 1.0); habit('tradeoffs', 0.6)
    if task == 'writing': pull('formality', 2.5, 0.3)
    if 'beginner' in tags: pull('explanation_depth', 3.5, 1.0); pull('warmth', 2.5, 0.5); habit('concrete_examples', 1.0); habit('plain_words', 1.0); habit('analogies', 0.5)
    if 'expert' in tags: pull('verbosity', 1, 0.8); habit('precise_terms', 1.0)
    if 'urgent' in tags: pull('verbosity', 0.5, 0.8); habit('summary_first', 1.0)
    if 'sensitive' in tags: pull('warmth', 3, 0.6)
    if 'error_present' in tags: pull('directness', 3, 0.3); pull('warmth', 2.5, 0.3)
    if 'first_turn' in tags: pull('formality', 2.5, 0.3)
    if 'long_session' in tags: pull('verbosity', 1.5, 0.3)
    if ctx.get('channel') == 'voice': pull('verbosity', 1, 0.6)
    if ctx.get('channel') == 'chat': pull('formality', 1.5, 0.3)
    if ctx.get('stakes') == 'high': pull('formality', 2.5, 0.5); pull('explanation_depth', 2.5, 0.4); habit('risks_first', 0.8); habit('flag_uncertainty', 0.8)
    if ctx.get('turn_origin') in ('tool', 'subagent', 'system'): pull('verbosity', 1, 0.5)
    return out

def context_table(ctx, weights=None):
    """(7, 5) context preference over levels, with a mild pull to the neutral default.
    Optional per-trait weights scale each trait's terms (development's sensitive periods)."""
    w = (lambda trait: weights.get(trait, 1.0)) if weights else (lambda trait: 1.0)
    table = torch.zeros(len(TRAITS), LEVELS)
    for t in TRAITS: _pull(table, t, NEUTRAL[t], 0.2 * w(t))
    for kind, name, target, weight in _rules(ctx):
        if kind == 'trait': _pull(table, name, target, weight * w(name))
    return table

def context_habits(ctx):
    x = torch.zeros(N_HABITS)
    for kind, name, _, weight in _rules(ctx):
        if kind == 'habit': x[HABIT_IDS.index(name)] += weight
    return x

def profile_table(profile):
    table = torch.zeros(len(TRAITS), LEVELS)
    for t, (target, w) in profile.items():
        if not t.startswith('habit:'): _pull(table, t, target, w)
    return table

def profile_habits(profile):
    x = torch.zeros(N_HABITS)
    for k, (target, w) in profile.items():
        if k.startswith('habit:') and k[6:] in HABIT_IDS: x[HABIT_IDS.index(k[6:])] += HABIT_SCALE * w * (1 if target else -1)
    return x

def trait_targets(ctx, *profiles, weights=None, temperature=0.35):
    """(7, 5) target level distributions for one context."""
    scores = context_table(ctx, weights) + sum((profile_table(p) for p in profiles), torch.zeros(len(TRAITS), LEVELS))
    return torch.softmax((scores / temperature).masked_fill(~level_mask(ctx), float('-inf')), 1)

def habit_logit_targets(ctx, *profiles):
    return (HABIT_BASE + context_habits(ctx) + sum((profile_habits(p) for p in profiles), torch.zeros(N_HABITS))).masked_fill(~habit_mask(ctx), -20.0)

def habit_targets(ctx, *profiles):
    return torch.sigmoid(habit_logit_targets(ctx, *profiles))

def target_choice(ctx, *profiles):
    """The profile's preferred approved configuration and habits in this context."""
    scores = joint(torch.log(trait_targets(ctx, *profiles))).masked_fill(~mask(ctx), float('-inf'))
    action = int(scores.argmax())
    return action, tuple(select_habits(habit_logit_targets(ctx, *profiles), action, ctx))

def random_context(rng):
    return dict(task_type=rng.choice(VOCAB['task_type']), channel=rng.choice(VOCAB['channel']),
        stakes=rng.choice(VOCAB['stakes']), turn_origin=rng.choices(VOCAB['turn_origin'], weights=[6, 1, 1, 1])[0],
        tags=sorted(rng.sample(VOCAB['tags'], rng.choice([0, 1, 1, 2]))))

def random_profile(rng, traits=(2, 4), habits=(0, 2)):
    chosen = rng.sample(list(TRAITS), rng.randint(*traits))
    profile = {t: (rng.choice([0, 1, 2, 3, 4]) if t != 'humour' else rng.choice([0, 0, 1, 2, 3, 4]), round(rng.uniform(0.6, 2.0), 3)) for t in chosen}
    for h in rng.sample(HABIT_IDS, rng.randint(*habits)): profile['habit:' + h] = (rng.choice([1, 1, 0]), round(rng.uniform(0.6, 1.6), 3))
    return profile

def reference_contexts():
    """Fixed, enumerable contexts used for deterministic seed fitting."""
    rows = []
    for task, stakes, tags in itertools.product(VOCAB['task_type'], ('low', 'medium', 'high'), ([], ['beginner'], ['expert'], ['urgent'])):
        rows.append(dict(task_type=task, channel='terminal', stakes=stakes, turn_origin='user', tags=tags))
    return rows

def distribution_loss(trait_logp, habit_logits, trait_target, habit_target):
    """Per-row cross-entropy to per-trait level targets plus habit binary cross-entropy."""
    ce = -(trait_target * trait_logp.masked_fill(trait_target == 0, 0)).sum((-1, -2))
    return ce + F.binary_cross_entropy_with_logits(habit_logits, habit_target, reduction='none').sum(-1)

def fit_seed_latent(decoder, seeds, steps=150, max_norm=None, profile=None, archetype=None):
    """Explicit seed initialization: fit a core latent to the declared profile (or a
    given variation of it) with the frozen decoder. Deterministic; labelled
    `seed_preferences`, never `learned`."""
    profile = seed_profile(seeds, archetype) if profile is None else profile
    if not profile or (not seeds and decoder.model is None): return torch.zeros(CORE_DIM)  # the neutral `balanced` prior
    if decoder.model is None: raise ValueError('trained decoder required for seed initialization')
    contexts = reference_contexts(); host = {'provider_family': 'other', 'adapter_id': 'seed'}
    tt = torch.stack([trait_targets(c, profile) for c in contexts]); ht = torch.stack([habit_targets(c, profile) for c in contexts])
    feats = torch.stack([features(c, host) for c in contexts]); lm = torch.stack([level_mask(c) for c in contexts])
    z = torch.zeros(CORE_DIM, requires_grad=True)
    optimizer = torch.optim.Adam([z], lr=0.05)
    for _ in range(steps):
        optimizer.zero_grad()
        t, h = decoder.batch(z, torch.zeros(REL_DIM), feats, lm)
        (distribution_loss(t, h, tt, ht).mean() + 1e-3 * z.square().sum()).backward(); optimizer.step()
    limit = max_norm or decoder.meta.get('latent_norm_limit', 6.0)
    with torch.no_grad(): z.mul_(min(1.0, limit / (float(z.norm()) + 1e-8)))
    return z.detach()

def selected(decoder, z, ctx, host, rel=None):
    """The decoder's argmax choice for latent z in one context."""
    rel = rel if rel is not None else torch.zeros(REL_DIM)
    t, h = decoder.heads(z, rel, ctx, host); action = int(joint(t).argmax())
    return action, tuple(select_habits(h, action, ctx))

def agreement(decoder, z, profile, contexts, host=None, rel=None):
    """Mean per-trait level agreement between the decoder's choice and the profile's."""
    from engine.neural.policy import APPROVED_LEVELS
    host = host or {'provider_family': 'other', 'adapter_id': 'eval'}
    with torch.no_grad():
        hits = [float((APPROVED_LEVELS[selected(decoder, z, c, host, rel)[0]] == APPROVED_LEVELS[target_choice(c, profile)[0]]).float().mean()) for c in contexts]
    return sum(hits) / len(hits)

__all__ = ['ARCHETYPES', 'ARCHETYPE_HABITS', 'seed_profile', 'fit_seed_latent', 'trait_targets', 'habit_targets', 'target_choice', 'random_context', 'random_profile',
    'reference_contexts', 'agreement', 'selected', 'SEEDS', 'context_table', 'context_habits', 'distribution_loss']
