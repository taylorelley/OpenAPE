"""Human-like development (ADR 0004): temperament and individuality, session state to
trait, lifelong plasticity, life events, relationship accommodation and cooling, the
self anchor, and maturity-weighted influence. Synthetic labels and fixed priors:
engineering evidence only, not measured user benefit."""
import json
from datetime import datetime,timedelta,timezone
import torch
from conftest import *
from test_evolution import make,end,audit,diag,solo
from engine.neural.policy import Decoder
from engine.neural.profiles import ARCHETYPES,fit_seed_latent,seed_profile,agreement,reference_contexts
from engine.learning import development as dev

def store(api):return api.app.state.store

def latent(api,persona,version,dim):
    return store(api).get(store(api).one('SELECT hash FROM versions WHERE persona=? AND id=?',(persona,version))['hash'],dim)

def relationship(api,persona,user):
    row=store(api).one('SELECT active FROM relationships WHERE persona=? AND user_id=?',(persona,user))
    return latent(api,persona,row['active'],32) if row else torch.zeros(32)

def served(decision):return {'controls':decision['controls'],'habits':decision['habits']}

def bolder(decision):
    """The served style, one level more direct and assertive (an approved configuration)."""
    c=dict(decision['controls']);c['directness']=min(4,c['directness']+1);c['assertiveness']=min(4,c['assertiveness']+1)
    return {'controls':c,'habits':decision['habits']}

def prefer(api,fid,decision,preferred,scope,source='explicit_user'):
    r=post(api,'/v1/feedback',dict(feedback_id=fid,decision_id=decision['decision_id'],source=source,kind='pairwise_preference',actor_id='owner',consent_scope=scope,
        learning_consent=True,preferred=preferred,rejected=served(decision),evidence_group=fid))
    assert r.status_code==200,r.text;return r.json()

def session(api,persona,sid,user='alice',adapter='custom',**context):
    req=expression(request_id=sid,persona=persona,user=user,session=sid) if user else solo(sid,persona,sid);req['host']['adapter_id']=adapter;req['context'].update(context)
    return post(api,'/v1/express',req).json()

def close(api,persona,sid,user='alice',adapter='custom'):
    e=dict(event_id='end-'+sid,occurred_at=datetime.now(timezone.utc).isoformat(),persona_id=persona,session_id=sid,type='session.ended')
    if user:e['user_id']=user
    assert post(api,'/v1/observations',dict(adapter_id=adapter,events=[e])).status_code==200
    api.app.state.drain()

def life(api,persona,user=''):
    return json.loads(store(api).one('SELECT life FROM maturation WHERE persona=? AND user_id=?',(persona,user))['life'])

def test_individuality_varies_temperament_reproducibly(api):
    a=make(api,'m1',archetype='mentor');b=make(api,'m2',archetype='mentor')
    c=make(api,'m3',archetype='mentor',individuality_seed=a['individuality']['seed']);z=make(api,'m0',archetype='mentor',individuality=0)
    lat={k:latent(api,k,v['active_version'],64) for k,v in dict(m1=a,m2=b,m3=c,m0=z).items()}
    assert a['individuality']['amount']==0.3 and a['individuality']['seed']!=b['individuality']['seed']
    assert float((lat['m1']-lat['m2']).norm())>0.05 and float((lat['m1']-lat['m3']).norm())<1e-6  # alike but not identical; the seed reproduces
    d=Decoder('models/decoder-v3/decoder.safetensors');assert float((lat['m0']-fit_seed_latent(d,ARCHETYPES['mentor'],archetype='mentor')).norm())<1e-6
    profile=seed_profile(ARCHETYPES['mentor'],'mentor');neutral=agreement(d,torch.zeros(64),profile,reference_contexts())
    assert all(agreement(d,lat[k],profile,reference_contexts())>neutral for k in ('m1','m2'))  # still recognisably mentors
    assert make(api,'kid',parent_persona_id='m1')['individuality']==a['individuality']
    info=api.get('/v1/personas/m1').json();assert info['temperament_version']==a['active_version'] and info['character_drift']==0 and info['character_radius']==dev.CHARACTER_RADIUS

