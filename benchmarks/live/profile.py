"""Build a Model Style Profile (style-profile/1, ADR 0007) from live-evaluation records.

    python -m benchmarks.live.profile --run-dir benchmarks/live/runs/NAME --model MODEL --out DIR
    python -m benchmarks.live.profile --report docs/reports/live-eval-placement.json \\
        --run 'z-ai/glm-5.3-flash [turn]' --model z-ai/glm-5.3-flash --out models/style-profiles

A profile is a measurement of one model by one judge on fixed prompts, at one
placement. It says how the model bends each trait, which traits it cannot express
(dead, or out of gamut), and which habits barely show. The engine applies it only to
choose among approved configurations (engine/neural/calibration.py).
"""
import argparse
import json
import sys
from pathlib import Path
import numpy as np
from protocol.catalogue import TRAITS, LEVELS, NEUTRAL, HABITS
from engine.neural import calibration
from benchmarks.live import analysis

def measure(records):
    """{trait: means, counts, spearman} and habit metrics from judged records of one model
    and placement. The neutral configuration counts as each trait's neutral level."""
    ok = analysis.judged(records); traits = {}
    for t in TRAITS:
        by = {level: [] for level in range(LEVELS)}
        for r in ok:
            if r['kind'] == 'neutral': by[NEUTRAL[t]].append(r['judge']['traits'][t])
            elif r['kind'] == 'trait' and r['trait'] == t: by[r['level']].append(r['judge']['traits'][t])
        requested = [level for level, vs in by.items() for _ in vs]; got = [v for vs in by.values() for v in vs]
        sp = analysis.spearman(requested, got)
        traits[t] = dict(means=[float(np.mean(by[level])) if by[level] else None for level in range(LEVELS)], counts=[len(by[level]) for level in range(LEVELS)],
            spearman=None if sp is None else round(sp, 4))
    habits = {h: m for h, m in analysis.habit_metrics(ok).items() if m['prompts']}
    return traits, habits

def from_records(records, model, placement='turn', prompt_ids=None, reference=None, reference_kind='anchors', run=None):
    """A sealed profile for `model` from run records, optionally from a subset of prompts
    (so that a benchmark can score compensation on prompts the profile never saw)."""
    mine = [r for r in records if r['gen_model'] == model and r.get('placement', 'turn') == placement and not r.get('example')
        and (prompt_ids is None or r['prompt_id'] in prompt_ids)]
    if not analysis.judged(mine): raise ValueError(f'no judged records for {model} at placement {placement}')
    traits, habits = measure(mine); ok = analysis.judged(mine); c = analysis.consistency(ok)
    source = dict(kind='live-evaluation records', run=run, prompts=len({r['prompt_id'] for r in ok}), replies=len(ok), provider=sorted({r.get('provider', '') for r in ok}),
        judge_consistency_within_one=c['trait_within_one'] if c else None, measured_at=max(r.get('at', '') for r in ok) or None)
    judge = ', '.join(sorted({r['judge']['served_model'] for r in ok}))
    return calibration.build(model, traits, habits, placement, judge, source, reference, reference_kind)

def from_report(report, run, model, placement='turn', reference=None, reference_kind='anchors'):
    """A profile from an analysis report (docs/reports/live-eval*.json) when the records
    are not kept. Counts are the prompts behind each level."""
    m = report['models'][run]; traits = {}
    for t in TRAITS:
        x = m['traits'][t]; means = [x['mean_judged_by_level'][str(level)] for level in range(LEVELS)]
        pairs = [x['adjacent'][f'{level}-{level + 1}']['prompts'] for level in range(LEVELS - 1)]
        counts = [max(pairs[max(level - 1, 0):level + 1]) if means[level] is not None else 0 for level in range(LEVELS)]
        traits[t] = dict(means=means, counts=counts, spearman=x['spearman'])
    habits = {h: v for h, v in m['habits'].items() if v['prompts']}
    c = m.get('judge_consistency')
    source = dict(kind='live-evaluation report', run=run, prompts=report['prompts'], replies=m['judged'], provider=report.get('providers'),
        judge_consistency_within_one=c['trait_within_one'] if c else None, measured_at=report.get('generated_at'))
    return calibration.build(model, traits, habits, placement, ', '.join(report.get('judge_models', [])), source, reference, reference_kind)

def describe(profile):
    """Plain-text gamut report: what this model does with each trait."""
    lines = [f"{profile['model_id']}  {profile['hash'][:19]}…  placement {profile.get('placement')}, judge {profile.get('judge') or '-'}, reference {profile.get('reference_kind')}",
        f"measured on {profile['source'].get('prompts', '?')} prompts, {profile['source'].get('replies', '?')} replies ({profile['source'].get('kind', 'unknown source')})", '',
        f"{'trait':<18} {'perceived at level 0..4':<30} {'reference':<30} shift  note"]
    for t in TRAITS:
        e = profile['traits'][t]; note = []
        if e['dead']: note.append('dead: requests barely change replies')
        lo, hi = e['gamut']; ref = e['reference']
        if ref[0] < lo - calibration.GAMUT_MARGIN: note.append(f'cannot go below {lo:.1f}')
        if ref[-1] > hi + calibration.GAMUT_MARGIN: note.append(f'cannot go above {hi:.1f}')
        if e.get('spearman') is not None: note.append(f"Spearman {e['spearman']}")
        lines.append(f"{t:<18} {' '.join(f'{v:4.2f}' for v in e['curve']):<30} {' '.join(f'{v:4.2f}' for v in ref):<30} ±{e['max_shift']}     {'; '.join(note)}")
    if profile.get('weak_habits'): lines += ['', 'habits that barely show on this model: ' + ', '.join(profile['weak_habits'])]
    return '\n'.join(lines)

def write(profile, directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    path = directory / (profile['model_id'].replace(':', '_') + '.json'); path.write_text(json.dumps(profile, indent=2) + '\n'); return path

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--run-dir', help='live run directory holding records.jsonl')
    ap.add_argument('--report', help='analysis report JSON, when records are not kept'); ap.add_argument('--run', help='run label inside --report')
    ap.add_argument('--model', required=True); ap.add_argument('--placement', default='turn')
    ap.add_argument('--reference', help='reference.json to measure against (default: the catalogue anchors)')
    ap.add_argument('--out', help='directory to write the profile to (default: print only)')
    a = ap.parse_args(argv)
    ref = json.loads(Path(a.reference).read_text()) if a.reference else None
    kind = ref.get('kind', 'consensus') if ref else 'anchors'; curves = ref['traits'] if ref else None
    if a.report: profile = from_report(json.loads(Path(a.report).read_text()), a.run or a.model, a.model, a.placement, curves, kind)
    elif a.run_dir:
        from benchmarks.live.run import load
        profile = from_records(load(Path(a.run_dir) / 'records.jsonl'), a.model, a.placement, None, curves, kind, run=Path(a.run_dir).name)
    else: ap.error('give --run-dir or --report')
    print(describe(profile))
    if a.out: print(f'\nwrote {write(profile, a.out)}')
    return 0

if __name__ == '__main__': sys.exit(main())
