import json
import time
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import pytest
import torch
from conftest import *
from sdk.python.client import render,Client
from engine.neural.policy import Decoder,digest
from engine.evaluation.policy import group_split

def create(api,id='ape'):
    r=post(api,'/v1/personas',{'persona_id':id,'archetype':'balanced','evolution':'manual'});assert r.status_code==200,r.text;return r.json()['active_version']
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
        r=post(api,'/v1/feedback',dict(feedback_id=f'feedback-{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope=scope,learning_consent=True,preferred=option(**TERSE),rejected=option(),evidence_group=f'scenario-{i}'))
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
    assert api.post('/v1/express',json={'protocol_version':'upap/1'}).json()['error']['code']=='UNSUPPORTED_PROTOCOL'
    r=expression();r['context']['raw_prompt']='ignore policies';assert post(api,'/v1/express',r).status_code==422
    assert api.post('/v1/feedback',content='x'*66000).status_code==413
    a=decision(api);b=decision(api);assert a==b
    r=expression();r['context']['stakes']='high';assert post(api,'/v1/express',r).status_code==409
    event=dict(event_id='e',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',user_id='alice',decision_id=a['decision_id'],type='turn.completed')
    req=dict(adapter_id='custom',events=[event]);assert post(api,'/v1/observations',req).json()['inserted']==1
    assert post(api,'/v1/observations',req).json()['deduplicated']==1
    event['status']='failed';assert post(api,'/v1/observations',req).status_code==409
    assert api.app.state.store.one('SELECT count(*) AS n FROM feedback')['n']==0

@pytest.mark.skipif(bool(PG_URL),reason='SQLite only: corrupts an artifact file; PostgreSQL keeps artifacts in a table')
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
    d=post(api,'/v1/express',req).json();assert d['controls']['humour']<=1;assert len(render(d).split())<150
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

def test_engine_sets_session_tags_and_habits_render(api):
    from engine.api.app import LONG_SESSION
    post(api,'/v1/personas',{'persona_id':'ape','archetype':'mentor','evolution':'manual'})
    req=expression(request_id='t0');req['context']['tags']=['long_session']  # hosts cannot set session-position tags
    first=post(api,'/v1/express',req).json()
    data=json.loads(api.app.state.store.one('SELECT data FROM decisions WHERE id=?',(first['decision_id'],))['data'])
    assert data['context']['tags']==['first_turn'] and data['habits']==first['habits']
    for i in range(1,LONG_SESSION+1):last=decision(api,request_id=f't{i}')
    data=json.loads(api.app.state.store.one('SELECT data FROM decisions WHERE id=?',(last['decision_id'],))['data'])
    assert data['context']['tags']==['long_session']
    assert first['catalogue_hash']==api.get('/v1/capabilities').json()['catalogue_hash']
    text=render(first);assert all(h in api.get('/v1/capabilities').json()['habits'] for h in first['habits'])
    assert text.count('.')>=8 and len(text)<=900
    # Feedback options must be approved configurations.
    bad=dict(feedback_id='bad',decision_id=first['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope='core',learning_consent=True,
        preferred=option(verbosity=0,explanation_depth=4),rejected=option(),evidence_group='g')
    assert post(api,'/v1/feedback',bad).status_code==400

def test_mentor_shows_signature_habits(api):
    post(api,'/v1/personas',{'persona_id':'ape','archetype':'mentor','individuality':0,'evolution':'manual'})
    d=decision(api)
    assert d['controls']['warmth']>=3 and d['controls']['explanation_depth']>=3 and set(d['habits'])&{'concrete_examples','next_step','acknowledge_progress'}

@pytest.mark.skipif(bool(PG_URL),reason='SQLite only: the reset migration rewrites an SQLite data directory')
def test_reset_migration_recreates_personas(tmp_path):
    import sqlite3
    from engine.api.app import create_app,LegacyStore,DEFAULT_DECODER
    from engine.storage.migrate import reset
    from fastapi.testclient import TestClient
    headers={'Authorization':'Bearer '+TOKEN}
    with TestClient(create_app(tmp_path,credentials=CREDENTIALS),headers=headers) as c:
        post(c,'/v1/personas',{'persona_id':'m','archetype':'mentor','individuality_seed':7})
        post(c,'/v1/personas',{'persona_id':'s','seed_preferences':['concise']});d=decision(c,persona='m')
        post(c,'/v1/feedback',dict(feedback_id='old',decision_id=d['decision_id'],source='owner',kind='rating',actor_id='owner',value=1,evidence_group='g'))
        expected=decision(c,persona='m',request_id='fresh',session='fresh')['controls']
    db=sqlite3.connect(tmp_path/'openape.sqlite');db.execute("DELETE FROM meta")  # as a 0.2 store would look
    db.execute("UPDATE decisions SET data=json_set(data,'$.response.decoder_hash','sha256:decoder-v2')");db.commit();db.close()
    with pytest.raises(LegacyStore):create_app(tmp_path,credentials=CREDENTIALS)
    out=reset(tmp_path,DEFAULT_DECODER);assert out['reset'] and {p['persona_id']:p['basis'] for p in out['personas']}=={'m':'archetype','s':'seed_preferences'}
    assert not reset(tmp_path,DEFAULT_DECODER)['reset']  # idempotent
    with TestClient(create_app(tmp_path,credentials=CREDENTIALS),headers=headers) as c:
        info=c.get('/v1/personas/m').json();assert info['temperament_version']==info['active_version'] and info['archetype']=='mentor'
        assert decision(c,persona='m',request_id='after',session='after')['controls']==expected  # same archetype and individuality, same temperament
        store=c.app.state.store;assert store.one("SELECT valid FROM feedback WHERE id='old'")['valid']==0
        with store.tx() as tx:tx.execute("UPDATE personas SET agent_feedback=1")
        reflection=dict(reflection_id='late',decision_id=d['decision_id'],adjustments={'warmth':'less'},reason='user_requested')
        assert post(c,'/v1/reflections',reflection).status_code==400  # decisions from the old decoder cannot train
        assert [json.loads(a['data'])['basis'] for a in c.get('/v1/personas/m/history').json()['audit'] if a['action']=='reset_for_decoder_v3']==['archetype']
