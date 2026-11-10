"""Persona identity benchmark (ADR 0007), offline on simulated models, and the human
rater export and scoring."""
import json
from pathlib import Path
import pytest
from benchmarks.identity import run, analysis, humans, lineup
from benchmarks.live import design

def test_split_is_disjoint_and_balanced():
    fit, score = run.split(design.load_prompts())
    assert len(fit) == len(score) == 18 and not {p['id'] for p in fit} & {p['id'] for p in score}
    assert {p['task_type'] for p in fit} == {p['task_type'] for p in score}

def test_trials_are_identical_across_arms_and_blind():
    prompts = run.split(design.load_prompts())[1]
    a = run.trials_plan(['m1', 'm2'], prompts, 2, 7); assert a == run.trials_plan(['m1', 'm2'], prompts, 2, 7) != run.trials_plan(['m1', 'm2'], prompts, 2, 8)
    assert len(a) == 7 * 2 * 2 and all(t['source_model'] != t['target_model'] and t['target_prompt'] not in t['reference_prompts'] for t in a)
    assert all(t['candidates'][t['correct']] == t['persona'] and len(set(t['candidates'])) == run.CANDIDATES for t in a)
    assert {t['correct'] for t in a} == set(range(run.CANDIDATES))  # the answer is not always in one slot
    # The judge's message names no persona, model or style.
    msg = lineup.message([('task one', 'reply one')], [('task two', 'x'), ('task two', 'y')])
    assert 'mentor' not in msg and 'model' not in msg.lower() and msg.count('<candidate n=') == 2 and lineup.schema(4)['properties']['choice']['enum'] == [1, 2, 3, 4]

def test_simulated_run_end_to_end(tmp_path, capsys):
    """Small run: two distorted models. Calibration must not make identity worse, nothing
    may be rendered outside the approved set, and the run resumes without new calls."""
    args = ['--models', 'sim-effusive', 'sim-stiff', '--per-task', '2', '--trials', '2', '--run-dir', str(tmp_path / 'run'), '--report-dir', str(tmp_path / 'out')]
    assert run.main(args) == 0 and not (tmp_path / 'run').exists()  # plan only
    assert run.main(args + ['--execute', '--export-items', str(tmp_path / 'items.json')]) == 0
    r = json.loads((tmp_path / 'out/identity-simulated.json').read_text())
    assert 'NOT live-model or human evidence' in r['kind'] and r['counts_towards_release_gate'] is False
    cal, base = r['arms']['calibrated'], r['arms']['uncalibrated']
    assert cal['rendered_outside_approved_set'] == base['rendered_outside_approved_set'] == 0 and r['shifted_share'] > 0.2
    assert cal['systematic_cross_model']['mean'] < base['systematic_cross_model']['mean']
    assert cal['same_persona_across_models']['mean'] < base['same_persona_across_models']['mean']
    assert cal['lineup_accuracy']['mean'] >= base['lineup_accuracy']['mean'] - 0.05 and cal['lineup_accuracy']['mean'] > 0.4
    h = r['hypotheses']
    assert h['H5 nothing rendered outside the approved, masked set']['result'] == 'met' and h['H3 line-up accuracy higher than a static persona']['result'] == 'not tested'
    assert r['profiles']['sim-stiff']['dead'] == ['formality'] and 'static' not in r['arms']
    lines = (tmp_path / 'run/replies.jsonl').read_text().count('\n')
    assert run.main(args + ['--execute']) == 0 and (tmp_path / 'run/replies.jsonl').read_text().count('\n') == lines
    assert 'Persona identity benchmark' in capsys.readouterr().out
    # Human rater files: items carry texts only; the key is separate.
    items = json.loads((tmp_path / 'items.json').read_text()); key = json.loads((tmp_path / 'items.json.key.json').read_text())
    assert items['format'] == 'openape-identity-items/1' and set(items['items'][0]) == {'id', 'references', 'candidate_task', 'candidates'}
    blob = json.dumps(items['items']); assert '"correct"' not in blob and 'sim-stiff' not in blob and 'mentor' not in blob and '"arm' not in blob
    assert {i['id'] for i in items['items']} == set(key['items'])
    # A perfect rater and a rater who always picks the first candidate.
    perfect = dict(rater='a', answers={k: v['correct'] for k, v in key['items'].items()}); first = dict(rater='b', answers={k: 0 for k in key['items']})
    s = humans.score(key, [perfect, first, dict(rater='c', answers={'unknown': 1, next(iter(key['items'])): 'x'})])
    assert s['raters'] == 2 and s['inter_rater']['pairs'] == len(key['items']) and 0 <= s['human_judge_agreement']['same_choice'] <= 1
    assert humans.score(key, [perfect])['accuracy']['calibrated']['mean'] == 1.0

def test_hypotheses_follow_their_thresholds():
    """Synthetic records: calibrated replies agree across models, uncalibrated differ."""
    from protocol.catalogue import TRAITS, HABITS, NEUTRAL
    def rec(arm, persona, model, prompt, level, quality=4):
        return dict(arm=arm, persona=persona, gen_model=model, prompt_id=prompt, controls=dict(NEUTRAL), rendered=dict(NEUTRAL), habits=[], violation=False,
            gen=dict(text='x', stop_reason='end_turn'), judge=dict(traits={t: level for t in TRAITS}, habits={h['id']: False for h in HABITS}, task_quality=quality, refused=False))
    records = []
    for prompt in ('p1', 'p2', 'p3', 'p4'):
        for persona, level in (('a', 1), ('b', 3)):
            records += [rec('calibrated', persona, 'm1', prompt, level), rec('calibrated', persona, 'm2', prompt, level),
                rec('uncalibrated', persona, 'm1', prompt, level), rec('uncalibrated', persona, 'm2', prompt, 2)]
    trials = [dict(arm=arm, trial_id=f't{i}', target_prompt=f'p{i % 4 + 1}', correct=0, answer=0 if arm == 'calibrated' else (i // 4) % 2) for arm in ('calibrated', 'uncalibrated') for i in range(16)]
    r = analysis.analyse(records, trials, 4)
    assert r['arms']['calibrated']['same_persona_across_models']['mean'] == 0 and r['arms']['uncalibrated']['same_persona_across_models']['mean'] == 1
    assert r['comparisons']['calibrated minus uncalibrated']['relative_reduction'] == 1.0
    assert [h['result'] for h in r['hypotheses'].values()] == ['met', 'met', 'met', 'not tested', 'met']
    # A quality drop or an out-of-catalogue rendering fails its hypothesis.
    worse = [dict(x, judge=dict(x['judge'], task_quality=3)) if x['arm'] == 'calibrated' else x for x in records]; worse[0] = dict(worse[0], violation=True)
    h = analysis.analyse(worse, trials, 4)['hypotheses']
    assert h['H4 task quality not harmed']['result'] == 'not met' and h['H5 nothing rendered outside the approved, masked set']['result'] == 'not met'

def test_rater_page_is_self_contained():
    html = Path('benchmarks/identity/rater.html').read_text()
    assert 'src=' not in html and 'http://' not in html and 'https://' not in html and 'fetch(' not in html and 'innerHTML' not in html
    assert 'openape-identity-items/1' in html and 'openape-identity-results/1' in html
