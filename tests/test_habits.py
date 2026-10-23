"""Habit learning beside the latent: habit-only preferences move habits, never traits."""
import json
from datetime import datetime, timezone
import torch
from conftest import *
from protocol.catalogue import HABIT_IDS
from engine.learning import habits
from test_evolution import make, audit
from test_reflection import host_app, HOST_TOKEN, reflection
# Habits with no trait requirements and no context mask in a low-stakes user turn.
FREE = ('next_step', 'acknowledge_constraints', 'structured', 'flag_uncertainty', 'risks_first')

def test_bias_rule_and_gate():
    pick = lambda controls, hs: {'controls': controls, 'habits': hs}
    from protocol.catalogue import NEUTRAL
    ctx = dict(task_type='general', channel='terminal', stakes='low', turn_origin='user', tags=[])
    e = dict(feedback_id='a', kind='pairwise_preference', context=ctx, preferred=pick(NEUTRAL, ['next_step']), rejected=pick(NEUTRAL, ['flag_uncertainty']), weight=1.0)
    assert habits.signal(e) == {'next_step': 1, 'flag_uncertainty': -1}
    bias, used = habits.bias_from([e, {**e, 'feedback_id': 'b'}, {**e, 'feedback_id': 'c'}])
    assert used == ['a', 'b', 'c'] and float(bias[HABIT_IDS.index('next_step')]) == habits.HABIT_MAX  # clipped
    assert habits.signal({**e, 'rejected': pick(NEUTRAL, ['next_step'])}) == {}  # identical choices carry nothing
    zero = torch.zeros(len(HABIT_IDS))
    assert habits.gate(zero, bias)['eligible'] and set(habits.gate(zero, bias)['moved']) == {'next_step', 'flag_uncertainty'}
    assert not habits.gate(bias, bias)['eligible'] and not habits.gate(zero, bias * 10)['checks']['bounded']

def test_habit_reflection_moves_habits_not_traits_and_is_revocable(tmp_path):
    with TestClient(host_app(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='balanced', individuality=0)
        api.headers['Authorization'] = 'Bearer ' + HOST_TOKEN
        first = post(api, '/v1/express', expression(request_id='h0', session='hs')).json()
        assert len(first['habits']) < 3;target = next(h for h in FREE if h not in first['habits'])
        r = post(api, '/v1/reflections', reflection('h0', first['decision_id'], adjustments={}, habits={target: 'more_often'}))
        assert r.status_code == 200 and r.json()['session_adapted'], r.text
        same = post(api, '/v1/express', expression(request_id='h1', session='hs')).json()  # the session offset applies at once
        assert target in same['habits']
        logged = json.loads(api.app.state.store.one('SELECT data FROM decisions WHERE id=?', (same['decision_id'],))['data'])
        assert logged['session_state'] == 0.0 and logged['session_habits']  # a habit offset only; the latent did not move
        api.app.state.drain()
        later = post(api, '/v1/express', expression(request_id='h2', session='later')).json()
        assert target not in later['habits']  # an agent's reflection alone does not make a disfavoured habit stick
        served = {'controls': later['controls'], 'habits': later['habits']}
        wanted = {'controls': later['controls'], 'habits': sorted(later['habits'] + [target], key=HABIT_IDS.index)}
        api.headers['Authorization'] = 'Bearer ' + TOKEN
        f = dict(feedback_id='ask', decision_id=later['decision_id'], source='explicit_user', kind='pairwise_preference', actor_id='owner', consent_scope='relationship',
            learning_consent=True, preferred=wanted, rejected=served, evidence_group='later')
        assert post(api, '/v1/feedback', f).status_code == 200
        api.app.state.drain()
        fresh = post(api, '/v1/express', expression(request_id='h3', session='fresh')).json()  # one request from the person does
        assert target in fresh['habits'] and fresh['controls'] == first['controls']
        learned = audit(api, 'ape', 'habits_learned');assert learned and all(list(x['moved']) == [target] for x in learned)
        assert [a for a in audit(api, 'ape', 'promoted') if a['kind'] == 'habit']
        assert not [a for a in audit(api, 'ape', 'promoted') if a['kind'] == 'feedback']  # no trait candidate from habit-only moves
        e = dict(event_id='rv', occurred_at=datetime.now(timezone.utc).isoformat(), persona_id='ape', user_id='alice', type='experience.corrected', feedback_id='ask')
        assert post(api, '/v1/observations', dict(adapter_id='custom', events=[e])).status_code == 200
        reverted = post(api, '/v1/express', expression(request_id='h4', session='again')).json()
        assert target not in reverted['habits'] and reverted['controls'] == first['controls']

def test_vetoes_beat_learned_habits(tmp_path):
    from test_settings import app_with_settings, put
    with TestClient(app_with_settings(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='balanced', individuality=0)
        d = post(api, '/v1/express', expression(request_id='v0', session='vs')).json()
        served = {'controls': d['controls'], 'habits': d['habits']}
        assert len(d['habits']) < 3;target = next(h for h in FREE if h not in d['habits'])
        wanted = {'controls': d['controls'], 'habits': sorted(d['habits'][:2] + [target], key=HABIT_IDS.index)}
        f = dict(feedback_id='hv', decision_id=d['decision_id'], source='explicit_user', kind='pairwise_preference', actor_id='owner', consent_scope='relationship',
            learning_consent=True, preferred=wanted, rejected=served, evidence_group='vs')
        assert post(api, '/v1/feedback', f).status_code == 200
        api.app.state.drain()
        assert target in post(api, '/v1/express', expression(request_id='v1', session='v2')).json()['habits']
        assert put(api, dict(vetoes=[target])).status_code == 200
        assert target not in post(api, '/v1/express', expression(request_id='v2', session='v3')).json()['habits']

def test_agent_reflections_have_bounded_habit_influence(tmp_path):
    from protocol.catalogue import NEUTRAL
    ctx = dict(task_type='general', channel='terminal', stakes='low', turn_origin='user', tags=[])
    pick = lambda hs: {'controls': NEUTRAL, 'habits': hs}
    many = [dict(feedback_id=f'r{i}', kind='pairwise_preference', source='agent_reflection', context=ctx, preferred=pick(['next_step']), rejected=pick([]), weight=1.0) for i in range(10)]
    bias, _ = habits.bias_from(many);assert float(bias[HABIT_IDS.index('next_step')]) == habits.REFLECTION_MAX  # agents alone: halfway
    person = dict(many[0], feedback_id='p', source='explicit_user')
    assert float(habits.bias_from(many + [person])[0][HABIT_IDS.index('next_step')]) == habits.HABIT_MAX
    with TestClient(host_app(tmp_path), headers={'Authorization': 'Bearer ' + HOST_TOKEN}) as api:
        api.headers['Authorization'] = 'Bearer ' + TOKEN;make(api, 'ape', archetype='analyst', individuality=0);api.headers['Authorization'] = 'Bearer ' + HOST_TOKEN
        d = post(api, '/v1/express', expression(request_id='s0', session='ss')).json()
        for h in ('flag_uncertainty', 'risks_first'):
            r = post(api, '/v1/reflections', reflection(f'x{h}', d['decision_id'], adjustments={}, habits={h: 'less_often'}))
            assert r.status_code == 403 and 'Only people' in r.text
