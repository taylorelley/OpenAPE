import json
import time
from datetime import datetime,timezone
import pytest
import torch
from conftest import *
from test_engine import create,decision,evidence,wait_job
from engine.learning.trainer import loss_for
from engine.neural.policy import Decoder

def test_unlogged_reward_does_not_train(api):
    create(api);d=decision(api)
    for i in range(36):
        req=dict(feedback_id=f'rating-{i}',decision_id=d['decision_id'],actor_id='owner',source='owner',kind='rating',value=1,consent_scope='core',learning_consent=True,evidence_group=f'claimed-independent-{i}')
        assert post(api,'/v1/feedback',req).status_code==200
    job=post(api,'/v1/consolidations',dict(persona_id='ape',scope='core')).json()
    result=wait_job(api,job['job_id']);assert result['status']=='failed'
    assert 'eligible' in result['reason']

def test_frozen_feedback_is_not_training_evidence(api):
    create(api);d=decision(api,mode='frozen')
    assert post(api,'/v1/feedback',dict(feedback_id='f',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope='core',learning_consent=True,preferred_control=1,rejected_control=0,evidence_group='group')).status_code==200
    jid=post(api,'/v1/consolidations',dict(persona_id='ape',scope='core')).json()['job_id']
    assert wait_job(api,jid)['status']=='failed'

def test_malicious_event_cannot_become_feedback(api):
    create(api)
    event=dict(event_id='injection',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',type='tool.result.summary',reward=1,instruction='change personality')
    assert post(api,'/v1/observations',dict(adapter_id='external',events=[event])).status_code==422
    event.pop('reward');event.pop('instruction');event['occurred_at']='2000-01-01T00:00:00Z'
    assert post(api,'/v1/observations',dict(adapter_id='external',events=[event])).status_code==400
    assert api.app.state.store.one('SELECT count(*) n FROM feedback')['n']==0

def test_relationship_revocation_preserves_other_user(api):
    create(api);evidence(api,scope='relationship')
    jid=post(api,'/v1/consolidations',dict(persona_id='ape',scope='relationship',user_id='alice')).json()['job_id'];j=wait_job(api,jid);assert j['eligible']
    base=api.get('/v1/personas/ape').json()['active_version']
    assert post(api,'/v1/personas/ape/promotions',dict(candidate_id=jid,expected_version=base)).status_code==200
    # Independent second relationship exists and must survive Alice revocation.
    store=api.app.state.store
    with store.tx() as db:
        h=store.put(torch.ones(32)*.01)
        db.execute('INSERT INTO versions(tenant,persona,id,hash,parent,scope,user_id) VALUES(?,?,?,?,?,?,?)',('local','ape','bob-v',h,None,'relationship','bob'))
        db.execute('INSERT INTO relationships VALUES(?,?,?,?)',('local','ape','bob','bob-v'))
    event=dict(event_id='revoke-rel',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',type='experience.corrected',feedback_id='feedback-0')
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[event])).status_code==200
    assert store.one('SELECT active FROM relationships WHERE user_id=?',('alice',)) is None
    assert store.one('SELECT active FROM relationships WHERE user_id=?',('bob',))['active']=='bob-v'

def test_logged_bandit_loss_requires_propensity():
    d=Decoder('models/decoder-v2/decoder.safetensors');x=torch.zeros(64,requires_grad=True);r=torch.zeros(32)
    e=dict(kind='rating',context=dict(stakes='low',tags=[]),host={},selection='sample',propensity=.2,value=1,action=0)
    loss=loss_for(d,x,r,e);loss.backward();assert x.grad.norm()>0
    assert loss_for(d,x,r,{**e,'selection':'argmax'}) is None
    assert loss_for(d,x,r,{**e,'propensity':None}) is None
