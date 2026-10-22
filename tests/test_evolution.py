"""Archetype creation, automatic evolution from consented feedback, and natural
maturation on a square-root curve. Synthetic labels and a fixed prior: engineering
evidence only, not measured user benefit."""
import json
import itertools
from datetime import datetime,timezone
import torch
from conftest import *
from engine.neural.policy import Decoder,CATALOGUE
from engine.neural.profiles import ARCHETYPES,fit_seed_latent,seed_profile,agreement,reference_contexts
from engine.learning import maturation

def make(api,id,**kw):
    r=post(api,'/v1/personas',{'persona_id':id,**kw});assert r.status_code==200,r.text;return r.json()

def solo(request_id,persona,session,**context):
    req=expression(request_id=request_id,persona=persona,user=None,session=session);req['identity'].pop('user_id');req['context'].update(context);return req

def end(api,persona,session,user=None,event=None):
    e=dict(event_id=event or f'end-{persona}-{session}',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id=persona,session_id=session,type='session.ended')
    if user:e['user_id']=user
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200

def audit(api,persona,action):
    return [json.loads(a['data']) for a in api.get(f'/v1/personas/{persona}/history').json()['audit'] if a['action']==action]

def diag(api,persona,user,rid,**context):
    req=expression(request_id=rid,persona=persona,user=user,session=rid) if user else solo(rid,persona,rid);req['context'].update(context);req['debug']=True
    return post(api,'/v1/express',req).json()['diagnostics']

def test_creation_requires_a_starting_persona(api):
    r=post(api,'/v1/personas',{'persona_id':'blank'});assert r.status_code==400 and 'archetype' in r.json()['error']['message']
    assert post(api,'/v1/personas',{'persona_id':'two','archetype':'mentor','seed_preferences':['warm']}).status_code==400
    assert post(api,'/v1/personas',{'persona_id':'bad','archetype':'wizard'}).status_code==422
    out=make(api,'m',archetype='mentor')
    assert out['initialization']=='archetype' and out['archetype']=='mentor' and out['evolution']=='automatic' and out['maturation_rate']=='normal' and out['agent_feedback']
    child=make(api,'child',parent_persona_id='m');assert child['archetype']=='mentor'
    info=api.get('/v1/personas/m').json();assert info['archetype']=='mentor' and info['growth']['core']['maturity']==0
    caps=api.get('/v1/capabilities').json();assert set(caps['archetypes'])==set(ARCHETYPES) and caps['automatic_promotion']=='persona_policy'

def test_archetypes_are_distinct_and_track_their_profiles():
    d=Decoder('models/decoder-v2/decoder.safetensors');contexts=reference_contexts();host={'provider_family':'other','adapter_id':'x'}
    choices={}
    for name,seeds in ARCHETYPES.items():
        z=fit_seed_latent(d,seeds);choices[name]=[int(d.logits(z,torch.zeros(32),c,host).argmax()) for c in contexts]
        if seeds:assert agreement(d,z,seed_profile(seeds),contexts)>agreement(d,torch.zeros(64),seed_profile(seeds),contexts),name
    for a,b in itertools.combinations(choices,2):assert choices[a]!=choices[b],(a,b)

def test_square_root_schedule():
    T=30;ms=[maturation.maturity(t,T) for t in range(0,61)]
    assert ms[0]==0 and ms[T]==1 and all(x==1 for x in ms[T:])
    gains=[b-a for a,b in zip(ms,ms[1:T+1])];assert all(x>y for x,y in zip(gains,gains[1:]))  # concave: big early, small late
    steps=[];last=0
    for t in range(1,100):
        m=maturation.due(t,T,last)
        if m is not None:steps.append((t,maturation.step_budget('relationship',m,last)));last=m
    times=[t for t,_ in steps];budgets=[b for _,b in steps]
    assert times[0]==1 and times[-1]==T and max(times)<=T
    gaps=[b-a for a,b in zip(times,times[1:])];assert gaps[-1]>gaps[0]  # changes become rarer
    assert budgets[0]>budgets[-2] and abs(sum(budgets)-maturation.BUDGET['relationship'])<1e-9  # total drift budget is bounded
    first_settled=lambda rate:next(t for t in range(1,1001) if maturation.maturity(t,maturation.horizons(rate)['relationship'])>=1)
    assert first_settled('fast')<first_settled('normal')<first_settled('slow')
    assert maturation.horizons({'relationship_horizon':7,'core_horizon':9})=={'rate':'custom','relationship':7,'core':9}

def test_relationship_matures_fast_then_settles_for_that_user_only(api):
    make(api,'host',archetype='concierge',maturation_rate='fast')
    before=diag(api,'host','alice','before');bob_before=diag(api,'host','bob','bob-before')
    for i in range(16):
        post(api,'/v1/express',expression(request_id=f'r{i}',persona='host',session=f's{i}'));end(api,'host',f's{i}','alice');api.app.state.drain()
    steps=[m for m in audit(api,'host','matured') if m['scope']=='relationship']
    assert [s['experience'] for s in steps]==list(range(1,11))  # every session early on, none after the horizon
    assert all(s['eligible'] for s in steps) and steps[-1]['maturity']==1
    drifts=[s['drift'] for s in steps];assert drifts[0]>drifts[-1]
    after=diag(api,'host','alice','after')
    assert after['verbosity']<before['verbosity'] and after['formality']<=before['formality'] and after['warmth']>=before['warmth']-0.05
    # Bob only shares the core's slower habituation; no relationship state is created for him.
    assert abs(diag(api,'host','bob','bob-after')['verbosity']-bob_before['verbosity'])<0.1
    assert {v['user_id'] for v in api.get('/v1/personas/host/history').json()['versions'] if v['scope']=='relationship'}=={'alice'}
    growth=api.get('/v1/personas/host?user_id=alice').json()['growth'];assert growth['relationship']['maturity']==1
    promoted=[a for a in audit(api,'host','promoted') if a['kind']=='maturation'];assert promoted and all(a['actor']=='openape:maturation' for a in promoted)

