"""Live-model evaluation of the style catalogue (ADR 0005). Not run in CI.

Does each trait level and habit actually change what a model writes, and does style
text leave task quality and refusals unchanged? For every prompt and condition (see
design.py) the model under test writes a reply with the injected style text; a blind
Claude judge rates the reply. analysis.py turns the judgements into fidelity,
distinguishability, habit lift, quality parity and a list of templates to revise.

Dry run by default: prints the plan and a rough cost estimate. Add --execute to call
models. Records are appended to <run-dir>/records.jsonl, so an interrupted run resumes
where it stopped, and several models (for example another provider family) can share
one run directory and one report.

    pip install -e '.[live]'                          # anthropic SDK
    python -m benchmarks.live.run                     # plan + estimate, no calls
    python -m benchmarks.live.run --per-task 1 --execute         # small pilot
    python -m benchmarks.live.run --execute                      # full run
    python -m benchmarks.live.run --provider openai-compatible --model MODEL \\
        --base-url URL --key-env PROVIDER_API_KEY --execute     # second provider family
    python -m benchmarks.live.run --report-only       # recompute the report
"""
import argparse
import json
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from protocol.catalogue import CATALOGUE_HASH
from benchmarks.live import design, analysis
from benchmarks.live.providers import AnthropicProvider, OpenAICompatibleProvider, MockProvider, Refused

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = 'claude-opus-5-5'
# Rough per-call token assumptions for the estimate (thinking tokens bill as output).
GEN_IN, GEN_OUT, JUDGE_IN, JUDGE_OUT = 450, 1200, 2300, 1000
PRICES = {'claude-opus-5-5': (4.0, 20.0), 'claude-sonnet-5-5': (2.0, 10.0), 'claude-haiku-5-5': (0.10, 0.50), 'claude-fable-5-1': (10.0, 50.0)}

def select_prompts(prompts, per_task, seed):
    rng = random.Random(seed); by = {}
    for p in prompts: by.setdefault(p['task_type'], []).append(p)
    return [p for task in sorted(by) for p in sorted(rng.sample(by[task], min(per_task, len(by[task]))), key=lambda p: p['id'])]

def estimate(n_gen, n_judge, gen_model, judge_model):
    def cost(model, calls, tin, tout):
        price = PRICES.get(model)
        return None if price is None else calls * (tin * price[0] + tout * price[1]) / 1e6
    g, j = cost(gen_model, n_gen, GEN_IN, GEN_OUT), cost(judge_model, n_judge, JUDGE_IN, JUDGE_OUT)
    return dict(generation_calls=n_gen, judge_calls=n_judge, generation_usd=None if g is None else round(g, 2), judge_usd=None if j is None else round(j, 2),
        total_usd=None if g is None or j is None else round(g + j, 2),
        note=f'rough: assumes ~{GEN_IN}/{GEN_OUT} tokens per generation and ~{JUDGE_IN}/{JUDGE_OUT} per judgement (in/out incl. thinking); unknown models are not priced')

