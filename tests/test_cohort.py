"""Cohort prior: a new relationship starts from the shrunk mean of opted-in relationships."""
import json
import torch
from conftest import *
from test_evolution import make

def relate(api, user, x, **settings):
    """Give `user` a relationship version holding latent x, and the given settings."""
    store = api.app.state.store;h = store.put(x)
    with store.tx() as db:
        db.execute("INSERT OR REPLACE INTO versions(tenant,persona,id,hash,parent,scope,user_id,job,core_base) VALUES('local','ape',?,?,NULL,'relationship',?,NULL,NULL)", ('v-' + user, h, user))
        db.execute("INSERT OR REPLACE INTO relationships VALUES('local','ape',?,?)", (user, 'v-' + user))
        db.execute('INSERT OR REPLACE INTO user_settings VALUES(?,?,?,?,?)', ('local', 'ape', user, json.dumps({**dict(preferences={}, pins={}, vetoes=[], frozen=False, cohort_contribution=True), **settings}), 'now'))

def levels(api, rid, user='zed'):
    req = expression(request_id=rid, user=user, session=rid);req['debug'] = True
    return post(api, '/v1/express', req).json()['diagnostics']

def test_cohort_prior_needs_enough_opted_in_relationships(api):
    make(api, 'ape', archetype='balanced', individuality=0, evolution='manual')
    lean = torch.randn(32, generator=torch.Generator().manual_seed(3));lean = 2.0 * lean / lean.norm()
    alone = levels(api, 'a0')
    for k in range(4):relate(api, f'u{k}', lean)
    relate(api, 'quiet', lean, cohort_contribution=False);relate(api, 'ice', lean, frozen=True)  # not contributors
    assert levels(api, 'a1') == alone and not api.get('/v1/personas/ape?user_id=zed').json()['cohort_prior']['applies']
    relate(api, 'u4', lean)
    assert api.get('/v1/personas/ape?user_id=zed').json()['cohort_prior']['applies']
    assert levels(api, 'a2') != alone  # five contributors: zed starts nearer the cohort
    assert not api.get('/v1/personas/ape?user_id=u0').json()['cohort_prior']['applies']  # u0 has its own relationship
    relate(api, 'u4', lean, cohort_contribution=False)  # withdrawing consent removes the contribution
    assert levels(api, 'a3') == alone
