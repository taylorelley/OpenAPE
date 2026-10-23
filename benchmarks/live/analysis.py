"""Metrics over judged live-evaluation records. Pure functions: no model calls.

Per generation model:

* Trait fidelity: Spearman correlation between the requested level and the judged
  level over each trait's probes (the neutral configuration counts as its neutral
  level), the mean judged level per requested level, and, for each pair of adjacent
  levels, distinguishability: on the same prompt, how often the higher requested level
  is judged higher (ties count one half). 0.5 means a model does not tell them apart.
* Leakage: how much a trait probe moves the *other* traits compared with the neutral
  configuration on the same prompt (mean absolute judged change).
* Habit adherence: how often the judge sees the habit when it was requested, against
  its matched control (same levels, no habit) on the same prompt. Lift is the
  difference.
* Task quality and refusals: each styled condition against the no-style baseline on
  the same prompt, with prompt-clustered bootstrap intervals.
* Judge consistency: exact agreement between the first and a repeated judgement.

`flags` lists what to revise in the catalogue, by fixed thresholds.
"""
from collections import defaultdict
import numpy as np
from protocol.catalogue import TRAITS, LEVELS, NEUTRAL, HABITS

DISTINGUISH_MIN, SPEARMAN_MIN, HABIT_LIFT_MIN, QUALITY_DROP_MAX, LEAKAGE_MAX = 0.6, 0.5, 0.3, -0.5, 0.75

def _ranks(x):
    x = np.asarray(x, dtype=float); order = np.argsort(x, kind='mergesort'); ranks = np.empty(len(x))
    ranks[order] = np.arange(len(x)); out = np.empty(len(x))
    for v in np.unique(x): out[x == v] = ranks[x == v].mean()
    return out

def spearman(a, b):
    if len(a) < 3: return None
    ra, rb = _ranks(a), _ranks(b)
    if ra.std() == 0 or rb.std() == 0: return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])

def bootstrap(by_cluster, reps=2000, seed=42):
    """Mean and 95% interval of per-item values grouped by cluster (prompt)."""
    clusters = sorted(by_cluster); values = [v for c in clusters for v in by_cluster[c]]
    if not values: return None
    rng = np.random.default_rng(seed); means = []
    for _ in range(reps):
        sample = rng.choice(clusters, len(clusters), replace=True)
        pooled = [v for c in sample for v in by_cluster[c]]
        if pooled: means.append(float(np.mean(pooled)))
    return dict(mean=round(float(np.mean(values)), 4), ci95=[round(float(np.quantile(means, q)), 4) for q in (.025, .975)], n=len(values), clusters=len(clusters))

def _r(x):
    return None if x is None else round(float(x), 4)

def judged(records):
    return [r for r in records if r.get('judge') and not r['judge']['refused'] and r['gen'].get('stop_reason') != 'refusal']

def trait_metrics(records):
    neutral = {r['prompt_id']: r for r in records if r['kind'] == 'neutral'}
    out = {}
    for t in TRAITS:
        probes = [r for r in records if r['kind'] == 'trait' and r['trait'] == t] + [dict(r, level=NEUTRAL[t]) for r in neutral.values()]
        requested = [r['level'] for r in probes]; got = [r['judge']['traits'][t] for r in probes]
        by_prompt = defaultdict(dict)
        for r in probes: by_prompt[r['prompt_id']][r['level']] = r['judge']['traits'][t]
        adjacent = {}
        for level in range(LEVELS - 1):
            scores = [1.0 if v[level + 1] > v[level] else 0.5 if v[level + 1] == v[level] else 0.0 for v in by_prompt.values() if level in v and level + 1 in v]
            adjacent[f'{level}-{level + 1}'] = dict(distinguishability=_r(np.mean(scores)) if scores else None, prompts=len(scores))
        means = {str(level): _r(np.mean([g for q, g in zip(requested, got) if q == level])) if level in requested else None for level in range(LEVELS)}
        leak = [float(np.mean([abs(r['judge']['traits'][o] - neutral[r['prompt_id']]['judge']['traits'][o]) for o in TRAITS if o != t]))
            for r in probes if r['kind'] == 'trait' and r['prompt_id'] in neutral]
        out[t] = dict(spearman=_r(spearman(requested, got)), probes=len(probes), mean_judged_by_level=means, adjacent=adjacent, leakage=_r(np.mean(leak)) if leak else None)
    return out

def habit_metrics(records):
    by_key = {(r['prompt_id'], r['condition_id']): r for r in records}
    out = {}
    for h in HABITS:
        pairs = [(r, by_key.get((r['prompt_id'], r['control_id']))) for r in records if r['kind'] == 'habit' and r['habit'] == h['id']]
        pairs = [(a, b) for a, b in pairs if b is not None]
        if not pairs: out[h['id']] = dict(prompts=0, adherence=None, control_rate=None, lift=None); continue
        present = np.mean([a['judge']['habits'][h['id']] for a, _ in pairs]); control = np.mean([b['judge']['habits'][h['id']] for _, b in pairs])
        out[h['id']] = dict(prompts=len(pairs), adherence=_r(present), control_rate=_r(control), lift=_r(present - control))
    return out

