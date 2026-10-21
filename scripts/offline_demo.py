"""Offline engineering demonstration through the real HTTP API; synthetic feedback."""
import argparse
import json
import time
import uuid
from pathlib import Path
from sdk.python.client import Client

def demo(c):
    persona='demo-'+uuid.uuid4().hex[:8]
    prior=c.request('POST','/v1/personas',{'persona_id':persona})['active_version']
    req=json.loads(Path('examples/express.json').read_text());req['identity']['persona_id']=persona
    d=None
    for i in range(36):
        req['request_id']=f'demo-{i}';req['session']['id']=f'scenario-{i}'
        d=c.request('POST','/v1/express',{**req,'mode':'active'})
        c.request('POST','/v1/feedback',dict(feedback_id=f'{persona}-f-{i}',decision_id=d['decision_id'],actor_id='owner',source='owner',kind='pairwise_preference',consent_scope='core',learning_consent=True,preferred_control=1,rejected_control=0,evidence_group=f'synthetic-{i}'))
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
if __name__=='__main__':
    import os
    token=os.environ.get('OPENAPE_TOKEN') or json.loads(Path('.openape/credentials.json').read_text())[0]['token']
    c=Client(os.environ.get('OPENAPE_URL','http://127.0.0.1:8765'),token,timeout=10)
    try:print(json.dumps(demo(c),indent=2))
    finally:c.close()
