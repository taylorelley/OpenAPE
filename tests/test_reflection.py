"""Agent reflections: the agent's persona_feedback tool. Bounded trait moves only."""
import json
from datetime import datetime,timezone
from conftest import *
import random
from engine.neural.policy import ACTIONS,APPROVED_LEVELS,TRAITS,INDEX,NEUTRAL_ACTION,mask
from engine.learning.reflection import adjusted_choice
PATIENT=dict(warmth=3,verbosity=3,formality=1,explanation_depth=3,assertiveness=1)
from test_evolution import make,solo,audit

HOST_TOKEN='host-agent-token-000000000000000000'
def host_app(tmp_path,scopes=('persona:express','observations:write','reflection:write')):
    return create_app(tmp_path,credentials=CREDENTIALS+[dict(token=HOST_TOKEN,tenant='local',actor='agent-host',scopes=list(scopes),personas=['*'],users=['*'])])

def reflection(rid,decision,**kw):
    return dict(reflection_id=rid,decision_id=decision,adjustments=kw.pop('adjustments',{'verbosity':'less'}),reason=kw.pop('reason','user_requested'),**kw)

def test_adjustment_maps_to_nearest_approved_configuration():
    ctx=dict(task_type='general',channel='terminal',stakes='low',turn_origin='user',tags=[])
    for served in random.Random(0).sample(range(ACTIONS),150):
        for k,trait in enumerate(TRAITS):
            for way,sign in (('more',1),('less',-1)):
                moved=adjusted_choice((served,()),{trait:way},ctx)
                if moved is None:continue
                row=moved[0];delta=APPROVED_LEVELS[row]-APPROVED_LEVELS[served]
                assert row!=served and int(delta[k])*sign>=1 and mask(ctx)[row]
                assert int(delta.abs().sum())-abs(int(delta[k]))<=2  # other traits barely move
                assert moved==adjusted_choice((served,()),{trait:way},ctx)
    neutral=(NEUTRAL_ACTION,());urgent=dict(ctx,tags=['urgent'])
    assert adjusted_choice(neutral,{'verbosity':'more'},urgent) is None  # urgent turns cap verbosity
    brief=INDEX[(2,2,0,0,2,2,2)];assert adjusted_choice((brief,()),{'verbosity':'less'},ctx) is None  # already as brief as it gets

def test_habit_moves():
    ctx=dict(task_type='general',channel='terminal',stakes='low',turn_origin='user',tags=[]);neutral=(NEUTRAL_ACTION,())
    assert adjusted_choice(neutral,{},ctx,{'next_step':'more_often'})==(NEUTRAL_ACTION,('next_step',))
    assert adjusted_choice((NEUTRAL_ACTION,('next_step','flag_uncertainty')),{},ctx,{'next_step':'less_often'})==(NEUTRAL_ACTION,('flag_uncertainty',))
    assert adjusted_choice(neutral,{},ctx,{'light_aside':'more_often'}) is None  # needs some humour
    wry=INDEX[(2,2,2,1,2,2,2)];assert adjusted_choice((wry,()),{'humour':'more'},ctx,{'light_aside':'more_often'})==(INDEX[(2,2,2,2,2,2,2)],('light_aside',))
    assert adjusted_choice(neutral,{},dict(ctx,tags=['urgent']),{'clarify_once':'more_often'}) is None
    assert adjusted_choice(neutral,{},ctx,{'next_step':'less_often'}) is None  # nothing changes

