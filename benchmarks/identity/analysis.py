"""Metrics for the persona identity benchmark. Pure functions over records; no model calls.

* Sameness: for one persona and prompt, the mean absolute difference between the judged
  trait vectors of its replies on two models (0 = perceived identically). Reported per
  arm, with the distance between *different* personas on the same model and prompt as
  the yardstick: a persona is recognisable when the first is well below the second.
  Two replies never get identical ratings, so this distance has a noise floor that no
  calibration can remove. The systematic distance (a persona's mean style per model,
  averaged over prompts) is reported beside it as a secondary measure.
* Line-up accuracy per arm (chance = 1 / candidates), and paired differences between
  arms on identical trials.
* Task quality per arm, paired.
* Safety: rendered configurations outside the approved, context-masked set (must be 0).

Intervals are prompt-clustered bootstraps. Hypotheses H1-H5 of ADR 0007 are evaluated
with their pre-registered thresholds.
"""
from collections import defaultdict
import numpy as np
from protocol.catalogue import TRAITS

H1_REDUCTION, H4_QUALITY, H4_LOWER = 0.30, -0.1, -0.25

def judged(records):
    return [r for r in records if r.get('judge') and not r['judge']['refused'] and r['gen'].get('stop_reason') != 'refusal']

def boot(by_cluster, reps=2000, seed=42):
    clusters = sorted(by_cluster); values = [v for c in clusters for v in by_cluster[c]]
    if not values: return None
    rng = np.random.default_rng(seed); means = []
    for _ in range(reps):
        pooled = [v for c in rng.choice(clusters, len(clusters), replace=True) for v in by_cluster[c]]
        means.append(float(np.mean(pooled)))
    return dict(mean=round(float(np.mean(values)), 4), ci95=[round(float(np.quantile(means, q)), 4) for q in (.025, .975)], n=len(values), clusters=len(clusters))

def _vector(r): return np.array([r['judge']['traits'][t] for t in TRAITS], dtype=float)

def sameness(records):
    """{arm: {cross_model: {(persona, prompt, a, b): d}, between_personas: {(prompt, model, x, y): d}}}"""
    out = defaultdict(lambda: dict(cross_model={}, between_personas={}, intent={}))
    by = defaultdict(dict)
    for r in judged(records): by[(r['arm'], r['prompt_id'])][(r['persona'], r['gen_model'])] = r
    for (arm, prompt), cell in by.items():
        keys = sorted(cell)
        for i, (p1, m1) in enumerate(keys):
            r1 = cell[(p1, m1)]
            if r1.get('controls'): out[arm]['intent'][(p1, prompt, m1)] = float(np.mean(np.abs(_vector(r1) - np.array([r1['controls'][t] for t in TRAITS]))))
            for p2, m2 in keys[i + 1:]:
                d = float(np.mean(np.abs(_vector(r1) - _vector(cell[(p2, m2)]))))
                if p1 == p2: out[arm]['cross_model'][(p1, prompt, m1, m2)] = d
                elif m1 == m2: out[arm]['between_personas'][(prompt, m1, p1, p2)] = d
    return out

def systematic(records, arm, minus=None, reps=1000, seed=42):
    """Cross-model distance between a persona's *mean* judged style on each model
    (averaged over prompts), which removes reply and judge noise. With `minus`, the
    paired difference to another arm, with a prompt-resampled bootstrap interval."""
    def table(a):
        by = defaultdict(dict)
        for r in judged(records):
            if r['arm'] == a: by[r['prompt_id']][(r['persona'], r['gen_model'])] = _vector(r)
        return by
    tables = [table(arm)] + ([table(minus)] if minus else [])
    prompts = sorted(set.intersection(*[set(t) for t in tables])) if all(tables) else []
    if not prompts: return None
    def stat(t, sample):
        sums = defaultdict(list)
        for q in sample:
            for k, v in t[q].items(): sums[k].append(v)
        means = {k: np.mean(v, axis=0) for k, v in sums.items()}; ds = []
        for (p1, m1) in means:
            for (p2, m2) in means:
                if p1 == p2 and m1 < m2: ds.append(float(np.mean(np.abs(means[(p1, m1)] - means[(p2, m2)]))))
        return float(np.mean(ds)) if ds else float('nan')
    value = lambda sample: stat(tables[0], sample) - (stat(tables[1], sample) if minus else 0.0)
    # A resample has fewer distinct prompts, so its means are noisier and a single arm's
    # distance is biased upwards; the bias cancels in a paired difference. Only
    # differences get an interval.
    if not minus: return dict(mean=round(value(prompts), 4), ci95=None, n=len(prompts), clusters=len(prompts))
    rng = np.random.default_rng(seed); boots = [value(list(rng.choice(prompts, len(prompts), replace=True))) for _ in range(reps)]
    return dict(mean=round(value(prompts), 4), ci95=[round(float(np.nanquantile(boots, q)), 4) for q in (.025, .975)], n=len(prompts), clusters=len(prompts))

