"""Perceptual calibration (ADR 0007): profile maths against known distortions, the
compensation's safety properties, and the engine, SDK and CLI wiring."""
import json
import os
import random
import subprocess
import sys
from pathlib import Path
import pytest
import torch
from fastapi.testclient import TestClient
from conftest import *
from engine.api.app import create_app
from engine.neural import calibration as cal
from engine.neural.policy import APPROVED_LEVELS, ACTIONS, INDEX, levels_of, level_mask, mask, habits_allowed, select_habits
from protocol.catalogue import TRAITS, NEUTRAL, LEVELS, CATALOGUE_HASH, HABIT_IDS
from benchmarks.live import design, profile as profiles, simulated_model as sim
from sdk.python.client import render

CONTEXTS = [dict(stakes='low', tags=[]), dict(stakes='high', tags=[]), dict(stakes='low', tags=['urgent']), dict(stakes='high', tags=['urgent', 'sensitive'])]

def flat(curve, n=30): return {t: dict(means=list(curve), counts=[n] * LEVELS) for t in TRAITS}
def make(model='m', n=30, **curves):
    traits = flat(cal.ANCHORS, n)
    for t, c in curves.items(): traits[t] = dict(means=list(c), counts=[n] * LEVELS)
    return cal.build(model, traits)

def measured(model, per_task=4, kinds=('trait',), seed=0):
    provider = sim.SimulatedProvider(seed); out = []
    from benchmarks.live.run import select_prompts
    for p, c in design.plan(select_prompts(design.load_prompts(), per_task, 1), set(kinds)):
        gen = provider.generate(model, p['prompt'], c['text'])
        out.append(dict(gen_model=model, provider='simulated', placement='turn', prompt_id=p['id'], condition_id=c['id'], kind=c['kind'], trait=c.get('trait'),
            level=c.get('level'), habit=c.get('habit'), control_id=c.get('control_id'), gen=gen, judge=provider.judge('j', p['prompt'], gen['text'])))
    return out

def test_isotonic_and_shrinkage():
    assert cal.isotonic([1, 3, 2, 4]) == [1, 2.5, 2.5, 4] and cal.isotonic([3, 2, 1]) == [2, 2, 2] and cal.isotonic([0, 1, 2]) == [0, 1, 2]
    # Thin data stays near the reference; plenty of data follows the measurement.
    thin = cal.fit_curve([2, 2, 2, 2, 2], [1] * 5, cal.ANCHORS); thick = cal.fit_curve([2, 2, 2, 2, 2], [400] * 5, cal.ANCHORS)
    assert thin[0] < 0.5 and thin[4] > 3.5 and abs(thick[0] - 2) < 0.05 and abs(thick[4] - 2) < 0.05
    # Unmeasured levels take the reference; the result is always monotone and in range.
    curve = cal.fit_curve([None, 3.5, 1.0, None, 9.0], [0, 20, 20, 0, 20], cal.ANCHORS)
    assert curve == sorted(curve) and curve[0] == 0 and max(curve) <= 4

def test_profile_is_sealed_and_bound_to_the_catalogue(tmp_path):
    p = make('Vendor/Model X', warmth=[1, 1.5, 2, 2.5, 3]); assert p['model_id'] == 'vendor:model:x' and cal.validate(p) is p
    with pytest.raises(ValueError, match='checksum'): cal.validate({**p, 'traits': {**p['traits'], 'warmth': {**p['traits']['warmth'], 'max_shift': 2, 'curve': [0, 0, 0, 0, 4]}}})
    with pytest.raises(ValueError, match='catalogue'): cal.validate(cal.seal({**p, 'catalogue_hash': 'sha256:' + '0' * 64}))
    bad = json.loads(json.dumps(p)); bad['traits']['warmth']['curve'] = [3, 2, 1, 0, 0]
    with pytest.raises(ValueError, match='monotone'): cal.validate(cal.seal(bad))
    dead = json.loads(json.dumps(make('d', formality=[2, 2, 2.1, 2.1, 2.2]))); assert dead['traits']['formality']['dead'] and dead['traits']['formality']['max_shift'] == 0
    dead['traits']['formality']['max_shift'] = 1
    with pytest.raises(ValueError, match='dead'): cal.validate(cal.seal(dead))
    # A directory loads good profiles and reports, never applies, bad ones.
    (tmp_path / 'good.json').write_text(json.dumps(p)); (tmp_path / 'tampered.json').write_text(json.dumps({**p, 'model_id': 'other'})); (tmp_path / 'junk.json').write_text('[')
    loaded = cal.Profiles([tmp_path, tmp_path / 'missing'])
    assert list(loaded.by_model) == ['vendor:model:x'] and len(loaded.rejected) == 2 and loaded.get('VENDOR/model x')['hash'] == p['hash'] and loaded.get('nope') is None