def test_session_state_adapts_within_a_session_only(api):
    base=make(api,'m',archetype='mentor',individuality=0)['active_version']
    d=session(api,'m','s1');alt=bolder(d);assert alt!=served(d)
    turns=[d]+[post(api,'/v1/express',expression(request_id=f's1-{i}',persona='m',session='s1')).json() for i in (1,2)]
    for i,turn in enumerate(turns):
        r=prefer(api,f'f{i}',turn,alt,'session');assert r['session_adapted'] and not r['learning_recorded']
    assert prefer(api,'f0-again',d,alt,'session')['session_adapted']  # the same judgement again counts once
    later=post(api,'/v1/express',{**expression(request_id='s1-later',persona='m',session='s1')}).json()
    assert later['controls']['directness']>d['controls']['directness'] and later['controls']['assertiveness']>d['controls']['assertiveness']
    assert later['persona_version']==base  # the mood shows; the version is unchanged
    assert session(api,'m','s2')['controls']==d['controls']  # other sessions are unaffected
    assert store(api).one('SELECT updates FROM states WHERE persona=? AND session=?',('m','s1'))['updates']==3
    close(api,'m','s1')
    assert not store(api).all('SELECT 1 FROM states') and not store(api).all('SELECT 1 FROM samples')  # session-only consent never lasts
    r=post(api,'/v1/feedback',dict(feedback_id='plain',decision_id=d['decision_id'],source='explicit_user',kind='pairwise_preference',actor_id='owner',consent_scope='record_only',
        learning_consent=True,preferred=alt,rejected=served(d),evidence_group='g')).json()
    assert not r['session_adapted']

def test_consistent_states_become_a_trait(api):
    make(api,'h',archetype='mentor',individuality=0)
    before=diag(api,'h','alice','before')
    for s in range(3):
        d=session(api,'h',f'h{s}')
        for i in range(2):prefer(api,f'h{s}-{i}',d,bolder(d),'relationship')
        close(api,'h',f'h{s}')
    habits=[m for m in audit(api,'h','matured') if 'habit' in m['components']]
    assert habits and habits[0]['eligible'] and habits[0]['components']['habit']['consistency']>=dev.HABIT_CONSISTENCY
    assert store(api).one('SELECT COUNT(*) AS n FROM samples WHERE persona=? AND consumed=0',('h',))['n']==0
    after=diag(api,'h','alice','after')
    assert after['directness']>before['directness'] and after['assertiveness']>before['assertiveness']  # the habit leans more direct
    # Revoking evidence behind a habit revokes the version built on it.
    job=[a for a in audit(api,'h','promoted') if a['kind']=='maturation'][-1]['candidate']
    first=api.get('/v1/consolidations/'+job).json()['evidence_ids'][0]
    e=dict(event_id='revoke',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='h',type='experience.corrected',feedback_id=first)
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200
    assert audit(api,'h','evidence_revoked')[0]['revoked_versions']

def test_inconsistent_states_do_not_become_a_trait():
    up=torch.zeros(32);up[0]=1;down=-up
    assert dev.habit_step([up,up,up],0.0,1.0) is not None
    assert dev.habit_step([up,down,up,down],0.0,1.0) is None and dev.habit_step([up,up],0.0,1.0) is None
    step=dev.habit_step([up*2]*4,0.0,3.0);assert float(step.norm())<=dev.STATE_BUDGET*dev.HABIT_GAIN+1e-6

def test_revoked_evidence_leaves_session_state(api):
    make(api,'r',archetype='mentor',individuality=0,evolution='manual')
    d=session(api,'r','open')
    for i in range(2):prefer(api,f'r{i}',d,bolder(d),'relationship')
    e=dict(event_id='revoke-r0',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='r',type='experience.corrected',feedback_id='r0')
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200
    assert json.loads(store(api).one('SELECT feedback FROM states WHERE persona=?',('r',))['feedback'])==['r1']
    close(api,'r','open');assert json.loads(store(api).one('SELECT feedback FROM samples WHERE persona=?',('r',))['feedback'])==['r1']
    e=dict(event_id='revoke-r1',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id='r',type='experience.corrected',feedback_id='r1')
    assert post(api,'/v1/observations',dict(adapter_id='custom',events=[e])).status_code==200
    assert not store(api).all('SELECT 1 FROM samples WHERE persona=?',('r',))

def test_novelty_and_life_events(api):
    make(api,'w',archetype='balanced',evolution='manual')
    for i in range(12):session(api,'w',f'code{i}',user=None,task_type='coding');close(api,'w',f'code{i}',user=None)
    growth=api.get('/v1/personas/w').json()['growth']['core'];assert growth['experience']==12 and growth['effective_experience']<9  # repetition counts less
    assert not audit(api,'w','life_event')
    for i in range(4):session(api,'w',f'help{i}',user=None,task_type='support');close(api,'w',f'help{i}',user=None)
    events=[e['event'] for e in audit(api,'w','life_event')];assert events==['role_change']  # one event per transition
    assert api.get('/v1/personas/w').json()['growth']['core']['boost']>1
    session(api,'w','elsewhere',user=None,adapter='hermes');close(api,'w','elsewhere',user=None,adapter='hermes')
    assert audit(api,'w','life_event')[-1]['event']=='new_host'
    d=session(api,'w','rough',user=None)
    for i in range(2):prefer(api,f'w{i}',d,option(**TERSE),'core',source='owner')
    close(api,'w','rough',user=None);assert audit(api,'w','life_event')[-1]['event']=='correction_burst'
    make(api,'v',archetype='balanced',evolution='manual')
    for i,task in enumerate(('coding','support','research','creative')):session(api,'v',f'v{i}',user=None,task_type=task);close(api,'v',f'v{i}',user=None)
    assert api.get('/v1/personas/v').json()['growth']['core']['effective_experience']==4  # every session was new

