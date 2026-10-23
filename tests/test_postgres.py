"""PostgreSQL backend: SQL translation (always) and several replicas on one database
(with OPENAPE_TEST_DATABASE_URL, e.g. postgresql://openape@127.0.0.1:55432/openape)."""
import pytest
from conftest import *
from engine.storage.store import translate
from test_evolution import make

def test_translation_of_sqlite_idioms():
    assert translate('INSERT OR REPLACE INTO relationships VALUES(?,?,?,?)') == \
        'INSERT INTO relationships(tenant,persona,user_id,active) VALUES(?,?,?,?) ON CONFLICT (tenant,persona,user_id) DO UPDATE SET active=EXCLUDED.active'
    assert translate('INSERT OR IGNORE INTO experience VALUES(?,?,?,?,?)').endswith(') VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING')
    assert translate('INSERT INTO feedback VALUES(?,?,?,?,?,?,1)') == 'INSERT INTO feedback(tenant,id,persona,user_id,actor,data,valid) VALUES(?,?,?,?,?,?,1)'
    assert translate("SELECT 1 FROM d WHERE json_extract(d.data,'$.session.id')=? AND user_id IS ?") == \
        "SELECT 1 FROM d WHERE (d.data::jsonb #>> '{session,id}')=? AND user_id IS NOT DISTINCT FROM ?"
    assert translate('EXISTS (SELECT 1 FROM json_each(states.feedback) WHERE value=?)') == \
        'EXISTS (SELECT 1 FROM jsonb_array_elements_text(states.feedback::jsonb) AS je(value) WHERE value=?)'
    assert translate('INSERT INTO meta VALUES(\'a,b\',?)') == "INSERT INTO meta(key,value) VALUES('a,b',?)"  # commas in literals do not count

@pytest.mark.skipif(not PG_URL, reason='set OPENAPE_TEST_DATABASE_URL to a PostgreSQL database')
def test_replicas_share_state_and_serialize_promotions(tmp_path):
    one, two = (TestClient(create_app(tmp_path, credentials=CREDENTIALS), headers={'Authorization': 'Bearer ' + TOKEN}) for _ in range(2))
    with one as a, two as b:
        make(a, 'ape', archetype='mentor', evolution='manual')
        assert b.get('/v1/personas/ape').json()['active_version'] == a.get('/v1/personas/ape').json()['active_version']
        decisions = [post(b if i % 2 else a, '/v1/express', expression(request_id=f'r{i}', session=f's{i % 3}')).json() for i in range(12)]
        assert len({d['decision_id'] for d in decisions}) == 12 and all(d['engine_status'] == 'experimental_synthetic' for d in decisions)
        again = post(b, '/v1/express', expression(request_id='r0', session='s0')).json()
        assert again['decision_id'] == decisions[0]['decision_id']  # idempotent across replicas
        for i, d in enumerate(decisions):
            f = dict(feedback_id=f'f{i}', decision_id=d['decision_id'], source='owner', kind='pairwise_preference', actor_id='owner', consent_scope='relationship', learning_consent=True,
                preferred=option(**TERSE), rejected={'controls': d['controls'], 'habits': d['habits']} if d['controls'] != option(**TERSE)['controls'] else option(), evidence_group=f's{i % 3}')
            assert post(a if i % 2 else b, '/v1/feedback', f).status_code == 200
        job = post(a, '/v1/consolidations', dict(persona_id='ape', scope='relationship', user_id='alice')).json()['job_id']
        a.app.state.drain();report = b.get('/v1/consolidations/' + job).json()
        assert report['status'] == 'evaluated' and report['report']['evaluator']['isolation'] == 'process', report
        base = a.get('/v1/personas/ape').json()['active_version']
        if report['eligible']:
            results = [post(x, '/v1/personas/ape/promotions', dict(candidate_id=job, expected_version=base)).status_code for x in (a, b)]
            assert sorted(results) == [200, 409]  # compare-and-swap holds across replicas
            later = post(b, '/v1/express', expression(request_id='after', session='new')).json()
            assert later['relationship_version'] is not None  # the artifact written by one replica is read by the other

def test_stale_queued_job_does_not_block_its_kind(api):
    """A queued automatic job lost with its replica is abandoned once stale."""
    import json, time
    from datetime import datetime, timezone
    from test_evolution import audit
    make(api, 'ape', archetype='mentor', maturation_rate='fast')
    with api.app.state.store.tx() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', ('local', 'lost', 'ape', 'queued', json.dumps(dict(scope='core', user_id=None, auto=True, kind='maturation', queued_at=time.time() - 3600))))
    for i in range(6):
        post(api, '/v1/express', expression(request_id=f'q{i}', session=f'qs{i}'))
        e = dict(event_id=f'end{i}', occurred_at=datetime.now(timezone.utc).isoformat(), persona_id='ape', user_id='alice', session_id=f'qs{i}', type='session.ended')
        assert post(api, '/v1/observations', dict(adapter_id='custom', events=[e])).status_code == 200
    assert api.app.state.store.one("SELECT status FROM jobs WHERE id='lost'")['status'] == 'abandoned'  # (drain would wait on it otherwise)
    api.app.state.drain()
    assert [m for m in audit(api, 'ape', 'matured') if m['scope'] == 'core']