def test_identity_profile_changes_nothing():
    p = make(); rng = random.Random(0)
    for ctx in CONTEXTS:
        allowed = torch.nonzero(mask(ctx)).flatten().tolist()
        for action in rng.sample(allowed, 200): assert cal.compensate(action, [], ctx, p) == (action, [])

def test_known_distortions_are_recovered_and_corrected():
    for model in sim.MODELS:
        p = profiles.from_records(measured(model), model); spec = sim.MODELS[model]
        for t in TRAITS:
            if not p['traits'][t]['dead']: assert max(abs(a - b) for a, b in zip(p['traits'][t]['curve'], spec['curves'][t])) < 0.45, (model, t)
    stiff = profiles.from_records(measured('sim-stiff'), 'sim-stiff')
    assert stiff['traits']['formality']['dead'] and stiff['traits']['formality']['max_shift'] == 0 and not stiff['traits']['warmth']['dead']
    # On the effusive model (too warm, too wordy, too casual) a mentor-like intent is asked for
    # less warmth and detail and more formality, and its true percept moves closer to the intent.
    effusive = profiles.from_records(measured('sim-effusive'), 'sim-effusive'); ctx = CONTEXTS[0]
    intent = dict(NEUTRAL, warmth=3, verbosity=3, formality=1, explanation_depth=3); action = INDEX[tuple(intent[t] for t in TRAITS)]
    best, notes = cal.compensate(action, ['next_step'], ctx, effusive); shown = levels_of(best)
    assert shown['warmth'] < 3 and shown['verbosity'] < 3 and shown['formality'] > 1 and 'shifted:warmth' in notes
    err = lambda levels: sum(abs(sim.true_percept('sim-effusive', levels)[t] - intent[t]) for t in TRAITS)
    assert err(shown) < err(intent) - 1.0
    # The dead trait is never moved and is reported as out of gamut when the intent is far away.
    informal = INDEX[tuple(dict(NEUTRAL, formality=0)[t] for t in TRAITS)]
    best, notes = cal.compensate(informal, [], ctx, stiff)
    assert levels_of(best)['formality'] == 0 and 'out_of_gamut:formality' in notes and 'shifted:formality' not in notes

def test_compensation_never_leaves_the_approved_masked_bounded_set():
    """Whatever the profile says: an approved configuration, allowed in this context,
    within max_shift, pinned traits untouched, habits still eligible, and no worse than
    the intent under the profile's own curves."""
    rng = random.Random(7); wild = []
    for k in range(6):
        curves = {t: sorted(rng.uniform(0, 4) for _ in range(LEVELS)) for t in TRAITS}
        wild.append(cal.compiled(make(f'wild-{k}', n=rng.choice([5, 60]), **curves)))
    wild += [cal.compiled(profiles.from_records(measured(m, per_task=2), m)) for m in ('sim-compressed', 'sim-stiff', 'sim-dramatic')]
    shifts = 0
    for p in wild:
        for ctx in CONTEXTS:
            allowed = torch.nonzero(mask(ctx)).flatten().tolist(); lm = level_mask(ctx)
            for action in rng.sample(allowed, 60):
                habits = select_habits(torch.tensor([rng.uniform(-1, 2) for _ in HABIT_IDS]), action, ctx)
                pins = {rng.choice(TRAITS): {'min': 0, 'max': 4}} if rng.random() < 0.3 else {}
                best, notes = cal.compensate(action, habits, ctx, p, pins); shifts += best != action
                intended, shown = APPROVED_LEVELS[action], APPROVED_LEVELS[best]
                assert 0 <= best < ACTIONS and bool(mask(ctx)[best]) and all(bool(lm[i, int(shown[i])]) for i in range(len(TRAITS)))
                assert habits_allowed(habits, best, ctx)
                for i, t in enumerate(TRAITS):
                    assert abs(int(shown[i]) - int(intended[i])) <= (0 if t in pins else p['traits'][t]['max_shift'])
                    assert (f'shifted:{t}' in notes) == (int(shown[i]) != int(intended[i]))
                target = cal.intent(p, levels_of(action)); err = lambda a: sum(abs(cal.predict(p, levels_of(a))[t] - target[t]) for t in TRAITS)
                assert err(best) <= err(action) + 1e-6
    assert shifts > 100  # the property is not vacuous