def test_agent_reflection_guardrails(tmp_path):
    with TestClient(host_app(tmp_path),headers={'Authorization':'Bearer '+TOKEN}) as api:
        make(api,'ape',archetype='mentor');make(api,'mute',archetype='mentor',agent_feedback=False)
        api.headers['Authorization']='Bearer '+HOST_TOKEN
        d=post(api,'/v1/express',expression(request_id='h1',session='hs')).json()
        r=post(api,'/v1/reflections',reflection('one',d['decision_id']));assert r.status_code==200,r.text
        out=r.json();assert out['scope']=='relationship' and out['preferred']['controls']['verbosity']<d['controls']['verbosity']
        assert out['rejected']=={'controls':d['controls'],'habits':d['habits']}
        assert post(api,'/v1/reflections',reflection('one',d['decision_id'])).json()['deduplicated']
        assert post(api,'/v1/reflections',reflection('two',d['decision_id'],adjustments={'warmth':'less'})).status_code==429  # one per decision
        for i in range(2,5):
            d=post(api,'/v1/express',expression(request_id=f'h{i}',session='hs')).json()
            r=post(api,'/v1/reflections',reflection(f'r{i}',d['decision_id'],adjustments={'formality':'more' if i%2 else 'less'}))
            assert r.status_code==(200 if i<4 else 429),r.text  # three per session
        tool=expression(request_id='tool',session='ts');tool['context']['turn_origin']='tool'
        d=post(api,'/v1/express',tool).json();assert post(api,'/v1/reflections',reflection('t',d['decision_id'])).status_code==400
        d=post(api,'/v1/express',expression(request_id='m',persona='mute',session='ms')).json()
        assert post(api,'/v1/reflections',reflection('m',d['decision_id'])).status_code==403
        d=post(api,'/v1/express',expression(request_id='c',session='cs')).json()
        assert post(api,'/v1/reflections',reflection('c',d['decision_id'],scope='core')).status_code==403  # core needs admin on a user's turn
        bad=reflection('x',d['decision_id']);bad['note']='be ruder';assert post(api,'/v1/reflections',bad).status_code==422  # no free text
        f=dict(feedback_id='spoof',decision_id=d['decision_id'],source='agent_reflection',kind='pairwise_preference',actor_id='agent-host',preferred=option(**TERSE),rejected=option(),evidence_group='g')
        api.headers['Authorization']='Bearer '+TOKEN;assert post(api,'/v1/feedback',f).status_code==403
    with TestClient(host_app(tmp_path/'b',scopes=('persona:express',)),headers={'Authorization':'Bearer '+TOKEN}) as api:
        make(api,'ape',archetype='mentor');api.headers['Authorization']='Bearer '+HOST_TOKEN
        d=post(api,'/v1/express',expression(request_id='n',session='ns')).json()
        assert post(api,'/v1/reflections',reflection('n',d['decision_id'])).status_code==403

def test_agent_reflections_evolve_relationship_and_are_revocable(tmp_path):
    with TestClient(host_app(tmp_path),headers={'Authorization':'Bearer '+TOKEN}) as api:
        make(api,'ape',archetype='mentor',maturation_rate='slow')
        api.headers['Authorization']='Bearer '+HOST_TOKEN
        before=api.get('/v1/personas/ape').json()
        fids=[]
        for i in range(30):
            d=post(api,'/v1/express',expression(request_id=f'q{i}',session=f'qs{i}')).json()
            r=post(api,'/v1/reflections',reflection(f'q{i}',d['decision_id']))
            if r.status_code==200:fids.append(r.json()['feedback_id'])
        api.app.state.drain();api.headers['Authorization']='Bearer '+TOKEN
        promoted=[a for a in audit(api,'ape','promoted') if a['kind']=='feedback'];assert promoted,audit(api,'ape','candidate_evaluated')
        reasons=audit(api,'ape','reflection_recorded');assert reasons and reasons[0]['reason']=='user_requested' and reasons[0]['adjustments']=={'verbosity':'less'}
        req=expression(request_id='after',session='after');req['debug']=True
        assert post(api,'/v1/express',req).json()['relationship_version'] is not None
        used=api.get('/v1/consolidations/'+promoted[0]['candidate']).json()['evidence_ids']
        api.headers['Authorization']='Bearer '+HOST_TOKEN
        e=dict(event_id='rv',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='ape',user_id='alice',type='experience.corrected',feedback_id=used[0])
        assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200
        api.headers['Authorization']='Bearer '+TOKEN
        assert all(v['revoked'] for v in api.get('/v1/personas/ape/history').json()['versions'] if v['job']==promoted[0]['candidate'])

def test_reflections_never_outweigh_people(api):
    make(api,'ape',archetype='balanced',maturation_rate='slow')
    for i in range(30):
        d=post(api,'/v1/express',expression(request_id=f'w{i}',session=f'ws{i}')).json()
        if i<6:
            served={'controls':d['controls'],'habits':d['habits']}
            f=dict(feedback_id=f'u{i}',decision_id=d['decision_id'],source='explicit_user',kind='pairwise_preference',actor_id='owner',consent_scope='relationship',learning_consent=True,preferred=option(**PATIENT),rejected=served if served!=option(**PATIENT) else option(**TERSE),evidence_group=f'ws{i}')
            assert post(api,'/v1/feedback',f).status_code==200
        else:assert post(api,'/v1/reflections',reflection(f'w{i}',d['decision_id'],adjustments={'verbosity':'less'})).status_code==200
    api.app.state.drain()
    jobs=[json.loads(r['data']) for r in api.app.state.store.all("SELECT data FROM jobs WHERE status IN ('evaluated','promoted','superseded')")]
    assert jobs
    for job in jobs:
        ids=job['evidence_ids'];assert sum(i.startswith('reflection') for i in ids)<=len(ids)/2,ids
