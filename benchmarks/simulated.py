"""Simulated-user A/B/C/D engineering benchmark. NOT human evidence.

Simulated users hold hidden random per-trait utility tables drawn from a generator
that differs from the decoder's training profiles (continuous utilities over all five
levels of 2-3 traits, plus noisy answers). They interact through the real UPAP API
(in-process ASGI): express -> explicit pairwise feedback -> consolidation ->
independent evaluator -> manual CAS promotion. Evaluation contexts are sealed and
disjoint from the feedback contexts.

A: static markdown persona. Simulated users cannot read text, so A is scored as the
   configuration closest to its wording ("concise neutral"): an approximation.
B: fixed approved controls (the neutral default).
C: trained decoder with the frozen initial persona (pinned version, no learning).
D: same decoder after authorised experience-driven persona learning.

Metric: preference satisfied = the chosen configuration reaches the user's best
allowed level on every trait they care about; regret = best utility minus chosen
utility. Habits are not simulated. Paired, user-clustered
bootstrap 95% intervals. Task correctness and safety are not simulated.
"""
import json
import time
import random
import sys
from pathlib import Path
import numpy as np
from fastapi.testclient import TestClient
from engine.api.app import create_app
from engine.neural.policy import APPROVED_LEVELS, INDEX, NEUTRAL_ACTION, TRAITS, mask, levels_of
from engine.neural.profiles import random_context

ROOT=Path(__file__).resolve().parents[1]
SEALED_SEED=20261022
TOKEN='simulated-benchmark-token-000000000000'
USERS,FEEDBACK_PER_ROUND,ROUNDS,EVAL_CONTEXTS,NOISE=24,12,2,16,0.1
STATIC_MARKDOWN=INDEX[(2,2,1,0,2,1,2)]  # concise neutral

def make_user(rng):
    traits=rng.sample(list(TRAITS),rng.randint(2,3))
    return {t:[rng.gauss(0,1) for _ in range(5)] for t in traits}

def utilities(user,ctx):
    """Utility of every approved configuration; masked ones are -inf."""
    u=np.zeros(len(APPROVED_LEVELS))
    for t,table in user.items():u+=np.array(table)[APPROVED_LEVELS[:,TRAITS.index(t)].numpy()]
    return np.where(mask(ctx).numpy(),u,-np.inf)

def score(user,ctx,choice):
    u=utilities(user,ctx);best=float(u.max())
    return int(u[choice]>=best-1e-9),best-float(u[choice])

def option(action):return {'controls':levels_of(action),'habits':[]}

def index(decision):return INDEX[tuple(decision['controls'][t] for t in TRAITS)]

def request(persona,rid,session,ctx,mode='active',pinned=None):
    r=dict(protocol_version='upap/2',request_id=rid,identity=dict(tenant_id='local',persona_id=persona),session=dict(id=session,turn_id=rid),
        host=dict(adapter_id='benchmark',adapter_version='0.3.0',host_version='simulated',provider_family=random.Random(rid).choice(['openai','anthropic','google']),model_id='simulated'),context=ctx,mode=mode)
    if pinned:r['pinned_version']=pinned
    return r