def test_consensus_reference_cancels_what_models_share():
    # Every model sits one level high on directness: against the anchors each would be
    # pushed down; against their consensus none moves, because they already agree.
    ps = [make(f'm{i}', directness=[1, 2, 3, 3.9, 4]) for i in range(3)]; action = INDEX[tuple(dict(NEUTRAL, directness=2)[t] for t in TRAITS)]
    assert levels_of(cal.compensate(action, [], CONTEXTS[0], ps[0])[0])['directness'] == 1
    ref = cal.consensus(ps); rebased = cal.rebase(ps[0], ref)
    assert rebased['reference_kind'] == 'consensus' and rebased['hash'] != ps[0]['hash'] and cal.compensate(action, [], CONTEXTS[0], rebased) == (action, [])

SETTINGS_TOKEN = 'alice-settings-token-00000000000000'
def profile_app(tmp_path, profile, mode=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / 'style-profiles').mkdir(); (tmp_path / 'style-profiles' / 'p.json').write_text(json.dumps(profile))
    creds = CREDENTIALS + [dict(token=SETTINGS_TOKEN, tenant='local', actor='alice-settings', scopes=['persona:express', 'settings:write'], personas=['ape'], users=['alice'])]
    return TestClient(create_app(tmp_path, credentials=creds, calibration_mode=mode), headers={'Authorization': 'Bearer ' + TOKEN})

def express(api, request_id, model, session=None, user='alice', **context):
    req = expression(request_id, session=session or request_id); req['host']['model_id'] = model; req['context'].update(context)
    if user is None: del req['identity']['user_id']
    r = api.post('/v1/express', json=req); assert r.status_code == 200, r.text; return r.json()

WARM_MODEL = dict(warmth=[1.0, 2.0, 3.0, 3.8, 4.0], humour=[0.0, 0.0, 0.3, 0.9, 1.6], formality=[2.0, 2.0, 2.05, 2.1, 2.1])

def test_engine_renders_for_the_model_and_keeps_the_intent(tmp_path):
    with profile_app(tmp_path, make('Acme/Chatty-1', **WARM_MODEL)) as api:
        assert post(api, '/v1/personas', {'persona_id': 'ape', 'archetype': 'concierge', 'evolution': 'manual', 'individuality': 0}).status_code == 200
        # A mentor's acknowledge_progress habit needs warmth 3-4, so its warmth cannot be rendered lower.
        assert post(api, '/v1/personas', {'persona_id': 'tutor', 'archetype': 'mentor', 'evolution': 'manual', 'individuality': 0}).status_code == 200
        tutor = api.post('/v1/express', json={**expression('r-tutor', persona='tutor'), 'host': {**expression()['host'], 'model_id': 'acme:chatty-1'}}).json()
        assert 'acknowledge_progress' in tutor['habits'] and tutor['rendering']['controls']['warmth'] == tutor['controls']['warmth'] >= 3
        caps = api.get('/v1/capabilities').json()['calibration']
        assert caps['mode'] == 'installed' and caps['profiles'][0]['model_id'] == 'acme:chatty-1' and caps['profiles'][0]['dead'] == ['formality'] and caps['rejected'] == 0
        plain = express(api, 'r-plain', 'some-other-model'); calibrated = express(api, 'r-cal', 'acme:chatty-1')
        # The persona's intent is identical on both models; only the rendering differs.
        assert plain['rendering'] is None and calibrated['controls'] == plain['controls'] and calibrated['habits'] == plain['habits']
        r = calibrated['rendering']; assert r['model_id'] == 'acme:chatty-1' and r['style_profile'].startswith('sha256:')
        assert calibrated['controls']['warmth'] >= 3 and r['controls']['warmth'] == calibrated['controls']['warmth'] - 1 and 'shifted:warmth' in r['notes']
        assert r['controls']['formality'] == calibrated['controls']['formality']  # dead trait untouched
        # The host renders the calibrated levels; the same decision without `rendering` renders the intent.
        from protocol.catalogue import TEMPLATES
        text = render(calibrated); assert TEMPLATES['warmth'][r['controls']['warmth']] in text and TEMPLATES['warmth'][calibrated['controls']['warmth']] not in text
        assert render({**calibrated, 'rendering': None}) == render(plain)
        # Replay is idempotent, and the explanation says what was adjusted and why.
        assert express(api, 'r-cal', 'acme:chatty-1') == calibrated
        why = api.get(f"/v1/decisions/{calibrated['decision_id']}/explanation").json()
        assert why['calibration']['traits']['warmth']['rendered'] == r['controls']['warmth'] and 'over-expresses' in why['calibration']['traits']['warmth']['why']
        assert why['traits']['warmth']['level'] == calibrated['controls']['warmth'] and any('Calibrated for acme:chatty-1' in s for s in why['summary'])
        assert api.get(f"/v1/decisions/{plain['decision_id']}/explanation").json()['calibration'] is None
        # Feedback stays in intent space: comparing serves the intent, not the rendering.
        options = post(api, '/v1/comparisons', {'decision_id': calibrated['decision_id']}).json()['options']
        assert calibrated['controls'] in [o['controls'] for o in options]