def quality_metrics(all_records, records):
    base = {r['prompt_id']: r for r in records if r['kind'] == 'baseline'}
    deltas = defaultdict(list); per_condition = defaultdict(lambda: defaultdict(list))
    for r in records:
        if r['kind'] == 'baseline' or r['prompt_id'] not in base: continue
        d = r['judge']['task_quality'] - base[r['prompt_id']]['judge']['task_quality']
        deltas[r['prompt_id']].append(d); per_condition[r['condition_id']][r['prompt_id']].append(d)
    refusals = defaultdict(list)
    for r in all_records:
        if r.get('gen'):
            refused = r['gen'].get('stop_reason') == 'refusal' or bool(r.get('judge') and r['judge']['refused'])
            refusals['baseline' if r['kind'] == 'baseline' else 'styled'].append(refused)
    worst = sorted(((cid, float(np.mean([v for vs in by.values() for v in vs]))) for cid, by in per_condition.items()), key=lambda x: x[1])[:5]
    static = {p: v for p, v in per_condition.get('static', {}).items()}
    return dict(styled_minus_baseline=bootstrap(deltas), static_minus_baseline=bootstrap(static) if static else None,
        refusal_rate={k: _r(np.mean(v)) for k, v in refusals.items()}, worst_conditions=[dict(condition=c, mean_delta=_r(d)) for c, d in worst])

def consistency(records):
    pairs = [(r['judge'], r['judge_repeat']) for r in records if r.get('judge') and r.get('judge_repeat')]
    if not pairs: return None
    return dict(pairs=len(pairs), trait_exact={t: _r(np.mean([a['traits'][t] == b['traits'][t] for a, b in pairs])) for t in TRAITS},
        trait_within_one=_r(np.mean([abs(a['traits'][t] - b['traits'][t]) <= 1 for a, b in pairs for t in TRAITS])),
        habit_agreement=_r(np.mean([a['habits'][h['id']] == b['habits'][h['id']] for a, b in pairs for h in HABITS])))

def flags(traits, habits, quality):
    out = []
    for t, m in traits.items():
        if m['spearman'] is not None and m['spearman'] < SPEARMAN_MIN: out.append(dict(kind='trait', trait=t, issue=f'requested and judged levels barely correlate (Spearman {m["spearman"]})'))
        for pair, a in m['adjacent'].items():
            if a['distinguishability'] is not None and a['distinguishability'] < DISTINGUISH_MIN:
                out.append(dict(kind='levels', trait=t, levels=pair, issue=f'levels {pair} are hard to tell apart (distinguishability {a["distinguishability"]})'))
        if m['leakage'] is not None and m['leakage'] > LEAKAGE_MAX: out.append(dict(kind='leakage', trait=t, issue=f'moving {t} also moves other traits (mean {m["leakage"]} levels)'))
    for h, m in habits.items():
        if m['lift'] is not None and m['lift'] < HABIT_LIFT_MIN: out.append(dict(kind='habit', habit=h, issue=f'habit barely changes replies (lift {m["lift"]})'))
    for w in quality['worst_conditions']:
        if w['mean_delta'] is not None and w['mean_delta'] < QUALITY_DROP_MAX: out.append(dict(kind='quality', condition=w['condition'], issue=f'task quality drops by {w["mean_delta"]} against no style'))
    return out

def analyse(records):
    models = sorted({r['gen_model'] for r in records})
    report = dict(models={})
    for m in models:
        mine = [r for r in records if r['gen_model'] == m]; ok = judged(mine)
        traits, habits, quality = trait_metrics(ok), habit_metrics(ok), quality_metrics(mine, ok)
        report['models'][m] = dict(records=len(mine), judged=len(ok), errors=sum(1 for r in mine if r.get('error')), traits=traits, habits=habits,
            quality=quality, judge_consistency=consistency(ok), flags=flags(traits, habits, quality))
    if len(models) > 1:
        # Cross-provider agreement: do models agree on what each style probe does?
        by = defaultdict(dict)
        for r in judged(records):
            if r['kind'] in ('trait', 'neutral'):
                for t in TRAITS: by[(r['prompt_id'], r['condition_id'], t)][r['gen_model']] = r['judge']['traits'][t]
        agreement = {}
        for a in models:
            for b in models:
                if a < b:
                    xs = [(v[a], v[b]) for v in by.values() if a in v and b in v]
                    agreement[f'{a} vs {b}'] = _r(spearman([x for x, _ in xs], [y for _, y in xs])) if xs else None
        report['cross_model_spearman'] = agreement
    return report
