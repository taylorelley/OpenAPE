"""User-controlled relationship settings: preferences, pins, habit vetoes, freeze."""
import json
from conftest import *
from fastapi.testclient import TestClient
from engine.api.app import create_app
from sdk.python.client import render
from test_evolution import make, audit

SETTINGS_TOKEN = 'alice-settings-token-00000000000000'
def app_with_settings(tmp_path):
    creds = CREDENTIALS + [dict(token=SETTINGS_TOKEN, tenant='local', actor='alice', scopes=['persona:express', 'settings:write'], personas=['ape'], users=['alice'])]
    return create_app(tmp_path, credentials=creds)

def put(api, body, user='alice', token=SETTINGS_TOKEN):
    return api.put(f'/v1/personas/ape/users/{user}/settings', json={'protocol_version': 'upap/2', **body}, headers={'Authorization': 'Bearer ' + token})

def express(api, rid, session=None, **context):
    req = expression(request_id=rid, session=session or rid);req['context'].update(context)
    r = post(api, '/v1/express', req);assert r.status_code == 200, r.text;return r.json()

def test_preferences_pins_and_vetoes_apply_next_turn(tmp_path):
    with TestClient(app_with_settings(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='collaborator', individuality=0, evolution='manual')
        before = express(api, 'b0')
        assert before['controls']['humour'] >= 2 and 'light_aside' in before['habits'] and before['preferences'] == {}
        body = dict(preferences={'spelling': 'british', 'format': 'code_first'}, pins={'humour': {'min': 0, 'max': 0}}, vetoes=['light_aside', 'next_step'])
        r = put(api, body);assert r.status_code == 200, r.text
        after = express(api, 'b1')
        assert after['controls']['humour'] == 0 and not {'light_aside', 'next_step'} & set(after['habits'])
        assert after['preferences'] == {'spelling': 'british', 'format': 'code_first'} and 'user_pins' in after['policy']['mask_reason']
        text = render(after);assert 'Use British English spelling.' in text and text.index('Avoid humour.') < text.index('When code answers the question')
        got = api.get('/v1/personas/ape/users/alice/settings').json();assert got['pins'] == {'humour': {'min': 0, 'max': 0}} and got['vetoes'] == ['light_aside', 'next_step']
        assert audit(api, 'ape', 'user_settings_changed')[0]['pins'] == ['humour']

def test_context_masks_beat_pins_and_bad_settings_are_refused(tmp_path):
    with TestClient(app_with_settings(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='balanced', individuality=0, evolution='manual')
        assert put(api, dict(pins={'humour': {'min': 3, 'max': 4}})).status_code == 200
        assert express(api, 'p0')['controls']['humour'] >= 3
        risky = express(api, 'p1', stakes='high')  # safety mask wins over the user's pin
        assert risky['controls']['humour'] <= 1 and 'pin_overridden_by_context' in risky['policy']['mask_reason']
        assert put(api, dict(pins={'verbosity': {'min': 0, 'max': 0}, 'explanation_depth': {'min': 4, 'max': 4}})).status_code == 400  # no approved style fits
        assert put(api, dict(pins={'warmth': {'min': 3, 'max': 1}})).status_code == 422
        assert put(api, dict(preferences={'spelling': 'klingon'})).status_code == 422
        assert put(api, dict(vetoes=['light_aside', 'light_aside'])).status_code == 400
        assert put(api, dict(note='be ruder')).status_code == 422  # no free text
        assert put(api, {}, user='bob').status_code == 403  # alice cannot change bob's settings
        assert put(api, {}, token=TOKEN).status_code == 403  # owner credential lacks settings:write

def test_freeze_stops_relationship_evolution_only(tmp_path):
    with TestClient(app_with_settings(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='mentor', maturation_rate='fast')
        assert put(api, dict(frozen=True)).status_code == 200
        d = express(api, 'f0')
        f = dict(feedback_id='f', decision_id=d['decision_id'], source='owner', kind='pairwise_preference', actor_id='owner', consent_scope='relationship', learning_consent=True,
            preferred=option(**TERSE), rejected={'controls': d['controls'], 'habits': d['habits']}, evidence_group='g')
        r = post(api, '/v1/feedback', f).json();assert not r['session_adapted']  # no session mood either
        assert post(api, '/v1/consolidations', dict(persona_id='ape', scope='relationship', user_id='alice')).json()['error']['code'] == 'RELATIONSHIP_FROZEN'
        from datetime import datetime, timezone
        for i in range(6):
            express(api, f'fs{i}')
            e = dict(event_id=f'end{i}', occurred_at=datetime.now(timezone.utc).isoformat(), persona_id='ape', user_id='alice', session_id=f'fs{i}', type='session.ended')
            assert post(api, '/v1/observations', dict(adapter_id='custom', events=[e])).status_code == 200
        api.app.state.drain()
        matured = audit(api, 'ape', 'matured')
        assert matured and all(m['scope'] == 'core' for m in matured)  # the core still matures; the relationship does not
        assert api.app.state.store.one("SELECT COUNT(*) n FROM relationships WHERE persona='ape'")['n'] == 0
        assert put(api, dict(frozen=False)).status_code == 200
        assert api.delete('/v1/personas/ape').json()['counts']['user_settings'] == 1

def test_opt_in_exploration_and_blind_comparisons(tmp_path):
    with TestClient(app_with_settings(tmp_path), headers={'Authorization': 'Bearer ' + TOKEN}) as api:
        make(api, 'ape', archetype='balanced', individuality=0, evolution='manual')
        assert not any(express(api, f'n{i}')['exploration'] for i in range(20))  # off unless the user opts in
        assert put(api, dict(exploration=True)).status_code == 200
        served = [express(api, f'e{i}') for i in range(60)]
        explored = [d for d in served if d['exploration']];assert 1 <= len(explored) <= 25
        assert not any(express(api, f'h{i}', stakes='high')['exploration'] for i in range(30))  # never on high-stakes turns
        logged = [json.loads(r['data']) for r in api.app.state.store.all("SELECT data FROM decisions WHERE json_extract(data,'$.response.request_id') LIKE 'e%'")]
        assert all(d['selection'] == 'sample' and 0 < d['propensity'] <= 1 for d in logged)
        d = explored[0];r = post(api, '/v1/comparisons', dict(decision_id=d['decision_id']));assert r.status_code == 200, r.text
        options = r.json()['options'];mine = {'controls': d['controls'], 'habits': d['habits']}
        assert mine in options and options[0]['controls'] != options[1]['controls']
        other = options[1 - options.index(mine)]
        f = dict(feedback_id='cmp', decision_id=d['decision_id'], source='explicit_user', kind='pairwise_preference', actor_id='owner', consent_scope='relationship', learning_consent=True,
            preferred=other, rejected=mine, evidence_group='e')
        assert post(api, '/v1/feedback', f).status_code == 200
        alice = {'Authorization': 'Bearer ' + USER_TOKEN}
        assert api.post('/v1/comparisons', json={'protocol_version': 'upap/2', 'decision_id': d['decision_id']}, headers=alice).status_code == 403  # not alice's decision
        assert api.get('/v1/whoami', headers=alice).json()['actor'] == 'alice' and 'token' not in api.get('/v1/whoami').json()
