"""Offline engineering demonstration through the real HTTP API; synthetic feedback."""
import argparse
import json
import time
import uuid
from pathlib import Path
from sdk.python.client import Client

def demo(c):
    persona='demo-'+uuid.uuid4().hex[:8]
    prior=c.request('POST','/v1/personas',{'persona_id':persona,'archetype':'balanced','evolution':'manual'})['active_version']
    req=json.loads(Path('examples/express.json').read_text());req['identity']['persona_id']=persona
    d=None
    for i in range(36):
        req['request_id']=f'demo-{i}';req['session']['id']=f'scenario-{i}'
        d=c.request('POST','/v1/express',{**req,'mode':'active'})
        c.request('POST','/v1/feedback',dict(feedback_id=f'{persona}-f-{i}',decision_id=d['decision_id'],actor_id='owner',source='owner',kind='pairwise_preference',consent_scope='core',learning_consent=True,preferred={'controls':dict(directness=3,warmth=1,verbosity=1,humour=0,formality=2,explanation_depth=1,assertiveness=3),'habits':[]},rejected={'controls':dict(directness=2,warmth=2,verbosity=2,humour=0,formality=2,explanation_depth=2,assertiveness=2),'habits':[]},evidence_group=f'synthetic-{i}'))
    job=c.request('POST','/v1/consolidations',dict(persona_id=persona,scope='core'))
    deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        report=c.request('GET','/v1/consolidations/'+job['job_id'])
        if report['status']!='queued':break
        time.sleep(.1)
    assert report['status']=='evaluated',report
    if not report['eligible']:raise RuntimeError('Evaluator rejected candidate: '+json.dumps(report))
    promoted=c.request('POST',f'/v1/personas/{persona}/promotions',dict(candidate_id=job['job_id'],expected_version=prior))
    exported=c.request('POST',f'/v1/personas/{persona}/export',{})
    c.request('POST',f'/v1/personas/{persona}/rollbacks',dict(version=prior,reason='Offline demo rollback'))
    return dict(persona=persona,prior=prior,candidate=job['job_id'],promoted=promoted,rollback=c.request('GET',f'/v1/personas/{persona}'),evaluation=report['report'],export_checksum=exported['bundle']['sha256'],evidence='Synthetic explicit preference labels. No live-model benefit claimed.')
def evolution_demo(c):
    """Automatic evolution: a mentor persona matures with one linked user over ended
    sessions (fast rate) and adapts to that user's consented feedback, no operator steps."""
    from datetime import datetime,timezone
    persona='evolve-'+uuid.uuid4().hex[:8]
    c.request('POST','/v1/personas',{'persona_id':persona,'archetype':'mentor','maturation_rate':'fast'})
    req=json.loads(Path('examples/express.json').read_text());req['identity']['persona_id']=persona
    for i in range(20):
        req['request_id']=f'{persona}-{i}';req['session']['id']=f'{persona}-s{i}'
        d=c.request('POST','/v1/express',{**req,'mode':'active'})
        c.request('POST','/v1/feedback',dict(feedback_id=f'{persona}-f{i}',decision_id=d['decision_id'],actor_id='owner',source='explicit_user',kind='pairwise_preference',consent_scope='relationship',learning_consent=True,preferred={'controls':dict(directness=3,warmth=3,verbosity=1,humour=0,formality=2,explanation_depth=1,assertiveness=2),'habits':[]},rejected={'controls':d['controls'],'habits':d['habits']},evidence_group=f'{persona}-s{i}'))
        c.request('POST','/v1/observations',dict(adapter_id=req['host']['adapter_id'],events=[dict(event_id=f'{persona}-end{i}',occurred_at=datetime.now(timezone.utc).isoformat(),persona_id=persona,user_id='alice',session_id=f'{persona}-s{i}',type='session.ended')]))
    deadline=time.monotonic()+60;history=None
    while time.monotonic()<deadline:
        history=c.request('GET',f'/v1/personas/{persona}/history')
        if sum(a['action']=='matured' for a in history['audit'])>=10:break
        time.sleep(.2)
    time.sleep(1);history=c.request('GET',f'/v1/personas/{persona}/history')
    matured=[json.loads(a['data']) for a in history['audit'] if a['action']=='matured']
    promoted=[json.loads(a['data']) for a in history['audit'] if a['action']=='promoted']
    return dict(persona=persona,archetype='mentor',maturation_steps=[dict(scope=m['scope'],experience=m['experience'],maturity=m['maturity'],drift=m['drift']) for m in matured],
        automatic_promotions={k:sum(p['kind']==k for p in promoted) for k in ('feedback','maturation')},growth=c.request('GET',f'/v1/personas/{persona}?user_id=alice')['growth'],
        evidence='Fixed maturation prior and synthetic explicit labels. No live-model benefit claimed.')
if __name__=='__main__':
    import os
    token=os.environ.get('OPENAPE_TOKEN') or json.loads(Path('.openape/credentials.json').read_text())[0]['token']
    c=Client(os.environ.get('OPENAPE_URL','http://127.0.0.1:8765'),token,timeout=10)
    try:print(json.dumps(dict(manual=demo(c),automatic=evolution_demo(c)),indent=2))
    finally:c.close()
