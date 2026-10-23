"""Live-model evaluation harness, offline: design, judge schema, Claude request shape
(fake SDK client) and the analysis catching known defects injected by the mock."""
import json
from types import SimpleNamespace
import pytest
from protocol.catalogue import TRAITS, HABITS, NEUTRAL, CATALOGUE_HASH
from benchmarks.live import design, judge, analysis, run
from benchmarks.live.providers import MockProvider, AnthropicProvider, Refused

def records_for(provider, prompts, kinds=('trait', 'habit', 'static')):
    out = []
    for p, c in design.plan(prompts, set(kinds)):
        gen = provider.generate('m', p['prompt'], c['text'])
        out.append(dict(gen_model='m', provider='mock', placement='turn', prompt_id=p['id'], condition_id=c['id'], kind=c['kind'], trait=c.get('trait'),
            level=c.get('level'), habit=c.get('habit'), control_id=c.get('control_id'), gen=gen, judge=provider.judge('j', p['prompt'], gen['text'])))
    return out

def test_design_probes_and_matched_controls():
    conds = design.conditions(); ids = {c['id'] for c in conds}
    assert [c['kind'] for c in conds[:3]] == ['baseline', 'static', 'neutral']
    assert sum(c['kind'] == 'trait' for c in conds) == len(TRAITS) * 4 and sum(c['kind'] == 'habit' for c in conds) == len(HABITS)
    for c in conds:
        if c['kind'] == 'habit': assert c['control_id'] in ids and c['text'].endswith(next(h['text'] for h in HABITS if h['id'] == c['habit']))
    neutral = conds[2]['text'];assert neutral.startswith('Style preferences only.') and 'Avoid humour.' in neutral
    # High stakes: the engine never serves humour above 1, so those probes are skipped.
    risky = dict(id='x', task_type='debugging', stakes='high', tags=[], prompt='p')
    planned = {c['id'] for _, c in design.plan([risky])}
    assert design.condition_id(dict(NEUTRAL, humour=1)) in planned and design.condition_id(dict(NEUTRAL, humour=3)) not in planned
    assert not any(c.get('habit') == 'light_aside' for _, c in design.plan([risky]))
    # Selecting habits alone still brings their matched controls.
    only = {c['id'] for _, c in design.plan([dict(risky, stakes='low')], {'habit'})}
    assert all(c['control_id'] in only for c in conds if c['kind'] == 'habit')

def test_judge_schema_and_validation():
    assert set(judge.SCHEMA['properties']['traits']['required']) == set(TRAITS)
    good = dict(traits={t: 2 for t in TRAITS}, habits={h['id']: False for h in HABITS}, task_quality=4, refused=False)
    assert judge.parse(json.dumps(good)) == good
    for bad in (dict(good, traits={**good['traits'], 'warmth': 5}), dict(good, task_quality=0), dict(good, extra=1), dict(good, habits={}), dict(good, refused='no')):
        with pytest.raises(ValueError): judge.validate(bad)
    assert 'Use a very warm, encouraging tone.' in judge.SYSTEM and 'requested' not in judge.message('task', 'reply')

def test_analysis_flags_injected_defects():
    prompts = run.select_prompts(design.load_prompts(), 1, 0)
    clean = analysis.analyse(records_for(MockProvider(), prompts))['models']['m']
    assert clean['flags'] == [] and all(m['spearman'] == 1.0 for m in clean['traits'].values())
    mock = MockProvider(confuse={('humour', 4): 3}, ignored_habits=['clarify_once'], quality_drop={('verbosity', 0): 2})
    report = analysis.analyse(records_for(mock, prompts))['models']['m']
    issues = {(f['kind'], f.get('trait'), f.get('levels'), f.get('habit'), f.get('condition')) for f in report['flags']}
    assert ('levels', 'humour', '3-4', None, None) in issues
    assert ('habit', None, None, 'clarify_once', None) in issues
    assert ('quality', None, None, None, design.condition_id(dict(NEUTRAL, verbosity=0))) in issues
    assert report['traits']['humour']['adjacent']['3-4']['distinguishability'] == 0.5 and report['habits']['clarify_once']['lift'] == 0.0