def load(path):
    if not path.exists(): return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def key(r):
    return (r['gen_model'], r['placement'], r['prompt_id'], r['condition_id'])

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--provider', choices=['anthropic', 'openai-compatible', 'mock'], default='anthropic')
    ap.add_argument('--model', default=DEFAULT_MODEL, help='model under test')
    ap.add_argument('--effort', default='medium', help="generation effort for Claude models; 'none' omits it")
    ap.add_argument('--judge-model', default=DEFAULT_MODEL)
    ap.add_argument('--judge-effort', default='high', help="'none' omits it")
    ap.add_argument('--no-judge-fallback', action='store_true', help='do not let a declined judgement fall back to another model')
    ap.add_argument('--base-url', help='openai-compatible base URL'); ap.add_argument('--key-env', help='env var holding the openai-compatible key')
    ap.add_argument('--placement', choices=['turn', 'system'], default='turn', help='style text after the task in the user turn (as Claude Code and Hermes inject it) or in the system prompt')
    ap.add_argument('--per-task', type=int, default=4, help='prompts per task type (4 = all 36)')
    ap.add_argument('--kinds', default='trait,habit,static', help='condition kinds to include besides baseline and neutral')
    ap.add_argument('--rejudge', type=float, default=0.1, help='fraction of replies judged twice, for judge consistency')
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--seed', type=int, default=20261023)
    ap.add_argument('--run-dir', default=str(ROOT / 'benchmarks/live/runs/default'))
    ap.add_argument('--report-dir', default=str(ROOT / 'docs/reports'))
    ap.add_argument('--execute', action='store_true', help='call models (otherwise a dry run)')
    ap.add_argument('--report-only', action='store_true')
    a = ap.parse_args(argv)
    run_dir = Path(a.run_dir); records_path = run_dir / 'records.jsonl'
    if a.report_only: return write_report(load(records_path), a, run_dir)
    prompts = select_prompts(design.load_prompts(), a.per_task, a.seed)
    rows = design.plan(prompts, set(a.kinds.split(',')))
    done = {key(r) for r in load(records_path) if r.get('judge') or (r.get('gen') and r['gen'].get('stop_reason') == 'refusal')}
    todo = [(p, c) for p, c in rows if (a.model, a.placement, p['id'], c['id']) not in done]
    rng = random.Random(a.seed); rejudge = {(p['id'], c['id']) for p, c in todo if rng.random() < a.rejudge}
    est = estimate(len(todo), len(todo) + len(rejudge), a.model if a.provider == 'anthropic' else None, a.judge_model)
    summary = dict(prompts=len(prompts), conditions=len({c['id'] for _, c in rows}), planned=len(rows), already_done=len(rows) - len(todo), to_run=len(todo), rejudged=len(rejudge), **est)
    print(json.dumps(summary, indent=2))
    if not a.execute:
        print('Dry run: nothing was called. Add --execute to run.' if a.provider != 'mock' else 'Dry run. Add --execute to run the mock pipeline.'); return 0
    if a.provider == 'anthropic': gen = AnthropicProvider()
    elif a.provider == 'openai-compatible':
        if not a.base_url or not a.key_env: ap.error('--base-url and --key-env are required for openai-compatible')
        gen = OpenAICompatibleProvider(a.base_url, a.key_env)
    else: gen = MockProvider()
    judge = gen if a.provider == 'mock' else AnthropicProvider()
    effort = None if a.effort == 'none' or a.provider != 'anthropic' else a.effort
    judge_effort = None if a.judge_effort == 'none' else a.judge_effort
    run_dir.mkdir(parents=True, exist_ok=True); lock = threading.Lock()
    def work(p, c):
        r = dict(gen_model=a.model, provider=a.provider, placement=a.placement, prompt_id=p['id'], task_type=p['task_type'], condition_id=c['id'], kind=c['kind'],
            trait=c.get('trait'), level=c.get('level'), habit=c.get('habit'), control_id=c.get('control_id'), controls=c['controls'], habits=c['habits'],
            style_text=c['text'], at=datetime.now(timezone.utc).isoformat())
        try:
            r['gen'] = gen.generate(a.model, p['prompt'], c['text'], a.placement, effort)
            if r['gen']['stop_reason'] != 'refusal':
                r['judge'] = judge.judge(a.judge_model, p['prompt'], r['gen']['text'], judge_effort, not a.no_judge_fallback)
                if (p['id'], c['id']) in rejudge: r['judge_repeat'] = judge.judge(a.judge_model, p['prompt'], r['gen']['text'], judge_effort, not a.no_judge_fallback)
        except Refused as exc: r['error'] = f'judge refused: {exc}'
        except Exception as exc: r['error'] = f'{type(exc).__name__}: {str(exc)[:300]}'
        with lock, open(records_path, 'a') as f: f.write(json.dumps(r) + '\n')
        return r
    failed = 0
    with ThreadPoolExecutor(a.workers) as pool:
        for i, fut in enumerate(as_completed([pool.submit(work, p, c) for p, c in todo]), 1):
            failed += bool(fut.result().get('error'))
            if i % 25 == 0 or i == len(todo): print(f'{i}/{len(todo)} done, {failed} errors', file=sys.stderr)
    return write_report(load(records_path), a, run_dir)