def test_engine_masks_and_pins_hold_under_calibration(tmp_path):
    # A model that barely jokes: the profile would ask for much more humour.
    with profile_app(tmp_path, make('dry', n=60, humour=[0.0, 0.0, 0.2, 0.6, 1.2], warmth=[0, 0.4, 1.0, 1.8, 2.6])) as api:
        assert post(api, '/v1/personas', {'persona_id': 'ape', 'archetype': 'collaborator', 'evolution': 'manual', 'individuality': 0}).status_code == 200
        low = express(api, 'low', 'dry'); assert low['controls']['humour'] >= 1 and low['rendering']['controls']['humour'] > low['controls']['humour']
        for i, ctx in enumerate([dict(stakes='high'), dict(tags=['sensitive']), dict(stakes='high', tags=['urgent'])]):
            d = express(api, f'serious-{i}', 'dry', **ctx)
            assert d['controls']['humour'] <= 1 and d['rendering']['controls']['humour'] <= 1 and 'light_aside' not in d['habits']
            if 'urgent' in ctx.get('tags', []): assert d['rendering']['controls']['verbosity'] <= 2
        # A user's pin is literal: the pinned trait is rendered exactly as chosen.
        warm = low['controls']['warmth']
        assert api.put('/v1/personas/ape/users/alice/settings', json={'protocol_version': 'upap/2', 'pins': {'warmth': {'min': warm, 'max': warm}, 'humour': {'min': 0, 'max': 0}}},
            headers={'Authorization': 'Bearer ' + SETTINGS_TOKEN}).status_code == 200
        pinned = express(api, 'pinned', 'dry')
        assert pinned['controls']['warmth'] == pinned['rendering']['controls']['warmth'] == warm and pinned['rendering']['controls']['humour'] == 0

def test_calibration_off_and_rejected_profiles(tmp_path):
    good = make('dry', humour=[0.0, 0.0, 0.2, 0.6, 1.2])
    with profile_app(tmp_path / 'off', good, 'off') as api:
        post(api, '/v1/personas', {'persona_id': 'ape', 'archetype': 'collaborator', 'evolution': 'manual'})
        assert express(api, 'r', 'dry')['rendering'] is None and api.get('/v1/capabilities').json()['calibration']['profiles'] == []
    tampered = {**good, 'traits': {**good['traits'], 'humour': {**good['traits']['humour'], 'curve': [0, 0, 0, 0, 0]}}}
    with profile_app(tmp_path / 'bad', tampered) as api:
        post(api, '/v1/personas', {'persona_id': 'ape', 'archetype': 'collaborator', 'evolution': 'manual'})
        assert express(api, 'r', 'dry')['rendering'] is None and api.get('/v1/capabilities').json()['calibration']['rejected'] == 1
    with pytest.raises(ValueError): create_app(tmp_path / 'x', credentials=CREDENTIALS, calibration_mode='sometimes')

def test_learning_carries_across_models(tmp_path):
    """What a persona learns is intent: feedback given while one model is calibrated moves
    the persona the same way for a model with another profile or none."""
    with profile_app(tmp_path, make('dry', n=60, warmth=[0, 0.4, 1.0, 1.8, 2.6])) as api:
        assert post(api, '/v1/personas', {'persona_id': 'ape', 'archetype': 'balanced', 'evolution': 'manual', 'individuality': 0}).status_code == 200
        before = express(api, 'before', 'other', user=None)
        for i in range(36):
            d = express(api, f'fb-{i}', 'dry', session=f's-{i}', user=None); assert d['rendering'] is not None
            served = {'controls': d['controls'], 'habits': d['habits']}
            r = post(api, '/v1/feedback', dict(feedback_id=f'f-{i}', decision_id=d['decision_id'], source='owner', kind='pairwise_preference', actor_id='owner', consent_scope='core',
                learning_consent=True, preferred=option(**TERSE), rejected=served if served != option(**TERSE) else option(), evidence_group=f's-{i}'))
            assert r.status_code == 200, r.text
        from test_engine import wait_job
        jid = post(api, '/v1/consolidations', {'persona_id': 'ape', 'scope': 'core'}).json()['job_id']; job = wait_job(api, jid); assert job['eligible'], job
        assert post(api, '/v1/personas/ape/promotions', {'candidate_id': jid, 'expected_version': before['persona_version']}).status_code == 200
        on_dry = express(api, 'after-dry', 'dry', user=None); on_other = express(api, 'after-other', 'other', user=None)
        assert on_dry['controls'] == on_other['controls'] != before['controls'] and on_other['rendering'] is None
        assert on_other['controls']['verbosity'] < before['controls']['verbosity']