def test_relationship_accommodates_to_the_user(api):
    make(api,'acc',archetype='balanced',individuality=0,maturation_rate='fast')
    for i in range(12):
        session(api,'acc',f'a{i}',user='alice',tags=['expert']);close(api,'acc',f'a{i}',user='alice')
        session(api,'acc',f'b{i}',user='bob',tags=['beginner']);close(api,'acc',f'b{i}',user='bob')
    alice=diag(api,'acc','alice','alice-now');bob=diag(api,'acc','bob','bob-now')
    assert alice['verbosity']<bob['verbosity'] and alice['explanation_depth']<bob['explanation_depth']
    assert dev.accommodation_profile({'expert':1.0},1.0)['verbosity'][0]==1 and dev.accommodation_profile({'beginner':1.0},1.0)['explanation_depth'][0]==3
    assert dev.accommodation_profile({'beginner':1.0},0.0)['explanation_depth'][1]==0  # nothing before the relationship has grown

def set_life(api,anchor=None,**fields):
    """Edit alice's relationship life record in place (portable across store backends)."""
    with store(api).tx() as tx:
        row=tx.execute("SELECT life,anchor FROM maturation WHERE persona='c' AND user_id='alice'").fetchone();life={**json.loads(row['life'] or '{}'),**fields}
        tx.execute("UPDATE maturation SET life=?,anchor=? WHERE persona='c' AND user_id='alice'",(json.dumps(life),anchor if anchor is not None else row['anchor']))

def test_relationship_cools_after_absence_and_anchor_pulls_back(api):
    make(api,'c',archetype='concierge',individuality=0,maturation_rate='fast')
    for i in range(14):session(api,'c',f'c{i}');close(api,'c',f'c{i}')
    warm=relationship(api,'c','alice');assert float(warm.norm())>0.1
    ago=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()
    set_life(api,last_seen=ago)
    session(api,'c','back');close(api,'c','back')
    assert audit(api,'c','life_event')[-1]['event']=='long_absence'
    cooled=[m for m in audit(api,'c','matured') if 'cooling' in m['components']]
    assert cooled and cooled[0]['eligible'] and float(relationship(api,'c','alice').norm())<float(warm.norm())
    # Learned change the self anchor has not absorbed fades a little at each pass.
    current=relationship(api,'c','alice')
    set_life(api,last_sleep=0,anchor=json.dumps([0.0]*32))
    session(api,'c','pull');close(api,'c','pull')
    pulled=[m for m in audit(api,'c','matured') if m['scope']=='relationship'][-1];assert isinstance(pulled['components']['elastic'],float) and pulled['eligible']
    assert abs(float(relationship(api,'c','alice').norm())/float(current.norm())-(1-dev.ELASTIC))<0.05
    # A rollback is a deliberate change: the anchor restarts from it.
    first=[v['id'] for v in api.get('/v1/personas/c/history').json()['versions'] if v['scope']=='relationship'][0]
    assert post(api,'/v1/personas/c/rollbacks',dict(version=first,reason='restore early relationship')).status_code==200
    assert store(api).one("SELECT anchor FROM maturation WHERE persona='c' AND user_id='alice'")['anchor'] is None

def test_plasticity_influence_and_character_bounds():
    young,old=dev.trait_plasticity(0.0),dev.trait_plasticity(1.0)
    assert all(v==1 for v in young.values()) and all(v>0 for v in old.values())
    assert max(old[t] for t in dev.SURFACE)<min(old[t] for t in dev.INTERPERSONAL)  # surface style settles first
    assert dev.plasticity(1.0)==dev.PLASTICITY_FLOOR and dev.plasticity(1.0,3.0)>dev.plasticity(1.0)
    assert dev.influence('owner',0)==2 and dev.influence('owner',1)==1 and dev.influence('explicit_user',0)==0.5 and dev.influence('explicit_user',1)==1
    assert dev.influence('agent_reflection',0)<dev.influence('agent_reflection',1)==1 and dev.reflection_share(0)<dev.reflection_share(1)==1
    assert abs(dev.recency(dev.RECENCY_HALF_LIFE)-0.5)<1e-12
    centre=torch.zeros(64);far=torch.ones(64)
    assert abs(float(dev.within(far,centre,1.6).norm())-1.6)<1e-5 and torch.equal(dev.within(far*0.01,centre,1.6),far*0.01)
    a=dev.individual_profile(seed_profile(['warm']),7,0.3);assert a==dev.individual_profile(seed_profile(['warm']),7,0.3) and a['warmth'][0]==3 and len(a)>1
    assert dev.individual_profile(seed_profile(['warm']),7,0)==seed_profile(['warm'])
