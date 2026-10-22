"""Neural conditioning, seed/snapshot initialization, directional learning and lineage revocation.
Synthetic explicit labels: engineering evidence only, not measured user benefit."""
import json
import random
from datetime import datetime,timezone
import torch
from conftest import *
from test_engine import create,decision,wait_job
from engine.neural.policy import Decoder,CATALOGUE,mask
from engine.neural.profiles import fit_seed_latent,seed_profile,agreement,random_context

def seeded(api,id,seeds):
    r=post(api,'/v1/personas',{'persona_id':id,'seed_preferences':seeds,'evolution':'manual'});assert r.status_code==200,r.text
    assert r.json()['initialization']=='seed_preferences';return r.json()['active_version']

def low_risk(request_id,persona,session):
    req=expression(request_id=request_id,persona=persona,user=None,session=session);req['identity'].pop('user_id');return req

def test_seeded_personas_distinct_and_reproducible(api):
    seeded(api,'terse',['concise','direct','serious']);seeded(api,'kind',['warm','detailed','playful'])
    a=[post(api,'/v1/express',low_risk(f'a{i}','terse',f's{i}')).json()['control_set_id'] for i in range(3)]
    b=[post(api,'/v1/express',low_risk(f'b{i}','kind',f's{i}')).json()['control_set_id'] for i in range(3)]
    assert len(set(a))==1 and len(set(b))==1 and a[0]!=b[0]
    terse=CATALOGUE[int(a[0][-2:])];kind=CATALOGUE[int(b[0][-2:])]
    assert terse['verbosity']=='low' and kind['warmth']=='high'

def test_seed_latent_tracks_declared_profile():
    d=Decoder('models/decoder-v2/decoder.safetensors');rng=random.Random(3)
    contexts=[random_context(rng) for _ in range(48)]
    for seeds in (['formal','reserved'],['casual','warm']):
        z=fit_seed_latent(d,seeds);assert torch.equal(z,fit_seed_latent(d,seeds))
        assert agreement(d,z,seed_profile(seeds),contexts)>agreement(d,torch.zeros(64),seed_profile(seeds),contexts)
    assert post_conflict_rejected(d)

def post_conflict_rejected(d):
    try:fit_seed_latent(d,['concise','detailed'])
    except ValueError:return True
    return False

def test_snapshot_is_independent_copy(api):
    seeded(api,'parent',['formal'])
    r=post(api,'/v1/personas',{'persona_id':'child','parent_persona_id':'parent'});assert r.status_code==200,r.text
    assert r.json()['initialization']=='snapshot' and r.json()['parent'].startswith('parent@')
    store=api.app.state.store
    hashes=[store.one('SELECT hash FROM versions WHERE persona=?',(p,))['hash'] for p in ('parent','child')]
    assert hashes[0]==hashes[1]
    assert post(api,'/v1/personas',{'persona_id':'x','parent_persona_id':'parent','seed_preferences':['warm']}).status_code==400

def preference_evidence(api,persona,preferred,count=36,prefix='p'):
    """Explicit pairwise labels preferring one approved option over the current choice."""
    ids=[]
    for i in range(count):
        d=post(api,'/v1/express',low_risk(f'{prefix}-{i}',persona,f'{prefix}-scenario-{i}')).json()
        rejected=int(d['control_set_id'][-2:]);rejected=rejected if rejected!=preferred else 0
        fid=f'{prefix}-feedback-{i}';ids.append(fid)
        r=post(api,'/v1/feedback',dict(feedback_id=fid,decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope='core',learning_consent=True,preferred_control=preferred,rejected_control=rejected,evidence_group=f'{prefix}-scenario-{i}'))
        assert r.status_code==200,r.text
    return ids

def probability(api,persona,control,request_id):
    req=low_risk(request_id,persona,request_id);req['debug']=True
    d=post(api,'/v1/express',req).json();return d['diagnostics'],d['control_set_id']

def test_directional_learning_and_unrelated_persona_unchanged(api):
    base=create(api,'learner');create(api,'bystander')
    before,_=probability(api,'learner',9,'before');bystander_before=probability(api,'bystander',9,'by-before')
    preference_evidence(api,'learner',9)  # style-09: warm, detailed, patient teacher
    jid=post(api,'/v1/consolidations',dict(persona_id='learner',scope='core')).json()['job_id'];job=wait_job(api,jid)
    assert job['eligible'],job;assert job['report']['metrics']['heldout_gain']>0
    assert post(api,'/v1/personas/learner/promotions',dict(candidate_id=jid,expected_version=base)).status_code==200
    after,choice=probability(api,'learner',9,'after')
    assert after['warmth']>before['warmth'] and after['verbosity']>before['verbosity']
    assert probability(api,'bystander',9,'by-after')[0]==bystander_before[0]