def test_sdk_rejects_a_rendering_outside_the_catalogue():
    from sdk.python import lite
    d = dict(protocol_version='upap/2', request_id='r', decision_id='d', persona_version='v', decoder_hash='h', control_schema='behaviour-controls/2', catalogue_hash=CATALOGUE_HASH,
        controls=dict(NEUTRAL, verbosity=3), habits=['recap_end'], preferences={}, mode='active', applies_to='next_model_request', policy={'eligible': True, 'mask_reason': None}, cache_ttl_ms=0)
    ok = {**d, 'rendering': dict(controls=dict(NEUTRAL, verbosity=4), style_profile='sha256:' + '1' * 64, model_id='m', notes=[])}
    assert 'Be thorough and comprehensive.' in lite.render(ok) and 'Include useful detail.' in lite.render(d)
    for bad in (dict(NEUTRAL, verbosity=2), dict(NEUTRAL, verbosity=0, explanation_depth=4), dict(NEUTRAL, verbosity=9), {'warmth': 2}):
        with pytest.raises(ValueError): lite.render({**ok, 'rendering': {**ok['rendering'], 'controls': bad}})

def cli(tmp_path, *args):
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
    return subprocess.run([sys.executable, '-m', 'sdk.cli.main', *args], cwd=tmp_path, env=env, text=True, capture_output=True)

def test_cli_calibrate_simulated_model_and_manage_profiles(tmp_path):
    dry = cli(tmp_path, 'calibrate', '--provider', 'simulated', '--model', 'sim-effusive', '--per-task', '1', '--run-dir', str(tmp_path / 'run'))
    assert dry.returncode == 0 and 'Dry run' in dry.stdout and not (tmp_path / 'run').exists()
    r = cli(tmp_path, 'calibrate', '--provider', 'simulated', '--model', 'sim-effusive', '--as', 'Acme/Effusive', '--per-task', '2', '--run-dir', str(tmp_path / 'run'), '--execute', '--install')
    assert r.returncode == 0, r.stderr
    assert 'cannot go below' in r.stdout and 'installed' in r.stdout
    listed = json.loads(cli(tmp_path, 'profile', 'list').stdout)
    assert [p['model_id'] for p in listed['installed']] == ['acme:effusive'] and listed['rejected'] == []
    shown = cli(tmp_path, 'profile', 'inspect', 'acme/effusive'); assert shown.returncode == 0 and 'warmth' in shown.stderr
    # A tampered file is refused at install; a second profile and a consensus reference rebase both.
    installed = tmp_path / '.openape/style-profiles/acme_effusive.json'; p = json.loads(installed.read_text())
    (tmp_path / 'tampered.json').write_text(json.dumps({**p, 'model_id': 'acme:other'}))
    bad = cli(tmp_path, 'profile', 'install', 'tampered.json'); assert bad.returncode != 0 and 'checksum' in bad.stderr
    assert cli(tmp_path, 'calibrate', '--provider', 'simulated', '--model', 'sim-stiff', '--per-task', '2', '--run-dir', str(tmp_path / 'run2'), '--execute').returncode == 0
    ref = cli(tmp_path, 'profile', 'reference', str(installed), str(tmp_path / 'run2/sim-stiff.json'), '--out', str(tmp_path / 'consensus'))
    assert ref.returncode == 0, ref.stderr
    rebased = json.loads((tmp_path / 'consensus/sim-stiff.json').read_text()); assert cal.validate(rebased)['reference_kind'] == 'consensus'
    assert json.loads((tmp_path / 'consensus/reference.json').read_text())['models'] == ['acme:effusive', 'sim-stiff']
    assert cli(tmp_path, 'profile', 'install', str(tmp_path / 'consensus/sim-stiff.json')).returncode == 0
    assert cli(tmp_path, 'profile', 'remove', 'acme/effusive').returncode == 0 and not installed.exists()
    assert [p['model_id'] for p in json.loads(cli(tmp_path, 'profile', 'list').stdout)['installed']] == ['sim-stiff']