def write_report(records, a, run_dir):
    # Only the latest record per key counts (a failed attempt is retried by a later run).
    latest = {}
    for r in records: latest[key(r)] = r
    records = list(latest.values())
    if not records: print('no records'); return 1
    report = dict(kind='live-model style evaluation; judged by a model, not by people', catalogue_hash=CATALOGUE_HASH, generated_at=datetime.now(timezone.utc).isoformat(),
        run_dir=str(run_dir), placements=sorted({r['placement'] for r in records}), providers=sorted({r['provider'] for r in records}),
        judge_models=sorted({r['judge']['served_model'] for r in records if r.get('judge')}), prompts=len({r['prompt_id'] for r in records}),
        thresholds=dict(distinguishability=analysis.DISTINGUISH_MIN, spearman=analysis.SPEARMAN_MIN, habit_lift=analysis.HABIT_LIFT_MIN,
            quality_delta=analysis.QUALITY_DROP_MAX, leakage=analysis.LEAKAGE_MAX),
        **analysis.analyse(records),
        limitations=['A model judges style; no human raters. Judge consistency is reported, judge validity against people is not.',
            'Fixed single-turn prompts; no multi-turn sessions, tools or host harness.',
            'Some habits are conditional ("when useful", "when ambiguous"); low adherence can be correct behaviour on prompts that do not call for them.',
            'Probes vary one trait from the neutral configuration; interactions between traits are not measured.'])
    out = Path(a.report_dir); out.mkdir(parents=True, exist_ok=True)
    mock = any(r['provider'] == 'mock' for r in records)
    stem = 'live-eval-mock' if mock else 'live-eval'
    (out / f'{stem}.json').write_text(json.dumps(report, indent=2) + '\n'); (out / f'{stem}.md').write_text(markdown(report))
    print(f'wrote {out / stem}.json and .md'); return 0

def markdown(r):
    lines = [f'# Live-model style evaluation', '', f'{r["kind"]}. Catalogue `{r["catalogue_hash"][:19]}…`, {r["prompts"]} prompts, placement {", ".join(r["placements"])}, '
        f'judge {", ".join(r["judge_models"]) or "-"}.', '']
    for model, m in r['models'].items():
        lines += [f'## {model}', '', f'{m["judged"]} judged replies of {m["records"]} ({m["errors"]} errors).', '',
            '| Trait | Spearman | mean judged at level 0 / 1 / 2 / 3 / 4 | distinguishability 0-1 / 1-2 / 2-3 / 3-4 | leakage |', '|---|---|---|---|---|']
        for t, x in m['traits'].items():
            means = ' / '.join('-' if v is None else f'{v:.2f}' for v in x['mean_judged_by_level'].values())
            dist = ' / '.join('-' if v['distinguishability'] is None else f'{v["distinguishability"]:.2f}' for v in x['adjacent'].values())
            lines.append(f'| {t} | {x["spearman"]} | {means} | {dist} | {x["leakage"]} |')
        lines += ['', '| Habit | adherence | control rate | lift |', '|---|---|---|---|']
        lines += [f'| {h} | {x["adherence"]} | {x["control_rate"]} | {x["lift"]} |' for h, x in m['habits'].items()]
        q = m['quality']
        lines += ['', f'Task quality, styled minus no style: {q["styled_minus_baseline"]}. Static persona minus no style: {q["static_minus_baseline"]}. '
            f'Refusal rate: {q["refusal_rate"]}.', '', f'Judge consistency: {m["judge_consistency"]}.', '', '### To revise', '']
        lines += [f'* {f["issue"]}' for f in m['flags']] or ['* nothing below the thresholds']
        lines.append('')
    if r.get('cross_model_spearman'): lines += ['## Cross-model agreement (Spearman of judged trait levels)', '', *[f'* {k}: {v}' for k, v in r['cross_model_spearman'].items()], '']
    lines += ['## Limitations', '', *[f'* {x}' for x in r['limitations']], '']
    return '\n'.join(lines)

if __name__ == '__main__': sys.exit(main())
