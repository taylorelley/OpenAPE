"""Run after openape init && docker compose up --build -d. No provider call."""
import json
import time
import uuid
from pathlib import Path
import httpx
from sdk.python.client import Client

def main():
    credentials=json.loads(Path('.openape/credentials.json').read_text())
    c=Client('http://127.0.0.1:8765',credentials[0]['token'],timeout=5)
    try:
        for _ in range(100):
            try:
                ready=c.request('GET','/health/ready')
                if ready['engine_status']=='experimental_synthetic':break
            except httpx.TransportError:pass
            time.sleep(.1)
        else:raise RuntimeError('Trained decoder not ready')
        assert c.request('GET','/v1/capabilities')['engine_status']=='experimental_synthetic'
        persona='docker-smoke-'+uuid.uuid4().hex[:8]
        c.request('POST','/v1/personas',{'persona_id':persona,'archetype':'balanced'})
        req=json.loads(Path('examples/express.json').read_text());req['identity']['persona_id']=persona
        decision=c.request('POST','/v1/express',req)
        assert decision['engine_status']=='experimental_synthetic'
        assert httpx.get('http://127.0.0.1:8765/v1/capabilities',trust_env=False).status_code==401
        # A consolidation runs the evaluator in its own spawned process inside the hardened container.
        terse={'controls':dict(directness=3,warmth=1,verbosity=1,humour=0,formality=2,explanation_depth=1,assertiveness=3),'habits':[]}
        for i in range(12):
            d=c.request('POST','/v1/express',{**req,'request_id':f'docker-{i}','session':{'id':f'docker-s{i%6}','turn_id':str(i)}})
            served={'controls':d['controls'],'habits':d['habits']}
            c.request('POST','/v1/feedback',dict(protocol_version='upap/2',feedback_id=f'{persona}-f{i}',decision_id=d['decision_id'],source='owner',kind='pairwise_preference',actor_id=credentials[0]['actor'],
                consent_scope='core',learning_consent=True,preferred=terse if served!=terse else {**terse,'habits':['next_step']},rejected=served,evidence_group=f'docker-s{i%6}'))
        job=c.request('POST','/v1/consolidations',dict(protocol_version='upap/2',persona_id=persona,scope='core'))['job_id']
        for _ in range(600):
            state=c.request('GET','/v1/consolidations/'+job)
            if state['status']!='queued':break
            time.sleep(.2)
        assert state['status']=='evaluated' and state['report']['evaluator']['isolation']=='process',state
        report=dict(image='openape:0.3.0',health='PASS',auth='PASS',create='PASS',neural_express='PASS',isolated_evaluator='PASS',evaluator_pid=state['report']['evaluator']['pid'],
            candidate_eligible=state['eligible'],decoder_hash=decision['decoder_hash'],persona_id=persona,evidence='Actual Docker HTTP service (compose hardening: read-only root, no capabilities); no LLM/model-provider call')
        Path('docs/reports/docker-smoke.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    finally:c.close()
if __name__=='__main__':main()