def test_core_habituates_to_its_work_within_budget(api):
    make(api,'rev',archetype='balanced',maturation_rate={'relationship_horizon':10,'core_horizon':12})
    base=diag(api,'rev',None,'base',task_type='code_review')
    for i in range(14):
        for j in range(3):post(api,'/v1/express',solo(f'c{i}-{j}','rev',f'cs{i}',task_type='code_review',tags=['review']))
        end(api,'rev',f'cs{i}');api.app.state.drain()
    steps=[m for m in audit(api,'rev','matured') if m['scope']=='core']
    assert len(steps)>=6 and steps[-1]['maturity']==1 and set(steps[0]['task_counts'])=={'code_review'}
    assert sum(s['drift'] for s in steps)<=maturation.BUDGET['core']+1e-3
    assert diag(api,'rev',None,'later',task_type='code_review')['directness']>=base['directness']

def test_shadow_sessions_and_manual_personas_do_not_mature(api):
    make(api,'quiet',archetype='mentor',maturation_rate='fast',evolution='manual');make(api,'trial',archetype='mentor',maturation_rate='fast')
    for i in range(4):
        post(api,'/v1/express',expression(request_id=f'q{i}',persona='quiet',session=f'q{i}'));end(api,'quiet',f'q{i}','alice')
        post(api,'/v1/express',expression(request_id=f't{i}',persona='trial',session=f't{i}',mode='shadow'));end(api,'trial',f't{i}','alice')
    api.app.state.drain()
    assert not audit(api,'quiet','matured') and not audit(api,'trial','matured')
    # Resuming re-anchors the curve at current experience: no catch-up jump.
    assert post(api,'/v1/personas/quiet/evolution',dict(evolution='automatic')).json()['evolution']=='automatic'
    post(api,'/v1/express',expression(request_id='q9',persona='quiet',session='q9'));end(api,'quiet','q9','alice');api.app.state.drain()
    step=[m for m in audit(api,'quiet','matured') if m['scope']=='relationship'][0]
    assert step['previous_maturity']>0 and step['maturity']-step['previous_maturity']<0.1

def preferences(api,persona,count,prefix,preferred=1,scope='core'):
    for i in range(count):
        d=post(api,'/v1/express',solo(f'{prefix}{i}',persona,f'{prefix}s{i}')).json()
        rejected=int(d['control_set_id'][-2:]);rejected=rejected if rejected!=preferred else 0
        r=post(api,'/v1/feedback',dict(feedback_id=f'{prefix}f{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='owner',consent_scope=scope,learning_consent=True,preferred_control=preferred,rejected_control=rejected,evidence_group=f'{prefix}s{i}'))
        assert r.status_code==200,r.text

def test_consented_feedback_evolves_persona_without_operator(api):
    base=make(api,'auto',archetype='balanced')['active_version']
    pinned=post(api,'/v1/express',solo('open','auto','open-session')).json()['persona_version'];assert pinned==base
    preferences(api,'auto',40,'a');api.app.state.drain()
    promoted=[a for a in audit(api,'auto','promoted') if a['kind']=='feedback']
    assert promoted and promoted[0]['actor']=='openape:auto-evolution' and promoted[0]['automatic']
    active=api.get('/v1/personas/auto').json()['active_version'];assert active!=base
    assert post(api,'/v1/express',solo('open-2','auto','open-session')).json()['persona_version']==base  # open session stays pinned
    assert post(api,'/v1/express',solo('new','auto','new-session')).json()['persona_version']==active
    jobs=[json.loads(a['data']) for a in api.get('/v1/personas/auto/history').json()['audit'] if a['action']=='candidate_evaluated']
    assert all(j['automatic'] for j in jobs) and len(jobs)<=5  # debounced, not one job per feedback
    # Revoking evidence that built the automatic version falls back to a clean ancestor.
    first=api.get('/v1/consolidations/'+promoted[0]['candidate']).json()['evidence_ids'][0]
    e=dict(event_id='revoke',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='auto',type='experience.corrected',feedback_id=first)
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200
    assert api.get('/v1/personas/auto').json()['active_version']==base

def test_manual_persona_keeps_operator_promotion(api):
    base=make(api,'ops',archetype='balanced',evolution='manual')['active_version']
    preferences(api,'ops',40,'o');api.app.state.drain()
    assert api.get('/v1/personas/ops').json()['active_version']==base and not audit(api,'ops','candidate_evaluated')

def test_maturation_never_undoes_feedback():
    d=Decoder('models/decoder-v2/decoder.safetensors')
    from engine.evaluation.policy import evaluate_maturation
    core=torch.zeros(64);rel=torch.zeros(32);ctx=reference_contexts()[0];host={'provider_family':'other','adapter_id':'x'}
    feedback=[dict(kind='pairwise_preference',preferred_control=14,rejected_control=8,context=c,host=host) for c in reference_contexts()]  # formal-neutral over supportive
    x=maturation.familiarize(d,core,rel,{},1.0,1.0)  # warmer/less formal: the opposite of the feedback
    assert not evaluate_maturation(d,core,rel,x,'relationship',1.0,feedback)['checks']['feedback_preserved']
    assert evaluate_maturation(d,core,rel,x,'relationship',1.0,[])['eligible']
