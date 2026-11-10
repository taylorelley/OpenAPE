"""Persona identity benchmark (ADR 0007): is a persona the same character on another model?

Three stages, all resumable, all through the real engine API (in-process):

1. Calibrate. Each model answers the trait probes on the *fit* half of the prompts; a
   blind judge rates every reply; a Model Style Profile is fitted per model, then all
   are rebased on their consensus reference.
2. Speak. Seven archetype personas answer the *score* half of the prompts on every
   model, in each arm: `uncalibrated` (the persona's intent rendered as is),
   `calibrated` (the engine's rendering for that model's profile) and, on live models,
   `static` (a hand-written persona paragraph, no engine). The judge rates every reply.
3. Line-up. A blind judge reads three replies by one persona on one model and picks
   that persona out of four replies to another prompt on another model.

    python -m benchmarks.identity.run                       # simulated models: plan only
    python -m benchmarks.identity.run --execute             # simulated models, offline (~1 min)
    python -m benchmarks.identity.run --provider openai-compatible --base-url URL \\
        --models A B C --judge-provider openai-compatible --judge-model JUDGE          # live: plan
    ... --execute                                           # live: calls models with your key

Simulated models have distortions built in (benchmarks/live/simulated_model.py), so a
simulated run shows that the mechanism works on distortions of that kind. It is not
evidence about real models or people. Only a live run with at least three model
families and two judge families counts towards the release gate.
"""
import argparse
import hashlib
import json
import random
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from protocol.catalogue import TRAITS, CATALOGUE_HASH
from engine.api.app import create_app
from engine.neural import calibration
from engine.neural.policy import choice, choice_allowed
from engine.neural.profiles import ARCHETYPES
from sdk.python.lite import render, model_key
from benchmarks.live import design, profile as profiles
from benchmarks.live.run import add_provider_args, build_providers, load, OFFLINE
from benchmarks.live.providers import Refused
from benchmarks.live.simulated_model import MODELS as SIMULATED
from benchmarks.identity import analysis, lineup

ROOT = Path(__file__).resolve().parents[2]
TOKEN = 'identity-benchmark-token-0000000000000'
REFERENCES, CANDIDATES = 3, 4
# Hand-written personas for the static arm: what an operator would put in a system prompt.
STATIC = {
    'balanced': 'Be clear, considerate and professional. Use moderate detail and explain your key reasoning.',
    'mentor': 'You are a patient mentor. Be warm and encouraging, phrase things gently, and explain in detail with concrete examples. Acknowledge progress and end with a next step.',
    'pragmatic_engineer': 'You are a pragmatic senior engineer. Be concise and direct, keep the tone casual, use precise technical terms, flag risks first and end with the next step.',
    'concierge': 'You are a courteous concierge. Be warm and formal, acknowledge the constraints you were given, structure your answer and end with a next step.',
    'collaborator': 'You are a friendly collaborator. Be warm, casual and a little playful, name the trade-offs and suggest a next step.',
    'analyst': 'You are a rigorous analyst. Be formal, reserved and serious, give detailed structured answers, name the trade-offs and say plainly when you are unsure.',
    'critic': 'You are a demanding reviewer. Be direct, detailed and reserved, lead with risks, name the trade-offs and use precise technical terms.',
}

def split(prompts):
    """Alternate prompts within each task type: (fit, score)."""
    by = {}
    for p in sorted(prompts, key=lambda p: p['id']): by.setdefault(p['task_type'], []).append(p)
    fit = [p for ps in by.values() for p in ps[0::2]]; score = [p for ps in by.values() for p in ps[1::2]]
    return fit, score

class Ledger:
    """Append-only JSONL keyed records, so an interrupted run resumes."""
    def __init__(self, path, key='key'):
        self.path = Path(path); self.lock = threading.Lock(); self.rows = {}
        for r in load(self.path):
            if not r.get('error'): self.rows[r[key]] = r
    def run(self, items, work, workers, label):
        """items: {key: args}. Runs work(key, args) -> record for the missing keys."""
        todo = [(k, v) for k, v in items.items() if k not in self.rows]; failed = 0
        if not todo: return 0
        random.Random(0).shuffle(todo)  # an interrupted stage then leaves an unbiased sample, not the first arm only
        self.path.parent.mkdir(parents=True, exist_ok=True)
        def one(k, v):
            try: r = dict(work(k, v), key=k)
            except Refused as exc: r = dict(key=k, error=f'refused: {exc}')
            except Exception as exc: r = dict(key=k, error=f'{type(exc).__name__}: {str(exc)[:300]}')
            with self.lock, open(self.path, 'a') as f: f.write(json.dumps(r) + '\n')
            return r
        with ThreadPoolExecutor(workers) as pool:
            for i, fut in enumerate(as_completed([pool.submit(one, k, v) for k, v in todo]), 1):
                r = fut.result()
                if r.get('error'): failed += 1
                else: self.rows[r['key']] = r
                if i % 100 == 0 or i == len(todo): print(f'{label}: {i}/{len(todo)} done, {failed} errors', file=sys.stderr)
        return failed

