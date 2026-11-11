"""Why does a hand-written persona beat the engine? One change at a time (step 1 of the
expression work that followed ADR 0007's first live run).

The same engine decisions (seven archetypes, their served controls and habits) are
rendered several ways. Every variant goes to the same model on the same prompts, and a
blind judge picks each persona out of a four-way line-up. Only reply texts are needed,
so no trait ratings are made.

| Variant | Text |
|---|---|
| `engine` | what adapters inject today: precedence prefix, all seven traits, habits |
| `no_prefix` | `engine` without the precedence prefix |
| `deviations` | prefix, only traits away from neutral (most distinctive first), habits |
| `role` | the archetype's one-line role, then `engine` |
| `card` | role line, traits away from neutral, habits; no prefix |
| `static` | the hand-written persona paragraph (same role line, its own wording) |
| `none` | no style text: the line-up should sit at chance (0.25) |

Each variant runs at every `--placements` (user turn, system prompt); `none` runs once.
With one model the line-up is within that model (references and candidates answer
different prompts); with several it is across models.

    python -m benchmarks.identity.ablation --provider simulated --models sim-effusive   # offline plumbing check
    python -m benchmarks.identity.ablation --provider openai-compatible --base-url URL \\
        --models MODEL --judge-provider openai-compatible --judge-model MODEL --execute

Validity: if `static` is not clearly above `none`, the judge cannot tell voices apart
and the comparison says nothing about the variants. The report says which.
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
from protocol.catalogue import TRAITS, TEMPLATES, NEUTRAL, PREFIX, HABITS
from engine.neural.profiles import ARCHETYPES
from benchmarks.live import design
from benchmarks.live.run import add_provider_args, build_providers, OFFLINE, select_prompts
from benchmarks.identity import analysis, lineup
from benchmarks.identity.run import Ledger, STATIC, REFERENCES, CANDIDATES, split, speak_plan, digest

ROOT = Path(__file__).resolve().parents[2]
# The role line of each hand-written persona (STATIC), alone: isolates "names a character".
ROLE = {'balanced': 'You are a balanced, professional assistant.', 'mentor': 'You are a patient mentor.', 'pragmatic_engineer': 'You are a pragmatic senior engineer.',
    'concierge': 'You are a courteous concierge.', 'collaborator': 'You are a friendly collaborator.', 'analyst': 'You are a rigorous analyst.', 'critic': 'You are a demanding reviewer.'}
VARIANTS = ('engine', 'no_prefix', 'deviations', 'role', 'card', 'static', 'none')
_HABIT = {h['id']: h['text'] for h in HABITS}

def deviations(controls):
    """Trait sentences away from neutral, largest departure first (catalogue order breaks ties)."""
    away = [t for t in TRAITS if controls[t] != NEUTRAL[t]]
    return [TEMPLATES[t][controls[t]] for t in sorted(away, key=lambda t: (-abs(controls[t] - NEUTRAL[t]), TRAITS.index(t)))]

def variant_text(variant, persona, engine_text, controls, habits):
    habit_text = [_HABIT[h] for h in habits]
    if variant == 'engine': return engine_text
    if variant == 'no_prefix':
        assert engine_text.startswith(PREFIX + ' '); return engine_text[len(PREFIX) + 1:]
    if variant == 'deviations': return ' '.join([PREFIX] + deviations(controls) + habit_text)
    if variant == 'role': return ROLE[persona] + ' ' + engine_text
    if variant == 'card': return ' '.join([ROLE[persona]] + deviations(controls) + habit_text)
    if variant == 'static': return STATIC[persona]
    if variant == 'none': return ''
    raise ValueError(variant)

def arms_for(variants, placements):
    return [f'{v}@{p}' for v in variants if v != 'none' for p in placements] + (['none'] if 'none' in variants else [])

def trials(models, prompts, n, seed):
    """Line-up trials, identical for every arm. One model: within it; several: across them."""
    pairs = [(m, m) for m in models] if len(models) == 1 else [(a, b) for a in models for b in models if a != b]
    rng = random.Random(seed); ids = [p['id'] for p in prompts]; personas = list(ARCHETYPES); out = []
    for persona in personas:
        for a, b in pairs:
            for k in range(n):
                picked = rng.sample(ids, REFERENCES + 1); cands = rng.sample([x for x in personas if x != persona], CANDIDATES - 1) + [persona]; rng.shuffle(cands)
                out.append(dict(trial_id=digest('ablation-trial', persona, a, b, k), persona=persona, source_model=a, target_model=b, reference_prompts=picked[:REFERENCES],
                    target_prompt=picked[-1], candidates=cands, correct=cands.index(persona)))
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_provider_args(ap); ap.set_defaults(provider='simulated')
    ap.add_argument('--models', nargs='+', required=True)
    ap.add_argument('--variants', nargs='+', choices=VARIANTS, default=list(VARIANTS))
    ap.add_argument('--placements', nargs='+', choices=['turn', 'system', 'prefix'], default=['turn', 'system'])
    ap.add_argument('--per-task', type=int, default=4, help='prompts per task type (4 = 36; line-ups use the scored half, 18)')
    ap.add_argument('--trials', type=int, default=12, help='line-ups per persona and model pair')
    ap.add_argument('--workers', type=int, default=8); ap.add_argument('--seed', type=int, default=20261111)
    ap.add_argument('--run-dir'); ap.add_argument('--report-dir'); ap.add_argument('--label', help='report name suffix')
    ap.add_argument('--execute', action='store_true')
    a = ap.parse_args(argv)
    if a.provider == 'mock': ap.error('use --provider simulated for an offline run')
    offline = a.provider in OFFLINE
    _, score = split(select_prompts(design.load_prompts(), a.per_task, a.seed)); by_id = {p['id']: p for p in score}
    arms = arms_for(a.variants, a.placements); plan = trials(a.models, score, a.trials, a.seed)
    print(json.dumps(dict(models=a.models, arms=arms, prompts=len(score), replies_at_most=len(arms) * len(ARCHETYPES) * len(a.models) * len(score),
        lineups=len(arms) * len(plan)), indent=2))
    if not a.execute: print('Plan only: nothing was called. Add --execute to run.'); return 0
    gen, judge, effort, judge_effort = build_providers(a)
    judge_model = f'{a.provider}-judge' if offline else a.judge_model
    run_dir = Path(a.run_dir or ROOT / 'benchmarks/identity/runs' / ('ablation-' + (a.label or ('simulated' if offline else 'live'))))
    # Engine decisions once, uncalibrated: the same controls and habits under every variant.
    decided = {(r['persona'], r['gen_model'], r['prompt_id']): r for r in speak_plan(a.models, score, [], False) if r['arm'] == 'uncalibrated'}
    texts = {}
    for (persona, model, prompt_id), r in decided.items():
        for arm in arms:
            variant, _, placement = arm.partition('@')
            texts[(arm, persona, model, prompt_id)] = (variant_text(variant, persona, r['text'], r['controls'], r['habits']), placement or 'turn')
    replies = Ledger(run_dir / 'replies.jsonl')
    def key(text, placement, model, prompt_id): return digest('ablation-reply', model, placement, prompt_id, text)
    items = {key(t, pl, m, q): (m, q, t, pl) for (_, _, m, q), (t, pl) in texts.items()}
    def write(_, v):
        m, q, t, pl = v
        return dict(gen_model=m, prompt_id=q, placement=pl, style_text=t, gen=gen.generate(m, by_id[q]['prompt'], t, pl, effort), at=datetime.now(timezone.utc).isoformat())
    replies.run(items, write, a.workers, 'replies')
    said = {}
    for k, (t, pl) in texts.items():
        got = replies.rows.get(key(t, pl, k[2], k[3]))
        if got and got['gen'].get('stop_reason') != 'refusal' and got['gen'].get('text'): said[k] = got['gen']['text']
    lineups = Ledger(run_dir / f"lineups-{digest(judge_model)[:12]}.jsonl"); run_trials = []; asks = {}
    for arm in arms:
        for t in plan:
            refs = [(by_id[q]['prompt'], said.get((arm, t['persona'], t['source_model'], q))) for q in t['reference_prompts']]
            cands = [(by_id[t['target_prompt']]['prompt'], said.get((arm, c, t['target_model'], t['target_prompt']))) for c in t['candidates']]
            if any(x[1] is None for x in refs + cands): continue
            k = digest('ablation-lineup', judge_model, json.dumps(refs), json.dumps(cands)); run_trials.append(dict(t, arm=arm, key=k)); asks[k] = (refs, cands)
    lineups.run(asks, lambda _, v: lineup.ask(judge, judge_model, v[0], v[1], judge_effort), a.workers, 'line-ups')
    for t in run_trials: t['answer'] = lineups.rows.get(t['key'], {}).get('choice')
    report = analyse(run_trials, arms)
    report.update(kind=('simulated models; plumbing check only' if offline else 'live model, judged by a model, not by people'), generated_at=datetime.now(timezone.utc).isoformat(),
        models=a.models, judge_model=judge_model, prompts=len(score), personas=list(ARCHETYPES), lineup=dict(references=REFERENCES, candidates=CANDIDATES, chance=1 / CANDIDATES),
        replies=len(said), within_model=len(a.models) == 1, examples={persona: {arm: texts[(arm, persona, a.models[0], score[0]['id'])][0] for arm in arms} for persona in ARCHETYPES})
    out = Path(a.report_dir) if a.report_dir else ROOT / 'docs/reports'; out.mkdir(parents=True, exist_ok=True)
    stem = 'identity-ablation' + (f'-{a.label}' if a.label else '-simulated' if offline else '')
    (out / f'{stem}.json').write_text(json.dumps(report, indent=2) + '\n'); (out / f'{stem}.md').write_text(markdown(report)); print(markdown(report)); return 0

def analyse(run_trials, arms):
    acc = analysis.lineup_metrics(run_trials)
    report = dict(arms={}, versus={}, confusions={})
    for arm in arms:
        mine = [t for t in run_trials if t['arm'] == arm and t['answer'] is not None]
        per_persona = defaultdict(list); picked = defaultdict(Counter)
        for t in mine:
            per_persona[t['persona']].append(t['answer'] == t['correct'])
            if t['answer'] != t['correct']: picked[t['persona']][t['candidates'][t['answer']]] += 1
        report['arms'][arm] = dict(lineups=len(mine), accuracy=analysis.boot(analysis._cluster(acc.get(arm, {}), 1)),
            by_persona={p: round(float(np.mean(v)), 3) for p, v in sorted(per_persona.items())},
            answer_positions=dict(sorted(Counter(t['answer'] for t in mine).items())))
        report['confusions'][arm] = {p: c.most_common(1)[0][0] for p, c in picked.items() if c}
    for base in ('engine@turn', 'static@turn'):
        if base not in arms: continue
        report['versus'][base] = {arm: analysis._paired(acc.get(arm, {}), acc.get(base, {}), 1) for arm in arms if arm != base}
    s, n = report['arms'].get('static@turn', {}).get('accuracy'), report['arms'].get('none', {}).get('accuracy')
    report['judge_can_tell_voices_apart'] = None if not (s and n) else bool(s['ci95'][0] > n['ci95'][1])
    return report

def _ci(x):
    return '-' if not x else f"{x['mean']:.2f} [{x['ci95'][0]:.2f}, {x['ci95'][1]:.2f}]"

def markdown(r):
    lines = ['# Expression ablation: which change makes a persona recognisable?', '', f"{r['kind'].capitalize()}.", '',
        f"Model{'s' if len(r['models']) > 1 else ''}: {', '.join(r['models'])} ({'line-ups within the model' if r['within_model'] else 'line-ups across models'}). "
        f"Judge: {r['judge_model']}. {len(r['personas'])} archetype personas, {r['prompts']} prompts, {r['replies']} replies. Chance is {r['lineup']['chance']:.2f}.", '']
    ok = r['judge_can_tell_voices_apart']
    lines += [f"**Judge validity:** {'the hand-written persona is identified clearly above the no-style control, so differences between variants are informative.' if ok else 'the hand-written persona is NOT clearly above the no-style control: this judge cannot reliably tell voices apart, so the comparison below is not informative.' if ok is False else 'not checked (needs the static and none variants).'}", '',
        '| Arm | line-up accuracy | line-ups | weakest persona | answer positions |', '|---|---|---|---|---|']
    for arm, x in sorted(r['arms'].items(), key=lambda kv: -(kv[1]['accuracy'] or {}).get('mean', -1)):
        weakest = min(x['by_persona'].items(), key=lambda kv: kv[1], default=('-', None))
        lines.append(f"| {arm} | {_ci(x['accuracy'])} | {x['lineups']} | {weakest[0]} ({weakest[1]}) | {' '.join(f'{k}:{v}' for k, v in x['answer_positions'].items())} |")
    for base, diffs in r['versus'].items():
        lines += ['', f'## Paired difference against `{base}`', '', '| Arm | difference |', '|---|---|']
        lines += [f'| {arm} | {_ci(d)} |' for arm, d in diffs.items()]
    lines += ['', '## Most common confusion (persona → picked instead)', '', '| Arm | confusions |', '|---|---|']
    lines += [f"| {arm} | {', '.join(f'{p}→{q}' for p, q in c.items()) or '-'} |" for arm, c in r['confusions'].items()]
    lines += ['', '## What each variant sends (mentor, first prompt)', '']
    lines += [f"* `{arm}`: {text or '(nothing)'}" for arm, text in r['examples']['mentor'].items()]
    lines += ['', 'Intervals are prompt-clustered 95% bootstraps. One judge model; no human raters.', '']
    return '\n'.join(lines)

if __name__ == '__main__': sys.exit(main())
