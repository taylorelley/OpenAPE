"""Why this style: per-layer attribution of served decisions, and the persona timeline."""
import torch
from conftest import *
from protocol.catalogue import TRAITS
from test_evolution import make
from test_cohort import relate

def test_explanation_names_layers_limits_and_habits(api):
    make(api, 'ape', archetype='mentor', individuality=0, evolution='manual')
    lean = torch.randn(32, generator=torch.Generator().manual_seed(5));relate(api, 'alice', 2.0 * lean / lean.norm(), pins={'humour': {'min': 0, 'max': 0}})
    req = expression(request_id='x1', session='xs');req['context'].update(stakes='high')
    d = post(api, '/v1/express', req).json()
    r = api.get(f"/v1/decisions/{d['decision_id']}/explanation");assert r.status_code == 200, r.text
    e = r.json()
    assert e['layers'] == ['temperament', 'character', 'relationship'] and set(e['traits']) == set(TRAITS)
    for t, x in e['traits'].items():
        assert x['level'] == d['controls'][t] and x['why'].startswith(t.replace('_', ' ').capitalize()) and x['shaped_by'] in e['layers']
        assert set(x['expected']) == set(e['layers'])
    assert {'kind': 'context', 'levels': [0, 1], 'reason': 'high_stakes_or_sensitive'} in e['traits']['humour']['limits']
    assert {'kind': 'user_pin', 'levels': [0, 0]} in e['traits']['humour']['limits']
    assert 1 <= len(e['summary']) <= 3 and all(h['state'] == 'served' for k, h in e['habits'].items() if k in d['habits'])
    assert set(d['habits']) <= set(e['habits'])
    alice = {'Authorization': 'Bearer ' + USER_TOKEN}
    assert api.get(f"/v1/decisions/{d['decision_id']}/explanation", headers=alice).status_code == 403  # alice did not request it
    assert api.get('/v1/decisions/nope/explanation').status_code == 404
    other = {'Authorization': 'Bearer ' + OTHER_TOKEN}
    assert api.get(f"/v1/decisions/{d['decision_id']}/explanation", headers=other).status_code == 404  # another tenant

def test_timeline_lists_versions_with_expected_levels(api):
    make(api, 'ape', archetype='critic', individuality=0, evolution='manual')
    relate(api, 'alice', torch.full((32,), 0.3))
    core_only = api.get('/v1/personas/ape/timeline').json()
    assert [v['scope'] for v in core_only['versions']] == ['core'] and core_only['versions'][0]['kind'] == 'created' and core_only['versions'][0]['active']
    t = api.get('/v1/personas/ape/timeline?user_id=alice').json()
    assert [v['scope'] for v in t['versions']] == ['core', 'relationship'] and all(v['active'] for v in t['versions'])
    assert all(0 <= v['traits'][k] <= 4 for v in t['versions'] for k in TRAITS) and t['events']['created'] == 1
    assert api.get('/v1/personas/ape/timeline?user_id=bob', headers={'Authorization': 'Bearer ' + USER_TOKEN}).status_code == 403