def digest(*parts):
    return hashlib.sha256('\x1f'.join(map(str, parts)).encode()).hexdigest()[:32]

def reply_key(model, placement, prompt_id, text):
    return digest('reply', model, placement, prompt_id, text)

def speak_plan(models, prompts, profile_set, static):
    """Every (arm, persona, model, prompt) with the style text it gets, via the real engine."""
    rows = []
    with tempfile.TemporaryDirectory(prefix='openape-identity-') as tmp:
        for p in profile_set: profiles.write(p, Path(tmp) / 'style-profiles')
        creds = [dict(token=TOKEN, tenant='local', actor='owner', scopes=['persona:express', 'persona:admin', 'training:admin'], personas=['*'], users=['*'])]
        with TestClient(create_app(tmp, credentials=creds, rate_limit_per_minute=10**9, calibration_mode='installed'), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
            for persona in ARCHETYPES:
                r = api.post('/v1/personas', json=dict(protocol_version='upap/2', persona_id=persona, archetype=persona, evolution='manual', individuality=0)); assert r.status_code == 200, r.text
            for persona in ARCHETYPES:
                for model in models:
                    for p in prompts:
                        ctx = design.context_of(p); rid = digest(persona, model, p['id'])
                        req = dict(protocol_version='upap/2', request_id=rid, identity=dict(tenant_id='local', persona_id=persona), session=dict(id=rid, turn_id='t'),
                            host=dict(adapter_id='identity-benchmark', adapter_version='1', host_version='1', provider_family='other', model_id=model_key(model)), context=ctx, mode='active')
                        r = api.post('/v1/express', json=req); assert r.status_code == 200, r.text
                        d = r.json(); shown = d['rendering']['controls'] if d.get('rendering') else d['controls']
                        base = dict(persona=persona, gen_model=model, prompt_id=p['id'], controls=d['controls'], habits=d['habits'])
                        rows.append(dict(base, arm='uncalibrated', rendered=d['controls'], text=render({**d, 'rendering': None}), violation=not choice_allowed(choice(d['controls'], d['habits']), ctx)))
                        rows.append(dict(base, arm='calibrated', rendered=shown, text=render(d), notes=(d.get('rendering') or {}).get('notes', []),
                            violation=not choice_allowed(choice(shown, d['habits']), ctx)))
                        if static: rows.append(dict(persona=persona, gen_model=model, prompt_id=p['id'], arm='static', controls=None, rendered=None, habits=[], text=STATIC[persona], violation=False))
            api.app.state.store.db.close()
    return rows

def trials_plan(models, prompts, n, seed):
    """Line-up trials, identical across arms: persona, source and target model, reference
    prompts, target prompt and the shuffled candidate personas."""
    rng = random.Random(seed); out = []; personas = list(ARCHETYPES); ids = [p['id'] for p in prompts]
    for persona in personas:
        for a in models:
            for b in models:
                if a == b: continue
                for k in range(n):
                    picked = rng.sample(ids, REFERENCES + 1); cands = rng.sample([x for x in personas if x != persona], CANDIDATES - 1) + [persona]; rng.shuffle(cands)
                    out.append(dict(trial_id=digest('trial', persona, a, b, k), persona=persona, source_model=a, target_model=b, reference_prompts=picked[:REFERENCES],
                        target_prompt=picked[-1], candidates=cands, correct=cands.index(persona)))
    return out

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_provider_args(ap)
    ap.set_defaults(provider='simulated')
    ap.add_argument('--models', nargs='+', help='models under test (default: every simulated model)')
    ap.add_argument('--placement', choices=['turn', 'prefix', 'system'], default='turn')
    ap.add_argument('--per-task', type=int, default=4, help='prompts per task type; half fit the profiles, half are scored')
    ap.add_argument('--trials', type=int, default=3, help='line-ups per persona and ordered model pair')
    ap.add_argument('--reference', choices=['consensus', 'anchors'], default='consensus')
    ap.add_argument('--no-static', action='store_true', help='skip the hand-written persona arm on live models')
    ap.add_argument('--workers', type=int, default=4); ap.add_argument('--seed', type=int, default=20261110)
    ap.add_argument('--run-dir'); ap.add_argument('--report-dir')
    ap.add_argument('--no-new-judgements', action='store_true', help='rate no further replies (keep those already rated); line-ups still run, since they need only the reply texts')
    ap.add_argument('--label', help='suffix for the report name, e.g. the judge, when several judges rate one run')
    ap.add_argument('--export-items', help='also write blinded line-up items for human raters to this file (and FILE.key.json)')
    ap.add_argument('--execute', action='store_true', help='run (otherwise print the plan)')
    a = ap.parse_args(argv)
    offline = a.provider in OFFLINE
    if a.provider == 'mock': ap.error('use --provider simulated for an offline run')
    models = a.models or (list(SIMULATED) if offline else None)
    if not models or len(models) < 2: ap.error('--models needs at least two models')
    run_dir = Path(a.run_dir or ROOT / 'benchmarks/identity/runs' / ('simulated' if offline else 'live'))
    from benchmarks.live.run import select_prompts
    fit, score = split(select_prompts(design.load_prompts(), a.per_task, a.seed))
    static = not offline and not a.no_static  # a simulated model cannot read free prose
    cal_rows = design.plan(fit, {'trait'})
    n_speak = len(ARCHETYPES) * len(models) * len(score) * (3 if static else 2); n_trials = len(ARCHETYPES) * len(models) * (len(models) - 1) * a.trials * (3 if static else 2)
    plan = dict(models=models, fit_prompts=len(fit), score_prompts=len(score), calibration_replies=len(cal_rows) * len(models), persona_replies_at_most=n_speak, lineups_at_most=n_trials,
        note='each reply is generated and judged once; identical style text across arms is not repeated, so real counts are lower')
    print(json.dumps(plan, indent=2))
    if not a.execute: print('Plan only: nothing was called. Add --execute to run.'); return 0
    gen, judge, effort, judge_effort = build_providers(a); judge_model = 'simulated-judge' if offline else a.judge_model
    conds = {c['id']: c for _, c in cal_rows}; by_id = {p['id']: p for p in fit + score}
    # Replies are generated once and kept apart from judgements, so a second judge model
    # can rate the same replies (same --run-dir, another --judge-model and --label).
    generated = Ledger(run_dir / 'replies.jsonl'); judgements = Ledger(run_dir / f'judgements-{model_key(judge_model).replace(":", "_")}.jsonl')
    class Replies:
        rows = {}
        def run(self, items, workers, label):
            def write(_, v):
                model, prompt_id, text = v
                return dict(gen_model=model, placement=a.placement, prompt_id=prompt_id, style_text=text, gen=gen.generate(model, by_id[prompt_id]['prompt'], text, a.placement, effort),
                    at=datetime.now(timezone.utc).isoformat())
            generated.run(items, write, workers, label)
            todo = {k: v for k, v in items.items() if k in generated.rows and generated.rows[k]['gen']['stop_reason'] != 'refusal'}
            if not a.no_new_judgements: judgements.run(todo, lambda k, v: dict(judge=judge.judge(judge_model, by_id[v[1]]['prompt'], generated.rows[k]['gen']['text'], judge_effort, True)), workers, label + ' (judge)')
            for k in items:
                if k in generated.rows and (k in judgements.rows or generated.rows[k]['gen']['stop_reason'] == 'refusal'):
                    self.rows[k] = dict(generated.rows[k], judge=judgements.rows.get(k, {}).get('judge'))
    replies = Replies()
    # 1. Calibrate on the fit prompts.
    cal_items = {reply_key(m, a.placement, p['id'], c['text']): (m, p['id'], c['text']) for m in models for p, c in cal_rows}
    replies.run(cal_items, a.workers, 'calibrate')
    measured = []
    for m in models:
        recs = []
        for p, c in cal_rows:
            r = replies.rows.get(reply_key(m, a.placement, p['id'], c['text']))
            if r: recs.append(dict(r, provider=a.provider, condition_id=c['id'], kind=c['kind'], trait=c.get('trait'), level=c.get('level'), habit=None, control_id=None))
        measured.append(profiles.from_records(recs, m, a.placement, run=run_dir.name))
    reference = calibration.consensus(measured) if a.reference == 'consensus' else None
    profile_set = [calibration.rebase(p, reference) for p in measured] if reference else measured
    for p in profile_set: profiles.write(p, run_dir / 'profiles')
    # 2. Speak on the score prompts.
    rows = speak_plan(models, score, profile_set, static)
    replies.run({reply_key(r['gen_model'], a.placement, r['prompt_id'], r['text']): (r['gen_model'], r['prompt_id'], r['text']) for r in rows}, a.workers, 'speak')
    records = []
    for r in rows:
        got = replies.rows.get(reply_key(r['gen_model'], a.placement, r['prompt_id'], r['text']))
        if got: records.append(dict(r, gen=got['gen'], judge=got.get('judge')))
    # 3. Line-up.
    # A line-up needs only the reply texts, so it does not wait for trait ratings.
    said = {}
    for r in rows:
        got = generated.rows.get(reply_key(r['gen_model'], a.placement, r['prompt_id'], r['text']))
        if got and got['gen'].get('stop_reason') != 'refusal': said[(r['arm'], r['persona'], r['gen_model'], r['prompt_id'])] = got['gen']['text']
    arms = ['uncalibrated', 'calibrated'] + (['static'] if static else [])
    lineups = Ledger(run_dir / 'lineups.jsonl'); trials = []; items = {}
    for arm in arms:
        for t in trials_plan(models, score, a.trials, a.seed):
            refs = [(by_id[q]['prompt'], said.get((arm, t['persona'], t['source_model'], q))) for q in t['reference_prompts']]
            cands = [(by_id[t['target_prompt']]['prompt'], said.get((arm, c, t['target_model'], t['target_prompt']))) for c in t['candidates']]
            if any(x[1] is None for x in refs + cands): continue
            key = digest('lineup', judge_model, json.dumps(refs), json.dumps(cands)); trials.append(dict(t, arm=arm, key=key)); items[key] = (refs, cands)
    lineups.run(items, lambda _, v: lineup.ask(judge, judge_model, v[0], v[1], judge_effort), a.workers, 'line-up')
    for t in trials: t['answer'] = lineups.rows.get(t['key'], {}).get('choice')
    if a.export_items:
        from benchmarks.identity import humans
        humans.export(trials, items, a.export_items, seed=a.seed)
    return write_report(a, run_dir, models, fit, score, profile_set, records, trials, offline, judge_model)

def write_report(a, run_dir, models, fit, score, profile_set, records, trials, offline, judge_model):
    judges = sorted({r['judge']['served_model'] for r in records if r.get('judge')})
    report = dict(kind=('simulated models with built-in distortions; engineering evidence, NOT live-model or human evidence' if offline
            else 'live models, judged by a model, not by people'),
        catalogue_hash=CATALOGUE_HASH, generated_at=datetime.now(timezone.utc).isoformat(), provider=a.provider, models=models, judge_models=judges, placement=a.placement,
        reference=a.reference, personas=list(ARCHETYPES), fit_prompts=len(fit), score_prompts=len(score), lineup=dict(references=REFERENCES, candidates=CANDIDATES, chance=1 / CANDIDATES, trials=len(trials)),
        profiles={p['model_id']: dict(hash=p['hash'], dead=[t for t in TRAITS if p['traits'][t]['dead']], max_shift={t: p['traits'][t]['max_shift'] for t in TRAITS},
            curves={t: p['traits'][t]['curve'] for t in TRAITS}) for p in profile_set},
        shifted_share=round(sum(1 for r in records if r['arm'] == 'calibrated' and r['rendered'] != r['controls']) / max(1, sum(1 for r in records if r['arm'] == 'calibrated')), 4),
        **analysis.analyse(records, trials, CANDIDATES))
    report['limitations'] = (['Simulated models: their distortions were built in, and the simulated judge reads percepts directly. This tests the mechanism, not real models.',
            'Task quality is constant in simulation, so H4 is not informative here.', 'The static-persona arm (H3) cannot be simulated: a simulated model does not read free prose.'] if offline
        else ['A model judges style and picks line-ups; agreement with human raters is unmeasured (see benchmarks/identity/rater.html).',
            'Single-turn prompts; no sessions, tools or host harness.']) + \
        ['Personas are the seven archetypes with no individual variation and no learned state.', 'Profiles are fitted on half of the prompts and scored on the other half, from the same prompt set and judge.']
    # One report has one judge. The gate needs this result from two judge families.
    report['counts_towards_release_gate'] = False
    report['release_gate_note'] = 'simulated' if offline else 'needs at least three model families and the same run rated by a second judge family'
    stem = ('identity-simulated' if offline else 'identity-live') + (f'-{a.label}' if a.label else '')
    out = Path(a.report_dir) if a.report_dir else ROOT / 'docs/reports'; out.mkdir(parents=True, exist_ok=True)
    if offline and not a.report_dir: (ROOT / 'benchmarks/reports' / f'{stem}.json').write_text(json.dumps(report, indent=2) + '\n')
    else: (out / f'{stem}.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / f'{stem}.md').write_text(markdown(report)); print(markdown(report)); return 0

def _ci(x, digits=2):
    if not x: return '-'
    return f"{x['mean']:.{digits}f}" + (f" [{x['ci95'][0]:.{digits}f}, {x['ci95'][1]:.{digits}f}]" if x.get('ci95') else '')

def markdown(r):
    lines = ['# Persona identity benchmark', '', f"{r['kind'].capitalize()}.", '',
        f"Models: {', '.join(r['models'])}. Judge: {', '.join(r['judge_models']) or '-'}. {len(r['personas'])} personas, {r['fit_prompts']} prompts to fit profiles, "
        f"{r['score_prompts']} other prompts scored, {r['lineup']['trials']} line-ups. Reference: {r['reference']}. "
        f"Calibration changed the rendered style in {r['shifted_share']:.0%} of calibrated replies.", '',
        '| Arm | same persona, two models (distance) | same, averaged over prompts | two personas, one model (distance) | identity ratio | distance from intent | line-up accuracy | task quality |', '|---|---|---|---|---|---|---|---|']
    for arm, x in r['arms'].items():
        lines.append(f"| {arm} | {_ci(x['same_persona_across_models'])} | {_ci(x['systematic_cross_model'])} | {_ci(x['different_personas_same_model'])} | {x['identity_ratio']} | {_ci(x['distance_from_intent'])} | "
            f"{_ci(x['lineup_accuracy'])} | {_ci(x['task_quality'])} |")
    lines += ['', f"Distances are mean absolute differences in judged trait levels (0-4), with prompt-clustered 95% intervals. Line-up chance is {r['lineup']['chance']:.2f}. "
        "\"Averaged over prompts\" compares each persona's mean judged style on two models, which removes reply and judge noise and leaves the systematic difference between models. "
        'The identity ratio is the distance between two personas over the per-reply distance of one persona across models: above 1, a persona differs less from itself on another model than from another persona.', '',
        '## Differences between arms (paired)', '', '| Comparison | cross-model distance | relative change | averaged over prompts | relative change | line-up accuracy | task quality |', '|---|---|---|---|---|---|---|']
    for name, c in r['comparisons'].items():
        rel = '-' if c['relative_reduction'] is None else f"{-c['relative_reduction']:+.0%}"
        srel = '-' if c['systematic_relative_reduction'] is None else f"{-c['systematic_relative_reduction']:+.0%}"
        lines.append(f"| {name} | {_ci(c['cross_model_distance'])} | {rel} | {_ci(c['systematic_distance'])} | {srel} | {_ci(c['lineup_accuracy'])} | {_ci(c['task_quality'])} |")
    lines += ['', '## Pre-registered hypotheses (ADR 0007)', '']
    lines += [f"* **{name}: {h['result']}**" + (f" (reduction {h['relative_reduction']:.0%})" if h.get('relative_reduction') is not None else '') for name, h in r['hypotheses'].items()]
    lines += ['', '## What each model does to the catalogue', '', '| Model | cannot steer | perceived warmth at levels 0-4 | perceived formality at levels 0-4 |', '|---|---|---|---|']
    lines += [f"| {m} | {', '.join(p['dead']) or '-'} | {' '.join(f'{v:.1f}' for v in p['curves']['warmth'])} | {' '.join(f'{v:.1f}' for v in p['curves']['formality'])} |" for m, p in r['profiles'].items()]
    lines += ['', '## Limitations', '', *[f'* {x}' for x in r['limitations']], '',
        f"Counts towards the live-model release gate on its own: **no** ({r['release_gate_note']}).", '']
    return '\n'.join(lines)

if __name__ == '__main__': sys.exit(main())