def test_cli_dry_run_calls_nothing_and_mock_run_resumes(tmp_path, capsys):
    args = ['--provider', 'mock', '--model', 'mock-model', '--per-task', '1', '--kinds', 'habit', '--run-dir', str(tmp_path / 'run'), '--report-dir', str(tmp_path / 'rep')]
    assert run.main(args) == 0 and not (tmp_path / 'run').exists()
    plan = json.loads(capsys.readouterr().out.split('Dry run')[0])
    assert plan['to_run'] == plan['planned'] > 0 and plan['generation_usd'] is None  # mock models are not priced
    assert run.main(args + ['--execute']) == 0
    report = json.loads((tmp_path / 'rep/live-eval-mock.json').read_text())
    assert report['catalogue_hash'] == CATALOGUE_HASH and report['models']['mock-model']['judged'] == plan['planned']
    capsys.readouterr();assert run.main(args) == 0
    assert json.loads(capsys.readouterr().out.split('Dry run')[0])['to_run'] == 0  # resumes: nothing left
    assert run.estimate(10, 11, 'claude-opus-5-5', 'claude-opus-5-5')['total_usd'] > 0

class FakeMessages:
    def __init__(self, response):self.calls = [];self.response = response
    def create(self, **kwargs):self.calls.append(kwargs);return self.response

def fake_provider(text, stop_reason='end_turn'):
    response = SimpleNamespace(content=[SimpleNamespace(type='thinking', thinking=''), SimpleNamespace(type='text', text=text)], stop_reason=stop_reason,
        model='claude-opus-5-5', usage=SimpleNamespace(input_tokens=10, output_tokens=20), stop_details=SimpleNamespace(category='cyber'))
    provider = object.__new__(AnthropicProvider)  # no SDK import or credentials needed
    provider.client = SimpleNamespace(messages=FakeMessages(response), beta=SimpleNamespace(messages=FakeMessages(response)))
    return provider

def test_anthropic_request_shape():
    p = fake_provider('a reply')
    out = p.generate('claude-opus-5-5', 'task', 'STYLE', 'turn', 'medium')
    call = p.client.messages.calls[0]
    assert out['text'] == 'a reply' and 'fallbacks' not in call and 'temperature' not in call and call['output_config'] == {'effort': 'medium'}
    assert [b['text'] for b in call['messages'][0]['content']] == ['task', 'STYLE'] and 'system' not in call
    p.generate('claude-opus-5-5', 'task', 'STYLE', 'system', None)
    call = p.client.messages.calls[1];assert call['system'] == 'STYLE' and 'output_config' not in call
    good = dict(traits={t: 1 for t in TRAITS}, habits={h['id']: True for h in HABITS}, task_quality=5, refused=False)
    p = fake_provider(json.dumps(good))
    assert p.judge('claude-opus-5-5', 'task', 'reply', 'high')['traits'] == good['traits']
    call = p.client.beta.messages.calls[0]
    assert call['fallbacks'] == 'default' and call['betas'] == ['server-side-fallback-2026-07-01']
    assert call['output_config']['format']['schema'] == judge.SCHEMA and call['output_config']['effort'] == 'high' and call['system'] == judge.SYSTEM
    p.judge('claude-opus-5-5', 'task', 'reply', None, fallback=False)
    assert 'fallbacks' not in p.client.messages.calls[0] and 'effort' not in p.client.messages.calls[0]['output_config']
    with pytest.raises(Refused):fake_provider('', 'refusal').judge('claude-opus-5-5', 't', 'r')
    with pytest.raises(ValueError):fake_provider('{"traits"', 'max_tokens').judge('claude-opus-5-5', 't', 'r')

def test_statistics():
    assert analysis.spearman([0, 1, 2, 3], [0, 1, 2, 3]) == 1.0 and analysis.spearman([0, 1, 2, 3], [3, 2, 1, 0]) == -1.0 and analysis.spearman([1, 2], [1, 2]) is None
    b = analysis.bootstrap({'a': [1, 1], 'b': [0]});assert b['mean'] == round(2 / 3, 4) and b['clusters'] == 2 and b['ci95'][0] <= b['mean'] <= b['ci95'][1]