def _cluster(values, prompt_index):
    by = defaultdict(list)
    for k, v in values.items(): by[k[prompt_index]].append(v)
    return by

def _paired(a, b, prompt_index):
    """Bootstrap of a - b over keys present in both, clustered by prompt."""
    return boot(_cluster({k: a[k] - b[k] for k in a if k in b}, prompt_index))

def lineup_metrics(trials):
    by_arm = defaultdict(dict)
    for t in trials:
        if t.get('answer') is not None: by_arm[t['arm']][(t['trial_id'], t['target_prompt'])] = float(t['answer'] == t['correct'])
    return by_arm

def analyse(records, trials, candidates, base='uncalibrated', test='calibrated'):
    s = sameness(records); arms = sorted(s); report = dict(arms={}, comparisons={}, hypotheses={})
    lm = lineup_metrics(trials)
    quality = defaultdict(dict)
    for r in judged(records): quality[r['arm']][(r['persona'], r['prompt_id'], r['gen_model'])] = float(r['judge']['task_quality'])
    for arm in arms:
        cross, between = boot(_cluster(s[arm]['cross_model'], 1)), boot(_cluster(s[arm]['between_personas'], 0))
        report['arms'][arm] = dict(replies=sum(1 for r in records if r['arm'] == arm), judged=sum(1 for r in judged(records) if r['arm'] == arm),
            same_persona_across_models=cross, systematic_cross_model=systematic(records, arm), different_personas_same_model=between,
            identity_ratio=round(between['mean'] / cross['mean'], 3) if cross and between and cross['mean'] else None,
            distance_from_intent=boot(_cluster(s[arm]['intent'], 1)), lineup_accuracy=boot(_cluster(lm.get(arm, {}), 1)),
            task_quality=boot(_cluster(quality[arm], 1)),
            rendered_outside_approved_set=sum(1 for r in records if r['arm'] == arm and r.get('violation')))
    def compare(a, b):
        if a not in s or b not in s: return None
        d = _paired(s[a]['cross_model'], s[b]['cross_model'], 1); base_mean = float(np.mean(list(s[b]['cross_model'].values()))) if s[b]['cross_model'] else None
        sd = systematic(records, a, b); sb = systematic(records, b)
        return dict(cross_model_distance=d, relative_reduction=round(-d['mean'] / base_mean, 4) if d and base_mean else None,
            systematic_distance=sd, systematic_relative_reduction=round(-sd['mean'] / sb['mean'], 4) if sd and sb and sb['mean'] else None,
            lineup_accuracy=_paired(lm.get(a, {}), lm.get(b, {}), 1), task_quality=_paired(quality[a], quality[b], 1))
    for a, b in ((test, base), (test, 'static'), (base, 'static')):
        c = compare(a, b)
        if c: report['comparisons'][f'{a} minus {b}'] = c
    main = report['comparisons'].get(f'{test} minus {base}'); static = report['comparisons'].get(f'{test} minus static')
    def verdict(ok, tested=True): return 'not tested' if not tested else 'met' if ok else 'not met'
    h = report['hypotheses']
    if main:
        d = main['cross_model_distance']; l = main['lineup_accuracy']; q = main['task_quality']
        h['H1 cross-model distance at least 30% lower'] = dict(result=verdict(bool(d and main['relative_reduction'] is not None and main['relative_reduction'] >= H1_REDUCTION and d['ci95'][1] < 0)),
            relative_reduction=main['relative_reduction'], difference=d)
        h['H2 line-up accuracy higher than uncalibrated'] = dict(result=verdict(bool(l and l['ci95'][0] > 0), bool(l)), difference=l, chance=round(1 / candidates, 3))
        h['H4 task quality not harmed'] = dict(result=verdict(bool(q and q['mean'] >= H4_QUALITY and q['ci95'][0] >= H4_LOWER), bool(q)), difference=q)
    l = static['lineup_accuracy'] if static else None
    h['H3 line-up accuracy higher than a static persona'] = dict(result=verdict(bool(l and l['ci95'][0] > 0), bool(l)), difference=l)
    violations = sum(a['rendered_outside_approved_set'] for a in report['arms'].values())
    h['H5 nothing rendered outside the approved, masked set'] = dict(result=verdict(violations == 0), violations=violations)
    return report
