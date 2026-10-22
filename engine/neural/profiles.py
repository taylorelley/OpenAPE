"""Declared style profiles: synthetic decoder supervision and explicit seed initialization.

A profile is a set of (trait, target level, weight) preferences. Profiles are an
authoring/supervision device only; they are never stored as persona state and do
not assign meaning to latent coordinates.
"""
import itertools
import torch
from engine.neural.policy import CATALOGUE, VOCAB, CORE_DIM, REL_DIM, SESSION_DIM, features, mask

LEVEL = {'low': 0, 'moderate': 1, 'high': 2}
SEEDS = {
    'concise': {'verbosity': (0, 1.6), 'explanation_depth': (0, 0.6)},
    'detailed': {'verbosity': (2, 1.6), 'explanation_depth': (2, 1.0)},
    'warm': {'warmth': (2, 1.6)},
    'reserved': {'warmth': (0, 1.4)},
    'formal': {'formality': (2, 1.6)},
    'casual': {'formality': (0, 1.4)},
    'direct': {'directness': (2, 1.6), 'assertiveness': (2, 0.6)},
    'gentle': {'directness': (0, 1.4), 'assertiveness': (0, 0.8)},
    'playful': {'humour': (1, 1.6)},
    'serious': {'humour': (0, 1.2)},
}
# Named starting personas. Each is a fixed, documented combination of seeds; the
# chosen archetype is the anchor that natural maturation builds on.
ARCHETYPES = {
    'balanced': (),
    'mentor': ('warm', 'detailed', 'gentle'),
    'pragmatic_engineer': ('concise', 'direct', 'casual'),
    'concierge': ('warm', 'formal'),
    'collaborator': ('warm', 'casual', 'playful'),
    'analyst': ('detailed', 'formal', 'reserved', 'serious'),
    'critic': ('direct', 'detailed', 'reserved'),
}
CONFLICTS = [{'concise', 'detailed'}, {'warm', 'reserved'}, {'formal', 'casual'}, {'direct', 'gentle'}, {'playful', 'serious'}]

def seed_profile(seeds):
    seeds = set(seeds)
    for pair in CONFLICTS:
        if pair <= seeds: raise ValueError('conflicting seed preferences: ' + '+'.join(sorted(pair)))
    profile = {}
    for s in sorted(seeds):
        for trait, (target, weight) in SEEDS[s].items(): profile[trait] = (target, weight)
    return profile

def context_score(item, ctx):
    """Synthetic, documented context rules (CC0). Not human evidence."""
    task, tags, s = ctx.get('task_type'), ctx.get('tags', []), 0.0
    if task == 'code_review': s += 0.8 * (item['directness'] == 'high')
    if task == 'support': s += 1.0 * (item['warmth'] == 'high')
    if task == 'creative': s += 0.6 * (item['humour'] != 'low')
    if task == 'research': s += 0.6 * (item['explanation_depth'] == 'high')
    if task == 'coding': s += 0.4 * (item['verbosity'] != 'high')
    if 'beginner' in tags: s += 1.0 * (item['explanation_depth'] == 'high') + 0.5 * (item['warmth'] != 'low')
    if 'expert' in tags: s += 0.8 * (item['verbosity'] == 'low')
    if 'urgent' in tags: s += 0.8 * (item['verbosity'] == 'low')
    if 'sensitive' in tags: s += 0.6 * (item['warmth'] == 'high')
    if ctx.get('channel') == 'voice': s += 0.6 * (item['verbosity'] == 'low')
    if ctx.get('channel') == 'chat': s += 0.3 * (item['formality'] != 'high')
    if ctx.get('stakes') == 'high': s += 0.5 * (item['formality'] != 'low') + 0.4 * (item['explanation_depth'] != 'low')
    if ctx.get('turn_origin') in ('tool', 'subagent', 'system'): s += 0.5 * (item['verbosity'] == 'low')
    s += 0.5 * (item == CATALOGUE[0])  # mild pull to the neutral approved default
    return s

