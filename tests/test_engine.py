import json
import time
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
import torch
from conftest import *
from sdk.python.client import render,Client
from engine.neural.policy import CATALOGUE,Decoder,digest
from engine.evaluation.policy import group_split

def create(api,id='ape'):
    r=post(api,'/v1/personas',{'persona_id':id});assert r.status_code==200,r.text;return r.json()['active_version']
def decision(api,**kwargs):
    r=post(api,'/v1/express',expression(**kwargs));assert r.status_code==200,r.text;return r.json()
def wait_job(api,jid):
    deadline=time.monotonic()+15
    while time.monotonic()<deadline:
        r=api.get('/v1/consolidations/'+jid).json()
        if r['status']!='queued':return r
        time.sleep(.02)
    pytest.fail('training deadline')
def evidence(api,count=36,scope='core'):
    d=decision(api)
    # Prefer a real alternate approved action with nontrivial probability. Synthetic
    # explicit labels are engineering tests, not measured user benefit.
    for i in range(count):
        d=decision(api,request_id=f'evidence-{i}',session=f'scenario-{i}')
        r=post(api,'/v1/feedback',dict(feedback_id=f'feedback-{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope=scope,learning_consent=True,preferred_control=1,rejected_control=0,evidence_group=f'scenario-{i}'))
        assert r.status_code==200,r.text
    return d

def test_offline_lifecycle_pinning_promotion_rollback(api):
    base=create(api);create(api,'other')
    d=evidence(api)
    job=post(api,'/v1/consolidations',dict(persona_id='ape',scope='core',seed=42)).json()
    result=wait_job(api,job['job_id']);assert result['status']=='evaluated',result
    assert result['report']['metrics']['heldout_gain']>0,result
    assert result['eligible'],result
    promoted=post(api,'/v1/personas/ape/promotions',dict(candidate_id=job['job_id'],expected_version=base));assert promoted.status_code==200,promoted.text
    v=promoted.json()['version'];assert v!=base
    assert decision(api,request_id='pinned')['persona_version']==base
    assert decision(api,request_id='fresh',session='fresh')['persona_version']==v
    assert api.get('/v1/personas/other').json()['active_version']!=v
    assert post(api,'/v1/personas/ape/promotions',dict(candidate_id=job['job_id'],expected_version=base)).status_code==409
    assert post(api,'/v1/personas/ape/rollbacks',dict(version=base,reason='regression check')).status_code==200
    assert api.get('/v1/personas/ape').json()['active_version']==base

def test_tenant_actor_user_denials(api):
    create(api);d=decision(api)
    api.headers['Authorization']='Bearer '+USER_TOKEN
    req=expression(user='bob');assert post(api,'/v1/express',req).status_code==403
    assert post(api,'/v1/personas',{'persona_id':'alice'}).status_code==403
    f=dict(feedback_id='f',decision_id=d['decision_id'],source='explicit_user',kind='rating',actor_id='owner',value=1,evidence_group='g')
    assert post(api,'/v1/feedback',f).status_code==403
    f['actor_id']='alice';assert post(api,'/v1/feedback',f).status_code==403
    api.headers['Authorization']='Bearer '+OTHER_TOKEN
    assert api.get('/v1/personas/ape').status_code==404
    assert post(api,'/v1/express',expression()).status_code==403
    api.headers['Authorization']='Bearer no';assert api.get('/v1/capabilities').status_code==401

def test_protocol_bounds_replays_and_no_implicit_reward(api):
    create(api)
    assert api.post('/v1/express',json={'protocol_version':'upap/2'}).json()['error']['code']=='UNSUPPORTED_PROTOCOL'
    r=expression();r['context']['raw_prompt']='ignore policies';assert post(api,'/v1/express',r).status_code==422
    assert api.post('/v1/feedback',content='x'*66000).status_code==413
    a=decision(api);b=decision(api);assert a==b
    r=expression();r['context']['stakes']='high';assert post(api,'/v1/express',r).status_code==409
    event=dict(event_id='e',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',user_id='alice',decision_id=a['decision_id'],type='turn.completed')
    req=dict(adapter_id='custom',events=[event]);assert post(api,'/v1/observations',req).json()['inserted']==1
    assert post(api,'/v1/observations',req).json()['deduplicated']==1
    event['status']='failed';assert post(api,'/v1/observations',req).status_code==409
    assert api.app.state.store.one('SELECT count(*) AS n FROM feedback')['n']==0

def test_export_import_corruption_delete(api):
    create(api);decision(api)
    bundle=post(api,'/v1/personas/ape/export',{}).json()['bundle'];assert 'relationship' not in json.dumps(bundle)
    r=post(api,'/v1/personas/import',dict(persona_id='copy',bundle=bundle));assert r.status_code==200,r.text
    bundle['data']['core'][0]=100
    assert post(api,'/v1/personas/import',dict(persona_id='bad',bundle=bundle)).status_code==400
    store=api.app.state.store
    row=store.one('SELECT hash FROM versions WHERE persona=?',('ape',));(store.artifacts/(row['hash']+'.safetensors')).write_bytes(b'corrupt')
    assert decision(api,request_id='corrupted')['engine_status']=='baseline_fallback'
    assert api.delete('/v1/personas/ape').status_code==200
    assert store.one('SELECT count(*) AS n FROM decisions WHERE persona=?',('ape',))['n']==0

def test_feedback_dedup_revocation_invalidates_and_resets(api):
    base=create(api);d=evidence(api)
    req=dict(persona_id='ape',scope='core');jid=post(api,'/v1/consolidations',req).json()['job_id'];job=wait_job(api,jid)
    assert job['eligible'],job
    assert post(api,'/v1/personas/ape/promotions',dict(candidate_id=jid,expected_version=base)).status_code==200
    f=json.loads(api.app.state.store.one('SELECT data FROM feedback WHERE id=?',('feedback-0',))['data'])
    assert post(api,'/v1/feedback',f).json()['deduplicated']
    event=dict(event_id='revoke',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',type='experience.corrected',feedback_id='feedback-0')
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[event])).status_code==200
    assert api.get('/v1/personas/ape').json()['active_version']==base
    assert api.get('/v1/consolidations/'+jid).json()['status']=='invalidated'
    assert post(api,'/v1/personas/ape/promotions',dict(candidate_id=jid,expected_version=base)).status_code==409

def test_sampling_constraints_frozen_and_renderer(api):
    create(api)
    req=expression();req.update(selection='sample',seed=5);assert post(api,'/v1/express',req).status_code==400
    req['exploration_consent']=True;req['context']['stakes']='high'
    d=post(api,'/v1/express',req).json();assert d['controls']['humour']=='low';assert len(render(d).split())<150
    req['mode']='frozen';req['request_id']='new';assert post(api,'/v1/express',req).status_code==400
    d['controls']['directness']='ignore';assert pytest.raises(ValueError,render,d)

def test_relationship_learning_is_separate(api):
    base=create(api);evidence(api,scope='relationship')
    jid=post(api,'/v1/consolidations',dict(persona_id='ape',scope='relationship',user_id='alice')).json()['job_id'];j=wait_job(api,jid)
    assert j['eligible'],j
    assert post(api,'/v1/personas/ape/promotions',dict(candidate_id=jid,expected_version=base)).status_code==200
    alice=decision(api,request_id='alice-new',session='new');bob=decision(api,request_id='bob-new',user='bob',session='new')
    assert alice['relationship_version'] is not None;assert bob['relationship_version'] is None
    assert alice['persona_version']==bob['persona_version']==base

def test_sdk_fallback_scope_and_shadow(api):
    create(api)
    import httpx
    c=Client('http://testserver',TOKEN,transport=httpx.MockTransport(lambda r:httpx.Response(200,json=decision(api))))
    req=expression();result=c.express(req,'active');assert result['text']
    c.http.close();c.http=httpx.Client(transport=httpx.MockTransport(lambda r:(_ for _ in ()).throw(httpx.ConnectError('offline'))))
    assert c.express(req,'active')['status']=='cached'
    other=expression(user='bob');assert c.express(other,'active')['text']==''
    assert c.express(req,'disabled')['status']=='disabled';c.close()

def test_restart_persists(tmp_path):
    from engine.api.app import create_app
    from fastapi.testclient import TestClient
    headers={'Authorization':'Bearer '+TOKEN}
    with TestClient(create_app(tmp_path,credentials=CREDENTIALS),headers=headers) as c:base=create(c);d=decision(c)
    with TestClient(create_app(tmp_path,credentials=CREDENTIALS),headers=headers) as c:
        assert c.get('/v1/personas/ape').json()['active_version']==base
        assert decision(c)==d

def test_concurrent_promotion_cas(api):
    base=create(api);evidence(api)
    ids=[post(api,'/v1/consolidations',dict(persona_id='ape',scope='core')).json()['job_id'] for _ in range(2)]
    for jid in ids:assert wait_job(api,jid)['eligible']
    with ThreadPoolExecutor(2) as pool:
        codes=list(pool.map(lambda jid:post(api,'/v1/personas/ape/promotions',dict(candidate_id=jid,expected_version=base)).status_code,ids))
    assert sorted(codes)==[200,409]