def run(data_dir):
    rng=random.Random(SEALED_SEED)
    creds=[dict(token=TOKEN,tenant='local',actor='sim',scopes=['persona:express','observations:write','feedback:write','persona:admin','training:admin'],personas=['*'],users=['*'])]
    rows=[];promotions=0;rejections=0
    with TestClient(create_app(data_dir,credentials=creds,rate_limit_per_minute=100000),headers={'Authorization':'Bearer '+TOKEN}) as api:
        post=lambda path,body:api.post(path,json={'protocol_version':'upap/2',**body})
        for u in range(USERS):
            user=make_user(rng);persona=f'sim-{u:02d}'
            initial=post('/v1/personas',{'persona_id':persona,'archetype':'balanced','individuality':0,'evolution':'manual'}).json()['active_version']
            n=0
            for round_ in range(ROUNDS):
                for _ in range(FEEDBACK_PER_ROUND):
                    ctx=random_context(rng);n+=1
                    d=post('/v1/express',request(persona,f'{persona}-fb-{n}',f'{persona}-s-{n}',ctx)).json()
                    shown=index(d);allowed=mask(ctx).nonzero().flatten().tolist();util=utilities(user,ctx)
                    other=rng.choice(allowed)
                    while other==shown:other=rng.choice(allowed)
                    better,worse=(shown,other) if util[shown]>=util[other] else (other,shown)
                    if rng.random()<NOISE:better,worse=worse,better
                    post('/v1/feedback',dict(feedback_id=f'{persona}-f-{n}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id='sim',consent_scope='core',learning_consent=True,preferred=option(better),rejected=option(worse),evidence_group=f'{persona}-s-{n}'))
                job=post('/v1/consolidations',dict(persona_id=persona,scope='core',seed=round_)).json()['job_id']
                while (j:=api.get('/v1/consolidations/'+job).json())['status']=='queued':time.sleep(.05)
                active=api.get(f'/v1/personas/{persona}').json()['active_version']
                if j.get('eligible'):
                    post(f'/v1/personas/{persona}/promotions',dict(candidate_id=job,expected_version=active));promotions+=1
                else:rejections+=1
            learned=api.get(f'/v1/personas/{persona}').json()['active_version']
            for k in range(EVAL_CONTEXTS):
                ctx=random_context(rng)
                c=index(post('/v1/express',request(persona,f'{persona}-c-{k}',f'{persona}-eval-c',ctx,'frozen',initial)).json())
                d=index(post('/v1/express',request(persona,f'{persona}-d-{k}',f'{persona}-eval-d',ctx,'frozen',learned)).json())
                choices={'A':STATIC_MARKDOWN if mask(ctx)[STATIC_MARKDOWN] else NEUTRAL_ACTION,'B':NEUTRAL_ACTION,'C':c,'D':d}
                rows.append(dict(user=u,**{f'{k}_{metric}':v for k,ch in choices.items() for metric,v in zip(('satisfied','regret'),score(user,ctx,ch))}))
    return rows,promotions,rejections

def bootstrap(rows,key,a,b,reps=2000):
    users=sorted({r['user'] for r in rows});by={u:[r[f'{a}_{key}']-r[f'{b}_{key}'] for r in rows if r['user']==u] for u in users}
    rng=np.random.default_rng(42);means=[]
    for _ in range(reps):
        sample=rng.choice(users,len(users),replace=True);means.append(float(np.mean([v for u in sample for v in by[u]])))
    return dict(mean=round(float(np.mean([v for u in users for v in by[u]])),4),ci95=[round(float(np.quantile(means,q)),4) for q in (.025,.975)])

def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:rows,promotions,rejections=run(tmp)
    report=dict(kind='simulated-user engineering benchmark; NOT human or live-model evidence',sealed_seed=SEALED_SEED,simulated_users=USERS,feedback_pairs_per_user=FEEDBACK_PER_ROUND*ROUNDS,answer_noise=NOISE,
        heldout_interactions=len(rows),promotions=promotions,evaluator_rejections=rejections,
        rates={k:dict(preference_satisfied=round(float(np.mean([r[f'{k}_satisfied'] for r in rows])),4),mean_regret=round(float(np.mean([r[f'{k}_regret'] for r in rows])),4)) for k in 'ABCD'},
        paired_differences={f'{a}-{b}':dict(satisfied=bootstrap(rows,'satisfied',a,b),regret=bootstrap(rows,'regret',a,b)) for a,b in (('D','B'),('D','C'),('D','A'),('C','B'))},
        limitations=['Simulated users with synthetic utilities; no human raters or live LLM outputs','A is approximated by the closest catalogue row; real markdown effects are unmeasured',
            'Task correctness and safety are not simulated','Habits are not simulated','User-clustered bootstrap over 24 users; provisional sample size'],
        measured_behavioral_benefit=False)
    out=ROOT/'benchmarks/reports/simulated.json';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':sys.exit(main())