def profile_score(item, profile):
    return -sum(w * abs(LEVEL[item[t]] - target) for t, (target, w) in profile.items())

def target_distribution(ctx, *profiles, temperature=0.35):
    scores = torch.tensor([context_score(c, ctx) + sum(profile_score(c, p) for p in profiles) for c in CATALOGUE])
    return torch.softmax((scores / temperature).masked_fill(~mask(ctx), float('-inf')), 0)

def random_context(rng):
    return dict(task_type=rng.choice(VOCAB['task_type']), channel=rng.choice(VOCAB['channel']),
        stakes=rng.choice(VOCAB['stakes']), turn_origin=rng.choices(VOCAB['turn_origin'], weights=[6, 1, 1, 1])[0],
        tags=sorted(rng.sample(VOCAB['tags'], rng.choice([0, 1, 1, 2]))))

def random_profile(rng, traits=(2, 4)):
    chosen = rng.sample(list(CATALOGUE[0]), rng.randint(*traits))
    return {t: (rng.choice([0, 1, 2]) if t != 'humour' else rng.choice([0, 1, 1, 2]), round(rng.uniform(0.6, 2.0), 3)) for t in chosen}

def reference_contexts():
    """Fixed, enumerable contexts used for deterministic seed fitting."""
    rows = []
    for task, stakes, tags in itertools.product(VOCAB['task_type'], ('low', 'medium', 'high'), ([], ['beginner'], ['expert'], ['urgent'])):
        rows.append(dict(task_type=task, channel='terminal', stakes=stakes, turn_origin='user', tags=tags))
    return rows

def fit_seed_latent(decoder, seeds, steps=150, max_norm=None):
    """Explicit seed initialization: fit a core latent to the declared profile with the
    frozen decoder. Deterministic; labelled `seed_preferences`, never `learned`."""
    if not seeds: return torch.zeros(CORE_DIM)  # the explicit `balanced` archetype
    if decoder.model is None: raise ValueError('trained decoder required for seed initialization')
    profile = seed_profile(seeds); contexts = reference_contexts(); host = {'provider_family': 'other', 'adapter_id': 'seed'}
    targets = torch.stack([target_distribution(c, profile) for c in contexts])
    feats = torch.stack([features(c, host) for c in contexts]); masks = torch.stack([mask(c) for c in contexts])
    fixed = torch.cat((torch.zeros(len(contexts), REL_DIM + SESSION_DIM), feats), 1)
    z = torch.zeros(CORE_DIM, requires_grad=True)
    optimizer = torch.optim.Adam([z], lr=0.05)
    for _ in range(steps):
        optimizer.zero_grad()
        logp = torch.log_softmax(decoder.model(torch.cat((z.expand(len(contexts), -1), fixed), 1)).masked_fill(~masks, -1e9), 1)
        loss = -(targets * logp.masked_fill(targets == 0, 0)).sum(1).mean()
        (loss + 1e-3 * z.square().sum()).backward(); optimizer.step()
    limit = max_norm or decoder.meta.get('latent_norm_limit', 6.0)
    with torch.no_grad(): z.mul_(min(1.0, limit / (float(z.norm()) + 1e-8)))
    return z.detach()

def agreement(decoder, z, profile, contexts, host=None, rel=None):
    host = host or {'provider_family': 'other', 'adapter_id': 'eval'}; rel = rel if rel is not None else torch.zeros(32)
    with torch.no_grad():
        return sum(int(decoder.logits(z, rel, c, host).argmax()) == int(target_distribution(c, profile).argmax()) for c in contexts) / len(contexts)

__all__ = ['ARCHETYPES', 'seed_profile', 'fit_seed_latent', 'target_distribution', 'random_context', 'random_profile', 'reference_contexts', 'agreement', 'SEEDS']