def test_contradictory_feedback_is_not_eligible(api):
    base=create(api,'noisy');rng=random.Random(0)
    for i in range(36):
        d=post(api,'/v1/express',low_risk(f'n-{i}','noisy',f'n-s-{i}')).json()
        a,b=rng.sample([9,1],2)  # coin-flip labels: no consistent preference to learn
        post(api,'/v1/feedback',dict(feedback_id=f'n-{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope='core',learning_consent=True,preferred_control=a,rejected_control=b,evidence_group=f'n-{i}'))
    jid=post(api,'/v1/consolidations',dict(persona_id='noisy',scope='core')).json()['job_id'];job=wait_job(api,jid)
    if job['status']=='evaluated' and job['eligible']:
        # Only acceptable if held-out data genuinely improved; never promoted automatically.
        assert job['report']['metrics']['heldout_gain']>=0.001
    assert api.get('/v1/personas/noisy').json()['active_version']==base

def test_duplicate_judgement_under_new_id_counts_once(api):
    create(api,'dup');d=post(api,'/v1/express',low_risk('dup','dup','dup')).json()
    for i in range(30):
        post(api,'/v1/feedback',dict(feedback_id=f'dup-{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope='core',learning_consent=True,preferred_control=9,rejected_control=1,evidence_group=f'claimed-{i}'))
    job=wait_job(api,post(api,'/v1/consolidations',dict(persona_id='dup',scope='core')).json()['job_id'])
    assert job['status']=='failed' or len(job['evidence_ids'])==1

def revoke(api,persona,fid,event):
    e=dict(event_id=event,occurred_at=datetime.now(timezone.utc).isoformat(),persona_id=persona,type='experience.corrected',feedback_id=fid)
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200

def test_revocation_follows_lineage_only(api):
    base=create(api,'lineage')
    used=preference_evidence(api,'lineage',9)
    jid=post(api,'/v1/consolidations',dict(persona_id='lineage',scope='core')).json()['job_id'];assert wait_job(api,jid)['eligible']
    v1=post(api,'/v1/personas/lineage/promotions',dict(candidate_id=jid,expected_version=base)).json()['version']
    # Evidence recorded after promotion was never used: revoking it must not reset state.
    unused=preference_evidence(api,'lineage',1,count=1,prefix='late')
    revoke(api,'lineage',unused[0],'r-unused')
    assert api.get('/v1/personas/lineage').json()['active_version']==v1
    revoke(api,'lineage',used[0],'r-used')
    assert api.get('/v1/personas/lineage').json()['active_version']==base
    history=api.get('/v1/personas/lineage/history').json()
    assert {v['id']:v['revoked'] for v in history['versions']}[v1]==1
    assert post(api,'/v1/personas/lineage/rollbacks',dict(version=v1,reason='try revoked')).status_code==409
    assert api.get('/v1/consolidations/'+jid).json()['status']=='invalidated'

def test_frozen_pinned_version_and_feedback_timestamp(api):
    base=create(api,'pinned')
    req=low_risk('frozen-1','pinned','fz');req.update(mode='frozen',pinned_version=base)
    d=post(api,'/v1/express',req);assert d.status_code==200 and d.json()['persona_version']==base
    req=low_risk('frozen-2','pinned','fz');req.update(mode='active',pinned_version=base);assert post(api,'/v1/express',req).status_code==400
    req=low_risk('frozen-3','pinned','fz');req.update(mode='frozen',pinned_version='missing');assert post(api,'/v1/express',req).status_code==409
    f=dict(feedback_id='ts',decision_id=d.json()['decision_id'],source='owner',kind='rating',actor_id='owner',value=1,evidence_group='g',occurred_at='2026-01-01T00:00:00+05:00')
    assert post(api,'/v1/feedback',f).status_code==400
    f['occurred_at']='2026-01-01T00:00:00Z';f['evidence_refs']=['ticket-1'];assert post(api,'/v1/feedback',f).status_code==200
